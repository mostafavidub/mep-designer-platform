from __future__ import annotations

from typing import Any, Dict, Optional

from .models import EngineeringStatus, EvidenceValue


def _final(ev): return isinstance(ev,EvidenceValue) and ev.status==EngineeringStatus.FINAL and ev.value is not None


def build_service_feeders(topology: Dict[str,Any], service_inputs: Optional[Dict[str,Any]]=None):
    cfg=service_inputs or {}; service=cfg.get("service"); meter=cfg.get("meter"); main=cfg.get("main_distribution"); feeder_cfg=cfg.get("feeders") or {}
    nodes=[
        {"id":"SERVICE","kind":"service","data":service,"status":"FINAL" if service else "INPUT_REQUIRED"},
        {"id":"METER","kind":"meter","data":meter,"status":"FINAL" if meter else "INPUT_REQUIRED"},
        {"id":"MAIN","kind":"main_distribution","data":main,"status":"FINAL" if main else "INPUT_REQUIRED"},
    ]
    feeders=[]; missing=[]
    if not service: missing.append("service")
    if not meter: missing.append("meter")
    if not main: missing.append("main_distribution")
    for panel in topology.get("panels",[]):
        data=feeder_cfg.get(panel.id)
        required=("cable","breaker","route_length_m","tag")
        ok=isinstance(data,dict) and all(k in data for k in required)
        if not ok: missing.append(f"feeder:{panel.id}")
        feeders.append({"id":f"F-{panel.id}","source":"MAIN","destination":panel.id,"demand_load_w":panel.demand_load_w.value,
                        "cable":data.get("cable") if isinstance(data,dict) else None,"breaker":data.get("breaker") if isinstance(data,dict) else None,
                        "route_length_m":data.get("route_length_m") if isinstance(data,dict) else None,"tag":data.get("tag") if isinstance(data,dict) else None,
                        "status":"FINAL" if ok and _final(panel.demand_load_w) else "INPUT_REQUIRED"})
    topology["feeders"]=feeders; topology["service_nodes"]=nodes
    return {"status":"PASS" if not missing and all(f["status"]=="FINAL" for f in feeders) else "PRELIMINARY","missing":missing,"feeders":feeders,"nodes":nodes}


def full_traceability_qa(topology):
    errors=[]; loads=topology.get("loads",[]); circuits=topology.get("circuits",[]); panels=topology.get("panels",[]); feeders=topology.get("feeders",[])
    circuit_ids={c.id for c in circuits}; panel_ids={p.id for p in panels}; feeder_dest={f["destination"] for f in feeders if f.get("status")=="FINAL"}
    for load in loads:
        if not load.circuit_id or load.circuit_id not in circuit_ids: errors.append(f"orphan_load:{load.id}")
    for circuit in circuits:
        if circuit.panel_id not in panel_ids: errors.append(f"orphan_circuit:{circuit.id}")
        if not circuit.load_ids: errors.append(f"empty_circuit:{circuit.id}")
    for panel in panels:
        if panel.id not in feeder_dest: errors.append(f"orphan_panel_no_final_feeder:{panel.id}")
    if panels and not topology.get("service_nodes"): errors.append("service_chain_missing")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,
            "chain":"LOAD -> BRANCH_CIRCUIT -> PANEL -> FEEDER -> MAIN -> METER -> SERVICE"}


def service_single_line(topology):
    nodes=list(topology.get("service_nodes") or []); edges=[{"from":"SERVICE","to":"METER","kind":"service"},{"from":"METER","to":"MAIN","kind":"main"}]
    for panel in topology.get("panels",[]):
        nodes.append({"id":panel.id,"kind":"panel","status":"FINAL" if _final(panel.main_breaker) and _final(panel.bus_rating) else "PRELIMINARY",
                      "main_breaker":panel.main_breaker.value,"bus_rating":panel.bus_rating.value})
    for feeder in topology.get("feeders",[]):
        edges.append({"from":"MAIN","to":feeder["destination"],"kind":"feeder","tag":feeder.get("tag"),"cable":feeder.get("cable"),"breaker":feeder.get("breaker"),"status":feeder.get("status")})
    for circuit in topology.get("circuits",[]):
        edges.append({"from":circuit.panel_id,"to":circuit.id,"kind":"branch","breaker":circuit.breaker.value,"cable":circuit.cable.value,
                      "status":"FINAL" if _final(circuit.breaker) and _final(circuit.cable) else "PRELIMINARY"})
    status="PASS" if nodes and all(n.get("status")=="FINAL" for n in nodes) and all(e.get("status","FINAL")=="FINAL" for e in edges) else "PRELIMINARY"
    return {"status":status,"nodes":nodes,"edges":edges}
