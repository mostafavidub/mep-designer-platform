"""Project HVAC planner for explicit split-AC + wall-package/radiator systems.

This stage designs new HVAC equipment from room evidence; it does not rely on
pre-existing HVAC blocks in the architectural DXF. Physical routes stay inside
one print plan. It deliberately avoids assuming specific level labels because
consultant DXFs use many naming conventions for otherwise valid primary floors.
"""
from __future__ import annotations
import math
from hashlib import sha256

COOLING_ROOMS={"bedroom","living"}
HEATING_ROOMS={"bedroom","living","kitchen","bathroom"}
COOLING_CAPACITIES_BTU=(9000,12000,18000,24000,30000,36000)
HEATING_ALLOCATION_WEIGHTS={"bedroom":1.0,"living":1.7,"kitchen":0.9,"bathroom":0.55,"toilet":0.35}
PRELIMINARY_HEATING_BASIS={
    "supply_c":75.0,"return_c":55.0,"indoor_c":20.0,
    "fluid_density_kg_m3":983.0,"fluid_specific_heat_j_kgk":4180.0,
    "max_velocity_m_s":1.0,"max_friction_pa_m":300.0,
    "candidate_diameters_mm":[12.0,15.0,20.0,25.0,32.0],
    "pipe_roughness_mm":0.007,"fittings_equivalent_length_factor":1.30,
}


def _manhattan(a,b):
    if not a or not b:return []
    mid=(b[0],a[1])
    pts=[tuple(a)]
    if mid!=pts[-1]:pts.append(mid)
    if tuple(b)!=pts[-1]:pts.append(tuple(b))
    return pts


def _inside(p,b,t=1e-6):
    return bool(b) and b[0]-t<=p[0]<=b[2]+t and b[1]-t<=p[1]<=b[3]+t


def _next_capacity(required_btu, capacities):
    return next((value for value in capacities if value >= required_btu), capacities[-1] if capacities else None)


def _positive_number(value):
    try:
        number=float(value)
    except (TypeError,ValueError):
        return None
    return number if math.isfinite(number) and number>0 else None


def _heating_basis(cfg):
    supplied=dict(cfg.get("heating_design") or {})
    result={}
    preliminary=[]
    for key,default in PRELIMINARY_HEATING_BASIS.items():
        value=supplied.get(key)
        if value in (None,"",[]):
            value=default;preliminary.append(key)
        result[key]=value
    result["design_delta_t_k"]=float(result["supply_c"])-float(result["return_c"])
    result["basis_status"]="PROJECT_CONFIRMED" if not preliminary else "PRELIMINARY_OFFICE_BASIS"
    result["preliminary_fields"]=preliminary
    return result


def _allocate_heating_load(heat_rooms,room_calcs,declared_total_kw):
    """Resolve room duties without treating corrupt tiny polygons as real areas.

    Calculation rows remain authoritative when their sum is physically consistent.
    A user-confirmed project total may be allocated by disclosed room-type weights
    only for Pre-Submission when all room rows are missing/degenerate.  The result
    never represents an envelope heat-loss calculation or Submission Ready evidence.
    """
    raw={}
    for room in heat_rooms:
        calc=room_calcs.get(room.get("id")) or {}
        raw[room.get("id")]=max(0.0,float(calc.get("heating_w") or 0.0))
    calculated_total=sum(raw.values())
    declared_w=(_positive_number(declared_total_kw) or 0.0)*1000.0
    # A total below five percent of an explicit project load is a unit/geometry
    # failure, not a legitimately low heat-loss result.
    degenerate=declared_w>0 and calculated_total < declared_w*0.05
    if degenerate:
        weights={room.get("id"):HEATING_ALLOCATION_WEIGHTS.get(room.get("type"),1.0) for room in heat_rooms}
        total_weight=sum(weights.values()) or 1.0
        return ({rid:declared_w*weight/total_weight for rid,weight in weights.items()},
                "PROJECT_TOTAL_WEIGHTED_ALLOCATION","PRELIMINARY_GEOMETRY_INVALID",calculated_total,declared_w)
    return raw,"ROOM_HEAT_LOSS","PROJECT_CALCULATION",calculated_total,declared_w


def _hydronic_size(load_w,points,basis):
    delta_t=float(basis["design_delta_t_k"])
    density=float(basis["fluid_density_kg_m3"]);cp=float(basis["fluid_specific_heat_j_kgk"])
    flow_m3_s=load_w/(density*cp*delta_t)
    chosen=None
    for dn in sorted(float(x) for x in basis["candidate_diameters_mm"]):
        area=math.pi*(dn/1000.0)**2/4.0
        velocity=flow_m3_s/area if area else float("inf")
        reynolds=velocity*(dn/1000.0)/(0.00000055)
        relative=float(basis["pipe_roughness_mm"])/dn
        friction=0.25/(math.log10(relative/3.7+5.74/max(reynolds,1.0)**0.9)**2) if reynolds>2300 else 64.0/max(reynolds,1.0)
        gradient=friction*density*velocity*velocity/(2.0*(dn/1000.0))
        if velocity<=float(basis["max_velocity_m_s"]) and gradient<=float(basis["max_friction_pa_m"]):
            chosen=(dn,velocity,reynolds,gradient);break
    length=sum(math.dist(points[i-1],points[i]) for i in range(1,len(points)))
    calc_id="CALC-HEAT-"+sha256((str(load_w)+repr(points)).encode()).hexdigest()[:12].upper()
    if not chosen:
        return {"status":"FAIL","calc_id":calc_id,"flow_lps":round(flow_m3_s*1000,4),"error":"NO_COMPLIANT_DIAMETER"}
    dn,velocity,reynolds,gradient=chosen
    eq_length=length*float(basis["fittings_equivalent_length_factor"])
    return {"status":"PASS","calc_id":calc_id,"flow_lps":round(flow_m3_s*1000,4),"pipe_mm":dn,
            "velocity_m_s":round(velocity,3),"reynolds":round(reynolds),"friction_pa_m":round(gradient,1),
            "plan_length":round(length,3),"equivalent_plan_length":round(eq_length,3),
            "pressure_loss_relative":round(gradient*eq_length,1)}


def design_project_hvac(architecture,project_overrides=None,calculations=None):
    cfg=project_overrides or {}; hvac=cfg.get("hvac") or {}
    cooling_enabled=hvac.get("cooling") in {"split_ac","split","کولر گازی"}
    heating_enabled=hvac.get("heating") in {"package_radiator","package-radiator","پکیج-شوفاژ"}
    if not cooling_enabled and not heating_enabled:
        return {"version":"project-hvac-v13.14","status":"SKIPPED","equipment":[],"routes":[],"vertical_links":[],"design_basis":hvac}
    plans={p["plan_id"]:p for p in architecture.get("plans") or [] if p.get("mechanical_role")=="PRIMARY_FLOOR"}
    rooms=[r for r in architecture.get("rooms") or [] if r.get("plan_id") in plans]
    equipment=[];routes=[];vertical=[];engineering_errors=[]
    strict_calculation_linkage=calculations is not None
    room_calcs={row.get("room_id"):row for row in (calculations or {}).get("rooms") or []}
    capacities=tuple(sorted(float(value) for value in (cfg.get("split_capacity_btu_h") or COOLING_CAPACITIES_BTU)))
    by_plan={pid:[r for r in rooms if r.get("plan_id")==pid] for pid in plans}
    all_heat_rooms=[r for r in rooms if heating_enabled and r.get("type") in HEATING_ROOMS]
    heat_loads,heat_source,heat_status,raw_total_w,declared_total_w=_allocate_heating_load(
        all_heat_rooms,room_calcs,cfg.get("heating_load_kw"))
    heating_basis=_heating_basis(cfg)
    if heat_source=="ROOM_HEAT_LOSS" and declared_total_w and abs(raw_total_w-declared_total_w)>declared_total_w*0.20:
        engineering_errors.append("ROOM_AND_PROJECT_HEATING_LOAD_CONFLICT")

    # Do not key heating sources to literal level names. Every primary plan that
    # actually contains heatable rooms receives a traceable local source point.
    # This keeps physical routing plan-local and works with Persian/custom level labels.
    package_point={}
    for pid,p in plans.items():
        floor_rooms=by_plan[pid]
        heat_rooms=[r for r in floor_rooms if heating_enabled and r.get("type") in HEATING_ROOMS]
        if not heat_rooms:
            continue
        candidates=[r for r in floor_rooms if r.get("type")=="kitchen"] or heat_rooms
        base=candidates[0].get("label_point")
        if not base:
            continue
        point=(base[0]+0.55,base[1])
        if not _inside(point,p["bounds"]):point=base
        eid=f"PKG-{pid}";package_point[pid]=point
        calculated_kw=sum(heat_loads.get(r.get("id"),0.0) for r in heat_rooms)/1000.0
        package_kw=max(24.0,math.ceil(calculated_kw*1.15))
        equipment.append({"id":eid,"kind":"package","plan_id":pid,"point":point,"capacity_kw":package_kw,
                          "required_capacity_kw":round(calculated_kw,3),"selection_margin":0.15,
                          "source_calc_room_ids":[r.get("id") for r in heat_rooms],
                          "note":"wall-mounted condensing package; final combustion/flue check required"})

    for pid,p in plans.items():
        floor_rooms=by_plan[pid]; b=p["bounds"]
        terraces=[r for r in floor_rooms if r.get("type")=="terrace"]
        wet=[r for r in floor_rooms if r.get("type") in {"bathroom","toilet","kitchen"}]
        # Split AC indoors + outdoor unit + refrigerant/condensate routes.
        split_rooms=[r for r in floor_rooms if cooling_enabled and r.get("type") in COOLING_ROOMS]
        for n,r in enumerate(split_rooms,1):
            ip=r.get("label_point")
            if not ip:continue
            iid=f"AC-I-{pid}-{n:02d}"; room_calc=room_calcs.get(r.get("id")) or {}
            required_btu=float(room_calc.get("cooling_w") or 0)*3.412142
            geometry_proxy=bool(room_calc and room_calc.get("area_m2") is None)
            if required_btu<=0 and geometry_proxy:
                required_btu=12000 if r.get("type")=="bedroom" else 18000
            if required_btu<=0 and not strict_calculation_linkage:
                required_btu=12000 if r.get("type")=="bedroom" else 18000
            if required_btu<=0:
                continue
            capacity=_next_capacity(required_btu,capacities)
            if not capacity:
                continue
            equipment.append({"id":iid,"kind":"split_indoor","plan_id":pid,"point":ip,"capacity_btu_h":capacity,
                              "required_capacity_btu_h":round(required_btu),"room_id":r.get("id"),
                              "source_calc_id":room_calc.get("calc_id"),
                              "calculation_source":"unenclosed_room_type_proxy" if geometry_proxy else "room_cooling_load","calculation_status":"PRELIMINARY_GEOMETRY_PROXY" if geometry_proxy else "PRELIMINARY_PROJECT_BASIS"})
            if terraces:
                target=min(terraces,key=lambda x:math.dist(ip,x.get("label_point")))['label_point']
            else:
                target=(b[0]+0.55,b[1]+1.5+n*0.55)
            oid=f"AC-O-{pid}-{n:02d}";equipment.append({"id":oid,"kind":"split_outdoor","plan_id":pid,"point":target,"capacity_btu_h":capacity,"serves":iid})
            routes.append({"id":f"REF-{pid}-{n:02d}","system":"refrigerant","plan_id":pid,"points":_manhattan(ip,target),"from":iid,"to":oid})
            if wet:
                target_room=min(wet,key=lambda x:math.dist(ip,x.get("label_point")))
                drain=target_room['label_point']
                routes.append({"id":f"COND-{pid}-{n:02d}","system":"condensate","plan_id":pid,"points":_manhattan(ip,drain),"from":iid,"to_room":target_room.get("id"),"slope_percent":1.0})

        # Radiators and hydronic branches stay entirely inside the same print plan.
        source=package_point.get(pid);source_id=f"PKG-{pid}"
        heat_rooms=[r for r in floor_rooms if heating_enabled and r.get("type") in HEATING_ROOMS]
        for n,r in enumerate(heat_rooms,1):
            rp=r.get("label_point")
            if not rp:continue
            rid=f"RAD-{pid}-{n:02d}"; room_calc=room_calcs.get(r.get("id")) or {}
            required_kw=float(heat_loads.get(r.get("id"),0.0))/1000.0
            geometry_proxy=bool(room_calc and room_calc.get("area_m2") is None)
            if required_kw<=0 and geometry_proxy:
                required_kw={"bedroom":1.5,"living":2.5,"kitchen":1.5,"bathroom":.7}.get(r.get("type"),1.2)
            if required_kw<=0 and not strict_calculation_linkage:
                required_kw={"bedroom":1.5,"living":2.5,"kitchen":1.5,"bathroom":.7}.get(r.get("type"),1.2)
            kw=math.ceil(required_kw*1.10*10)/10 if required_kw>0 else 0
            if kw<=0:
                continue
            source_calc_id=room_calc.get("calc_id") or ("CALC-HEAT-ALLOC-"+sha256(str(r.get("id")).encode()).hexdigest()[:12].upper() if heat_source=="PROJECT_TOTAL_WEIGHTED_ALLOCATION" else None)
            equipment.append({"id":rid,"kind":"radiator","plan_id":pid,"point":rp,"capacity_kw":kw,
                              "required_capacity_kw":round(required_kw,3),"room_id":r.get("id"),
                              "source_calc_id":source_calc_id,
                              "calculation_source":heat_source if heat_source!="ROOM_HEAT_LOSS" else ("unenclosed_room_type_proxy" if geometry_proxy else "room_heating_load"),
                              "calculation_status":heat_status if heat_source!="ROOM_HEAT_LOSS" else ("PRELIMINARY_GEOMETRY_PROXY" if geometry_proxy else "PRELIMINARY_PROJECT_BASIS"),
                              "selection_status":"DESIGN_ENVELOPE","placement_basis":"ROOM_IDENTITY_POINT; EXTERNAL_WALL/WINDOW CONFIRMATION REQUIRED"})
            if source:
                flow_points=_manhattan(source,rp);flow_calc=_hydronic_size(kw*1000.0,flow_points,heating_basis)
                if flow_calc.get("status")!="PASS":engineering_errors.append(f"{rid}:{flow_calc.get('error')}")
                routes.append({"id":f"HF-{pid}-{n:02d}","system":"heating_flow","plan_id":pid,"points":flow_points,"from":source_id,"to":rid,**flow_calc})
                ret=[(x,y-0.08) for x,y in _manhattan(rp,source)]
                return_calc=_hydronic_size(kw*1000.0,ret,heating_basis)
                if return_calc.get("status")!="PASS":engineering_errors.append(f"{rid}:{return_calc.get('error')}")
                routes.append({"id":f"HR-{pid}-{n:02d}","system":"heating_return","plan_id":pid,"points":ret,"from":rid,"to":source_id,**return_calc})
    bad=[r for r in routes if not r.get("points") or any(not _inside(pt,plans[r["plan_id"]]["bounds"],0.15) for pt in r["points"])]
    radiators=[row for row in equipment if row.get("kind")=="radiator"]
    heating_routes=[row for row in routes if row.get("system") in {"heating_flow","heating_return"}]
    orphan_rooms=sorted(r.get("id") for r in all_heat_rooms if r.get("id") not in {x.get("room_id") for x in radiators})
    orphan_radiators=sorted(x["id"] for x in radiators if sum(1 for r in heating_routes if x["id"] in {r.get("from"),r.get("to")})!=2)
    if orphan_rooms:engineering_errors.append("UNSERVED_HEATING_ROOMS:"+",".join(orphan_rooms))
    if orphan_radiators:engineering_errors.append("ORPHAN_HEATING_TERMINALS:"+",".join(orphan_radiators))
    total_duty=sum(float(x.get("required_capacity_kw") or 0) for x in radiators)*1000.0
    tolerance=max(10.0,(declared_total_w or raw_total_w)*0.01)
    load_reconciled=abs(total_duty-(declared_total_w if heat_source=="PROJECT_TOTAL_WEIGHTED_ALLOCATION" else raw_total_w))<=tolerance
    if heating_enabled and all_heat_rooms and not load_reconciled:engineering_errors.append("HEATING_LOAD_NOT_RECONCILED")
    status="PASS" if not bad and not engineering_errors else "FAIL"
    return {"runtime_identity":"project-hvac","status":status,"equipment":equipment,"routes":routes,"vertical_links":vertical,
            "design_basis":{"city":hvac.get("city"),"cooling":"split_ac","heating":"package_radiator","climate_status":"PROJECT_OVERRIDE",
                            "capacity_status":"PRELIMINARY_UNTIL_ENVELOPE_AND_DESIGN_DAY_VERIFIED","heating_hydraulic_basis":heating_basis},
            "heating_engineering":{"status":"PASS" if not engineering_errors else "FAIL","basis_status":"PRE_SUBMISSION" if heat_status.startswith("PRELIMINARY") or heating_basis["preliminary_fields"] else "PROJECT_CONFIRMED",
                "load_source":heat_source,"declared_total_w":round(declared_total_w,1),"raw_room_total_w":round(raw_total_w,1),
                "resolved_total_w":round(total_duty,1),"load_reconciled":load_reconciled,"heated_room_ids":sorted(r.get("id") for r in all_heat_rooms),
                "radiator_ids":sorted(r.get("id") for r in radiators),"route_calc_ids":sorted(r.get("calc_id") for r in heating_routes if r.get("calc_id")),
                "errors":sorted(set(engineering_errors)),"final_blockers":["ROOM_ENVELOPE_AND_DESIGN_DAY_CONFIRMATION","OFFICIAL_RADIATOR_CATALOGUE_SELECTION","EXTERNAL_WALL_WINDOW_PLACEMENT_CONFIRMATION"]},
            "quality":{"primary_plans":len(plans),"equipment":len(equipment),"routes":len(routes),"cross_plan_routes":0,"out_of_bounds":len(bad),
                "heating_rooms":len(all_heat_rooms),"heating_rooms_served":len(radiators),"heating_routes":len(heating_routes),"heating_load_reconciled":load_reconciled,
                "heating_hydraulics_calculated":all(r.get("status")=="PASS" for r in heating_routes)}}
