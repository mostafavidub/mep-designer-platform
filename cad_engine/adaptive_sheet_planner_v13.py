"""Adaptive mechanical sheet planning for authority-style drawing sets.

Creates real independent drawing contexts instead of relying on multiple
paperspace viewports over one shared modelspace underlay.
"""
from __future__ import annotations

CORE_FAMILIES = ("SANITARY_VENT", "WATER", "HEATING", "SPLIT_AC")
SUPPORT_FAMILIES = (
    ("GAS", "MULTI", "PLAN"),
    ("ROOF", "ROOF", "PLAN"),
    ("SANITARY_RISER", "MULTI", "RISER"),
    ("WATER_HEATING_RISER", "MULTI", "RISER"),
    ("GAS_RISER", "MULTI", "RISER"),
    ("HVAC_DETAILS", "MULTI", "DETAIL"),
    ("PLUMBING_DETAILS", "MULTI", "DETAIL"),
    ("EQUIPMENT_SCHEDULE", "MULTI", "SCHEDULE"),
)


def build_adaptive_manifest(levels, density):
    """Build a project-driven sheet list from actual per-family content density."""
    sheets = []
    def add(family, level, purpose):
        sheets.append({
            "sheet": f"M-{len(sheets)+1:02d}",
            "family": family,
            "level": level,
            "purpose": purpose,
        })

    for family in CORE_FAMILIES:
        for level in levels:
            if int(density.get((family, level), 0)) > 0:
                add(family, level, "PLAN")
    for family, level, purpose in SUPPORT_FAMILIES:
        add(family, level, purpose)
    return sheets


def validate_independent_sheet_set(manifest, layout_count, entities_outside_bounds):
    families = {row["family"] for row in manifest}
    required = set(CORE_FAMILIES) | {x[0] for x in SUPPORT_FAMILIES}
    errors = []
    if len(manifest) < 18:
        errors.append("insufficient_sheet_count_for_current_project")
    if not required.issubset(families):
        errors.append("missing_required_drawing_family")
    if layout_count != len(manifest):
        errors.append("layout_manifest_mismatch")
    if entities_outside_bounds:
        errors.append("cross_sheet_geometry")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {
            "sheet_count": len(manifest),
            "layout_count": layout_count,
            "entities_outside_sheet_bounds": entities_outside_bounds,
        },
    }
