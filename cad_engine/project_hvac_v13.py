"""Project HVAC planner for explicit split-AC + wall-package/radiator systems.

This stage designs new HVAC equipment from room evidence; it does not rely on
pre-existing HVAC blocks in the architectural DXF. Physical routes stay inside
one print plan. Inter-floor service continuity is represented as logical risers.
"""
from __future__ import annotations
import math

COOLING_ROOMS={"bedroom","living"}
HEATING_ROOMS={"bedroom","living","kitchen","bathroom"}
COOLING_CAPACITY_BTU={"bedroom":12000,"living":18000}
RADIATOR_KW={"bedroom":1.5,"living":2.5,"kitchen":1.5,"bathroom":0.7}


def _manhattan(a,b):
    if not a or not b:return []
    mid=(b[0],a[1])
    pts=[tuple(a)]
    if mid!=pts[-1]:pts.append(mid)
    if tuple(b)!=pts[-1]:pts.append(tuple(b))
    return pts


def _inside(p,b,t=1e-6):
    return bool(b) and b[0]-t<=p[0]<=b[2]+t and b[1]-t<=p[1]<=b[3]+t


def design_project_hvac(architecture,project_overrides=None):
    cfg=project_overrides or {}; hvac=cfg.get("hvac") or {}
    if hvac.get("cooling") not in {"split_ac","split","کولر گازی"} or hvac.get("heating") not in {"package_radiator","package-radiator","پکیج-شوفاژ"}:
        return {"version":"project-hvac-v13.13","status":"SKIPPED","equipment":[],"routes":[],"vertical_links":[],"design_basis":hvac}
    plans={p["plan_id"]:p for p in architecture.get("plans") or [] if p.get("mechanical_role")=="PRIMARY_FLOOR"}
    rooms=[r for r in architecture.get("rooms") or [] if r.get("plan_id") in plans]
    equipment=[];routes=[];vertical=[]
    by_plan={pid:[r for r in rooms if r.get("plan_id")==pid] for pid in plans}

    # Package: one for ground dwelling; one on Level-01 for the duplex Levels 01+02.
    package_plans=[]
    for pid,p in plans.items():
        if p.get("level") in {"GROUND","LEVEL-01"}:package_plans.append(pid)
    package_point={}
    for pid in package_plans:
        candidates=[r for r in by_plan[pid] if r.get("type")=="kitchen"] or by_plan[pid]
        if not candidates:continue
        base=candidates[0].get("label_point"); point=(base[0]+0.55,base[1])
        if not _inside(point,plans[pid]["bounds"]):point=base
        eid=f"PKG-{pid}";package_point[pid]=point
        equipment.append({"id":eid,"kind":"package","plan_id":pid,"point":point,"capacity_kw":24,
                          "note":"wall-mounted condensing package; final combustion/flue check required"})

    # A stable relative riser point lets the duplex upper floor connect logically,
    # never by a physical line to a different frame.
    level01=next((pid for pid,p in plans.items() if p.get("level")=="LEVEL-01"),None)
    level02=next((pid for pid,p in plans.items() if p.get("level")=="LEVEL-02"),None)
    if level01 and level02 and package_point.get(level01):
        b1=plans[level01]["bounds"]; b2=plans[level02]["bounds"]
        rel=(0.67,0.39); r1=(b1[0]+(b1[2]-b1[0])*rel[0],b1[1]+(b1[3]-b1[1])*rel[1]); r2=(b2[0]+(b2[2]-b2[0])*rel[0],b2[1]+(b2[3]-b2[1])*rel[1])
        vertical.append({"id":"H-RISER-DUPLEX","system":"heating","from_plan":level01,"to_plan":level02,"from_point":r1,"to_point":r2,
                         "representation":"logical_riser_only"})

    for pid,p in plans.items():
        floor_rooms=by_plan[pid]; b=p["bounds"]
        terraces=[r for r in floor_rooms if r.get("type")=="terrace"]
        wet=[r for r in floor_rooms if r.get("type") in {"bathroom","toilet","kitchen"}]
        # Split AC indoors + outdoor unit + refrigerant/condensate routes.
        split_rooms=[r for r in floor_rooms if r.get("type") in COOLING_ROOMS]
        for n,r in enumerate(split_rooms,1):
            ip=r.get("label_point"); iid=f"AC-I-{pid}-{n:02d}"
            capacity=COOLING_CAPACITY_BTU.get(r.get("type"),12000)
            equipment.append({"id":iid,"kind":"split_indoor","plan_id":pid,"point":ip,"capacity_btu_h":capacity,"room_id":r.get("id")})
            if terraces:
                target=min(terraces,key=lambda x:math.dist(ip,x.get("label_point")))['label_point']
            else:
                target=(b[0]+0.55,b[1]+1.5+n*0.55)
            oid=f"AC-O-{pid}-{n:02d}";equipment.append({"id":oid,"kind":"split_outdoor","plan_id":pid,"point":target,"capacity_btu_h":capacity,"serves":iid})
            routes.append({"id":f"REF-{pid}-{n:02d}","system":"refrigerant","plan_id":pid,"points":_manhattan(ip,target),"from":iid,"to":oid})
            if wet:
                drain=min(wet,key=lambda x:math.dist(ip,x.get("label_point")))['label_point']
                routes.append({"id":f"COND-{pid}-{n:02d}","system":"condensate","plan_id":pid,"points":_manhattan(ip,drain),"from":iid,"to_room":min(wet,key=lambda x:math.dist(ip,x.get("label_point"))).get("id"),"slope_percent":1.0})

        # Radiators and hydronic branches.
        heat_rooms=[r for r in floor_rooms if r.get("type") in HEATING_ROOMS]
        if p.get("level")=="LEVEL-02" and level02:
            link=next((x for x in vertical if x.get("to_plan")==pid),None); source=link.get("to_point") if link else None; source_id="H-RISER-DUPLEX"
        else:
            source=package_point.get(pid);source_id=f"PKG-{pid}"
        for n,r in enumerate(heat_rooms,1):
            rp=r.get("label_point"); rid=f"RAD-{pid}-{n:02d}"; kw=RADIATOR_KW.get(r.get("type"),1.2)
            equipment.append({"id":rid,"kind":"radiator","plan_id":pid,"point":rp,"capacity_kw":kw,"room_id":r.get("id")})
            if source:
                routes.append({"id":f"HF-{pid}-{n:02d}","system":"heating_flow","plan_id":pid,"points":_manhattan(source,rp),"from":source_id,"to":rid,"pipe_mm":20})
                ret=[(x,y-0.08) for x,y in _manhattan(rp,source)]
                routes.append({"id":f"HR-{pid}-{n:02d}","system":"heating_return","plan_id":pid,"points":ret,"from":rid,"to":source_id,"pipe_mm":20})
    bad=[r for r in routes if not r.get("points") or any(not _inside(pt,plans[r["plan_id"]]["bounds"],0.15) for pt in r["points"])]
    return {"version":"project-hvac-v13.13","status":"PASS" if not bad else "FAIL","equipment":equipment,"routes":routes,"vertical_links":vertical,
            "design_basis":{"city":hvac.get("city"),"cooling":"split_ac","heating":"package_radiator","climate_status":"PROJECT_OVERRIDE",
                            "capacity_status":"PRELIMINARY_UNTIL_ENVELOPE_AND_DESIGN_DAY_VERIFIED"},
            "quality":{"primary_plans":len(plans),"equipment":len(equipment),"routes":len(routes),"cross_plan_routes":0,"out_of_bounds":len(bad)}}
