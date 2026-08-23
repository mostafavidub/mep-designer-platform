"""Mechanical Drawing Set Planning Engine.

Determines required mechanical drawing sheets before CAD generation.
"""

SYSTEM_RULES = {
    "cooling": "conditioned_levels",
    "heating": "heated_levels",
    "water_supply": "wet_fixture_levels",
    "sanitary": "sanitary_fixture_levels",
    "ventilation": "ventilation_required_levels",
    "gas": "gas_consumer_levels",
    "roof_drainage": "roof_exists",
    "riser": "vertical_systems"
}


def _unique_levels(levels):
    return list(dict.fromkeys(levels or []))


def predict_drawing_set(scope):
    """Create an approval proposal before mechanical generation.

    Input is a normalized architectural/mechanical scope dictionary.
    """
    plans = {}

    mappings = {
        "cooling": scope.get("conditioned_levels", []),
        "heating": scope.get("heated_levels", []),
        "water_supply": scope.get("wet_fixture_levels", []),
        "sanitary": scope.get("sanitary_fixture_levels", []),
        "ventilation": scope.get("ventilation_required_levels", []),
        "gas": scope.get("gas_consumer_levels", []),
    }

    for system, levels in mappings.items():
        levels = _unique_levels(levels)
        plans[system] = {
            "count": len(levels),
            "levels": levels
        }

    plans["roof_drainage"] = {
        "count": 1 if scope.get("roof_exists") else 0,
        "levels": ["Roof"] if scope.get("roof_exists") else []
    }

    plans["riser"] = {
        "count": 1 if scope.get("vertical_systems") else 0,
        "levels": ["Riser Diagram"] if scope.get("vertical_systems") else []
    }

    total = sum(x["count"] for x in plans.values())

    return {
        "approved": False,
        "systems": plans,
        "total_plans": total,
        "approval_required": True
    }


def requires_approval(proposal):
    """Return True until a drawing-set proposal has explicit user approval."""
    return not bool((proposal or {}).get("approved"))
