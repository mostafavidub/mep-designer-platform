from __future__ import annotations

DETAIL_RULES = {
    "split_ac": ["D-AC-01", "D-AC-02", "D-AC-03", "D-AC-04"],
    "heating_radiator": ["D-HT-01", "D-HT-02"],
    "package_boiler": ["D-HT-03", "D-HT-04"],
    "sanitary": ["D-PL-01", "D-PL-02", "D-PL-03"],
    "vent": ["D-PL-04"],
    "water": ["D-PL-05", "D-GN-01"],
    "gas": ["D-GS-01", "D-GS-02"],
    "exhaust": ["D-HV-01"],
}

DETAIL_SHEETS = {
    "D-PL-01": "M-01", "D-PL-02": "M-01", "D-PL-03": "M-01", "D-PL-04": "M-01", "D-PL-05": "M-01",
    "D-GN-01": "M-02", "D-GS-01": "M-02", "D-GS-02": "M-02",
    "D-AC-01": "M-03", "D-AC-02": "M-03", "D-AC-03": "M-03", "D-AC-04": "M-03",
    "D-HT-01": "M-03", "D-HT-02": "M-03", "D-HT-03": "M-03", "D-HT-04": "M-03", "D-HV-01": "M-03",
}


def resolve_detail_requirements(active_systems: dict[str, bool]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for system, active in active_systems.items():
        if not active:
            continue
        for detail_id in DETAIL_RULES.get(system, []):
            if detail_id not in seen:
                seen.add(detail_id)
                out.append(detail_id)
    return out


def validate_detail_coverage(required: list[str], inserted: list[str], referenced: list[str]) -> dict:
    required_set = set(required)
    inserted_set = set(inserted)
    referenced_set = set(referenced)
    errors: list[str] = []
    if required_set != inserted_set:
        errors.append("required_inserted_mismatch")
    if required_set != referenced_set:
        errors.append("required_referenced_mismatch")
    if len(inserted) != len(inserted_set):
        errors.append("duplicate_detail_ids")
    if not referenced_set.issubset(inserted_set):
        errors.append("orphan_references")
    if not inserted_set.issubset(referenced_set):
        errors.append("orphan_details")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def build_project_legend(used_symbols: dict[str, bool], meanings: dict[str, str]) -> list[dict]:
    return [
        {"symbol": symbol, "meaning": meanings[symbol]}
        for symbol, used in used_symbols.items()
        if used and symbol in meanings
    ]
