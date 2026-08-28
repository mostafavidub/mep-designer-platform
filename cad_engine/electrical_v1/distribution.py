from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .models import ElectricalDesignBasis, EngineeringStatus, EvidenceValue, SystemRequirement


def _final(ev): return isinstance(ev,EvidenceValue) and ev.status==EngineeringStatus.FINAL and ev.value is not None


def _explicit_none(value):
    return value is False or value in ({}, [], (), "NONE", "none", "NOT_REQUIRED", "not_required")


def normalize_requirement_scope(requirements: Dict[str,SystemRequirement], basis: ElectricalDesignBasis):
    """Close requirement states only when the design basis explicitly proves absence.

    This prevents an UNKNOWN subsystem from being silently treated as not required,
    while allowing explicit empty schedules/false flags to close the gate.
    """
    hvac=basis.get("hvac_electrical_loads")
    if _final(hvac) and _explicit_none(hvac.value):
        requirements["HVAC_POWER"]=SystemRequirement("HVAC_POWER",EngineeringStatus.NOT_REQUIRED,False,["design_basis.hvac_electrical_loads"],1.0,"explicitly no HVAC electrical loads")

    dedicated=basis.get("dedicated_appliance_requirements")
    if _final(dedicated) and _explicit_none(dedicated.value):
        requirements["DEDICATED_POWER"]=SystemRequirement("DEDICATED_POWER",EngineeringStatus.NOT_REQUIRED,False,["design_basis.dedicated_appliance_requirements"],1.0,"explicitly no dedicated appliance loads")

    return requirements


def resolve_switch_quantities(equipment, project, basis):
    cfg=basis.get("switch_control_requirements")
    data=cfg.value if _final(cfg) and isinstance(cfg.value,dict) else {}
    room_map={r.id:r for r in project.rooms}
    for req in equipment:
        if req.equipment_type!="LIGHT_SWITCH": continue
        room=room_map.get(req.room_id); kind=str(room.room_type.value if room else "unknown")
        value=data.get(kind,data.get("default"))
        if isinstance(value,int) and value>=0:
            req.quantity=EvidenceValue.final(value,"project_design_basis",1.0,"switch control requirement")
        else:
            req.quantity=EvidenceValue.input_required(f"switch control count/type basis required for {kind}")
    return equipment


def finalize_panels(topology, basis: ElectricalDesignBasis, panel_rules: Optional[Dict[str,Any]]=None):
    rules=panel_rules or {}; warnings=[]; errors=[]
    phase_voltage=rules.get("phase_voltage_v"); three_phase_voltage=rules.get("three_phase_line_voltage_v")
    breakers=sorted(float(x) for x in (rules.get("main_breakers_a") or [])); buses=sorted(float(x) for x in (rules.get("bus_ratings_a") or []))
    spare=rules.get("spare_count")
    phase_cfg=basis.get("phase_configuration")
    for panel in topology.get("panels",[]):
        if not _final(panel.demand_load_w): warnings.append(f"panel_demand_unresolved:{panel.id}"); continue
        three=_final(phase_cfg) and any(x in str(phase_cfg.value).lower() for x in ("3","three","سه"))
        if three:
            if not isinstance(three_phase_voltage,(int,float)) or three_phase_voltage<=0: warnings.append(f"three_phase_voltage_missing:{panel.id}"); continue
            current=float(panel.demand_load_w.value)/(math.sqrt(3)*float(three_phase_voltage))
        else:
            v=phase_voltage if isinstance(phase_voltage,(int,float)) else (basis.get("supply_voltage_v").value if _final(basis.get("supply_voltage_v")) else None)
            if not isinstance(v,(int,float)) or v<=0: warnings.append(f"panel_voltage_missing:{panel.id}"); continue
            current=float(panel.demand_load_w.value)/float(v)
        mb=next((x for x in breakers if x>=current),None)
        if mb is None: warnings.append(f"panel_main_breaker_unresolved:{panel.id}")
        else: panel.main_breaker=EvidenceValue.final(mb,"engineering_calculation",1.0,str(rules.get("reference") or "supplied panel rule"))
        bus=next((x for x in buses if x>=(mb or current)),None)
        if bus is None: warnings.append(f"panel_bus_unresolved:{panel.id}")
        else: panel.bus_rating=EvidenceValue.final(bus,"engineering_calculation",1.0,str(rules.get("reference") or "supplied panel rule"))
        if isinstance(spare,int) and spare>=0: panel.spare_count=EvidenceValue.final(spare,"applicable_rule",1.0,str(rules.get("reference") or "supplied panel spare rule"))
        else: warnings.append(f"panel_spare_policy_missing:{panel.id}")
    return {"status":"PRELIMINARY" if warnings else "PASS","errors":errors,"warnings":warnings}


def panel_design_qa(topology):
    unresolved=[]
    for p in topology.get("panels",[]):
        for attr in ("location","main_breaker","bus_rating","phase_configuration","spare_count","connected_load_w","demand_load_w"):
            if not _final(getattr(p,attr)): unresolved.append(f"{p.id}.{attr}")
    return {"status":"PASS" if topology.get("panels") and not unresolved else "PRELIMINARY","errors":[],"warnings":[f"panel_field_unresolved:{x}" for x in unresolved]}


def build_service_sld(topology, service_inputs: Optional[Dict[str,Any]]=None):
    inp=service_inputs or {}; required=("utility","meter","service_protection")
    missing=[x for x in required if x not in inp]
    nodes=[]; edges=[]
    for key in required:
        nodes.append({"id":key.upper(),"kind":key,"data":inp.get(key),"status":"FINAL" if key in inp else "INPUT_REQUIRED"})
    edges.extend([{"from":"UTILITY","to":"METER","kind":"service"},{"from":"METER","to":"SERVICE_PROTECTION","kind":"protected_service"}])
    for panel in topology.get("panels",[]):
        nodes.append({"id":panel.id,"kind":"panel","main_breaker":panel.main_breaker.value,"bus_rating":panel.bus_rating.value,"status":"FINAL" if _final(panel.main_breaker) and _final(panel.bus_rating) else "PRELIMINARY"})
        edges.append({"from":"SERVICE_PROTECTION","to":panel.id,"kind":"feeder","status":"PRELIMINARY"})
        for cid in panel.circuit_ids: edges.append({"from":panel.id,"to":cid,"kind":"branch_circuit","status":"FINAL"})
    return {"status":"PASS" if not missing and all(n.get("status")=="FINAL" for n in nodes) else "PRELIMINARY","missing":missing,"nodes":nodes,"edges":edges}


def build_electrical_riser(topology, project, feeder_inputs: Optional[Dict[str,Any]]=None):
    if len(project.levels)<=1: return {"status":"NOT_REQUIRED","transitions":[]}
    inputs=feeder_inputs or {}; pmap={p.level_id:p for p in topology.get("panels",[])}; transitions=[]; missing=[]
    for a,b in zip(project.levels,project.levels[1:]):
        pa,pb=pmap.get(a.id),pmap.get(b.id); key=f"{a.id}->{b.id}"; data=inputs.get(key)
        if not isinstance(data,dict) or not all(k in data for k in ("cable","protection","tag")): missing.append(key)
        transitions.append({"from_level":a.id,"to_level":b.id,"from_panel":pa.id if pa else None,"to_panel":pb.id if pb else None,
                            "cable":data.get("cable") if isinstance(data,dict) else None,"protection":data.get("protection") if isinstance(data,dict) else None,
                            "tag":data.get("tag") if isinstance(data,dict) else None,"representation":"RISER_ONLY","status":"FINAL" if key not in missing else "INPUT_REQUIRED"})
    return {"status":"PASS" if not missing else "PRELIMINARY","missing":missing,"transitions":transitions}


def grounding_model(requirements, inputs: Optional[Dict[str,Any]]=None):
    req=requirements.get("GROUNDING")
    if req and req.required is False: return {"status":"NOT_REQUIRED","elements":[]}
    cfg=(inputs or {}).get("grounding") or {}; required=("earth_electrode","main_earth_bar","protective_conductors","panel_grounding")
    missing=[x for x in required if x not in cfg]
    elements=[{"kind":x,"data":cfg.get(x),"status":"FINAL" if x in cfg else "INPUT_REQUIRED"} for x in required]
    return {"status":"PASS" if not missing else "PRELIMINARY","missing":missing,"elements":elements}
