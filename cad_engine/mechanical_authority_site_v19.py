"""Production adapter that makes v19 authoritative before legacy composition."""
from __future__ import annotations
import os
from pathlib import Path
from app.project_mechanical_model import build_project_mechanical_model
from .mechanical_authority_site_v17 import design_mechanical_authority_site as _design_v17
from .mechanical_authority_v15 import build_design_overrides
from .engineering_runner_v13 import run_engineering_pipeline, validate_pipeline
from .mechanical_pipeline_v19 import run_v19_pipeline
from .coordination_v19 import build_coordination_model
from .production_quality_truth import evaluate_production_truth
from .production_quality_documentation import rebuild_production_documentation
from .version_manifest import active_version_manifest


def _runtime_contract_errors(answers: dict) -> list[str]:
    supplied=answers.get("_runtime_contract") or {}; active=active_version_manifest()
    return [f"runtime_contract_mismatch:{key}" for key,value in active.items() if supplied.get(key)!=value]


def _derived_pmm_from_approved_analysis(answers: dict, plan_analysis: dict) -> dict:
    """Build the existing PMM v3 contract from the approved workflow snapshot.

    Older workflow records may predate persisted PMM installation. Production may
    derive the same deterministic PMM from the already-approved analysis and
    drawing manifest, but it may not invent missing architecture evidence.
    """
    manifest=answers.get("_approved_drawing_manifest")
    if manifest is None or not (plan_analysis.get("architectural_auto") or {}).get("level_profiles"):
        return {}
    rows=list(manifest or [])
    return build_project_mechanical_model(
        analysis=plan_analysis,
        answers=answers,
        scope={},
        proposal={"drawing_manifest":rows,"total_plans":len(rows)},
    )


def _v19_payload(answers: dict, plan_analysis: dict) -> dict:
    contract=answers.get("_v19_input_contract") or {}
    pmm=contract.get("project_mechanical_model") or plan_analysis.get("project_mechanical_model") or _derived_pmm_from_approved_analysis(answers,plan_analysis)
    calculation_rows=contract.get("calculation_rows")
    if calculation_rows is None:
        calculation_rows=plan_analysis.get("calculation_rows_v19")
    return {
        "coordination_inputs":contract.get("coordination_inputs") or plan_analysis.get("coordination_inputs_v19") or {},
        "route_request":contract.get("route_request") or plan_analysis.get("route_request_v19") or {},
        "equipment_requirements":contract.get("equipment_requirements") or plan_analysis.get("equipment_requirements_v19") or {},
        "manufacturer_catalogue":contract.get("manufacturer_catalogue") or plan_analysis.get("manufacturer_catalogue_v19") or [],
        "detail_specs":contract.get("detail_specs") or plan_analysis.get("detail_specs_v19") or [],
        "network_graph":contract.get("network_graph") or plan_analysis.get("network_graph_v19") or {},
        "calculation_rows":calculation_rows,
        "project_mechanical_model":pmm,
        "active_systems":contract.get("active_systems") or plan_analysis.get("active_systems_v19") or {},
        "submission_checks":contract.get("submission_checks") or plan_analysis.get("submission_checks_v19"),
        "golden_result":{"status":os.getenv("MECHANICAL_V19_GOLDEN_STATUS","MISSING")},
    }


def _production_preflight(src: Path, answers: dict, plan_analysis: dict, payload: dict) -> tuple[dict, dict | None]:
    """Run the coordination-independent truth gate only for workflow-bound jobs."""
    if answers.get("_approved_drawing_manifest") is None:
        return {"status":"NOT_APPLICABLE","reason":"DIRECT_ENGINE_CALL_WITHOUT_WORKFLOW_MANIFEST"}, None
    try:
        overrides=build_design_overrides(answers)
        pipeline=run_engineering_pipeline(src,design_basis=overrides,project_overrides=overrides)
        pipeline_qa=validate_pipeline(pipeline)
    except Exception as exc:
        return {"status":"FAIL","errors":["PRODUCTION_TRUTH_PIPELINE_EXCEPTION:"+type(exc).__name__]}, None
    truth=evaluate_production_truth(payload.get("project_mechanical_model") or {},pipeline,pipeline_qa)
    if truth.get("status")=="PASS":
        trace=truth.get("traceability") or {}
        if not payload.get("network_graph"):
            payload["network_graph"]=trace.get("network_graph") or {}
        if payload.get("calculation_rows") is None:
            payload["calculation_rows"]=trace.get("calculation_rows") or []
    truth["legacy_pipeline_qa"]=pipeline_qa
    return truth,pipeline


def _blocked_truth_response(truth: dict) -> dict:
    missing=list(truth.get("missing_inputs") or [])
    return {
        "status":"FAIL",
        "stage":"v19_production_truth_gate",
        "v19_truth_qa":truth,
        "input_required":{"status":"INPUT_REQUIRED" if missing else "FAIL","missing_inputs":missing},
    }


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src); dst=Path(dst); answers=dict(answers or {}); plan_analysis=dict(plan_analysis or {})
    contract_errors=_runtime_contract_errors(answers)
    if contract_errors:
        return {"status":"FAIL","stage":"v19_runtime_contract_gate","v19_qa":{"status":"FAIL","errors":contract_errors}}
    payload=_v19_payload(answers,plan_analysis)

    truth,pipeline=_production_preflight(src,answers,plan_analysis,payload)
    if truth.get("status") not in {"PASS","NOT_APPLICABLE"}:
        return _blocked_truth_response(truth)

    coordination=build_coordination_model(payload)
    missing_structure=coordination["status"]=="INPUT_REQUIRED" and set(coordination.get("missing_inputs") or {}) <= {"STRUCTURAL_MODEL","RCP_MODEL","SLAB","CEILING"}
    if missing_structure:
        # Architecture-only work is permitted only after the production truth
        # gate passes. It can never inherit coordinated/submission-ready claims.
        result={
            "status":"PRE_SUBMISSION","blocked_at":None,
            "operating_profile":"ARCHITECTURE_ONLY_PRE_SUBMISSION",
            "phases":{
                "truth":truth,
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
        missing=[]; coordination_phase=(result.get("phases") or {}).get("coordination") or {}; model=coordination_phase.get("model") or {}
        missing.extend(model.get("missing_inputs") or coordination_phase.get("missing_inputs") or [])
        if result.get("blocked_at")=="manufacturer": missing.append("OFFICIAL_MANUFACTURER_DATASHEET")
        if result.get("blocked_at")=="documentation": missing.append("PARAMETRIC_NETWORK_DOCUMENTATION")
        if result.get("blocked_at")=="golden": missing.append("V19_RELEASE_GOLDEN_PASS")
        return {"status":"FAIL","stage":"v19_preflight_gate","v19_qa":result,"v19_truth_qa":truth,
                "input_required":{"status":"INPUT_REQUIRED","missing_inputs":sorted(set(missing))}}

    legacy=_design_v17(src,dst,answers=answers,plan_analysis=plan_analysis)
    if legacy.get("status")!="PASS":
        legacy["v19_qa"]=result; legacy["v19_truth_qa"]=truth
        return legacy

    if pipeline is not None:
        documentation_truth=rebuild_production_documentation(dst,legacy,pipeline,answers,src.stem)
        legacy["production_documentation_truth_qa"]=documentation_truth
        if documentation_truth.get("status")!="PASS":
            dst.unlink(missing_ok=True)
            return {
                "status":"FAIL","stage":"v19_production_documentation_truth_gate",
                "v19_qa":result,"v19_truth_qa":truth,
                "production_documentation_truth_qa":documentation_truth,
            }
        legacy["reference_parity_documentation"]=documentation_truth.get("documentation_package") or legacy.get("reference_parity_documentation")
        legacy["documentation_enhancement_qa"]=documentation_truth.get("enhancement") or legacy.get("documentation_enhancement_qa")
        legacy["exact_file_final_delivery_qa"]=documentation_truth.get("exact_file_final_delivery_qa") or legacy.get("exact_file_final_delivery_qa")

    legacy["v19_qa"]=result; legacy["v19_truth_qa"]=truth; legacy["executed_versions"]=active_version_manifest(); legacy["pipeline_authority"]="mechanical-v19"
    legacy["submission_state"]="PRE_SUBMISSION" if result["status"]=="PRE_SUBMISSION" else "SUBMISSION_READY"
    legacy["coordination_claim"]="NOT_COORDINATED" if result["status"]=="PRE_SUBMISSION" else "COORDINATED"
    return legacy
