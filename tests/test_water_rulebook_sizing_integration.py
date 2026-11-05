from cad_engine.mechanical_execution_sizing import (
    design_water_network_from_rulebook, evaluate_remote_water_pressure_from_rulebook,
)


def _basis(**updates):
    result = {
        "system_mode": "FLUSH_VALVE",
        "candidate_diameters_mm": [10, 16, 20, 25, 32],
        "max_velocity_m_s": 2.0,
        "max_pressure_drop_pa_m": 5000,
        "hazen_williams_c": 150,
    }
    result.update(updates)
    return result


def test_rulebook_exact_sfu_row_drives_real_hydraulic_segment_and_minimum_dn():
    result = design_water_network_from_rulebook(
        [{"id": "CW-1", "system": "cold_water", "downstream_fixture_ids": ["U-1"],
          "length_m": 8, "fittings_equivalent_length_m": 2}],
        [{"id": "U-1", "fixture_sfu_type": "public_urinal_flush_valve",
          "fixture_type": "toilet_flush_valve", "count": 1}],
        _basis(),
    )
    assert result["status"] == "PASS", result
    row = result["segments"][0]
    assert row["downstream_fixture_units"] == 5
    assert row["probable_flow_lps"] == 0.95
    assert row["selected_dn_mm"] >= 25
    assert result["probable_demand_method"] == "M16_APPENDIX_1_EXACT_VERIFIED_ROWS_NO_INTERPOLATION"
    assert result["probable_demand_rule_id"] == "IR-M16-1396-APP1-SFU-PROBABLE-DEMAND"
    assert result["minimum_dn_rule_id"] == "IR-M16-1396-16.3.3.4-FIXTURE-MIN-DN"


def test_non_tabulated_sfu_total_is_input_required_not_interpolated():
    result = design_water_network_from_rulebook(
        [{"id": "CW-1", "system": "cold_water", "downstream_fixture_ids": ["B-1"],
          "length_m": 4, "fittings_equivalent_length_m": 0}],
        [{"id": "B-1", "fixture_sfu_type": "private_basin",
          "fixture_type": "basin", "count": 1}],
        _basis(system_mode="FLUSH_TANK"),
    )
    assert result["status"] == "INPUT_REQUIRED"
    assert result["segments"] == []
    assert result["missing_inputs"] == ["CW-1:probable_flow_curve_range"]


def test_unknown_fixture_or_missing_hydraulic_criterion_fails_closed():
    segment = [{"id": "CW-1", "system": "cold_water", "downstream_fixture_ids": ["X"],
                "length_m": 4, "fittings_equivalent_length_m": 0}]
    unknown = design_water_network_from_rulebook(
        segment, [{"id": "X", "fixture_sfu_type": "invented", "count": 1}], _basis())
    assert unknown["status"] == "INPUT_REQUIRED"
    assert unknown["missing_inputs"] == ["fixtures[0].supported_fixture_sfu_type"]

    incomplete = _basis()
    incomplete.pop("hazen_williams_c")
    missing = design_water_network_from_rulebook(
        segment, [{"id": "X", "fixture_sfu_type": "private_basin", "count": 1}], incomplete)
    assert missing["status"] == "INPUT_REQUIRED"
    assert missing["missing_inputs"] == ["hazen_williams_c"]


def test_galvanized_fitting_inventory_drives_effective_length_and_head_loss():
    result = design_water_network_from_rulebook(
        [{"id": "CW-GALV", "system": "cold_water", "downstream_fixture_ids": ["U-1"],
          "length_m": 8, "fittings_equivalent_length_m": 5.23,
          "pipe_material": "GALVANIZED_STEEL",
          "fittings": [{"type": "elbow_90", "quantity": 2},
                       {"type": "check_valve", "quantity": 1}]}],
        [{"id": "U-1", "fixture_sfu_type": "public_urinal_flush_valve",
          "fixture_type": "toilet_flush_valve", "count": 1}],
        _basis(candidate_diameters_mm=[25]),
    )
    assert result["status"] == "PASS", result
    row = result["segments"][0]
    assert row["selected_dn_mm"] == 25
    assert row["fittings_equivalent_length_m"] == 5.23
    assert row["total_effective_length_m"] == 13.23
    assert row["friction_head_m"] > 0
    assert row["fitting_equivalent_length_source"] == "IR-M16-1396-APP1-GALVANIZED-EQUIVALENT-LENGTH"


def test_galvanized_declared_length_mismatch_and_unsupported_fitting_fail_closed():
    base = {"id": "CW-GALV", "system": "cold_water", "downstream_fixture_ids": ["U-1"],
            "length_m": 8, "fittings_equivalent_length_m": 1,
            "pipe_material": "GALVANIZED_STEEL",
            "fittings": [{"type": "elbow_90", "quantity": 1}]}
    fixtures = [{"id": "U-1", "fixture_sfu_type": "public_urinal_flush_valve",
                 "fixture_type": "toilet_flush_valve", "count": 1}]
    mismatch = design_water_network_from_rulebook([base], fixtures, _basis(candidate_diameters_mm=[25]))
    assert mismatch["status"] == "FAIL"
    assert mismatch["errors"] == ["CW-GALV:declared_fitting_equivalent_length_m_mismatch"]

    unsupported = dict(base, fittings_equivalent_length_m=0,
                       fittings=[{"type": "invented_fitting", "quantity": 1}])
    result = design_water_network_from_rulebook([unsupported], fixtures, _basis(candidate_diameters_mm=[25]))
    assert result["status"] == "INPUT_REQUIRED"
    assert result["missing_inputs"] == ["CW-GALV:fittings[0].supported_type"]


def test_remote_fixture_pressure_uses_exact_sized_path_and_m16_fixture_limit():
    sized = [{"segment_id": "CW-MAIN", "friction_head_m": 1.2},
             {"segment_id": "CW-BRANCH", "friction_head_m": 0.4}]
    result = evaluate_remote_water_pressure_from_rulebook(
        sized,
        [{"outlet_id": "WC-REMOTE", "fixture_type": "toilet_flush_valve",
          "elevation_m": 8, "segment_ids": ["CW-MAIN", "CW-BRANCH"]}],
        {"source_static_pressure_bar": 3.0, "source_flowing_pressure_bar": 3.0,
         "source_elevation_m": 0, "meter_loss_m": 0.5, "valve_loss_m": 0.2},
    )
    assert result["status"] == "PASS", result
    row = result["outlets"][0]
    assert row["friction_head_m"] == 1.6
    assert row["minimum_flowing_pressure_mwc"] == 17
    assert row["calculated_flowing_pressure_mwc"] > 17
    assert row["rule_id"] == "IR-M16-1396-16.3.3.5-FIXTURE-PRESSURE"


def test_remote_pressure_static_and_flowing_failures_are_independent():
    sized = [{"segment_id": "CW-1", "friction_head_m": 0.5}]
    outlets = [{"outlet_id": "BASIN-1", "fixture_type": "basin",
                "elevation_m": 0, "segment_ids": ["CW-1"]}]
    high_static = evaluate_remote_water_pressure_from_rulebook(
        sized, outlets, {"source_static_pressure_bar": 4.1, "source_flowing_pressure_bar": 1,
                         "source_elevation_m": 0, "meter_loss_m": 0, "valve_loss_m": 0})
    assert high_static["status"] == "FAIL"
    assert "BASIN-1:STATIC_PRESSURE_ABOVE_MAXIMUM" in high_static["errors"]

    low_flow = evaluate_remote_water_pressure_from_rulebook(
        sized, outlets, {"source_static_pressure_bar": 4, "source_flowing_pressure_bar": 0.5,
                         "source_elevation_m": 0, "meter_loss_m": 0, "valve_loss_m": 0})
    assert low_flow["status"] == "FAIL"
    assert low_flow["errors"] == ["BASIN-1:FLOWING_PRESSURE_BELOW_MINIMUM"]


def test_remote_pressure_missing_project_or_path_evidence_is_input_required():
    missing_basis = evaluate_remote_water_pressure_from_rulebook([], [], {})
    assert missing_basis["status"] == "INPUT_REQUIRED"
    assert "source_flowing_pressure_bar" in missing_basis["missing_inputs"]

    unknown_path = evaluate_remote_water_pressure_from_rulebook(
        [], [{"outlet_id": "SH-1", "fixture_type": "shower", "elevation_m": 3,
              "segment_ids": ["MISSING"]}],
        {"source_static_pressure_bar": 3, "source_flowing_pressure_bar": 2,
         "source_elevation_m": 0, "meter_loss_m": 0, "valve_loss_m": 0})
    assert unknown_path["status"] == "INPUT_REQUIRED"
    assert unknown_path["missing_inputs"] == ["SH-1:unknown_segments:MISSING"]
