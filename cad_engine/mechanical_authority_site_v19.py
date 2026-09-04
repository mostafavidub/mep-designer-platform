"""Production adapter that makes v19 authoritative before legacy composition."""
from __future__ import annotations
import os
from pathlib import Path
from .mechanical_authority_site_v17 import design_mechanical_authority_site as _design_v17
from .mechanical_pipeline_v19 import run_v19_pipeline
from .version_manifest import active_version_manifest


def _runtime_contract_errors(answers: dict) -> list[str]:
    supplied=answers.get("_runtime_contract") or {}; active=active_version_manifest()
    return [f"runtime_contract_mismatch:{key}" for key,value in active.items() if supplied.get(key)!=value]


def _v19_payload(answers: dict, plan_analysis: dict) -> dict:
    contract=answers.get("_v19_input_contract") or {}
    return {
        "coordination_inputs":contract.get("coordination_inputs") or plan_analysis.get("coordination_inputs_v19") or {},
        "route_request":contract.get("route_request") or {},
        "equipment_requirements":contract.get("equipment_requirements") or {},
        "manufacturer_catalogue":contract.get("manufacturer_catalogue") or [],
        "detail_specs":contract.get("detail_specs") or [],
        "network_graph":contract.get("network_graph") or {},
        "golden_result":{"status":os.getenv("MECHANICAL_V19_GOLDEN_STATUS","MISSING")},
    }


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    answers=dict(answers or {}); plan_analysis=dict(plan_analysis or {})
    contract_errors=_runtime_contract_errors(answers)
    if contract_errors:
        return {"status":"FAIL","stage":"v19_runtime_contract_gate","v19_qa":{"status":"FAIL","errors":contract_errors}}
    result=run_v19_pipeline(_v19_payload(answers,plan_analysis))
    if result["status"]!="PASS":
        missing=[]; coordination=(result.get("phases") or {}).get("coordination") or {}; model=coordination.get("model") or {}
        missing.extend(model.get("missing_inputs") or coordination.get("missing_inputs") or [])
        if result.get("blocked_at")=="manufacturer": missing.append("OFFICIAL_MANUFACTURER_DATASHEET")
        if result.get("blocked_at")=="documentation": missing.append("PARAMETRIC_NETWORK_DOCUMENTATION")
        if result.get("blocked_at")=="golden": missing.append("V19_RELEASE_GOLDEN_PASS")
        return {"status":"FAIL","stage":"v19_preflight_gate","v19_qa":result,
                "input_required":{"status":"INPUT_REQUIRED","missing_inputs":sorted(set(missing))}}
    legacy=_design_v17(src,dst,answers=answers,plan_analysis=plan_analysis)
    legacy["v19_qa"]=result; legacy["executed_versions"]=active_version_manifest(); legacy["pipeline_authority"]="mechanical-v19"
    return legacy
