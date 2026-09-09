"""Production adapter that makes PMM v3 / canonical authoritative before CAD materialization.

Topology, segment execution data and final plan-route entities are now derived or
validated by canonical before a mechanical artifact can be issued. Legacy canonical remains
only the compatibility shell for boards, copied architecture and supporting
content; its plan-route decisions are replaced by the graph-native materializer.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from .mechanical_cad_shell import design_mechanical_authority_site as _design_shell
from .mechanical_pipeline import run_pipeline
from .mechanical_documentation import generate_riser_from_network, reconcile_calculation_outputs
from .mechanical_network_topology import build_authoritative_topology
from .mechanical_segment_execution import design_authoritative_segments
from .mechanical_network_materializer import materialize_authoritative_network
from .runtime_contract import runtime_contract


PMM_SCHEMA = "project-mechanical-model/v3"
PMM_POLICY = "NO_ORPHAN_ENGINEERING_OUTPUT"


def _runtime_contract_errors(answers: dict) -> list[str]:
    supplied = answers.get("_runtime_contract") or {}
    active = runtime_contract()
    return [f"runtime_contract_mismatch:{key}" for key, value in active.items() if supplied.get(key) != value]


def _active_systems_from_pmm(pmm: dict) -> dict:
    systems = pmm.get("systems") or {}
    wet = bool(systems.get("wet_fixture_levels"))
    sanitary = bool(systems.get("sanitary_fixture_levels"))
    return {
        "cold_water": wet,
        "hot_water": wet,
        "sanitary": sanitary,
        "vent": sanitary,
        "heating": bool(systems.get("heated_levels")),
        "cooling": bool(systems.get("conditioned_levels")),
        "gas": bool(systems.get("gas_consumer_levels")),
        "ventilation_exhaust": bool(systems.get("ventilation_required_levels")),
        "roof_rainwater": bool(systems.get("roof_exists")),
    }


def _first_value(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _authority_payload(answers: dict, plan_analysis: dict) -> dict:
    contract = answers.get("_canonical_input_contract") or {}
    pmm = _first_value(contract.get("project_mechanical_model"), plan_analysis.get("project_mechanical_model")) or {}
    calculation_rows = _first_value(
        contract.get("calculation_rows"),
        plan_analysis.get("calculation_rows_canonical"),
        plan_analysis.get("calculation_rows"),
        plan_analysis.get("engineering_calculation_rows"),
    )
    active_systems = _first_value(contract.get("active_systems"), plan_analysis.get("active_systems_canonical"))
    if active_systems is None:
        active_systems = _active_systems_from_pmm(pmm)
    return {
        "project_mechanical_model": pmm,
        "calculation_rows": calculation_rows,
        "active_systems": active_systems or {},
        "coordination_inputs": contract.get("coordination_inputs") or plan_analysis.get("coordination_inputs_canonical") or {},
        "route_request": contract.get("route_request") or plan_analysis.get("route_request_canonical") or {},
        "equipment_requirements": contract.get("equipment_requirements") or plan_analysis.get("equipment_requirements_canonical") or {},
        "manufacturer_catalogue": contract.get("manufacturer_catalogue") or plan_analysis.get("manufacturer_catalogue_canonical") or [],
        "manufacturer_database_records": _first_value(contract.get("manufacturer_database_records"), plan_analysis.get("manufacturer_database_records_canonical")),
        "equipment_selection_checks": _first_value(contract.get("equipment_selection_checks"), plan_analysis.get("equipment_selection_checks_canonical")),
        "declared_equipment_ids": contract.get("declared_equipment_ids") or plan_analysis.get("declared_equipment_ids_canonical") or [],
        "detail_specs": contract.get("detail_specs") or plan_analysis.get("detail_specs_canonical") or [],
        "final_parametric_detail_specs": contract.get("final_parametric_detail_specs") or plan_analysis.get("final_parametric_detail_specs_canonical") or [],
        "network_graph": contract.get("network_graph") or plan_analysis.get("network_graph_canonical") or {},
        "network_level_assignments": _first_value(contract.get("network_level_assignments"), plan_analysis.get("network_level_assignments_canonical"), answers.get("_network_level_assignments")),
        "network_design_basis": _first_value(contract.get("network_design_basis"), plan_analysis.get("network_design_basis_canonical"), answers.get("_network_design_basis")),
        "annotation_solver": _first_value(contract.get("annotation_solver"), plan_analysis.get("annotation_solver_canonical")),
        "submission_checks": _first_value(contract.get("submission_checks"), plan_analysis.get("submission_checks_canonical")),
        "engineer_review": _first_value(contract.get("engineer_review"), plan_analysis.get("engineer_review_canonical")),
        "quality_metrics": contract.get("quality_metrics") or plan_analysis.get("quality_metrics_canonical") or {},
        "golden_result": contract.get("golden_result") or plan_analysis.get("golden_result_canonical") or {"status": os.getenv("MECHANICAL_GOLDEN_STATUS", "MISSING")},
    }


def _prepare_network_authority(src: Path, payload: dict) -> dict:
    pmm = payload.get("project_mechanical_model") or {}
    if pmm.get("schema") != PMM_SCHEMA:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["PROJECT_MECHANICAL_MODEL_V3"], "errors": []}
    if (pmm.get("traceability_contract") or {}).get("policy") != PMM_POLICY:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["PMM_NO_ORPHAN_TRACEABILITY_POLICY_REQUIRED"], "errors": []}
    existing = payload.get("network_graph") or {}
    if existing.get("nodes") and existing.get("edges"):
        topology = {"status": "PASS", "network": existing, "source": "SUPPLIED_NETWORK_GRAPH"}
    else:
        topology = build_authoritative_topology(src, pmm, level_assignments=payload.get("network_level_assignments"))
    if topology.get("status") != "PASS":
        return {"status": topology.get("status") or "INPUT_REQUIRED",
                "missing_inputs": topology.get("missing_inputs") or [],
                "errors": topology.get("errors") or [], "topology": topology}

    execution = design_authoritative_segments(
        topology["network"],
        design_basis=payload.get("network_design_basis") or {},
        calculation_rows=payload.get("calculation_rows") or [],
    )
    if execution.get("status") != "PASS":
        return {"status": execution.get("status") or "INPUT_REQUIRED",
                "missing_inputs": execution.get("missing_inputs") or [],
                "errors": execution.get("errors") or [], "topology": topology, "execution": execution}

    payload["network_graph"] = execution["network"]
    payload["calculation_rows"] = execution["calculation_rows"]
    # Annotation support is identity-backed from the same execution records. A
    # caller may still supply an annotation solver for placement, but not a
    # disconnected annotation identity set.
    payload["annotations"] = execution["annotations"]
    return {"status": "PASS", "topology": topology, "execution": execution,
            "network_graph": payload["network_graph"], "calculation_rows": payload["calculation_rows"]}


def _authority_input_errors(payload: dict) -> list[str]:
    errors = []
    pmm = payload.get("project_mechanical_model") or {}
    if pmm.get("schema") != PMM_SCHEMA:
        errors.append("PROJECT_MECHANICAL_MODEL_V3_REQUIRED")
    if (pmm.get("traceability_contract") or {}).get("policy") != PMM_POLICY:
        errors.append("PMM_NO_ORPHAN_TRACEABILITY_POLICY_REQUIRED")
    rows = payload.get("calculation_rows")
    if not isinstance(rows, list) or not rows:
        errors.append("CALCULATION_ROWS_REQUIRED")
    elif any(not isinstance(row, dict) or not row.get("calc_id") for row in rows):
        errors.append("CALCULATION_IDENTITIES_REQUIRED")
    graph = payload.get("network_graph") or {}
    if not graph.get("nodes") or not graph.get("edges"):
        errors.append("NETWORK_GRAPH_REQUIRED")
    elif any(not edge.get("size") or not edge.get("material") for edge in graph.get("edges") or []):
        errors.append("NETWORK_EXECUTION_SIZE_AND_MATERIAL_REQUIRED")
    return errors


def _traceability_preflight(payload: dict) -> dict:
    input_errors = _authority_input_errors(payload)
    if input_errors:
        return {"status": "INPUT_REQUIRED", "errors": input_errors, "zero_mismatch": False}
    riser = generate_riser_from_network(payload["network_graph"])
    if riser.get("status") != "PASS":
        return {"status": "FAIL", "errors": riser.get("errors") or riser.get("missing_inputs") or ["RISER_GRAPH_RECONCILIATION_FAILED"],
                "zero_mismatch": False, "riser": riser}
    reconciliation = reconcile_calculation_outputs(payload["calculation_rows"], riser)
    return {"status": reconciliation.get("status"), "errors": reconciliation.get("errors") or [],
            "zero_mismatch": bool(reconciliation.get("zero_mismatch")), "riser": riser,
            "calculation_reconciliation": reconciliation}


def _result_authority_errors(result: dict) -> list[str]:
    errors = []
    if result.get("status") != "PASS":
        errors.append("V19_PIPELINE_NOT_PASS")
    submission = result.get("submission") or {}
    if submission.get("release_allowed") is not True:
        errors.append("V19_RELEASE_NOT_ALLOWED")
    documentation = (result.get("phases") or {}).get("documentation") or {}
    if documentation.get("status") != "PASS":
        errors.append("V19_DOCUMENTATION_NOT_PASS")
    if documentation.get("pmm_traceability_required") is not True:
        errors.append("PMM_TRACEABILITY_NOT_ENFORCED")
    reconciliation = documentation.get("calculation_reconciliation") or {}
    if reconciliation.get("status") != "PASS" or reconciliation.get("zero_mismatch") is not True:
        errors.append("CALCULATION_OUTPUT_RECONCILIATION_NOT_PASS")
    return errors


def _failure_missing(result: dict) -> list[str]:
    missing = []
    coordination = (result.get("phases") or {}).get("coordination") or {}
    model = coordination.get("model") or {}
    missing.extend(model.get("missing_inputs") or coordination.get("missing_inputs") or [])
    blocked = result.get("blocked_at")
    if blocked == "manufacturer":
        missing.append("OFFICIAL_MANUFACTURER_DATASHEET")
    if blocked == "documentation":
        missing.append("PARAMETRIC_NETWORK_DOCUMENTATION")
    if blocked == "golden":
        missing.append("MECHANICAL_RELEASE_GOLDEN_PASS")
    return sorted(set(missing))


def _restore_target(dst: Path, backup: Path | None):
    if backup and backup.exists():
        shutil.copy2(backup, dst)
    else:
        dst.unlink(missing_ok=True)


def design_mechanical_authority_site(src: Path, dst: Path, answers: dict | None = None, plan_analysis: dict | None = None) -> dict:
    src = Path(src); dst = Path(dst)
    answers = dict(answers or {}); plan_analysis = dict(plan_analysis or {})
    contract_errors = _runtime_contract_errors(answers)
    if contract_errors:
        return {"status": "FAIL", "stage": "runtime_contract_gate", "authority_pipeline_qa": {"status": "FAIL", "errors": contract_errors}}

    payload = _authority_payload(answers, plan_analysis)
    network_authority = _prepare_network_authority(src, payload)
    if network_authority.get("status") != "PASS":
        required = network_authority.get("missing_inputs") or network_authority.get("errors") or ["NETWORK_AUTHORITY_INCOMPLETE"]
        return {"status": "FAIL", "stage": "network_authority_gate",
                "network_authority_qa": network_authority,
                "input_required": {"status": "INPUT_REQUIRED" if network_authority.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": sorted(set(required))}}

    traceability = _traceability_preflight(payload)
    if traceability.get("status") != "PASS":
        return {"status": "FAIL", "stage": "authority_input_gate",
                "network_authority_qa": network_authority,
                "authority_pipeline_qa": {"status": traceability.get("status"), "traceability": traceability},
                "input_required": {"status": "INPUT_REQUIRED" if traceability.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": traceability.get("errors") or []}}

    result = run_pipeline(payload)
    authority_errors = _result_authority_errors(result)
    if authority_errors:
        missing = _failure_missing(result)
        missing.extend(authority_errors)
        return {"status": "FAIL", "stage": "authority_release_gate",
                "network_authority_qa": network_authority, "authority_pipeline_qa": result,
                "input_required": {"status": "INPUT_REQUIRED" if result.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": sorted(set(missing))}}

    # Preserve the pre-run artifact so a graph-materialization failure cannot
    # leave a legacy-only DXF behind after the canonical gate has rejected the run.
    backup = None
    if dst.exists():
        fd, name = tempfile.mkstemp(prefix="engitools-mechanical-authority-", suffix=".dxf")
        Path(name).unlink(missing_ok=True)
        backup = Path(name)
        shutil.copy2(dst, backup)

    rendered = _design_shell(src, dst, answers=answers, plan_analysis=plan_analysis)
    if rendered.get("status") != "PASS":
        if backup:
            backup.unlink(missing_ok=True)
        rendered["pipeline_authority"] = "mechanical"
        rendered["engineering_authority"] = "PMM_V3"
        rendered["cad_materializer"] = "canonical-cad-shell"
        rendered["cad_shell_role"] = "CAD_SHELL_ONLY"
        rendered["network_authority_qa"] = network_authority
        rendered["authority_pipeline_qa"] = result
        rendered["traceability_preflight"] = traceability
        return rendered

    materialization = materialize_authoritative_network(src, dst, rendered, payload["network_graph"])
    if materialization.get("status") != "PASS":
        _restore_target(dst, backup)
        if backup:
            backup.unlink(missing_ok=True)
        return {"status": "FAIL", "stage": "network_materialization_gate",
                "network_authority_qa": network_authority, "authority_pipeline_qa": result,
                "traceability_preflight": traceability,
                "materialization_qa": materialization,
                "input_required": {"status": "INPUT_REQUIRED" if materialization.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": materialization.get("missing_inputs") or materialization.get("errors") or []}}
    if backup:
        backup.unlink(missing_ok=True)

    rendered["network_authority_qa"] = network_authority
    rendered["materialization_qa"] = materialization
    rendered["authority_pipeline_qa"] = result
    rendered["traceability_preflight"] = traceability
    rendered["runtime_contract"] = runtime_contract()
    rendered["pipeline_authority"] = "mechanical"
    rendered["engineering_authority"] = "PMM_V3"
    rendered["cad_materializer"] = "canonical-cad-shell+graph-native-network"
    rendered["cad_shell_role"] = "CAD_SHELL_ONLY"
    rendered["submission_state"] = "SUBMISSION_READY"
    rendered["coordination_claim"] = "COORDINATED"
    return rendered
