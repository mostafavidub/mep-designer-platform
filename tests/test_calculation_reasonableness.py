from cad_engine.calculation_reasonableness import evaluate_calculation_reasonableness


def valid_payload():
    return {
        "network_design_basis": {"drawing_unit_to_m": 0.001},
        "network_graph": {"edges": [
            {"id": "E-MAIN", "plan_path": [[0, 0], [10000, 0]]},
            {"id": "E-BRANCH", "parent_edge_id": "E-MAIN", "plan_path": [[0, 0], [3000, 0]]},
        ]},
        "calculation_rows": [
            {"calc_id": "C-MAIN", "network_edge_id": "E-MAIN", "system": "cold_water", "source": "PROJECT_INPUT", "downstream_load": 4, "load_unit": "FU", "size_mm": 25, "flow_lps": .5, "equivalent_length_m": 12},
            {"calc_id": "C-BRANCH", "network_edge_id": "E-BRANCH", "system": "cold_water", "source": "PROJECT_INPUT", "downstream_load": 1, "load_unit": "FU", "size_mm": 16, "flow_lps": .2, "equivalent_length_m": 4},
        ],
        "sensitivity_checks": [{"id": "AREA+10", "input_delta_ratio": .1, "output_delta_ratio": .11, "max_response_ratio": 2}],
        "engineer_review": {"reviewer_id": "ME-001", "review_evidence_sha256": "d"*64, "redlines": [], "reviewed_calculation_ids": ["C-MAIN", "C-BRANCH"]},
    }


def test_complete_evidence_passes():
    out = evaluate_calculation_reasonableness(valid_payload())
    assert out["status"] == "PASS"
    assert out["release_allowed"] is True
    assert all(out["checks"].values())


def test_unit_scale_corruption_fails_closed():
    data = valid_payload(); data["calculation_rows"][0]["equivalent_length_m"] = 9109
    out = evaluate_calculation_reasonableness(data)
    assert out["status"] == "FAIL"
    assert any("EQUIVALENT_LENGTH_SCALE_ANOMALY" in x for x in out["errors"])


def test_negative_nonfinite_and_duplicate_ids_fail():
    data = valid_payload(); data["calculation_rows"][0]["flow_lps"] = -1
    data["calculation_rows"][1]["calc_id"] = "C-MAIN"
    out = evaluate_calculation_reasonableness(data)
    assert out["status"] == "FAIL"
    assert any("OUT_OF_RANGE:flow_lps" in x for x in out["errors"])
    assert "DUPLICATE_CALC_ID:C-MAIN" in out["errors"]


def test_network_conservation_and_identity_fail():
    data = valid_payload(); data["calculation_rows"][1]["downstream_load"] = 7
    data["calculation_rows"].pop(0)
    out = evaluate_calculation_reasonableness(data)
    assert out["status"] == "FAIL"
    assert any("CALCULATION_ROWS_MISSING_EDGES" in x for x in out["errors"])


def test_missing_units_sensitivity_provenance_and_review_require_input():
    data = valid_payload(); data["network_design_basis"] = {}; data["sensitivity_checks"] = None
    data["engineer_review"] = {}; data["calculation_rows"][0].pop("source")
    out = evaluate_calculation_reasonableness(data)
    assert out["status"] == "INPUT_REQUIRED"
    assert {"DRAWING_UNIT_TO_M", "SENSITIVITY_CHECKS", "INDEPENDENT_ENGINEER_REVIEW"}.issubset(out["missing_inputs"])


def test_sensitivity_jump_and_undersized_equipment_fail():
    data = valid_payload()
    data["sensitivity_checks"][0]["output_delta_ratio"] = 1
    data["equipment_requirements"] = {"equipment": [{"id": "P1", "required_capacity_w": 1000}]}
    data["selected_equipment"] = [{"id": "P1", "capacity_w": 500}]
    out = evaluate_calculation_reasonableness(data)
    assert out["status"] == "FAIL"
    assert "SENSITIVITY_JUMP:AREA+10" in out["errors"]
    assert "UNDERSIZED_EQUIPMENT:P1" in out["errors"]


def test_zero_pump_head_and_zero_branches_are_blocked():
    data = valid_payload()
    data["network_graph"]["edges"][0]["endpoint_ids"] = ["F1"]
    data["calculation_totals"] = {"booster_required": True, "pump_head_m": 0, "branches": 0}
    out = evaluate_calculation_reasonableness(data)
    assert out["status"] == "FAIL"
    assert "PUMP_HEAD_ZERO_OR_MISSING_WHEN_BOOSTER_REQUIRED" in out["errors"]
    assert "BRANCHES_ZERO_WITH_CONNECTED_ENDPOINTS" in out["errors"]
