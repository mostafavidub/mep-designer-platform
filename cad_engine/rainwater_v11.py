"""Roof rainwater network and viewport-visibility hardening."""


def _families(calc):
    return {str(x.get('family') or '') for x in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []}


def install(v10_4):
    if getattr(v10_4,'_rainwater_v11_installed',False):
        return
    original_symbols=v10_4._add_standard_symbols

    def symbols_with_rain(doc, levels, model):
        count=original_symbols(doc,levels,model)
        msp=doc.modelspace(); routes=0; drains=0
        for level in levels:
            roof_drains=[d for d in (level.get('roof_drains') or []) if d.get('point')]
            if not roof_drains:
                continue
            hub=v10_4.v8._find_level_riser(msp,level)
            if not hub:
                # Roof drawings often have no plumbing fixture/riser marker.
                # Use the centroid only as a Proposed stack location and label it
                # explicitly so it cannot be mistaken for detected architecture.
                xs=[d['point'][0] for d in roof_drains]; ys=[d['point'][1] for d in roof_drains]
                hub=(sum(xs)/len(xs),sum(ys)/len(ys))
                v10_4._plan_text(msp,'RAINWATER STACK LOCATION [RULE-BASED PROPOSED]',hub,'ENGITOOLS-M-ROOF_RAINWATER',(.3,.3))
            for drain in roof_drains:
                point=drain['point']; drains+=1
                # Orthogonal branch to the rainwater stack; this is actual
                # drainage routing geometry, not merely a drain marker.
                elbow=(hub[0],point[1])
                msp.add_line(point,elbow,dxfattribs={'layer':'ENGITOOLS-M-ROOF_RAINWATER'})
                msp.add_line(elbow,hub,dxfattribs={'layer':'ENGITOOLS-M-ROOF_RAINWATER'})
                routes+=2
                mid=((point[0]+elbow[0])/2,(point[1]+elbow[1])/2)
                v10_4._plan_text(
                    msp,
                    f"RW DN{model.get('roof_drain_dn_mm')} | FLOW TO STACK | SLOPE TO RD",
                    mid,'ENGITOOLS-M-ROOF_RAINWATER',(.18,.14),
                )
            v10_4._plan_text(
                msp,
                f"RAINWATER STACK DN{model.get('roof_drain_dn_mm')} | Q={model.get('roof_flow_lps')} L/s [CALCULATED]",
                hub,'ENGITOOLS-M-ROOF_RAINWATER',(.35,-.28),
            )
        model['rainwater_network_drains']=drains
        model['rainwater_network_segments']=routes
        return count+routes

    v10_4._add_standard_symbols=symbols_with_rain
    v10_4._rainwater_v11_installed=True


def validate_rainwater(doc, manifest, model):
    families={str(x.get('family') or '') for x in (manifest or {}).get('sheets') or []}
    if 'roof_rainwater' not in families and not any(str(x.get('code') or '').endswith('-RAIN') for x in (manifest or {}).get('sheets') or []):
        return {'status':'NOT_APPLICABLE'}
    msp=doc.modelspace()
    canonical='ENGITOOLS-M-ROOF_RAINWATER'
    line_count=sum(1 for e in msp if e.dxftype() in {'LINE','LWPOLYLINE'} and str(getattr(e.dxf,'layer',''))==canonical)
    drain_count=sum(1 for e in msp.query('INSERT') if str(e.dxf.name)=='ET_M_ROOF_DRAIN' and str(e.dxf.layer)==canonical)
    required=int(model.get('roof_drain_count') or drain_count or 0)
    checks={
        'roof_drains_present': drain_count>0,
        'drain_count_matches_basis': required==0 or drain_count>=required,
        'rainwater_route_present': line_count>=max(1,drain_count),
        'rainwater_dn_resolved': model.get('roof_drain_dn_mm') not in (None,'',False),
    }
    failed=[k for k,v in checks.items() if not v]
    if failed:
        raise RuntimeError('Rainwater QA failed: '+', '.join(failed))
    return {'status':'PASS','checks':checks,'drains':drain_count,'segments':line_count}
