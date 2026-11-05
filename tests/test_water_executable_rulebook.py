import json

from jsonschema import Draft202012Validator

from app.mechanical_rulebook import automatic_answers
from cad_engine.executable_rulebook import RULEBOOK_ROOT, WATER_ROOT, load_rulebook_module, validate_rulebook_module
from cad_engine.water_rulebook import evaluate_water_rulebook, water_design_profile


def _snapshot():
    return {
        "duty_stage": "DESIGN_AND_LATER",
        "water": {
            "interconnections": [{"backflow_prevention": True, "device_id": "BFP-1",
                                    "product_evidence_id": "PD-BFP-1"}],
            "manifolds": [{"independent_fixture_branches": True, "velocity_m_s": 2.0,
                            "hydraulic_calculation_id": "CALC-MAN-1"}],
            "fixture_branches": [
                {"fixture_type": "basin", "dn_mm": 10},
                {"fixture_type": "toilet_flush_valve", "dn_mm": 25},
            ],
            "fixture_outlets": [
                {"fixture_type": "shower", "flow_fixture_type": "shower",
                 "static_pressure_bar": 4, "flowing_pressure_mwc": 5.5,
                 "rated_consumption": 8, "rated_consumption_unit": "L/min",
                 "flow_control_product_id": "FLOW-SH-1"}
            ],
            "quick_closing_valves": [{"point": [1, 2], "arrestor_product_id": "WH-1",
                                       "arrestor_standard": "ASSE 1010", "accessible": True}],
            "sizing_segments": [{"segment_id": "CW-1", "supply_scope": "total",
                                  "system_mode": "FLUSH_VALVE",
                                  "fixtures": [{"fixture_sfu_type": "public_urinal_flush_valve", "count": 1}],
                                  "declared_total_sfu": 5, "probable_flow_l_s": 0.95,
                                  "pipe_material": "GALVANIZED_STEEL", "dn_mm": 20,
                                  "fittings": [{"type": "elbow_90", "quantity": 2},
                                               {"type": "check_valve", "quantity": 1}],
                                  "declared_fitting_equivalent_length_m": 4.08}],
            "components": [
                {"system": "COLD_WATER", "rated_pressure_bar": 10, "rated_temperature_c": 25,
                 "maximum_operating_pressure_bar": 4, "manufacturer_evidence_id": "PD-CW-1"},
                {"system": "HOT_WATER", "rated_pressure_bar": 12, "rated_temperature_c": 80,
                 "maximum_operating_pressure_bar": 12, "manufacturer_evidence_id": "PD-HW-1"},
            ],
            "special_building_temperature_basis": False,
            "hot_outlets": [
                {"fixture_type": "bath", "design_temperature_c": 49},
                {"fixture_type": "shower", "design_temperature_c": 43},
                {"fixture_type": "basin", "design_temperature_c": 43},
                {"fixture_type": "kitchen_sink", "design_temperature_c": 60},
            ],
            "hot_water": {"heater_to_farthest_outlet_length_m": 10.01,
                          "temperature_maintenance_method": "RETURN_LOOP",
                          "temperature_maintenance_evidence_id": "ROUTE-HWR-1"},
            "construction_pressure_test_note": "Test to M16 16-3-9-2 before concealment.",
        },
    }


def _by_id(result, suffix):
    return next(row for row in result["results"] if row["rule_id"].endswith(suffix))


def test_water_module_integrity_and_strict_schema():
    module = load_rulebook_module(WATER_ROOT)
    assert validate_rulebook_module(module)["status"] == "PASS"
    schema = json.loads((RULEBOOK_ROOT / "schema" / "executable_rule.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    errors = [error for rule in module["registry"]["rules"]
              for error in Draft202012Validator(schema).iter_errors(rule)]
    assert errors == []
    assert len(module["registry"]["rules"]) == 12


def test_water_rules_positive_and_real_design_profile_consumer():
    result = evaluate_water_rulebook(_snapshot())
    assert result["status"] == "PASS"
    assert {row["status"] for row in result["results"]} <= {"PASS", "NOT_APPLICABLE"}
    profile = water_design_profile()
    answers = automatic_answers({})
    assert profile["authority"] == "PLANHA_INTERNAL"
    assert f"Hazen-Williams C={profile['hazen_williams_c']}" in answers["water_design_basis"]
    assert f"maximum loss {profile['maximum_friction_loss_kpa_per_100m']} kPa/100 m" in answers["water_design_basis"]
    assert profile["minimum_fixture_branch_dn_mm"]["toilet_flush_valve"] == 25
    basis = __import__("app.mechanical_rulebook", fromlist=["network_design_basis"]).network_design_basis()
    assert basis["systems"]["cold_water"]["minimum_fixture_branch_dn_mm"]["basin"] == 10
    provenance = basis["systems"]["cold_water"]["minimum_fixture_branch_dn_provenance"]
    assert provenance["authority"] == "STATUTORY_MANDATORY"
    assert provenance["rule_id"] == "IR-M16-1396-16.3.3.4-FIXTURE-MIN-DN"
    assert provenance["source_ids"] == ["M16-WATER-007"]
    method = basis["systems"]["cold_water"]["probable_demand_method"]
    assert method["method"] == "M16_APPENDIX_1_EXACT_VERIFIED_ROWS_NO_INTERPOLATION"
    assert method["probable_flow_l_s"]["FLUSH_VALVE"]["5"] == 0.95
    equivalent = basis["systems"]["cold_water"]["galvanized_fitting_equivalent_length_method"]
    assert equivalent["equivalent_length_m"]["20"]["check_valve"] == 2.56


def test_sfu_probable_demand_exact_rows_and_fail_closed_boundaries():
    snapshot = _snapshot()
    row = _by_id(evaluate_water_rulebook(snapshot), "SFU-PROBABLE-DEMAND")
    assert row["status"] == "PASS"
    assert "SFU=5" in row["evidence"][0]

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0]["declared_total_sfu"] = 4.99
    row = _by_id(evaluate_water_rulebook(snapshot), "SFU-PROBABLE-DEMAND")
    assert row["status"] == "FAIL"
    assert row["errors"] == ["SEGMENT_SFU_TOTAL_MISMATCH:0"]

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0]["probable_flow_l_s"] = 0.94
    assert _by_id(evaluate_water_rulebook(snapshot), "SFU-PROBABLE-DEMAND")["status"] == "FAIL"

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0].update({
        "system_mode": "FLUSH_TANK",
        "fixtures": [{"fixture_sfu_type": "private_basin", "count": 1}],
        "declared_total_sfu": 0.7,
        "probable_flow_l_s": 0.1,
    })
    row = _by_id(evaluate_water_rulebook(snapshot), "SFU-PROBABLE-DEMAND")
    assert row["status"] == "INPUT_REQUIRED"
    assert any("verified_probable_demand_row[0.7]" in value for value in row["missing_inputs"])

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0].update({
        "fixtures": [{"fixture_sfu_type": "public_toilet_flush_valve", "count": 500}],
        "declared_total_sfu": 5000,
        "probable_flow_l_s": 37.35,
    })
    assert _by_id(evaluate_water_rulebook(snapshot), "SFU-PROBABLE-DEMAND")["status"] == "PASS"


def test_galvanized_equivalent_length_exact_table_and_material_scope():
    snapshot = _snapshot()
    row = _by_id(evaluate_water_rulebook(snapshot), "GALVANIZED-EQUIVALENT-LENGTH")
    assert row["status"] == "PASS"
    assert "4.08m" in row["evidence"][0]

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0]["declared_fitting_equivalent_length_m"] = 4.079
    assert _by_id(evaluate_water_rulebook(snapshot), "GALVANIZED-EQUIVALENT-LENGTH")["status"] == "FAIL"

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0]["dn_mm"] = 22
    assert _by_id(evaluate_water_rulebook(snapshot), "GALVANIZED-EQUIVALENT-LENGTH")["status"] == "INPUT_REQUIRED"

    snapshot = _snapshot()
    snapshot["water"]["sizing_segments"][0]["pipe_material"] = "COPPER"
    assert _by_id(evaluate_water_rulebook(snapshot), "GALVANIZED-EQUIVALENT-LENGTH")["status"] == "NOT_APPLICABLE"


def test_manifold_velocity_boundary_and_failure():
    snapshot = _snapshot()
    assert _by_id(evaluate_water_rulebook(snapshot), "MANIFOLD-VELOCITY")["status"] == "PASS"
    snapshot["water"]["manifolds"][0]["velocity_m_s"] = 2.001
    row = _by_id(evaluate_water_rulebook(snapshot), "MANIFOLD-VELOCITY")
    assert row["status"] == "FAIL"
    assert row["errors"] == ["MANIFOLD_VELOCITY_ABOVE_2_M_S:0"]


def test_missing_or_invalid_evidence_never_passes():
    snapshot = _snapshot()
    snapshot["water"]["components"][0].pop("manufacturer_evidence_id")
    assert _by_id(evaluate_water_rulebook(snapshot), "COMPONENT-RATING")["status"] == "INPUT_REQUIRED"
    snapshot = _snapshot()
    snapshot["water"]["hot_outlets"][0]["design_temperature_c"] = 49.1
    assert _by_id(evaluate_water_rulebook(snapshot), "OUTLET-TEMPERATURE")["status"] == "FAIL"
    snapshot = _snapshot()
    snapshot["water"]["hot_water"]["heater_to_farthest_outlet_length_m"] = 11
    snapshot["water"]["hot_water"].pop("temperature_maintenance_method")
    assert _by_id(evaluate_water_rulebook(snapshot), "HOT-WATER-RETURN")["status"] == "INPUT_REQUIRED"


def test_fixture_size_pressure_and_flow_boundaries():
    snapshot = _snapshot()
    result = evaluate_water_rulebook(snapshot)
    assert _by_id(result, "FIXTURE-MIN-DN")["status"] == "PASS"
    assert _by_id(result, "FIXTURE-PRESSURE")["status"] == "PASS"
    assert _by_id(result, "FIXTURE-FLOW")["status"] == "PASS"
    snapshot["water"]["fixture_branches"][0]["dn_mm"] = 9.99
    assert _by_id(evaluate_water_rulebook(snapshot), "FIXTURE-MIN-DN")["status"] == "FAIL"
    snapshot = _snapshot(); snapshot["water"]["fixture_outlets"][0]["static_pressure_bar"] = 4.001
    assert _by_id(evaluate_water_rulebook(snapshot), "FIXTURE-PRESSURE")["status"] == "FAIL"
    snapshot = _snapshot(); snapshot["water"]["fixture_outlets"][0]["flowing_pressure_mwc"] = 5.49
    assert _by_id(evaluate_water_rulebook(snapshot), "FIXTURE-PRESSURE")["status"] == "FAIL"
    snapshot = _snapshot(); snapshot["water"]["fixture_outlets"][0]["rated_consumption"] = 8.01
    assert _by_id(evaluate_water_rulebook(snapshot), "FIXTURE-FLOW")["status"] == "FAIL"
    snapshot = _snapshot(); snapshot["water"]["fixture_outlets"][0]["rated_consumption_unit"] = "L/flush"
    assert _by_id(evaluate_water_rulebook(snapshot), "FIXTURE-FLOW")["status"] == "INPUT_REQUIRED"


def test_water_hammer_requires_real_location_product_and_equivalent_approval():
    snapshot = _snapshot()
    assert _by_id(evaluate_water_rulebook(snapshot), "WATER-HAMMER")["status"] == "PASS"
    snapshot["water"]["quick_closing_valves"][0]["accessible"] = False
    assert _by_id(evaluate_water_rulebook(snapshot), "WATER-HAMMER")["status"] == "FAIL"
    snapshot = _snapshot(); snapshot["water"]["quick_closing_valves"][0]["arrestor_standard"] = "OTHER"
    assert _by_id(evaluate_water_rulebook(snapshot), "WATER-HAMMER")["status"] == "INPUT_REQUIRED"


def test_return_rule_exact_ten_meters_is_not_applicable_but_over_ten_is():
    snapshot = _snapshot()
    snapshot["water"]["hot_water"] = {"heater_to_farthest_outlet_length_m": 10.0}
    assert _by_id(evaluate_water_rulebook(snapshot), "HOT-WATER-RETURN")["status"] == "NOT_APPLICABLE"
    snapshot["water"]["hot_water"] = {"heater_to_farthest_outlet_length_m": 10.0001}
    assert _by_id(evaluate_water_rulebook(snapshot), "HOT-WATER-RETURN")["status"] == "INPUT_REQUIRED"


def test_construction_test_is_stage_aware_and_not_fabricated_at_design():
    snapshot = _snapshot()
    snapshot["water"].pop("construction_pressure_test_note")
    assert _by_id(evaluate_water_rulebook(snapshot), "PRESSURE-TEST")["status"] == "INPUT_REQUIRED"
    snapshot["duty_stage"] = "CONSTRUCTION_AND_FINAL_INSPECTION"
    snapshot["water"]["construction_pressure_test"] = {
        "test_pressure_bar": 10, "maximum_operating_pressure_bar": 4,
        "duration_h": 1, "result": "PASS", "supervisor_approval_id": "SUP-1"
    }
    assert _by_id(evaluate_water_rulebook(snapshot), "PRESSURE-TEST")["status"] == "PASS"
    snapshot["water"]["construction_pressure_test"]["duration_h"] = 0.99
    assert _by_id(evaluate_water_rulebook(snapshot), "PRESSURE-TEST")["status"] == "FAIL"
    snapshot["water"]["construction_pressure_test"]["duration_h"] = 1
    snapshot["water"]["construction_pressure_test"]["maximum_operating_pressure_bar"] = 12
    assert _by_id(evaluate_water_rulebook(snapshot), "PRESSURE-TEST")["status"] == "FAIL"
