import base64
import shutil
import tempfile
from pathlib import Path

import ezdxf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

from . import main_v4  # installs structured-input normalization onto main_v3
from . import main_v3 as engine

app = FastAPI(title='EngiTools CAD Designer', version='0.5.1')

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


def render_pdf_resilient(dxf_path, pdf_path, discipline):
    """Render a DXF without allowing one unsupported entity to blank the whole sheet.

    First use ezdxf's normal layout renderer. If any entity makes that pass fail,
    retry entity-by-entity, skipping only the incompatible entities. A PDF is only
    written when real geometry was rendered; the old placeholder-only PDF is never
    emitted.
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([.03, .06, .94, .88])
    ax.set_aspect('equal', adjustable='datalim')
    ax.axis('off')
    skipped = []
    rendered = 0
    try:
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        try:
            Frontend(ctx, out).draw_layout(msp, finalize=True)
            rendered = len(msp)
        except Exception as exc:
            print(f'[cad-render] full-layout render failed for {dxf_path.name}: {type(exc).__name__}: {exc}; retrying entity-by-entity', flush=True)
            ax.clear()
            ax.set_aspect('equal', adjustable='datalim')
            ax.axis('off')
            ctx = RenderContext(doc)
            out = MatplotlibBackend(ax)
            frontend = Frontend(ctx, out)
            for entity in msp:
                try:
                    frontend.draw_entities([entity])
                    rendered += 1
                except Exception as entity_exc:
                    skipped.append((entity.dxftype(), str(entity_exc)[:180]))
            out.finalize()
            if skipped:
                sample = '; '.join(f'{kind}: {msg}' for kind, msg in skipped[:8])
                print(f'[cad-render] skipped {len(skipped)} of {len(msp)} entities in {dxf_path.name}: {sample}', flush=True)
        if rendered <= 0:
            raise RuntimeError(f'No renderable DXF entities found in {dxf_path.name}')
        fig.suptitle(
            f'EngiTools {discipline.title()} - PRELIMINARY DESIGN + CALCULATION ASSIST - ENGINEERING REVIEW REQUIRED',
            fontsize=10,
        )
        fig.savefig(pdf_path, format='pdf', bbox_inches='tight')
    finally:
        plt.close(fig)


engine.electrical_calc = electrical_calc
engine.mechanical_calc = mechanical_calc
engine.render_pdf = render_pdf_resilient


@app.get('/health')
def health():
    return {'ok': True, 'service': 'cad-designer', 'version': '0.5.1', 'mode': 'architecture-first-auto-calculation'}


@app.get('/engine-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '0.5.1',
        'questionnaire': 'dynamic-unresolved-only',
        'architecture_auto_calculation': True,
        'resilient_dxf_pdf_rendering': True,
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
            reports.append({'source': src.name, **engine.design_dxf(src, dxf, discipline, systems, req.revision, calc)})
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
            'engine_version': '0.5.1', 'mode': 'architecture-first-auto-calculation',
            'preliminary': True, 'requires_professional_review': True,
            'systems': systems, 'calculation_report': calc, 'design_reports': reports,
            'generated_files': [p.name for p in generated],
            'pdf_path': str(merged), 'zip_path': str(package),
            'pdf_base64': base64.b64encode(merged.read_bytes()).decode('ascii'),
            'zip_base64': base64.b64encode(package.read_bytes()).decode('ascii'),
        }
