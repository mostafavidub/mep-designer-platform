from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from .models import (
    Circuit, ElectricalDesignBasis, ElectricalLoad, ElectricalProjectModel,
    EngineeringStatus, EquipmentPlacement, EquipmentRequirement, EvidenceValue,
    Panel,
)


def _final(ev: EvidenceValue) -> bool:
    return ev.status == EngineeringStatus.FINAL and ev.value is not None


def build_loads(requirements: List[EquipmentRequirement], placements: List[EquipmentPlacement]) -> List[ElectricalLoad]:
    reqs={r.id:r for r in requirements}; loads=[]
    for p in placements:
        req=reqs[p.requirement_id]
        if req.equipment_type=="LIGHT_SWITCH":
            continue
        load=EvidenceValue.input_required(f"load for {req.equipment_type} not established")
        if _final(req.load_w):
            load=EvidenceValue.final(float(req.load_w.value),req.load_w.source or "engineering_calculation",req.load_w.confidence,req.load_w.reference)
        loads.append(ElectricalLoad(f"LOAD-{len(loads)+1:04d}",p.equipment_id,req.system,p.level_id,p.frame_id,load))
    return loads


def build_circuit_topology(loads: List[ElectricalLoad], project: ElectricalProjectModel,
                           basis: ElectricalDesignBasis, rules: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    rules=rules or {}; circuits=[]; panels=[]; errors=[]
    by_level=defaultdict(list)
    for load in loads: by_level[load.level_id].append(load)
    grouping=rules.get("grouping") or {}; demand_factors=rules.get("demand_factors") or {}; panel_locations=rules.get("panel_locations") or {}
    for level_id, level_loads in by_level.items():
        panel_id=f"DB-{level_id}"
        loc=(EvidenceValue.final(panel_locations[level_id],"explicit_user_input",1.0) if level_id in panel_locations else EvidenceValue.input_required(f"panel location for {level_id}"))
        buckets=[]
        for load in level_loads:
            g=grouping.get(load.system) or {}
            max_points=g.get("max_points")
            bucket=next((b for b in reversed(buckets) if b["system"]==load.system and isinstance(max_points,int) and max_points>0 and len(b["loads"])<max_points),None)
            if bucket is None:
                bucket={"system":load.system,"loads":[]}; buckets.append(bucket)
            bucket["loads"].append(load)
        for bucket in buckets:
            cid=f"C-{len(circuits)+1:04d}"; group=bucket["loads"]
            for load in group: load.circuit_id=cid
            known=[float(l.load_w.value) for l in group if _final(l.load_w)]
            connected=(EvidenceValue.final(sum(known),"engineering_calculation",1.0) if len(known)==len(group) else EvidenceValue.input_required("all load values required"))
            factor=demand_factors.get(bucket["system"])
            demand=(EvidenceValue.final(float(connected.value)*float(factor),"engineering_calculation",1.0,"project demand factor")
                    if _final(connected) and isinstance(factor,(int,float)) and 0<=factor<=1
                    else EvidenceValue.input_required(f"demand factor for {bucket['system']} required"))
            circuits.append(Circuit(cid,panel_id,[l.id for l in group],bucket["system"],
                                    EvidenceValue.input_required("phase balance pending"),connected,demand))
        own=[c for c in circuits if c.panel_id==panel_id]
        conn=[float(c.connected_load_w.value) for c in own if _final(c.connected_load_w)]
        dem=[float(c.demand_load_w.value) for c in own if _final(c.demand_load_w)]
        conn_ev=EvidenceValue.final(sum(conn),"engineering_calculation") if len(conn)==len(own) else EvidenceValue.input_required("panel connected loads unresolved")
        dem_ev=EvidenceValue.final(sum(dem),"engineering_calculation") if len(dem)==len(own) else EvidenceValue.input_required("panel demand loads unresolved")
        panels.append(Panel(panel_id,level_id,loc,None,EvidenceValue.input_required("main breaker sizing pending"),
                            EvidenceValue.input_required("bus rating rule/input required"),basis.get("phase_configuration"),[c.id for c in own],
                            EvidenceValue.input_required("spare circuit policy required"),conn_ev,dem_ev))
    orphan=[l.id for l in loads if not l.circuit_id]
    if orphan: errors.append(f"orphan_loads:{orphan}")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"loads":loads,"circuits":circuits,"panels":panels,"feeders":[]}


def calculate_currents_and_phase_balance(topology: Dict[str,Any], basis: ElectricalDesignBasis,
                                         rules: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    rules=rules or {}; errors=[]; warnings=[]; voltage=basis.get("supply_voltage_v"); cfg=basis.get("phase_configuration"); pf=basis.get("power_factor")
    if not (_final(voltage) and _final(cfg)):
        return {"status":"PRELIMINARY","errors":[],"warnings":["supply_voltage_or_phase_configuration_missing"],"phase_balance_pct":{}}
    power_factor=float(pf.value) if _final(pf) and isinstance(pf.value,(int,float)) and pf.value>0 else 1.0
    three=any(t in str(cfg.value).lower() for t in ("3","three","سه")); phase_names=rules.get("phase_names") or ["L1","L2","L3"]
    for circuit in topology["circuits"]:
        if not _final(circuit.demand_load_w): continue
        panel=next(p for p in topology["panels"] if p.id==circuit.panel_id)
        if three:
            phase=min(phase_names,key=lambda p:panel.phase_loads_w.get(p,0.0)); circuit.phase=EvidenceValue.final(phase,"engineering_calculation")
            panel.phase_loads_w[phase]=panel.phase_loads_w.get(phase,0.0)+float(circuit.demand_load_w.value)
        else:
            circuit.phase=EvidenceValue.final("L","engineering_calculation")
        denom=float(voltage.value)*power_factor
        circuit.design_current_a=EvidenceValue.final(float(circuit.demand_load_w.value)/denom,"engineering_calculation") if denom>0 else EvidenceValue.input_required("invalid voltage/power factor")
    balance={}
    if three:
        for panel in topology["panels"]:
            vals=[panel.phase_loads_w.get(x,0.0) for x in phase_names]
            if max(vals)>0: balance[panel.id]=(max(vals)-min(vals))/max(vals)*100
    threshold=rules.get("max_phase_imbalance_pct")
    if balance and isinstance(threshold,(int,float)):
        for panel_id,pct in balance.items():
            if pct>float(threshold): errors.append(f"phase_imbalance:{panel_id}:{pct:.3f}>{threshold}")
    elif balance: warnings.append("phase_balance_threshold_missing")
    return {"status":"FAIL" if errors else ("PRELIMINARY" if warnings else "PASS"),"errors":errors,"warnings":warnings,"phase_balance_pct":balance}


def size_circuits(topology: Dict[str,Any], basis: ElectricalDesignBasis,
                  tables: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    tables=tables or {}; warnings=[]
    breakers=sorted(float(x) for x in (tables.get("breakers_a") or [])); cables=tables.get("cables") or []
    installation=basis.get("installation_method"); material=basis.get("conductor_material")
    for circuit in topology["circuits"]:
        if not _final(circuit.design_current_a): warnings.append(f"current_unresolved:{circuit.id}"); continue
        current=float(circuit.design_current_a.value); breaker=next((x for x in breakers if x>=current),None)
        if breaker is None:
            circuit.breaker=EvidenceValue.input_required("supplied breaker table does not resolve circuit"); warnings.append(f"breaker_unresolved:{circuit.id}"); continue
        circuit.breaker=EvidenceValue.final(breaker,"engineering_calculation",1.0,str(tables.get("reference") or "supplied breaker table"))
        if not (_final(installation) and _final(material)):
            circuit.cable=EvidenceValue.input_required("installation method and conductor material required"); warnings.append(f"cable_basis_missing:{circuit.id}"); continue
        candidates=[r for r in cables if str(r.get("installation_method"))==str(installation.value) and str(r.get("material"))==str(material.value)
                    and isinstance(r.get("ampacity_a"),(int,float)) and float(r["ampacity_a"])>=breaker and isinstance(r.get("size_mm2"),(int,float))]
        if not candidates:
            circuit.cable=EvidenceValue.input_required("no supplied ampacity row satisfies circuit"); warnings.append(f"cable_unresolved:{circuit.id}"); continue
        row=min(candidates,key=lambda r:float(r["size_mm2"]))
        circuit.cable=EvidenceValue.final({"size_mm2":row["size_mm2"],"conductors":row.get("conductors"),"voltage_rating":row.get("voltage_rating")},"engineering_calculation",1.0,str(tables.get("reference") or "supplied ampacity table"))
        if row.get("earth_mm2") is not None:
            circuit.earth_conductor=EvidenceValue.final(row["earth_mm2"],"applicable_rule",1.0,str(tables.get("reference") or "supplied earth conductor table"))
    return {"status":"PRELIMINARY" if warnings else "PASS","errors":[],"warnings":warnings}


def apply_route_lengths(topology: Dict[str,Any], route_lengths_m: Dict[str,float]) -> None:
    for circuit in topology["circuits"]:
        if circuit.id in route_lengths_m:
            circuit.route_length_m=EvidenceValue.final(float(route_lengths_m[circuit.id]),"engineering_calculation",1.0)


def calculate_voltage_drop(topology: Dict[str,Any], basis: ElectricalDesignBasis,
                           rules: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    rules=rules or {}; errors=[]; warnings=[]; rho=rules.get("resistivity_ohm_mm2_per_m"); voltage=basis.get("supply_voltage_v"); limits=basis.get("voltage_drop_limits")
    for circuit in topology["circuits"]:
        if not (_final(circuit.design_current_a) and _final(circuit.cable) and _final(circuit.route_length_m) and _final(voltage) and isinstance(rho,(int,float)) and rho>0):
            circuit.voltage_drop_pct=EvidenceValue.input_required("current+cable+length+voltage+resistivity required"); warnings.append(f"voltage_drop_inputs_missing:{circuit.id}"); continue
        size=circuit.cable.value.get("size_mm2") if isinstance(circuit.cable.value,dict) else None
        if not isinstance(size,(int,float)) or size<=0: warnings.append(f"cable_size_missing:{circuit.id}"); continue
        vd=2*float(circuit.route_length_m.value)*float(circuit.design_current_a.value)*float(rho)/float(size); pct=100*vd/float(voltage.value)
        circuit.voltage_drop_pct=EvidenceValue.final(pct,"engineering_calculation")
        cfg=limits.value if _final(limits) and isinstance(limits.value,dict) else {}; limit=cfg.get(circuit.system) or cfg.get("default")
        if isinstance(limit,(int,float)) and pct>float(limit): errors.append(f"voltage_drop:{circuit.id}:{pct:.3f}>{limit}")
        elif limit is None: warnings.append(f"voltage_drop_limit_missing:{circuit.id}")
    return {"status":"FAIL" if errors else ("PRELIMINARY" if warnings else "PASS"),"errors":errors,"warnings":warnings}


def panel_schedules(topology: Dict[str,Any]) -> Dict[str,List[Dict[str,Any]]]:
    load_map={l.id:l for l in topology["loads"]}; out={}
    for panel in topology["panels"]:
        rows=[]
        for circuit in [c for c in topology["circuits"] if c.panel_id==panel.id]:
            rows.append({"circuit_no":circuit.id,"description":circuit.system,"phase":circuit.phase.value,"load_w":circuit.demand_load_w.value,
                         "breaker":circuit.breaker.value,"cable":circuit.cable.value,"destination":[load_map[x].equipment_id for x in circuit.load_ids if x in load_map],
                         "status":"FINAL" if all(_final(x) for x in (circuit.phase,circuit.demand_load_w,circuit.breaker,circuit.cable)) else "PRELIMINARY"})
        out[panel.id]=rows
    return out


def schedule_sync_qa(topology, schedules):
    circuits={c.id for c in topology["circuits"]}; scheduled={r["circuit_no"] for rows in schedules.values() for r in rows}; errors=[]
    if circuits-scheduled: errors.append(f"missing_from_schedule:{sorted(circuits-scheduled)}")
    if scheduled-circuits: errors.append(f"orphan_schedule_rows:{sorted(scheduled-circuits)}")
    return {"status":"PASS" if not errors else "FAIL","errors":errors}


def build_single_line(topology):
    nodes=[{"id":"UTILITY","kind":"utility","status":"INPUT_REQUIRED"},{"id":"METER","kind":"meter","status":"INPUT_REQUIRED"}]; edges=[{"from":"UTILITY","to":"METER","kind":"service"}]
    for panel in topology["panels"]:
        nodes.append({"id":panel.id,"kind":"panel"}); edges.append({"from":"METER","to":panel.id,"kind":"feeder"})
        for cid in panel.circuit_ids: edges.append({"from":panel.id,"to":cid,"kind":"branch_circuit"})
    return {"nodes":nodes,"edges":edges}


def build_riser(topology, project):
    if len(project.levels)<=1: return {"status":"NOT_REQUIRED","transitions":[]}
    pmap={p.level_id:p.id for p in topology["panels"]}; transitions=[]
    for a,b in zip(project.levels,project.levels[1:]): transitions.append({"from_level":a.id,"to_level":b.id,"from_panel":pmap.get(a.id),"to_panel":pmap.get(b.id),"representation":"RISER_ONLY"})
    return {"status":"PASS","transitions":transitions}
