"""Production adapter that makes v19 authoritative before legacy composition.

The legacy composer remains transitional, but its exact generated DXF must pass
all fail-closed release gates before any artifact is returned.
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
from .calculation_evidence_step8 import validate_calculation_evidence, apply_canonical_pressure
from .required_scope_gate_step9 import validate_required_scope_support, validate_required_scope_artifact
from .exact_dxf_gate_step10 import validate_exact_dxf_health
from .final_delivery_gate_step12 import validate_non_destructive_final_delivery
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
        # Step 11: release Golden evidence must be supplied explicitly by the
        # v19 input contract. An environment variable or status-only PASS can
        # no longer grant release authority.
        "golden_result":contract.get("golden_result") or contract.get("golden_release_evidence"),
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

    # Step 8 runs before coordination or any CAD designer. A project pressure
    # may enter calculations only when it is explicit, finite, positive and not
    # tagged as an assumption/default/benchmark value. The canonical numeric
    # aliases are written only after this contract passes.
    calculation_evidence=validate_calculation_evidence(answers)
    if calculation_evidence.get("status") in {"FAIL","INPUT_REQUIRED"}:
        return {
            "status":"FAIL","stage":"calculation_evidence_gate",
            "calculation_evidence_qa":calculation_evidence,
            "input_required":{"status":"INPUT_REQUIRED","missing_inputs":calculation_evidence.get("missing_inputs") or []},
        }
    answers=apply_canonical_pressure(answers,calculation_evidence)

    # Step 9 prevents explicit project scope from disappearing silently. The
    # current production authority engine does not issue SEPTIC or FIRE_WATER,
    # therefore those explicit requirements are blocked before any DXF write.
    required_scope=validate_required_scope_support(answers)
    if required_scope.get("status") in {"FAIL","INPUT_REQUIRED","UNSUPPORTED"}:
        return {
            "status":"FAIL","stage":"required_scope_preflight_gate",
            "calculation_evidence_qa":calculation_evidence,
            "required_scope_qa":required_scope,
            "input_required":{"status":"INPUT_REQUIRED","missing_inputs":required_scope.get("unsupported_systems") or []},
        }

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
                "calculation_evidence":calculation_evidence,
                "required_scope":required_scope,
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
        (result.setdefault("phases", {}))["calculation_evidence"]=calculation_evidence
        result["phases"]["required_scope"]=required_scope
    if result["status"] not in {"PASS","PRE_SUBMISSION"}:
        missing=[]; coordination=(result.get("phases") or {}).get("coordination") or {}; model=coordination.get("model") or {}
        missing.extend(model.get("missing_inputs") or coordination.get("missing_inputs") or [])
        if result.get("blocked_at")=="manufacturer": missing.append("OFFICIAL_MANUFACTURER_DATASHEET")
        if result.get("blocked_at")=="documentation": missing.append("PARAMETRIC_NETWORK_DOCUMENTATION")
        if result.get("blocked_at")=="golden": missing.append("SEVEN_PROJECT_GOLDEN_RELEASE_EVIDENCE")
        return {"status":"FAIL","stage":"v19_preflight_gate","v19_qa":result,
                "calculation_evidence_qa":calculation_evidence,"required_scope_qa":required_scope,
                "input_required":{"status":"INPUT_REQUIRED","missing_inputs":sorted(set(missing))}}

    backup=_snapshot_existing_output(dst)
    try:
        legacy=_design_v17(src,dst,answers=answers,plan_analysis=plan_analysis)
        legacy["v19_qa"]=result; legacy["executed_versions"]=active_version_manifest(); legacy["pipeline_authority"]="mechanical-v19"
        legacy["calculation_evidence_qa"]=calculation_evidence
        legacy["required_scope_qa"]=required_scope
        if legacy.get("status") != "PASS":
            # Step 10 transaction rule: even a lower-layer generation failure
            # must not leave a partial candidate at the release path.
            _restore_or_remove_output(dst,backup)
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

        # Defense in depth for Step 9. Today explicit septic/fire-water scope
        # is already stopped upstream as unsupported. This exact-file proof is
        # retained so future support cannot regress to text-only evidence.
        scope_artifact=validate_required_scope_artifact(dst,answers)
        legacy["required_scope_artifact_qa"]=scope_artifact
        result["phases"]["required_scope_artifact"]=scope_artifact
        if scope_artifact.get("status") == "FAIL":
            legacy["status"]="FAIL"
            legacy["stage"]="required_scope_artifact_gate"
            legacy["submission_state"]="BLOCKED"
            legacy["coordination_claim"]="NOT_RELEASED"
            _restore_or_remove_output(dst,backup)
            return legacy

        # Step 10 is the final immutable-artifact health proof. It reopens the
        # exact candidate, runs ezdxf audit without repair/save, proves the file
        # hash is unchanged, and reopens it again. Any error rolls the release
        # path back to the previous known artifact (or removes a new candidate).
        exact_health=validate_exact_dxf_health(dst)
        legacy["exact_dxf_health_qa"]=exact_health
        result["phases"]["exact_dxf_health"]=exact_health
        result["submission"]["exact_dxf_health"]=exact_health.get("status")
        if exact_health.get("status") != "PASS":
            legacy["status"]="FAIL"
            legacy["stage"]="exact_dxf_health_gate"
            legacy["submission_state"]="BLOCKED"
            legacy["coordination_claim"]="NOT_RELEASED"
            _restore_or_remove_output(dst,backup)
            return legacy

        # Step 12 is the last artifact-delivery acceptance. The legacy v17
        # isolation pass may sanitize a candidate for backward compatibility,
        # but v19 release is forbidden if any entity or layout had to be deleted
        # to make the exact file look acceptable. The Step 12 validator itself
        # is read-only and independently rechecks the exact final-delivery file.
        final_delivery=validate_non_destructive_final_delivery(dst,legacy)
        legacy["final_delivery_step12_qa"]=final_delivery
        result["phases"]["final_delivery_step12"]=final_delivery
        result["submission"]["final_delivery_step12"]=final_delivery.get("status")
        if final_delivery.get("status") != "PASS":
            legacy["status"]="FAIL"
            legacy["stage"]="final_delivery_step12_gate"
            legacy["submission_state"]="BLOCKED"
            legacy["coordination_claim"]="NOT_RELEASED"
            result["submission"]["release_allowed"]=False
            missing=final_delivery.get("missing_inputs") or []
            if missing:
                legacy["input_required"]={"status":"INPUT_REQUIRED","missing_inputs":missing}
            _restore_or_remove_output(dst,backup)
            return legacy

        legacy["submission_state"]="PRE_SUBMISSION" if result["status"]=="PRE_SUBMISSION" else "SUBMISSION_READY"
        legacy["coordination_claim"]="NOT_COORDINATED" if result["status"]=="PRE_SUBMISSION" else "COORDINATED"
        return legacy
    except Exception:
        # Candidate generation/validation is transactional even for unexpected
        # exceptions: never leave partial/corrupt bytes at the release path.
        _restore_or_remove_output(dst,backup)
        raise
    finally:
        if backup:
            backup.unlink(missing_ok=True)
