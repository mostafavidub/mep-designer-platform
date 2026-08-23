import base64
import math
import shutil
import statistics
import tempfile
from pathlib import Path

import ezdxf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from fastapi import FastAPI, HTTPException
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

from . import main_v4  # installs structured-input normalization onto main_v3
from . import main_v3 as engine

app = FastAPI(title='EngiTools CAD Designer', version='0.5.2')

_prev_electrical_calc = engine.electrical_calc
_prev_mechanical_calc = engine.mechanical_calc


def _enrich_from_architecture(a, discipline):
    out = dict(a or {})
    auto = out.get('architectural_auto') or {}
    if discipline == 'electrical':
        if not out.get('design_load_kw') and auto.get('estimated_electrical_load_kw') is not None:
            out['design_load_kw'] = str(auto['estimated_electrical_load_kw'])
        if not out.get('cable_length_m') and auto.get('estimated_cable_route_m') is not None:
            out['cable_length_m'] = str(auto['estimated_cable_route_m'])
        if not out.get('power_factor') and auto.get('power_factor') is not None:
            out['power_factor'] = str(auto['power_factor'])
        if not out.get('max_voltage_drop_pct') and auto.get('max_voltage_drop_pct') is not None:
            out['max_voltage_drop_pct'] = str(auto['max_voltage_drop_pct'])
    else:
        if not out.get('design_water_flow_lps') and auto.get('estimated_water_flow_lps') is not None:
            out['design_water_flow_lps'] = str(auto['estimated_water_flow_lps'])
        if not out.get('target_water_velocity_mps') and auto.get('target_water_velocity_mps') is not None:
            out['target_water_velocity_mps'] = str(auto['target_water_velocity_mps'])
        if not out.get('cooling_load_kw') and auto.get('estimated_cooling_load_kw') is not None:
            out['cooling_load_kw'] = str(auto['estimated_cooling_load_kw'])
        if not out.get('heating_load_kw') and auto.get('estimated_heating_load_kw') is not None:
            out['heating_load_kw'] = str(auto['estimated_heating_load_kw'])
    return out


def electrical_calc(a):
    enriched = _enrich_from_architecture(a, 'electrical')
    result = _prev_electrical_calc(enriched)
    result['calculation_basis'] = 'architecture-derived where possible; user input only for unresolved project decisions'
    auto = enriched.get('architectural_auto') or {}
    if auto.get('estimated_electrical_load_kw') is not None:
        result.setdefault('warnings', []).insert(0, 'Base electrical load was inferred automatically from architectural room/area data; verify equipment-specific loads before construction.')
    if auto.get('estimated_cable_route_m') is not None:
        result.setdefault('warnings', []).append('Cable route length is geometry-derived and will be replaced/refined by final routed circuit lengths.')
    return result


def mechanical_calc(a):
    enriched = _enrich_from_architecture(a, 'mechanical')
    result = _prev_mechanical_calc(enriched)
    result['calculation_basis'] = 'architecture-derived where possible; user input only for unresolved project decisions'
    auto = enriched.get('architectural_auto') or {}
    if auto.get('estimated_water_flow_lps') is not None:
        result.setdefault('warnings', []).insert(0, 'Water demand was inferred automatically from architecture-detected plumbing spaces/fixtures; final code fixture-unit calculation remains required.')
    if auto.get('estimated_cooling_load_kw') is not None:
        result.setdefault('warnings', []).append('Thermal loads are architecture-derived preliminary proxies pending climate/envelope refinement.')
    return result


def _nearest_distances(points):
    values = []
    for i, point in enumerate(points):
        distances = [math.dist(point, other) for j, other in enumerate(points) if j != i]
        if distances:
            values.append(min(distances))
    return values


def _cluster_rooms(rooms):
    """Split a CAD modelspace into actual plan groups instead of using global extents.

    Architectural files frequently contain several plans thousands of drawing units
    apart while each individual plan is only tens of units wide. Fitting global
    extents made every floor appear as a few dots. Room-label proximity provides a
    stable, unit-agnostic way to identify the real plan viewports.
    """
    if not rooms:
        return []
    points = [tuple(item['point']) for item in rooms]
    nearest = _nearest_distances(points)
    if not nearest:
        return [rooms]
    median_nn = max(statistics.median(nearest), 1e-6)
    threshold = median_nn * 8.0
    unseen = set(range(len(rooms)))
    clusters = []
    while unseen:
        seed = unseen.pop()
        stack = [seed]
        indexes = [seed]
        while stack:
            current = stack.pop()
            near = [idx for idx in list(unseen) if math.dist(points[current], points[idx]) <= threshold]
            for idx in near:
                unseen.remove(idx)
                stack.append(idx)
                indexes.append(idx)
        clusters.append([rooms[idx] for idx in indexes])

    major = [cluster for cluster in clusters if len(cluster) >= 2]
    minor = [cluster for cluster in clusters if len(cluster) < 2]
    if major:
        for cluster in minor:
            item = cluster[0]
            point = tuple(item['point'])
            target = min(
                major,
                key=lambda candidate: min(math.dist(point, tuple(other['point'])) for other in candidate),
            )
            distance = min(math.dist(point, tuple(other['point'])) for other in target)
            if distance <= threshold * 2.5:
                target.append(item)
        clusters = major
    else:
        clusters = [rooms]
    clusters.sort(key=lambda c: (-max(x['point'][1] for x in c), min(x['point'][0] for x in c)))
    return clusters


def _cluster_metric(cluster):
    points = [tuple(item['point']) for item in cluster]
    nearest = _nearest_distances(points)
    median_nn = statistics.median(nearest) if nearest else 1.0
    minx = min(p[0] for p in points)
    maxx = max(p[0] for p in points)
    miny = min(p[1] for p in points)
    maxy = max(p[1] for p in points)
    span = max(maxx - minx, maxy - miny, median_nn * 4.0, 1e-6)
    return median_nn, span


def _route(msp, start, end, layer):
    if not end:
        return
    x1, y1 = start
    x2, y2 = end
    mid = (x2, y1)
    msp.add_lwpolyline([start, mid, end], dxfattribs={'layer': layer})


def mechanical_design_adaptive(msp, rooms, systems, _legacy_scale):
    """Place mechanical symbols using local plan scale, not global modelspace scale."""
    stats = {
        'cold_water': 0, 'hot_water': 0, 'sanitary': 0, 'vent': 0, 'gas': 0,
        'heating_supply': 0, 'heating_return': 0, 'cooling': 0, 'condensate': 0,
        'exhaust_ventilation': 0, 'mechanical_risers': 0,
    }
    for cluster in _cluster_rooms(rooms):
        median_nn, span = _cluster_metric(cluster)
        r = max(median_nn * 0.07, span * 0.0025, 0.04)
        r = min(r, median_nn * 0.22 if median_nn > 0 else r)
        text_h = max(r * 0.85, 0.03)
        shafts = [tuple(item['point']) for item in cluster if item['room'] == 'shaft']
        corridors = [tuple(item['point']) for item in cluster if item['room'] in ('corridor', 'stair')]
        wet = [tuple(item['point']) for item in cluster if item['room'] in ('kitchen', 'bath', 'toilet')]
        fallback_hub = None
        if wet:
            fallback_hub = (sum(p[0] for p in wet) / len(wet), sum(p[1] for p in wet) / len(wet))
        elif corridors:
            fallback_hub = corridors[0]

        for item in cluster:
            room = item['room']
            x, y = item['point']
            point = (x, y)
            hub = engine.nearest(point, shafts) if shafts else fallback_hub

            if room in ('kitchen', 'bath', 'toilet'):
                cw = (x - 1.7 * r, y)
                hw = (x, y)
                san = (x + 1.7 * r, y)
                if 'cold_water' in systems:
                    engine.add_circle(msp, cw, r * .5, 'ENGITOOLS-M-COLD_WATER', 'CW', text_h * .75)
                    _route(msp, cw, hub, 'ENGITOOLS-M-COLD_WATER')
                    stats['cold_water'] += 1
                if 'hot_water' in systems and room in ('kitchen', 'bath'):
                    engine.add_circle(msp, hw, r * .5, 'ENGITOOLS-M-HOT_WATER', 'HW', text_h * .75)
                    _route(msp, hw, hub, 'ENGITOOLS-M-HOT_WATER')
                    stats['hot_water'] += 1
                if 'sanitary' in systems:
                    engine.add_circle(msp, san, r * .55, 'ENGITOOLS-M-SANITARY', 'S', text_h * .75)
                    _route(msp, san, hub, 'ENGITOOLS-M-SANITARY')
                    stats['sanitary'] += 1
                if 'vent' in systems and room in ('bath', 'toilet'):
                    vent = (x + 1.7 * r, y + 1.8 * r)
                    engine.add_cross(msp, vent, r * .55, 'ENGITOOLS-M-VENT', 'V', text_h * .75)
                    _route(msp, vent, hub, 'ENGITOOLS-M-VENT')
                    stats['vent'] += 1
                if 'exhaust_ventilation' in systems and room in ('bath', 'toilet'):
                    exhaust = (x - 1.7 * r, y + 1.8 * r)
                    engine.add_box(msp, exhaust, r * .55, 'ENGITOOLS-M-EXHAUST_VENTILATION', 'EF', text_h * .75)
                    _route(msp, exhaust, hub, 'ENGITOOLS-M-EXHAUST_VENTILATION')
                    stats['exhaust_ventilation'] += 1

            if room == 'kitchen' and 'gas' in systems:
                gas = (x, y + 2.1 * r)
                engine.add_box(msp, gas, r * .55, 'ENGITOOLS-M-GAS', 'G', text_h * .8)
                _route(msp, gas, hub, 'ENGITOOLS-M-GAS')
                stats['gas'] += 1

            if room in ('bedroom', 'living'):
                if 'cooling' in systems:
                    ac = (x, y + 2.0 * r)
                    engine.add_box(msp, ac, r * .8, 'ENGITOOLS-M-COOLING', 'AC', text_h * .8)
                    _route(msp, ac, hub, 'ENGITOOLS-M-COOLING')
                    stats['cooling'] += 1
                    if 'condensate' in systems:
                        cond = (x + 1.8 * r, y + 2.0 * r)
                        engine.add_circle(msp, cond, r * .4, 'ENGITOOLS-M-CONDENSATE', 'C', text_h * .7)
                        _route(msp, cond, hub, 'ENGITOOLS-M-CONDENSATE')
                        stats['condensate'] += 1
                if 'heating_supply' in systems:
                    hs = (x - 1.15 * r, y - 2.0 * r)
                    engine.add_circle(msp, hs, r * .42, 'ENGITOOLS-M-HEATING_SUPPLY', 'HS', text_h * .68)
                    _route(msp, hs, hub, 'ENGITOOLS-M-HEATING_SUPPLY')
                    stats['heating_supply'] += 1
                if 'heating_return' in systems:
                    hr = (x + 1.15 * r, y - 2.0 * r)
                    engine.add_circle(msp, hr, r * .42, 'ENGITOOLS-M-HEATING_RETURN', 'HR', text_h * .68)
                    _route(msp, hr, hub, 'ENGITOOLS-M-HEATING_RETURN')
                    stats['heating_return'] += 1

        if 'mechanical_risers' in systems:
            for shaft in shafts:
                engine.add_box(msp, shaft, r * .95, 'ENGITOOLS-M-MECHANICAL_RISERS', 'R', text_h)
                stats['mechanical_risers'] += 1
    return stats


def _viewport_for_cluster(cluster):
    points = [tuple(item['point']) for item in cluster]
    median_nn, span = _cluster_metric(cluster)
    minx = min(p[0] for p in points)
    maxx = max(p[0] for p in points)
    miny = min(p[1] for p in points)
    maxy = max(p[1] for p in points)
    margin = max(span * 0.34, median_nn * 4.0, 1.0)
    return minx - margin, miny - margin, maxx + margin, maxy + margin


def _draw_layout_resilient(doc, msp, ax, dxf_path):
    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.COLOR_SWAP_BW,
    )
    skipped = []
    rendered = 0
    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    try:
        Frontend(ctx, out, config=cfg).draw_layout(msp, finalize=True)
        return len(msp), skipped
    except Exception as exc:
        print(f'[cad-render] full-layout render failed for {dxf_path.name}: {type(exc).__name__}: {exc}; retrying entity-by-entity', flush=True)
        ax.clear()
        ax.set_facecolor('white')
        ax.set_aspect('equal', adjustable='box')
        ax.axis('off')
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        frontend = Frontend(ctx, out, config=cfg)
        for entity in msp:
            try:
                frontend.draw_entities([entity])
                rendered += 1
            except Exception as entity_exc:
                skipped.append((entity.dxftype(), str(entity_exc)[:180]))
        out.finalize()
        if rendered <= 0:
            raise RuntimeError(f'No renderable DXF entities found in {dxf_path.name}')
        if skipped:
            sample = '; '.join(f'{kind}: {msg}' for kind, msg in skipped[:8])
            print(f'[cad-render] skipped {len(skipped)} of {len(msp)} entities in {dxf_path.name}: {sample}', flush=True)
        return rendered, skipped


def render_pdf_resilient(dxf_path, pdf_path, discipline):
    """Render readable plan pages, one viewport per detected architectural plan."""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    rooms = engine.detect_room_labels(msp)
    clusters = _cluster_rooms(rooms)
    if not clusters:
        clusters = [rooms] if rooms else []

    with PdfPages(pdf_path) as pdf:
        if clusters:
            for page_no, cluster in enumerate(clusters, start=1):
                fig = plt.figure(figsize=(11.69, 8.27), facecolor='white')
                ax = fig.add_axes([.025, .055, .95, .88])
                ax.set_facecolor('white')
                ax.set_aspect('equal', adjustable='box')
                ax.axis('off')
                try:
                    rendered, _ = _draw_layout_resilient(doc, msp, ax, dxf_path)
                    if rendered <= 0:
                        raise RuntimeError(f'No renderable DXF entities found in {dxf_path.name}')
                    minx, miny, maxx, maxy = _viewport_for_cluster(cluster)
                    ax.set_xlim(minx, maxx)
                    ax.set_ylim(miny, maxy)
                    ax.set_aspect('equal', adjustable='box')
                    fig.suptitle(
                        f'EngiTools {discipline.title()} - Plan {page_no}/{len(clusters)} - PRELIMINARY / ENGINEERING REVIEW REQUIRED',
                        fontsize=9,
                    )
                    pdf.savefig(fig, bbox_inches='tight', facecolor='white')
                finally:
                    plt.close(fig)
        else:
            fig = plt.figure(figsize=(11.69, 8.27), facecolor='white')
            ax = fig.add_axes([.025, .055, .95, .88])
            ax.set_facecolor('white')
            ax.set_aspect('equal', adjustable='datalim')
            ax.axis('off')
            try:
                rendered, _ = _draw_layout_resilient(doc, msp, ax, dxf_path)
                if rendered <= 0:
                    raise RuntimeError(f'No renderable DXF entities found in {dxf_path.name}')
                fig.suptitle(
                    f'EngiTools {discipline.title()} - PRELIMINARY DESIGN / ENGINEERING REVIEW REQUIRED',
                    fontsize=9,
                )
                pdf.savefig(fig, bbox_inches='tight', facecolor='white')
            finally:
                plt.close(fig)


engine.electrical_calc = electrical_calc
engine.mechanical_calc = mechanical_calc
engine.mechanical_design = mechanical_design_adaptive
engine.render_pdf = render_pdf_resilient


@app.get('/health')
def health():
    return {'ok': True, 'service': 'cad-designer', 'version': '0.5.2', 'mode': 'architecture-first-readable-plan-rendering'}


@app.get('/engine-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '0.5.2',
        'questionnaire': 'dynamic-unresolved-only',
        'architecture_auto_calculation': True,
        'resilient_dxf_pdf_rendering': True,
        'plan_cluster_viewports': True,
        'adaptive_mechanical_symbol_scale': True,
        'auto_inputs': [
            'room inventory', 'shaft/parking/roof/elevator detection', 'plausible geometry area',
            'representative route length', 'baseline electrical load', 'water-demand proxy',
            'preliminary cooling/heating load proxy', 'default PF/voltage-drop/water-velocity design assumptions'
        ],
        'asks_user_only_for': [
            'location/climate when absent', 'utility/service facts not encoded in plan',
            'owner system choices', 'special equipment/loads not inferable from architecture'
        ],
        'construction_ready': False,
        'professional_verification_required': True,
    }


@app.post('/design')
def design(req: engine.DesignRequest):
    discipline = req.discipline.strip().lower()
    if discipline not in engine.SYSTEMS:
        raise HTTPException(400, 'discipline must be mechanical or electrical')
    scope = req.output_scope or {}
    if scope.get('discipline') != discipline:
        raise HTTPException(400, 'output_scope discipline mismatch')
    if scope.get('only_this_discipline') is not True or scope.get('include_other_disciplines') is not False:
        raise HTTPException(400, 'discipline isolation flags are required')
    requested = scope.get('systems') or []
    allowed = engine.SYSTEMS[discipline]
    if any(s not in allowed for s in requested):
        raise HTTPException(400, 'output_scope contains unsupported or cross-discipline systems')
    systems = requested or allowed
    answers = _enrich_from_architecture(req.answers or {}, discipline)
    calc = engine.calc_for(discipline, answers)
    # Calculation normalization intentionally keeps only engineering values;
    # preserve the approved workflow contract explicitly for the sheet compositor.
    if discipline == 'mechanical' and answers.get('_approved_drawing_manifest'):
        calc['_approved_drawing_manifest'] = answers['_approved_drawing_manifest']

    project_out = engine.OUTPUT_ROOT / str(req.project_id) / f'R{req.revision:03d}' / discipline
    shutil.rmtree(project_out, ignore_errors=True)
    project_out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='engitools-cad-') as td:
        ti = Path(td) / 'input'
        ti.mkdir()
        try:
            sources = engine.source_files(req, ti)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        generated, pages, reports = [], [], []
        for idx, src in enumerate(sources, start=1):
            stem = ''.join(c if c.isalnum() or c in '-_' else '_' for c in src.stem)[:80] or f'plan_{idx}'
            dxf = project_out / f'{idx:02d}_{stem}_{discipline}.dxf'
            report = {'source': src.name, **engine.design_dxf(src, dxf, discipline, systems, req.revision, calc)}
            report['detected_plan_clusters'] = len(_cluster_rooms(engine.detect_room_labels(ezdxf.readfile(dxf).modelspace())))
            reports.append(report)
            generated.append(dxf)
            page = project_out / f'{idx:02d}_{discipline}.pdf'
            engine.render_pdf(dxf, page, discipline)
            pages.append(page)
        merged = project_out / f'EngiTools_{req.project_id}_{discipline}_R{req.revision}.pdf'
        engine.merge_pdfs(pages, merged)
        package = project_out / f'EngiTools_{req.project_id}_{discipline}_R{req.revision}_DXF.zip'
        engine.zip_outputs(generated, package)
        return {
            'ok': True, 'project_id': req.project_id, 'discipline': discipline,
            'engine_version': '0.5.2', 'mode': 'architecture-first-readable-plan-rendering',
            'preliminary': True, 'requires_professional_review': True,
            'systems': systems, 'calculation_report': calc, 'design_reports': reports,
            'generated_files': [p.name for p in generated],
            'pdf_path': str(merged), 'zip_path': str(package),
            'pdf_base64': base64.b64encode(merged.read_bytes()).decode('ascii'),
            'zip_base64': base64.b64encode(package.read_bytes()).decode('ascii'),
        }
