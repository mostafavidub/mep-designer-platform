"""Production adapter that makes v19 authoritative before legacy composition.

The legacy composer remains transitional, but its exact generated DXF must pass
the canonical generated-artifact integrity gate before any artifact is returned.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import tempfile

from .mechanical_authority_site_v17 import design_mechanical_authority_site as _design_v17
from .mechanical_pipeline_v19 import run_v19_pipeline
from .coordination_v19 import build_coordination_model
from .mechanical_integrity import validate_generated_mechanical_integrity
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


def _snapshot_existing_output(dst: Path):
    if not dst.exists():
        return None
    fd,name=tempfile.mkstemp(prefix="engitools-mechanical-integrity-backup-",suffix=".dxf")
    os.close(fd)
    backup=Path(name)
    shutil.copy2(dst,backup)
    return backup


def _restore_or_remove_output(dst: Path, backup):
    if backup and backup.exists():
        shutil.copy2(backup,dst)
    else:
        dst.unlink(missing_ok=True)


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    answers=dict(answers or {}); plan_analysis=dict(plan_analysis or {})
    src=Path(src);dst=Path(dst)
    contract_errors=_runtime_contract_errors(answers)
    if contract_errors:
        return {"status":"FAIL","stage":"v19_runtime_contract_gate","v19_qa":{"status":"FAIL","errors":contract_errors}}
    payload=_v19_payload(answers,plan_analysis)
    coordination=build_coordination_model(payload)
    missing_structure=coordination["status"]=="INPUT_REQUIRED" and set(coordination.get("missing_inputs") or {}) <= {"STRUCTURAL_MODEL","RCP_MODEL","SLAB","CEILING"}
    if missing_structure:
        # Current operating profile explicitly permits architecture-only work,
        # but it can never inherit coordinated/submission-ready claims.
        result={
            "status":"PRE_SUBMISSION","blocked_at":None,
            "operating_profile":"ARCHITECTURE_ONLY_PRE_SUBMISSION",
            "phases":{
                "coordination":coordination,
                "manufacturer":{"status":"PRE_SUBMISSION","selection_type":"DESIGN_ENVELOPE","claim":"NOT_MANUFACTURER_CONFIRMED"},
                "documentation":{"status":"PRE_SUBMISSION","source":"LEGACY_GRAPH_COMPOSER","claim":"REQUIRES_COORDINATION_REVALIDATION"},
                "golden":{"status":"NOT_APPLICABLE_TO_PRE_SUBMISSION"},
            },
            "submission":{"status":"PRE_SUBMISSION","release_allowed":True,"submission_ready":False,
                          "missing_inputs":coordination.get("missing_inputs") or [],
                          "claims":["NOT_COORDINATED","NOT_MANUFACTURER_CONFIRMED"]},
        }
    else:
        result=run_v19_pipeline(payload)
    if result["status"] not in {"PASS","PRE_SUBMISSION"}:
        missing=[]; coordination=(result.get("phases") or {}).get("coordination") or {}; model=coordination.get("model") or {}
        missing.extend(model.get("missing_inputs") or coordination.get("missing_inputs") or [])
        if result.get("blocked_at")=="manufacturer": missing.append("OFFICIAL_MANUFACTURER_DATASHEET")
        if result.get("blocked_at")=="documentation": missing.append("PARAMETRIC_NETWORK_DOCUMENTATION")
        if result.get("blocked_at")=="golden": missing.append("V19_RELEASE_GOLDEN_PASS")
        return {"status":"FAIL","stage":"v19_preflight_gate","v19_qa":result,
                "input_required":{"status":"INPUT_REQUIRED","missing_inputs":sorted(set(missing))}}

    backup=_snapshot_existing_output(dst)
    try:
        legacy=_design_v17(src,dst,answers=answers,plan_analysis=plan_analysis)
        legacy["v19_qa"]=result; legacy["executed_versions"]=active_version_manifest(); legacy["pipeline_authority"]="mechanical-v19"
        if legacy.get("status") != "PASS":
            return legacy

        integrity=validate_generated_mechanical_integrity(dst,report=legacy,answers=answers)
        legacy["generated_dxf_integrity_qa"]=integrity
        (result.setdefault("phases", {}))["generated_dxf_integrity"]=integrity
        result.setdefault("submission", {})["generated_dxf_integrity"]=integrity.get("status")
        if integrity.get("status") != "PASS":
            legacy["status"]="FAIL"
            legacy["stage"]="generated_dxf_integrity_gate"
            legacy["submission_state"]="BLOCKED"
            legacy["coordination_claim"]="NOT_RELEASED"
            _restore_or_remove_output(dst,backup)
            return legacy

        legacy["submission_state"]="PRE_SUBMISSION" if result["status"]=="PRE_SUBMISSION" else "SUBMISSION_READY"
        legacy["coordination_claim"]="NOT_COORDINATED" if result["status"]=="PRE_SUBMISSION" else "COORDINATED"
        return legacy
    finally:
        if backup:
            backup.unlink(missing_ok=True)
