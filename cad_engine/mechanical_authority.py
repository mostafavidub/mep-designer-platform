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
from hashlib import sha256

from .mechanical_cad_shell import design_mechanical_authority_site as _design_shell
from .mechanical_pipeline import run_pipeline
from .mechanical_documentation import generate_riser_from_network, reconcile_calculation_outputs
from .mechanical_network_topology import build_authoritative_topology
from .mechanical_segment_execution import design_authoritative_segments
from .mechanical_network_materializer import materialize_authoritative_network
from .runtime_contract import runtime_contract
from .calculation_reasonableness import evaluate_calculation_reasonableness
from .topology_routing_gate import evaluate_topology_routing
from .equipment_selection_placement_gate import (
    evaluate_equipment_selection_placement,
    exact_equipment_output_evidence,
)
from .final_engineering_release_gate import evaluate_final_engineering_release
from .architecture_space_equipment_gate import (
    evaluate_architecture_space_equipment,
    exact_architecture_source_evidence,
)


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
        "architecture_evidence": contract.get("architecture_evidence") or {},
        "fixture_evidence": contract.get("fixture_evidence") or [],
        "declared_fixture_schedule": contract.get("declared_fixture_schedule"),
        "mechanical_shaft_route": contract.get("mechanical_shaft_route"),
        "calculation_rows": calculation_rows,
        "active_systems": active_systems or {},
        "coordination_inputs": contract.get("coordination_inputs") or plan_analysis.get("coordination_inputs_canonical") or {},
        "route_request": contract.get("route_request") or plan_analysis.get("route_request_canonical") or {},
        "equipment_requirements": contract.get("equipment_requirements") or plan_analysis.get("equipment_requirements_canonical") or {},
        "manufacturer_catalogue": contract.get("manufacturer_catalogue") or plan_analysis.get("manufacturer_catalogue_canonical") or [],
        "manufacturer_database_records": _first_value(contract.get("manufacturer_database_records"), plan_analysis.get("manufacturer_database_records_canonical")),
        "target_design_inputs": _first_value(contract.get("target_design_inputs"), plan_analysis.get("target_design_inputs_canonical")),
        "target_design_packages": _first_value(contract.get("target_design_packages"), plan_analysis.get("target_design_packages_canonical")),
        "construction_delivery_inputs": _first_value(contract.get("construction_delivery_inputs"), plan_analysis.get("construction_delivery_inputs_canonical")),
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
        "sensitivity_checks": _first_value(contract.get("sensitivity_checks"), plan_analysis.get("sensitivity_checks_canonical")),
        "selected_equipment": _first_value(contract.get("selected_equipment"), plan_analysis.get("selected_equipment_canonical")),
        "calculation_totals": _first_value(contract.get("calculation_totals"), plan_analysis.get("calculation_totals_canonical")),
        "equipment_placement_context": _first_value(contract.get("equipment_placement_context"), plan_analysis.get("equipment_placement_context_canonical")),
        "final_release_context": _first_value(contract.get("final_release_context"), plan_analysis.get("final_release_context_canonical")),
        "architecture_recognition_context": _first_value(contract.get("architecture_recognition_context"), plan_analysis.get("architecture_recognition_context_canonical")),
    }


def _equipment_context(payload: dict, result: dict) -> dict:
    supplied = dict(payload.get("equipment_placement_context") or {})
    pmm = payload.get("project_mechanical_model") or {}
    supplied.setdefault("rooms", pmm.get("rooms") or [])
    supplied.setdefault("selected_equipment", payload.get("selected_equipment") or [])
    supplied.setdefault("calculations", payload.get("calculation_rows") or [])
    supplied.setdefault("routes", (payload.get("network_graph") or {}).get("edges") or [])
    documentation = (result.get("phases") or {}).get("documentation") or {}
    supplied.setdefault("schedules", documentation.get("equipment_schedule") or documentation.get("schedules") or [])
    supplied.setdefault("risers", documentation.get("equipment_risers") or documentation.get("riser_equipment") or [])
    return supplied


def _final_release_context(payload: dict, result: dict, equipment_qa: dict) -> dict:
    supplied = dict(payload.get("final_release_context") or {})
    phases = result.get("phases") or {}
    supplied.setdefault("equipment_selection_placement_qa", equipment_qa)
    supplied.setdefault("submission_quality", phases.get("submission_quality") or {})
    supplied.setdefault("independent_review", payload.get("engineer_review"))
    return supplied


def _exact_release_evidence(dst: Path, context: dict, materialization: dict) -> dict:
    supplied = dict(context.get("exact_release_package") or {})
    artifacts = dict(supplied.get("artifacts") or {})
    actual_cad_hash = sha256(dst.read_bytes()).hexdigest() if dst.exists() else ""
    # CAD identity is always measured from the exact issued file. Other package
    # members remain explicit inputs and are never inferred from filenames.
    if artifacts.get("cad") and artifacts.get("cad") != actual_cad_hash:
        supplied["cad_hash_mismatch"] = True
    artifacts["cad"] = actual_cad_hash
    supplied["artifacts"] = artifacts
    supplied["reopened"] = bool(materialization.get("exact_file_reopened"))
    supplied["immutable"] = bool(materialization.get("transactional_exact_output")) and not supplied.get("cad_hash_mismatch")
    return supplied


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
        topology = build_authoritative_topology(
            src, pmm,
            level_assignments=payload.get("network_level_assignments"),
            architecture_evidence=payload.get("architecture_evidence"),
            fixture_evidence=payload.get("fixture_evidence"),
            declared_fixture_schedule=payload.get("declared_fixture_schedule"),
        )
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
    topology_routing_qa = evaluate_topology_routing(
        payload["network_graph"], calculation_rows=payload["calculation_rows"],
        coordination=(payload.get("topology_routing_coordination") or {}),
        equipment_routes=(payload.get("equipment_selection_checks") or []),
    )
    if topology_routing_qa.get("status") != "PASS":
        return {"status": "FAIL", "errors": topology_routing_qa.get("errors") or ["TOPOLOGY_ROUTING_100_REQUIRED"],
                "topology": topology, "execution": execution, "topology_routing_qa": topology_routing_qa}
    return {"status": "PASS", "topology": topology, "execution": execution,
            "network_graph": payload["network_graph"], "calculation_rows": payload["calculation_rows"],
            "topology_routing_qa": topology_routing_qa}


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


def _pipeline_blockers(result: dict) -> list[str]:
    """Return actual blocked-phase evidence without inventing later failures."""
    blocked = result.get("blocked_at")
    phase = ((result.get("phases") or {}).get(blocked) or {}) if blocked else {}
    found = []

    def visit(value):
        if isinstance(value, dict):
            found.extend(str(item) for key in ("missing_inputs", "errors") for item in (value.get(key) or []))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(phase)
    if not found and blocked:
        found.append("PIPELINE_INPUT_REQUIRED:" + str(blocked))
    return sorted(set(found))


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
    pre_submission = result.get("status") == "INPUT_REQUIRED"
    authority_errors = _result_authority_errors(result)
    if result.get("status") == "FAIL" or (authority_errors and not pre_submission):
        missing = _failure_missing(result)
        missing.extend(authority_errors)
        return {"status": "FAIL", "stage": "authority_release_gate",
                "network_authority_qa": network_authority, "authority_pipeline_qa": result,
                "input_required": {"status": "INPUT_REQUIRED" if result.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": sorted(set(missing))}}

    recognition_context = dict(payload.get("architecture_recognition_context") or {})
    expected_architecture_hash = (recognition_context.get("source_identity") or {}).get("sha256")
    recognition_exact = exact_architecture_source_evidence(src, expected_architecture_hash)
    recognition_qa = evaluate_architecture_space_equipment(recognition_context, recognition_exact)
    if not pre_submission and recognition_qa.get("status") != "PASS":
        blockers = recognition_qa.get("errors") or recognition_qa.get("missing_inputs") or ["ARCHITECTURE_SPACE_EQUIPMENT_100_REQUIRED"]
        return {"status": "FAIL", "stage": "architecture_space_equipment_gate",
                "authority_pipeline_qa": result, "architecture_space_equipment_qa": recognition_qa,
                "input_required": {"status": "INPUT_REQUIRED" if recognition_qa.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": blockers}}

    reasonableness = evaluate_calculation_reasonableness(payload)
    # A preliminary artifact may still be delivered truthfully for an earlier
    # external-input blocker.  Only a submission-ready claim is stopped here.
    if not pre_submission and reasonableness.get("status") != "PASS":
        blockers = reasonableness.get("errors") or reasonableness.get("missing_inputs") or ["CALCULATION_REASONABLENESS_NOT_PASS"]
        return {"status": "FAIL", "stage": "calculation_reasonableness_gate",
                "network_authority_qa": network_authority, "traceability_preflight": traceability,
                "authority_pipeline_qa": result, "calculation_reasonableness_qa": reasonableness,
                "input_required": {"status": "INPUT_REQUIRED" if reasonableness.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": blockers}}

    equipment_context = _equipment_context(payload, result)
    equipment_preflight = evaluate_equipment_selection_placement(equipment_context)
    if not pre_submission and equipment_preflight.get("preflight_allowed") is not True:
        blockers = equipment_preflight.get("errors") or equipment_preflight.get("missing_inputs") or ["EQUIPMENT_SELECTION_PLACEMENT_PREFLIGHT_NOT_PASS"]
        return {"status": "FAIL", "stage": "equipment_selection_placement_gate",
                "network_authority_qa": network_authority, "traceability_preflight": traceability,
                "authority_pipeline_qa": result, "calculation_reasonableness_qa": reasonableness,
                "equipment_selection_placement_qa": equipment_preflight,
                "input_required": {"status": "INPUT_REQUIRED" if equipment_preflight.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": blockers}}

    final_release_context = _final_release_context(payload, result, equipment_preflight)
    final_release_preflight = evaluate_final_engineering_release(final_release_context)
    if not pre_submission and final_release_preflight.get("preflight_allowed") is not True:
        blockers = final_release_preflight.get("errors") or final_release_preflight.get("missing_inputs") or ["FINAL_ENGINEERING_RELEASE_PREFLIGHT_NOT_PASS"]
        return {"status": "FAIL", "stage": "final_engineering_release_gate",
                "authority_pipeline_qa": result,
                "final_engineering_release_qa": final_release_preflight,
                "input_required": {"status": "INPUT_REQUIRED" if final_release_preflight.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": blockers}}

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
    final_topology_routing = evaluate_topology_routing(
        payload["network_graph"], calculation_rows=payload["calculation_rows"],
        coordination=(payload.get("topology_routing_coordination") or {}),
        equipment_routes=(payload.get("equipment_selection_checks") or []),
        exact_output={"edge_ids": materialization.get("materialized_edge_ids") or [],
                      "reopened": materialization.get("exact_file_reopened"),
                      "immutable": materialization.get("transactional_exact_output")},
    )
    if final_topology_routing.get("status") != "PASS":
        _restore_target(dst, backup)
        return {"status": "FAIL", "stage": "topology_routing_exact_output_gate",
                "topology_routing_qa": final_topology_routing,
                "input_required": {"status": "FAIL", "missing_inputs": final_topology_routing.get("errors") or []}}
    expected_equipment_ids = sorted(_ids for _ids in {
        row.get("equipment_id") or row.get("id") for row in equipment_context.get("selected_equipment") or []
    } if _ids)
    exact_equipment = exact_equipment_output_evidence(dst, expected_equipment_ids)
    final_equipment = evaluate_equipment_selection_placement(equipment_context, exact_output=exact_equipment)
    if not pre_submission and final_equipment.get("status") != "PASS":
        _restore_target(dst, backup)
        return {"status": "FAIL", "stage": "equipment_selection_placement_exact_output_gate",
                "equipment_selection_placement_qa": final_equipment,
                "input_required": {"status": "FAIL", "missing_inputs": final_equipment.get("errors") or final_equipment.get("missing_inputs") or []}}
    final_release_context["equipment_selection_placement_qa"] = final_equipment
    exact_release = _exact_release_evidence(dst, final_release_context, materialization)
    final_release = evaluate_final_engineering_release(final_release_context, exact_output=exact_release)
    if not pre_submission and final_release.get("status") != "PASS":
        _restore_target(dst, backup)
        if backup:
            backup.unlink(missing_ok=True)
        return {"status": "FAIL", "stage": "final_engineering_release_exact_output_gate",
                "final_engineering_release_qa": final_release,
                "input_required": {"status": "INPUT_REQUIRED" if final_release.get("status") == "INPUT_REQUIRED" else "FAIL",
                                   "missing_inputs": final_release.get("errors") or final_release.get("missing_inputs") or []}}
    if backup:
        backup.unlink(missing_ok=True)

    rendered["network_authority_qa"] = network_authority
    rendered["materialization_qa"] = materialization
    rendered["authority_pipeline_qa"] = result
    rendered["traceability_preflight"] = traceability
    rendered["calculation_reasonableness_qa"] = reasonableness
    rendered["topology_routing_qa"] = final_topology_routing
    rendered["equipment_selection_placement_qa"] = final_equipment
    rendered["final_engineering_release_qa"] = final_release
    rendered["architecture_space_equipment_qa"] = recognition_qa
    rendered["runtime_contract"] = runtime_contract()
    rendered["pipeline_authority"] = "mechanical"
    rendered["engineering_authority"] = "PMM_V3"
    rendered["cad_materializer"] = "canonical-cad-shell+graph-native-network"
    rendered["cad_shell_role"] = "CAD_SHELL_ONLY"
    rendered["submission_state"] = "PRE_SUBMISSION" if pre_submission else "SUBMISSION_READY"
    rendered["submission_ready"] = not pre_submission
    rendered["coordination_claim"] = "NOT_COORDINATED" if pre_submission else "COORDINATED"
    rendered["manufacturer_claim"] = "NOT_MANUFACTURER_CONFIRMED" if pre_submission else "MANUFACTURER_CONFIRMED"
    rendered["missing_inputs"] = _pipeline_blockers(result) if pre_submission else []
    return rendered
