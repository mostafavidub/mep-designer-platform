"""Fail-closed roof catchment, drain and downpipe design."""
from __future__ import annotations

from hashlib import sha256
import json


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


def design_roof_rainwater(roof, design_basis):
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
        flow=area*float(design_basis['rainfall_intensity_mm_h'])*float(design_basis['runoff_coefficient'])/3600
        drain_sizes=[x for x in design_basis['drain_capacity_table'] if flow<=float(x['max_flow_lps'])]
        pipe_sizes=[x for x in design_basis['downpipe_capacity_table'] if flow<=float(x['max_flow_lps'])]
        if not drain_sizes:errors.append(f'{cid}:NO_DRAIN_CAPACITY_MATCH')
        if not pipe_sizes:errors.append(f'{cid}:NO_DOWNPIPE_CAPACITY_MATCH')
        calc_id=_calc_id({'catchment':catchment,'basis':design_basis})
        drain_dn=min((float(x['dn_mm']) for x in drain_sizes),default=None)
        pipe_dn=min((float(x['dn_mm']) for x in pipe_sizes),default=None)
        rows.append({'catchment_id':cid,'area_m2':round(area,3),'rainfall_intensity_mm_h':float(design_basis['rainfall_intensity_mm_h']),
                     'design_flow_lps':round(flow,4),'low_point':catchment['low_point'],'drain_id':drain.get('id'),
                     'drain_dn_mm':drain_dn,'stack_id':catchment['stack_id'],'downpipe_dn_mm':pipe_dn,
                     'slope_percent':float(catchment['slope_percent']),'emergency_overflow':catchment['emergency_overflow'],
                     'calc_id':calc_id})
        segments.append({'id':f"RW-{cid}-DRAIN",'from':drain.get('id'),'to':catchment['stack_id'],
                         'system':'rainwater','size_mm':pipe_dn,'slope_percent':float(catchment['slope_percent']),
                         'calc_id':calc_id,'plan_id':calc_id,'riser_id':calc_id,'schedule_id':calc_id})
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'errors':errors,'catchments':rows,'segments':segments}
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'roof_id':roof['roof_id'],
            'roof_boundary':boundary,'catchments':rows,'segments':segments,'stacks':roof['stacks'],
            'coverage':{'catchments':len(rows),'drains':len({x['drain_id'] for x in rows}),
                        'all_catchments_drained':len(rows)==len(roof['catchments']) and all(x['drain_id'] for x in rows)},
            'identity_policy':'Catchment -> Drain -> Segment -> Stack retains Calc ID'}
