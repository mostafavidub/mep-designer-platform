"""Authority v14 equipment representation contract.

This module makes equipment graphics a first-class engineering requirement rather
than allowing a sheet to pass with only an architectural underlay or generic
placeholder rectangle.
"""
from __future__ import annotations

INDOOR_BLOCK = "ENGI_AC_INDOOR"
OUTDOOR_BLOCK = "ENGI_AC_OUTDOOR"
AIRFLOW_BLOCK = "ENGI_AC_AIRFLOW"

REQUIRED_SPLIT_FIELDS = {
    "tag", "odu_tag", "level", "sheet", "equipment_type", "mode",
    "capacity_status", "refrigerant_size_source",
    "condensate_nominal_diameter_mm", "condensate_min_slope_percent",
}


def validate_split_representation(units: list[dict]) -> dict:
    """Validate per-unit plan representation and plan/schedule traceability.

    Expected booleans are populated by the DXF composer/re-open inspection:
    block, airflow, callout, refrigerant, condensate, odu_destination_note,
    schedule_match. Final engineering values must retain provenance when source
    data is incomplete.
    """
    errors: list[str] = []
    tags = [u.get("tag") for u in units]
    odu_tags = [u.get("odu_tag") for u in units]
    if not units:
        errors.append("no_split_units")
    if len(set(tags)) != len(tags) or None in tags:
        errors.append("duplicate_or_missing_ac_tag")
    if len(set(odu_tags)) != len(odu_tags) or None in odu_tags:
        errors.append("duplicate_or_missing_odu_tag")

    required_graphics = (
        "block", "airflow", "callout", "refrigerant", "condensate",
        "odu_destination_note", "schedule_match",
    )
    for u in units:
        tag = u.get("tag") or "UNKNOWN"
        missing_fields = sorted(REQUIRED_SPLIT_FIELDS - set(u))
        if missing_fields:
            errors.append(f"{tag}:missing_fields:{','.join(missing_fields)}")
        for key in required_graphics:
            if not u.get(key):
                errors.append(f"{tag}:missing_{key}")
        if u.get("condensate_nominal_diameter_mm", 0) < 25:
            errors.append(f"{tag}:condensate_dn_below_contract")
        if u.get("condensate_min_slope_percent", 0) < 1:
            errors.append(f"{tag}:condensate_slope_below_contract")
        if u.get("capacity_status") == "FINAL" and not u.get("capacity_source"):
            errors.append(f"{tag}:final_capacity_without_provenance")
        if not u.get("refrigerant_size_source"):
            errors.append(f"{tag}:refrigerant_size_without_provenance")

    return {
        "version": "equipment-representation-contract-v14.2",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {"units": len(units), "unique_ac_tags": len(set(tags)), "unique_odu_tags": len(set(odu_tags))},
    }
