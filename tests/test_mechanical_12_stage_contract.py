"""Regression contract for the 12-stage mechanical drawing-set upgrade."""

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set


def _reference_scope(**overrides):
    levels = ["Ground", "First Duplex", "Second Duplex"]
    scope = {
        "all_levels": levels + ["Roof"],
        "conditioned_levels": levels,
        "heated_levels": levels,
        "wet_fixture_levels": levels,
        "sanitary_fixture_levels": levels,
        "ventilation_required_levels": levels,
        "gas_consumer_levels": levels,
        "roof_exists": True,
        "roof_level_name": "Roof",
        "vertical_systems": True,
        "typical_groups": [],
    }
    scope.update(overrides)
    return scope


def test_stage_01_base_levels_are_not_the_deliverable_count():
    result = predict_drawing_set(_reference_scope())
    assert len(result["systems"]["roof_drainage"]["levels"]) == 1
    assert len(_reference_scope()["all_levels"]) == 4
    assert result["deliverable_sheet_count"] > len(_reference_scope()["all_levels"])
    assert result["count_semantics"] == "authority_separated_customer_deliverables"


def test_stage_02_system_families_are_authority_separated():
    result = predict_drawing_set(_reference_scope())
    expected = {"water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust", "roof_rainwater"}
    assert expected.issubset(result["sheet_families"])
    for key in expected - {"roof_rainwater"}:
        assert len(result["sheet_families"][key]["systems"]) == 1
    assert "plumbing_gas" not in result["sheet_families"]
    assert "heating_cooling_condensate" not in result["sheet_families"]


def test_stage_03_non_floor_deliverables_are_first_class_manifest_items():
    result = predict_drawing_set(_reference_scope())
    sheets = result["drawing_manifest"]["sheets"]
    assert any(not sheet.get("special") for sheet in sheets)
    assert any(sheet.get("special") for sheet in sheets)
    special_codes = {sheet["code"] for sheet in sheets if sheet.get("special")}
    assert "M-W-RISER" in special_codes
    assert "M-C-EQUIP" in special_codes


def test_stage_04_approval_freezes_exact_manifest_before_cad():
    proposal = predict_drawing_set(_reference_scope())
    expected_id = proposal["drawing_manifest"]["manifest_id"]
    approved = approve_drawing_set(proposal)
    frozen = approved["approved_manifest"]
    assert approved["approved"] is True
    assert frozen["manifest_id"] == expected_id
    assert frozen == approved["drawing_manifest"]
    approved["drawing_manifest"]["sheets"][0]["label"] = "MUTATED AFTER APPROVAL"
    assert frozen["sheets"][0]["label"] != "MUTATED AFTER APPROVAL"
