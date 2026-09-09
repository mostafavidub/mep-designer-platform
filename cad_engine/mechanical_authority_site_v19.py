"""Production adapter that makes PMM v3 / v19 authoritative before CAD materialization.

The legacy v17 path is retained only as a drawing materializer. It cannot issue a
mechanical artifact unless the PMM v3 identity contract, calculation identities,
network graph, and v19 reconciliation have already passed fail-closed authority
checks.
"""
from __future__ import annotations
import os
from pathlib import Path
from .mechanical_authority_site_v17 import design_mechanical_authority_site as _design_v17
from .mechanical_pipeline_v19 import run_v19_pipeline
from .coordination_v19 import build_coordination_model
from .parametric_documentation_v19 import generate_riser_from_network, reconcile_calculation_outputs
from .version_manifest import active_version_manifest


PMM_SCHEMA = "project-mechanical-model/v3"
PMM_POLICY = "NO_ORPHAN_ENGINEERING_OUTPUT"


def _runtime_contract_errors(answers: dict) -> list[str]:
    supplied=answers.get("_runtime_contract") or {}; active=active_version_manifest()
    return [f"runtime_contract_mismatch:{key}" for key,value in active.items() if supplied.get(key)!=value]


def _active_systems_from_pmm(pmm: dict) -> dict:
    systems=pmm.get("systems") or {}
    wet=bool(systems.get("wet_fixture_levels"))
    sanitary=bool(systems.get("sanitary_fixture_levels"))
    return {
        "cold_water":wet,
        "hot_water":wet,
        "sanitary":sanitary,
        "vent":sanitary,
        "heating":bool(systems.get("heated_levels")),
        "cooling":bool(systems.get("conditioned_levels")),
        "gas":bool(systems.get("gas_consumer_levels")),
        "ventilation_exhaust":bool(systems.get("ventilation_required_levels")),
        "roof_rainwater":bool(systems.get("roof_exists")),
    }


def _first_value(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _v19_payload(answers: dict, plan_analysis: dict) -> dict:
    contract=answers.get("_v19_input_contract") or {}
    pmm=_first_value(contract.get("project_mechanical_model"),plan_analysis.get("project_mechanical_model")) or {}
    calculation_rows=_first_value(
        contract.get("calculation_rows"),
        plan_analysis.get("calculation_rows_v19"),
        plan_analysis.get("calculation_rows"),
        plan_analysis.get("engineering_calculation_rows"),
    )
    active_systems=_first_value(contract.get("active_systems"),plan_analysis.get("active_systems_v19"))
    if active_systems is None:
        active_systems=_active_systems_from_pmm(pmm)
    return {
        "project_mechanical_model":pmm,
        "calculation_rows":calculation_rows,
        "active_systems":active_systems or {},
        "coordination_inputs":contract.get("coordination_inputs") or plan_analysis.get("coordination_inputs_v19") or {},
        "route_request":contract.get("route_request") or plan_analysis.get("route_request_v19") or {},
        "equipment_requirements":contract.get("equipment_requirements") or plan_analysis.get("equipment_requirements_v19") or {},
        "manufacturer_catalogue":contract.get("manufacturer_catalogue") or plan_analysis.get("manufacturer_catalogue_v19") or [],
        "manufacturer_database_records":_first_value(contract.get("manufacturer_database_records"),plan_analysis.get("manufacturer_database_records_v19")),
        "equipment_selection_checks":_first_value(contract.get("equipment_selection_checks"),plan_analysis.get("equipment_selection_checks_v19")),
        "declared_equipment_ids":contract.get("declared_equipment_ids") or plan_analysis.get("declared_equipment_ids_v19") or [],
        "detail_specs":contract.get("detail_specs") or plan_analysis.get("detail_specs_v19") or [],
        "final_parametric_detail_specs":contract.get("final_parametric_detail_specs") or plan_analysis.get("final_parametric_detail_specs_v19") or [],
        "network_graph":contract.get("network_graph") or plan_analysis.get("network_graph_v19") or {},
        "annotation_solver":_first_value(contract.get("annotation_solver"),plan_analysis.get("annotation_solver_v19")),
        "submission_checks":_first_value(contract.get("submission_checks"),plan_analysis.get("submission_checks_v19")),
        "engineer_review":_first_value(contract.get("engineer_review"),plan_analysis.get("engineer_review_v19")),
        "quality_metrics":contract.get("quality_metrics") or plan_analysis.get("quality_metrics_v19") or {},
        "golden_result":contract.get("golden_result") or plan_analysis.get("golden_result_v19") or {"status":os.getenv("MECHANICAL_V19_GOLDEN_STATUS","MISSING")},
    }


def _authority_input_errors(payload: dict) -> list[str]:
    errors=[]
    pmm=payload.get("project_mechanical_model") or {}
    if pmm.get("schema") != PMM_SCHEMA:
        errors.append("PROJECT_MECHANICAL_MODEL_V3_REQUIRED")
    if (pmm.get("traceability_contract") or {}).get("policy") != PMM_POLICY:
        errors.append("PMM_NO_ORPHAN_TRACEABILITY_POLICY_REQUIRED")
    rows=payload.get("calculation_rows")
    if not isinstance(rows,list) or not rows:
        errors.append("CALCULATION_ROWS_REQUIRED")
    elif any(not isinstance(row,dict) or not row.get("calc_id") for row in rows):
        errors.append("CALCULATION_IDENTITIES_REQUIRED")
    graph=payload.get("network_graph") or {}
    if not graph.get("nodes") or not graph.get("edges"):
        errors.append("NETWORK_GRAPH_REQUIRED")
    return errors


def _traceability_preflight(payload: dict) -> dict:
    input_errors=_authority_input_errors(payload)
    if input_errors:
        return {"status":"INPUT_REQUIRED","errors":input_errors,"zero_mismatch":False}
    riser=generate_riser_from_network(payload["network_graph"])
    if riser.get("status") != "PASS":
        return {"status":"FAIL","errors":riser.get("errors") or riser.get("missing_inputs") or ["RISER_GRAPH_RECONCILIATION_FAILED"],
                "zero_mismatch":False,"riser":riser}
    reconciliation=reconcile_calculation_outputs(payload["calculation_rows"],riser)
    return {"status":reconciliation.get("status"),"errors":reconciliation.get("errors") or [],
            "zero_mismatch":bool(reconciliation.get("zero_mismatch")),"riser":riser,
            "calculation_reconciliation":reconciliation}


def _result_authority_errors(result: dict) -> list[str]:
    errors=[]
    if result.get("status") != "PASS":
        errors.append("V19_PIPELINE_NOT_PASS")
    submission=result.get("submission") or {}
    if submission.get("release_allowed") is not True:
        errors.append("V19_RELEASE_NOT_ALLOWED")
    documentation=(result.get("phases") or {}).get("documentation") or {}
    if documentation.get("status") != "PASS":
        errors.append("V19_DOCUMENTATION_NOT_PASS")
    if documentation.get("pmm_traceability_required") is not True:
        errors.append("PMM_TRACEABILITY_NOT_ENFORCED")
    reconciliation=documentation.get("calculation_reconciliation") or {}
    if reconciliation.get("status") != "PASS" or reconciliation.get("zero_mismatch") is not True:
        errors.append("CALCULATION_OUTPUT_RECONCILIATION_NOT_PASS")
    return errors


def _failure_missing(result: dict) -> list[str]:
    missing=[]
    coordination=(result.get("phases") or {}).get("coordination") or {}
    model=coordination.get("model") or {}
    missing.extend(model.get("missing_inputs") or coordination.get("missing_inputs") or [])
    blocked=result.get("blocked_at")
    if blocked=="manufacturer": missing.append("OFFICIAL_MANUFACTURER_DATASHEET")
    if blocked=="documentation": missing.append("PARAMETRIC_NETWORK_DOCUMENTATION")
    if blocked=="golden": missing.append("V19_RELEASE_GOLDEN_PASS")
    return sorted(set(missing))


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    answers=dict(answers or {}); plan_analysis=dict(plan_analysis or {})
    contract_errors=_runtime_contract_errors(answers)
    if contract_errors:
        return {"status":"FAIL","stage":"v19_runtime_contract_gate","v19_qa":{"status":"FAIL","errors":contract_errors}}

    payload=_v19_payload(answers,plan_analysis)
    traceability=_traceability_preflight(payload)
    if traceability.get("status") != "PASS":
        return {"status":"FAIL","stage":"v19_authority_input_gate","v19_qa":{"status":traceability.get("status"),"traceability":traceability},
                "input_required":{"status":"INPUT_REQUIRED" if traceability.get("status")=="INPUT_REQUIRED" else "FAIL",
                                  "missing_inputs":traceability.get("errors") or []}}

    # No architecture-only bypass is allowed to issue an artifact. Structural/RCP
    # inputs may still be absent, but v19 then remains INPUT_REQUIRED and the CAD
    # materializer is not invoked.
    result=run_v19_pipeline(payload)
    authority_errors=_result_authority_errors(result)
    if authority_errors:
        missing=_failure_missing(result)
        missing.extend(authority_errors)
        return {"status":"FAIL","stage":"v19_authority_release_gate","v19_qa":result,
                "input_required":{"status":"INPUT_REQUIRED" if result.get("status")=="INPUT_REQUIRED" else "FAIL",
                                  "missing_inputs":sorted(set(missing))}}

    # v17 is now drawing-only compatibility materialization. It is unreachable
    # until PMM v3, calculations, graph, v19 documentation and reconciliation pass.
    rendered=_design_v17(src,dst,answers=answers,plan_analysis=plan_analysis)
    if rendered.get("status") != "PASS":
        rendered["pipeline_authority"]="mechanical-v19"
        rendered["engineering_authority"]="PMM_V3_V19"
        rendered["cad_materializer"]="legacy-v17-renderer-only"
        rendered["legacy_renderer_role"]="CAD_MATERIALIZER_ONLY"
        rendered["v19_qa"]=result
        rendered["v19_traceability_preflight"]=traceability
        return rendered

    rendered["v19_qa"]=result
    rendered["v19_traceability_preflight"]=traceability
    rendered["executed_versions"]=active_version_manifest()
    rendered["pipeline_authority"]="mechanical-v19"
    rendered["engineering_authority"]="PMM_V3_V19"
    rendered["cad_materializer"]="legacy-v17-renderer-only"
    rendered["legacy_renderer_role"]="CAD_MATERIALIZER_ONLY"
    rendered["submission_state"]="SUBMISSION_READY"
    rendered["coordination_claim"]="COORDINATED"
    return rendered
