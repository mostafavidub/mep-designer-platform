"""Fail-closed roof catchment, drain and downpipe design."""
from __future__ import annotations

from hashlib import sha256
import json


APPENDIX7_VERTICAL = (
    {"dn_mm": 80, "area_m2": 598, "flow_lps": 4.22},
    {"dn_mm": 100, "area_m2": 1286, "flow_lps": 9.07},
    {"dn_mm": 125, "area_m2": 2335, "flow_lps": 16.44},
    {"dn_mm": 150, "area_m2": 3792, "flow_lps": 26.71},
    {"dn_mm": 200, "area_m2": 8178, "flow_lps": 57.52},
)
APPENDIX7_HORIZONTAL = {
    1.0: ((80, 305, 2.15), (100, 698, 4.92), (125, 1241, 8.75), (150, 1988, 14.02),
          (200, 4275, 30.16), (250, 7695, 54.29), (300, 12379, 87.34), (375, 20260, 142.94)),
    2.0: ((80, 431, 3.04), (100, 985, 6.95), (125, 1754, 12.37), (150, 2806, 19.8),
          (200, 6059, 42.75), (250, 10855, 76.59), (300, 17472, 123.27), (375, 31226, 220.31)),
    4.0: ((80, 611, 4.31), (100, 1397, 9.85), (125, 2483, 17.52), (150, 3977, 28.06),
          (200, 8550, 60.32), (250, 15984, 112.52), (300, 24758, 174.68), (375, 44238, 312.12)),
}


def _polygon_area(points):
    return abs(sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1]
                   for i in range(len(points)))/2)


def _inside(point, polygon):
    x,y=point; inside=False; j=len(polygon)-1
    for i in range(len(polygon)):
        xi,yi=polygon[i]; xj,yj=polygon[j]
        if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/(yj-yi)+xi:inside=not inside
        j=i
    return inside


def _calc_id(payload):
    seed=json.dumps(payload,sort_keys=True,separators=(',',':'))
    return 'CALC-RW-'+sha256(seed.encode()).hexdigest()[:12].upper()


def _appendix7_size(table, effective_area_m2, rainfall_intensity_mm_h):
    corrected_demand = float(effective_area_m2) * float(rainfall_intensity_mm_h) / 25.4
    for row in table:
        dn, area, flow = ((row["dn_mm"], row["area_m2"], row["flow_lps"])
                          if isinstance(row, dict) else row)
        if corrected_demand <= float(area):
            return float(dn), float(area), float(flow), corrected_demand
    return None, None, None, corrected_demand


def _effective_areas(catchments):
    """Return source-bounded effective areas; each upstream identity is consumed once."""
    direct = {}
    transfers = {}
    for row in catchments:
        identity = str(row.get("id", "UNKNOWN"))
        plan_area = _polygon_area(row.get("polygon") or [])
        walls = row.get("contributing_wall_areas_m2")
        upstream = row.get("upstream_transfer_ids")
        if walls is None or upstream is None:
            continue
        direct[identity] = plan_area + 0.5 * sum(float(value) for value in walls)
        transfers[identity] = [str(value) for value in upstream]
    resolved = {}
    visiting = set()
    def visit(identity):
        if identity in resolved:
            return resolved[identity]
        if identity in visiting:
            raise ValueError("RAINWATER_TRANSFER_CYCLE")
        if identity not in direct:
            raise ValueError(f"RAINWATER_TRANSFER_UNKNOWN:{identity}")
        visiting.add(identity)
        seen = set(); total = direct[identity]
        for upstream in transfers[identity]:
            if upstream in seen:
                raise ValueError(f"RAINWATER_TRANSFER_DUPLICATE:{identity}:{upstream}")
            seen.add(upstream); total += visit(upstream)
        visiting.remove(identity); resolved[identity] = total
        return total
    for identity in direct:
        visit(identity)
    return resolved


def design_roof_rainwater(roof, design_basis, *, rule_context=None,
                          draft_assumption_basis=None, llm_suggestions=None):
    """Build actual catchment-to-drain-to-stack records from supplied geometry."""
    required_roof={'roof_id','boundary','catchments','stacks'}
    required_basis={'rainfall_intensity_mm_h','runoff_coefficient','minimum_slope_percent',
                    'drain_capacity_table','downpipe_capacity_table'}
    missing=[f'roof.{x}' for x in sorted(required_roof-set(roof or {}))]
    missing += [f'design_basis.{x}' for x in sorted(required_basis-set(design_basis or {}))]
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':missing,'catchments':[],'segments':[]}
    boundary=roof['boundary']
    if len(boundary)<3:return {'status':'FAIL','errors':['ROOF_BOUNDARY_INVALID'],'catchments':[],'segments':[]}
    if not roof['catchments']:return {'status':'INPUT_REQUIRED','missing_inputs':['roof.catchments'],'catchments':[],'segments':[]}
    stack_ids={row.get('id') for row in roof['stacks']}; rows=[];segments=[];errors=[];missing=[]
    appendix_method = design_basis.get('approved_engineering_method') == 'M16_APPENDIX_7'
    effective_areas = {}
    if appendix_method:
        for catchment in roof['catchments']:
            cid=catchment.get('id','UNKNOWN')
            if catchment.get('contributing_wall_areas_m2') is None:
                missing.append(f'catchment.{cid}.contributing_wall_areas_m2')
            if catchment.get('upstream_transfer_ids') is None:
                missing.append(f'catchment.{cid}.upstream_transfer_ids')
        if not missing:
            try:
                effective_areas = _effective_areas(roof['catchments'])
            except ValueError as exc:
                errors.append(str(exc))
    for catchment in roof['catchments']:
        cid=catchment.get('id','UNKNOWN')
        for key in ('id','polygon','low_point','drain','stack_id','slope_percent','emergency_overflow'):
            if key not in catchment:missing.append(f'catchment.{cid}.{key}')
        if any(key not in catchment for key in ('polygon','low_point','drain','stack_id','slope_percent','emergency_overflow')):continue
        polygon=catchment['polygon']; drain=catchment['drain'] or {}
        if len(polygon)<3 or not _inside(catchment['low_point'],polygon):errors.append(f'{cid}:LOW_POINT_OUTSIDE_CATCHMENT')
        if not _inside(catchment['low_point'],boundary):errors.append(f'{cid}:LOW_POINT_OUTSIDE_ROOF')
        if catchment['stack_id'] not in stack_ids:errors.append(f'{cid}:UNKNOWN_STACK')
        if float(catchment['slope_percent'])<float(design_basis['minimum_slope_percent']):errors.append(f'{cid}:SLOPE_BELOW_MINIMUM')
        if not catchment['emergency_overflow']:missing.append(f'catchment.{cid}.emergency_overflow')
        if not drain.get('id') or not drain.get('point'):missing.append(f'catchment.{cid}.drain.id/point')
        elif tuple(drain['point'])!=tuple(catchment['low_point']):errors.append(f'{cid}:DRAIN_NOT_AT_LOW_POINT')
        area=_polygon_area(polygon)
        effective_area=effective_areas.get(str(cid),area)
        flow=effective_area*float(design_basis['rainfall_intensity_mm_h'])*float(design_basis['runoff_coefficient'])/3600
        horizontal_pipe_slope = catchment.get('horizontal_pipe_slope_percent')
        appendix_evidence = None
        if appendix_method and horizontal_pipe_slope is not None and float(horizontal_pipe_slope) in APPENDIX7_HORIZONTAL:
            drain_dn, vertical_area, vertical_flow, corrected = _appendix7_size(
                APPENDIX7_VERTICAL, effective_area, design_basis['rainfall_intensity_mm_h'])
            pipe_dn, horizontal_area, horizontal_flow, _ = _appendix7_size(
                APPENDIX7_HORIZONTAL[float(horizontal_pipe_slope)], effective_area,
                design_basis['rainfall_intensity_mm_h'])
            appendix_evidence = {"base_rainfall_mm_h":25.4,"corrected_area_demand_m2":round(corrected,3),
                "vertical_table_area_m2":vertical_area,"vertical_table_flow_lps":vertical_flow,
                "horizontal_slope_percent":float(horizontal_pipe_slope),
                "horizontal_table_area_m2":horizontal_area,"horizontal_table_flow_lps":horizontal_flow,
                "printed_anomaly_preserved":bool(pipe_dn==250 and float(horizontal_pipe_slope)==4.0)}
        elif appendix_method:
            drain_dn=pipe_dn=None
            errors.append(f'{cid}:APPENDIX7_HORIZONTAL_SLOPE_NOT_PRINTED')
        else:
            drain_sizes=[x for x in design_basis['drain_capacity_table'] if flow<=float(x['max_flow_lps'])]
            pipe_sizes=[x for x in design_basis['downpipe_capacity_table'] if flow<=float(x['max_flow_lps'])]
            drain_dn=min((float(x['dn_mm']) for x in drain_sizes),default=None)
            pipe_dn=min((float(x['dn_mm']) for x in pipe_sizes),default=None)
        if drain_dn is None:errors.append(f'{cid}:NO_DRAIN_CAPACITY_MATCH')
        if pipe_dn is None:errors.append(f'{cid}:NO_DOWNPIPE_CAPACITY_MATCH')
        calc_id=_calc_id({'catchment':catchment,'basis':design_basis})
        roof_surface_slope = catchment.get('roof_surface_slope_percent', catchment.get('slope_percent'))
        rows.append({'catchment_id':cid,'area_m2':round(area,3),'effective_area_m2':round(effective_area,3),
                     'contributing_wall_area_m2':round(sum(float(x) for x in catchment.get('contributing_wall_areas_m2') or []),3),
                     'upstream_transfer_ids':list(catchment.get('upstream_transfer_ids') or []),
                     'rainfall_intensity_mm_h':float(design_basis['rainfall_intensity_mm_h']),
                     'design_flow_lps':round(flow,4),'low_point':catchment['low_point'],'drain_id':drain.get('id'),
                     'drain_dn_mm':drain_dn,'stack_id':catchment['stack_id'],'downpipe_dn_mm':pipe_dn,
                     'slope_percent':float(catchment['slope_percent']),
                     'roof_surface_slope_percent':float(roof_surface_slope),
                     'horizontal_pipe_slope_percent':(
                         float(horizontal_pipe_slope) if horizontal_pipe_slope is not None else None),
                     'emergency_overflow':catchment['emergency_overflow'],
                     'appendix7_evidence':appendix_evidence,'calc_id':calc_id})
        segments.append({'id':f"RW-{cid}-DRAIN",'from':drain.get('id'),'to':catchment['stack_id'],
                         'system':'rainwater','size_mm':pipe_dn,
                         'network_path_id':f"RW-PATH-{cid}",'flow_order':0,
                         'roof_surface_slope_percent':float(roof_surface_slope),
                         'horizontal_pipe_slope_percent':(
                             float(horizontal_pipe_slope) if horizontal_pipe_slope is not None else None),
                         'calc_id':calc_id,'plan_id':calc_id,'riser_id':calc_id,'schedule_id':calc_id})
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'errors':errors,'catchments':rows,'segments':segments}
    result = {'status':'PASS' if not errors else 'FAIL','errors':errors,'roof_id':roof['roof_id'],
            'roof_boundary':boundary,'catchments':rows,'segments':segments,'stacks':roof['stacks'],
            'coverage':{'catchments':len(rows),'drains':len({x['drain_id'] for x in rows}),
                        'all_catchments_drained':len(rows)==len(roof['catchments']) and all(x['drain_id'] for x in rows)},
            'identity_policy':'Catchment -> Drain -> Segment -> Stack retains Calc ID'}
    from .rainwater_rulebook import evaluate_rainwater_rules
    rule_snapshot = {
        'roof': roof, 'design_basis': design_basis,
        'rule_context': rule_context or {},
        'draft_assumption_basis': draft_assumption_basis or {},
        'calculated_segments': segments, 'calculated_catchments': rows,
    }
    result['rule_evaluation'] = evaluate_rainwater_rules(
        rule_snapshot, llm_suggestions=llm_suggestions)
    result['design_compliance_status'] = result['rule_evaluation']['status']
    result['release_allowed'] = False
    return result
