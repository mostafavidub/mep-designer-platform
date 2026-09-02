"""Heating, cooling and ventilation completion/QA layer for mechanical v11."""


def _families(calc):
    return {str(x.get('family') or '') for x in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []}


def _line_count(msp, layer):
    return sum(1 for e in msp if e.dxftype() in {'LINE','LWPOLYLINE'} and str(getattr(e.dxf,'layer','')) == layer)


def _ensure_blocks(doc):
    defs = {
        'ET_M_OUTDOOR_UNIT':'OU', 'ET_M_MAKEUP_AIR':'MA', 'ET_M_AIR_DISCHARGE':'AD',
    }
    for name, tag in defs.items():
        if name in doc.blocks:
            continue
        block=doc.blocks.new(name=name)
        block.add_lwpolyline([(-.15,-.12),(.15,-.12),(.15,.12),(-.15,.12),(-.15,-.12)])
        block.add_text(tag,dxfattribs={'height':.07}).set_placement((-.09,-.025))


def install(v10_4):
    if getattr(v10_4,'_hvac_v11_installed',False):
        return
    original=v10_4._add_shared_distribution_networks

    def with_hvac(doc, levels, model, calc):
        report=dict(original(doc, levels, model, calc) or {})
        families=_families(calc); msp=doc.modelspace(); _ensure_blocks(doc); v10_4._ensure_symbol_blocks(doc)
        checks={}; conditioned=[]; exhaust_levels=[]
        for level in levels:
            if v10_4.v8._is_roof(level):
                continue
            hab=[r for r in level.get('rooms',[]) if r.get('room') in {'bedroom','living','office','shop'} and r.get('point')]
            wet=[r for r in level.get('rooms',[]) if r.get('room') in {'bath','toilet','kitchen','parking'} and r.get('point')]
            if hab: conditioned.append(level)
            if wet: exhaust_levels.append(level)

        if 'heating' in families and levels:
            checks['heating_supply_network']=_line_count(msp,'ENGITOOLS-M-HEATING_SUPPLY') >= max(1,len(conditioned))
            checks['heating_return_network']=_line_count(msp,'ENGITOOLS-M-HEATING_RETURN') >= max(1,len(conditioned))
            checks['heating_load_resolved']=model.get('heating_load_kw') not in (None,'',False) and model.get('per_room_heating_kw') not in (None,'',False)

        if 'cooling' in families and levels:
            checks['cooling_network']=_line_count(msp,'ENGITOOLS-M-COOLING') >= max(1,len(conditioned))
            checks['condensate_network']=_line_count(msp,'ENGITOOLS-M-CONDENSATE') >= max(1,len(conditioned))
            checks['cooling_load_resolved']=model.get('cooling_load_kw') not in (None,'',False) and model.get('per_room_cooling_kw') not in (None,'',False)
            # Add one explicit outdoor-unit coordination point where a real roof
            # exists; otherwise the Equipment special sheet remains schematic.
            roofs=[x for x in levels if v10_4.v8._is_roof(x)]
            if roofs:
                roof=roofs[0]
                point=tuple((roof.get('title') or {}).get('point') or (0.0,0.0))
                point=(float(point[0])+2.0,float(point[1])+2.0)
                msp.add_blockref('ET_M_OUTDOOR_UNIT',point,dxfattribs={'layer':'ENGITOOLS-M-COOLING'})
                v10_4._plan_text(msp,'OUTDOOR UNIT / SERVICE CLEARANCE [COORDINATE]',point,'ENGITOOLS-M-COOLING',(.25,.2))

        if 'ventilation_exhaust' in families and levels:
            # The base engine already routes exhaust to the riser. Add explicit
            # make-up-air and safe-discharge endpoints, which were previously
            # present only as prose in the schedule.
            makeup=discharge=0
            for level in exhaust_levels:
                hub=v10_4.v8._find_level_riser(msp,level)
                if not hub:
                    continue
                bounds=v10_4.v8._level_bounds(level,[])
                make=(bounds[0]+.5,bounds[1]+.5)
                out=(bounds[2]-.5,bounds[3]-.5)
                msp.add_blockref('ET_M_MAKEUP_AIR',make,dxfattribs={'layer':'ENGITOOLS-M-EXHAUST_VENTILATION'}); makeup+=1
                msp.add_blockref('ET_M_AIR_DISCHARGE',out,dxfattribs={'layer':'ENGITOOLS-M-EXHAUST_VENTILATION'}); discharge+=1
                msp.add_line(make,hub,dxfattribs={'layer':'ENGITOOLS-M-EXHAUST_VENTILATION'})
                msp.add_line(hub,out,dxfattribs={'layer':'ENGITOOLS-M-EXHAUST_VENTILATION'})
                v10_4._plan_text(msp,'MAKE-UP AIR [RULE-BASED PROPOSED]',make,'ENGITOOLS-M-EXHAUST_VENTILATION',(.2,.18))
                v10_4._plan_text(msp,'SAFE EXHAUST DISCHARGE [COORDINATE]',out,'ENGITOOLS-M-EXHAUST_VENTILATION',(.2,.18))
            checks['ventilation_network']=_line_count(msp,'ENGITOOLS-M-EXHAUST_VENTILATION') >= max(1,len(exhaust_levels))
            checks['ventilation_airflow_resolved']=model.get('ventilation_airflow_m3h') not in (None,'',False)
            checks['makeup_air_points']=makeup >= max(1,len(exhaust_levels))
            checks['safe_discharge_points']=discharge >= max(1,len(exhaust_levels))

        failed=[k for k,v in checks.items() if not v]
        report['hvac_ventilation']={'status':'PASS' if not failed else 'FAIL','checks':checks}
        report['hvac_ventilation_status']=report['hvac_ventilation']['status']
        if failed:
            raise RuntimeError('HVAC/Ventilation network QA failed: '+', '.join(failed))
        return report

    v10_4._add_shared_distribution_networks=with_hvac
    v10_4._hvac_v11_installed=True
