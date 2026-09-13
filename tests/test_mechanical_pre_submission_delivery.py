from pathlib import Path
from unittest.mock import patch

from cad_engine import mechanical_authority as authority


def _network_pass():
    return {"status": "PASS", "network_graph": {"nodes": [{"id": "N1"}], "edges": [{"id": "E1"}]}}


def _traceability_pass():
    return {"status": "PASS", "zero_mismatch": True}


def _routing_pass():
    return {"contract_version": "topology-routing/1", "status": "PASS", "score": 100,
            "release_allowed": True, "controls": [{"status": "PASS"}] * 18}


def _unified_pass(*_args, **_kwargs):
    return {
        "schema": "unified-engineering-model/1",
        "status": "PASS",
        "identity": {"model_id": "UEM-TEST"},
        "totals": {"branches": 1, "plan_branches": 1},
        "branch_counts": {"DOMESTIC_WATER": 1},
        "level_branch_counts": {"GROUND": {"DOMESTIC_WATER": 1}},
        "calculation_records": [{"network_edge_id": "E1", "branch_on_plan": True}],
        "errors": [],
    }


@patch.object(authority, "evaluate_topology_routing", return_value=_routing_pass())
@patch.object(authority, "materialize_authoritative_network", return_value={"status": "PASS"})
@patch.object(authority, "build_unified_engineering_model", side_effect=_unified_pass)
@patch.object(authority, "_design_shell", return_value={"status": "PASS", "composition": {}})
@patch.object(authority, "run_pipeline")
@patch.object(authority, "_traceability_preflight", return_value=_traceability_pass())
@patch.object(authority, "_prepare_network_authority", return_value=_network_pass())
@patch.object(authority, "_runtime_contract_errors", return_value=[])
def test_external_input_blocker_delivers_truthful_pre_submission(
    _contract, _network, _traceability, pipeline, renderer, _unified, materializer, routing_gate, tmp_path
):
    pipeline.return_value = {
        "status": "INPUT_REQUIRED", "blocked_at": "target_design_packages",
        "phases": {"target_design_packages": {"status": "INPUT_REQUIRED", "errors": ["TARGET_DESIGN_PACKAGES_MISSING"]}},
        "submission": {"status": "FAIL", "release_allowed": False},
    }
    result = authority.design_mechanical_authority_site(Path("in.dxf"), tmp_path / "out.dxf", answers={}, plan_analysis={})
    renderer.assert_called_once()
    materializer.assert_called_once()
    routing_gate.assert_called_once()
    assert result["status"] == "PASS"
    assert result["submission_state"] == "PRE_SUBMISSION"
    assert result["submission_ready"] is False
    assert result["coordination_claim"] == "NOT_COORDINATED"
    assert result["manufacturer_claim"] == "NOT_MANUFACTURER_CONFIRMED"
    assert result["missing_inputs"] == ["TARGET_DESIGN_PACKAGES_MISSING"]


@patch.object(authority, "_design_shell")
@patch.object(authority, "run_pipeline", return_value={
    "status": "FAIL", "blocked_at": "documentation",
    "phases": {"documentation": {"status": "FAIL", "errors": ["OUTPUT_IDENTITY_MISMATCH:E1"]}},
    "submission": {"status": "FAIL", "release_allowed": False},
})
@patch.object(authority, "_traceability_preflight", return_value=_traceability_pass())
@patch.object(authority, "_prepare_network_authority", return_value=_network_pass())
@patch.object(authority, "build_unified_engineering_model", side_effect=_unified_pass)
@patch.object(authority, "_runtime_contract_errors", return_value=[])
def test_real_pipeline_failure_still_blocks_artifact(_contract, _unified, _network, _traceability, _pipeline, renderer, tmp_path):
    result = authority.design_mechanical_authority_site(Path("in.dxf"), tmp_path / "out.dxf", answers={}, plan_analysis={})
    renderer.assert_not_called()
    assert result["status"] == "FAIL"
    assert result["stage"] == "authority_release_gate"
