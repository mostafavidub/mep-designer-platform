"""Ordered fail-closed orchestration for the four v19 phases."""
from .coordination_v19 import build_coordination_model, route_25d
from .manufacturer_selector_v19 import select_equipment
from .parametric_documentation_v19 import generate_detail, generate_riser_from_network, documentation_gate
from .submission_qa_v19 import submission_gate


def run_v19_pipeline(payload: dict) -> dict:
    phases={}
    model=build_coordination_model(payload)
    route=route_25d(payload.get("route_request") or {},model) if model["status"] == "PASS" else {"status":"INPUT_REQUIRED","selected":None,"missing_inputs":model["missing_inputs"]}
    phases["coordination"]={"status":"PASS" if model["status"] == route["status"] == "PASS" else route["status"],"model":model,"route":route}
    if phases["coordination"]["status"] != "PASS": return _blocked(phases,"coordination")
    selection=select_equipment(payload.get("equipment_requirements") or {},payload.get("manufacturer_catalogue") or [],route)
    phases["manufacturer"]=selection
    if selection["status"] != "PASS": return _blocked(phases,"manufacturer")
    details=[generate_detail(x) for x in payload.get("detail_specs") or []]
    riser=generate_riser_from_network(payload.get("network_graph") or {})
    phases["documentation"]={**documentation_gate(details,riser),"details":details,"riser":riser}
    if phases["documentation"]["status"] != "PASS": return _blocked(phases,"documentation")
    phases["golden"]=payload.get("golden_result") or {"status":"MISSING"}
    gate=submission_gate(phases)
    return {"status":gate["status"],"blocked_at":None if gate["release_allowed"] else "golden","phases":phases,"submission":gate}


def _blocked(phases: dict, name: str) -> dict:
    return {"status":"INPUT_REQUIRED" if phases[name]["status"] in {"INPUT_REQUIRED","PRE_SUBMISSION"} else "FAIL",
            "blocked_at":name,"phases":phases,"submission":{"status":"FAIL","release_allowed":False,"errors":[f"{name}:{phases[name]['status']}"]}}
