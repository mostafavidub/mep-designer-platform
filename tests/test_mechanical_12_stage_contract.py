"""Regression contract for the 12-stage mechanical drawing-set upgrade."""

from app.mechanical_drawing_set import predict_drawing_set


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
