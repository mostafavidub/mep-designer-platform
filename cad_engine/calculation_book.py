"""Manufacturer-aware calculation-book assembly and selection verification."""
from __future__ import annotations


def _curve_capacity(points, x):
    rows=sorted((float(a),float(b)) for a,b in points or [])
    if not rows or x<rows[0][0] or x>rows[-1][0]:return None
    for (x1,y1),(x2,y2) in zip(rows,rows[1:]):
        if x1<=x<=x2:
            return y1 if x2==x1 else y1+(y2-y1)*(x-x1)/(x2-x1)
    return rows[-1][1]


def build_calculation_book(calculations, equipment_checks, declared_equipment_ids):
    """Require every declared equipment tag to have a traceable final selection check."""
    if not calculations:return {'status':'INPUT_REQUIRED','missing_inputs':['CALCULATION_ROWS'],'sections':[]}
    required={'equipment_id','calc_id','source_pmm_ids','calculated_load','selected_capacity','selection_margin_percent',
              'manufacturer','model','manufacturer_limits','route_length_m','elevation_m','status'}
    missing=[];errors=[];sections=[]
    by_id={row.get('equipment_id'):row for row in equipment_checks or []}
    if len(by_id)!=len(equipment_checks or []):errors.append('DUPLICATE_EQUIPMENT_SELECTION_CHECK')
    unverified=sorted(set(declared_equipment_ids or [])-set(by_id))
    undeclared=sorted(set(by_id)-set(declared_equipment_ids or []))
    if unverified:missing.extend(f'EQUIPMENT_SELECTION_CHECK:{x}' for x in unverified)
    if undeclared:errors.append('UNDECLARED_EQUIPMENT_SELECTION_CHECK:'+','.join(undeclared))
    for check in equipment_checks or []:
        eid=check.get('equipment_id','UNKNOWN')
        missing.extend(f'{eid}:{key}' for key in sorted(required-set(check)))
        if required-set(check):continue
        if not check['source_pmm_ids']:missing.append(f'{eid}:source_pmm_ids')
        limits=check['manufacturer_limits'] or {}
        for key in ('max_route_length_m','max_elevation_m'):
            if key not in limits:missing.append(f'{eid}:manufacturer_limits.{key}')
        computed_margin=(float(check['selected_capacity'])/float(check['calculated_load'])-1)*100 if float(check['calculated_load']) else 0
        if abs(computed_margin-float(check['selection_margin_percent']))>0.05:errors.append(f'{eid}:SELECTION_MARGIN_MISMATCH')
        if float(check['selected_capacity'])<float(check['calculated_load']):errors.append(f'{eid}:CAPACITY_BELOW_LOAD')
        if limits.get('max_route_length_m') is not None and float(check['route_length_m'])>float(limits['max_route_length_m']):errors.append(f'{eid}:ROUTE_LIMIT_EXCEEDED')
        if limits.get('max_elevation_m') is not None and float(check['elevation_m'])>float(limits['max_elevation_m']):errors.append(f'{eid}:ELEVATION_LIMIT_EXCEEDED')
        curve_check=None
        if check.get('equipment_type')=='pump':
            duty=check.get('operating_point') or {}; curve=check.get('pump_curve') or []
            if not {'flow_lps','head_m'}<=set(duty) or not curve:missing.append(f'{eid}:OPERATING_POINT_AND_PUMP_CURVE')
            else:
                available=_curve_capacity(curve,float(duty['flow_lps']))
                curve_check={'x':duty['flow_lps'],'required':duty['head_m'],'available':available}
                if available is None or available<float(duty['head_m']):errors.append(f'{eid}:PUMP_OPERATING_POINT_OFF_CURVE')
        if check.get('equipment_type')=='fan':
            duty=check.get('fan_duty') or {}; curve=check.get('fan_curve') or []
            if not {'cfm','esp_pa'}<=set(duty) or not curve:missing.append(f'{eid}:CFM_ESP_AND_FAN_CURVE')
            else:
                available=_curve_capacity(curve,float(duty['cfm']))
                curve_check={'x':duty['cfm'],'required':duty['esp_pa'],'available':available}
                if available is None or available<float(duty['esp_pa']):errors.append(f'{eid}:FAN_DUTY_OFF_CURVE')
        sections.append({'kind':'equipment_selection_check','equipment_id':eid,'calc_id':check['calc_id'],
                         'source_pmm_ids':check['source_pmm_ids'],'calculated_load':check['calculated_load'],
                         'selected_capacity':check['selected_capacity'],'selection_margin_percent':check['selection_margin_percent'],
                         'manufacturer':check['manufacturer'],'model':check['model'],'manufacturer_limits':limits,
                         'route_length_m':check['route_length_m'],'elevation_m':check['elevation_m'],
                         'curve_check':curve_check,'status':check['status']})
        if check['status']!='PASS':errors.append(f'{eid}:SELECTION_STATUS_{check["status"]}')
    calc_ids={row.get('calc_id') for row in calculations}; unknown=sorted(row['calc_id'] for row in sections if row['calc_id'] not in calc_ids)
    if unknown:errors.append('SELECTION_WITHOUT_CALCULATION:'+','.join(unknown))
    status='INPUT_REQUIRED' if missing else ('FAIL' if errors else 'PASS')
    return {'status':status,'missing_inputs':sorted(set(missing)),'errors':errors,'calculations':calculations,
            'sections':sections,'coverage':{'declared':len(declared_equipment_ids or []),'checked':len(sections),
            'unverified_equipment_ids':unverified,'complete':not unverified},
            'identity_policy':'PMM -> Calculation -> Manufacturer Selection Check'}
