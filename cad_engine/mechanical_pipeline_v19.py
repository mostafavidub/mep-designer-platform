"""Ordered v19 mechanical design pipeline. Later phases cannot run around gates."""
from __future__ import annotations
from .coordination_v19 import build_coordination_model, route_25d
from .equipment_representation_v14 import validate_equipment_integrity
from .manufacturer_selector_v19 import select_equipment
from .parametric_documentation_v19 import generate_parametric_documentation
from .submission_qa_v19 import submission_gate, validate_golden_release_evidence


def run_v19_pipeline(payload: dict) -> dict:
    phases={}; blocked=None
    coordination=build_coordination_model(payload)
    phases["coordination"]=coordination
    if coordination["status"]!="PASS":
        blocked="coordination"
        return _result(phases,blocked)
    route=route_25d(payload.get("route_request") or {},coordination["model"] if "model" in coordination else coordination)
    phases["routing_2_5d"]=route
    if route["status"]!="PASS":
        blocked="routing_2_5d"
        return _result(phases,blocked)

    # Step 5: if physical equipment entities are available at this boundary,
    # they must be geometrically and relationally coherent before selection.
    equipment_entities=payload.get("equipment_entities")
    if equipment_entities is not None:
        equipment_qa=validate_equipment_integrity(equipment_entities)
        phases["equipment_integrity"]=equipment_qa
        if equipment_qa["status"]!="PASS":
            blocked="equipment_integrity"
            return _result(phases,blocked)

    selection=select_equipment(payload.get("equipment_requirements") or {},payload.get("manufacturer_catalogue") or [])
    phases["manufacturer"]=selection
    if selection["status"]!="PASS":
        blocked="manufacturer"
        return _result(phases,blocked)
    documentation=generate_parametric_documentation(payload.get("detail_specs") or [],payload.get("network_graph") or {})
    phases["documentation"]=documentation
    if documentation["status"]!="PASS":
        blocked="documentation"
        return _result(phases,blocked)

    # Step 11: never trust a caller-provided {status: PASS}. The pipeline
    # independently verifies the locked seven-project evidence against the
    # repository baseline and the exact current build identity.
    golden=validate_golden_release_evidence(payload.get("golden_result"))
    phases["golden"]=golden
    if golden["status"]!="PASS":
        blocked="golden"
    return _result(phases,blocked)


def _result(phases:dict,blocked:str|None)->dict:
    gate=submission_gate(phases)
    status="PASS" if gate["status"]=="PASS" else ("INPUT_REQUIRED" if blocked in {"coordination","equipment_integrity","manufacturer","documentation"} else "FAIL")
    return {"version":"mechanical-pipeline-v19.1","status":status,"blocked_at":blocked,"phases":phases,"submission":gate}