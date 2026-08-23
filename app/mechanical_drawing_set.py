"""Mechanical Drawing Set Planning Engine.

Customer-facing counts follow the local authority submission profile: systems
that are submitted as separate mechanical drawings stay separate. Typical-floor
consolidation is allowed only inside the same system family and only when the
architecture analysis has verified equivalence.
"""

SYSTEM_RULES = {
    "cooling": "conditioned_levels",
    "heating": "heated_levels",
    "water_supply": "wet_fixture_levels",
    "sanitary": "sanitary_fixture_levels",
    "ventilation": "ventilation_required_levels",
    "gas": "gas_consumer_levels",
    "roof_drainage": "roof_exists",
    "riser": "vertical_systems",
}

AUTHORITY_FAMILIES = {
    "water_supply": {"code": "M-W", "label": "آب سرد و گرم", "system": "water_supply"},
    "sanitary_vent": {"code": "M-S", "label": "فاضلاب و ونت", "system": "sanitary"},
    "heating": {"code": "M-H", "label": "گرمایش", "system": "heating"},
    "cooling": {"code": "M-C", "label": "سرمایش / HVAC", "system": "cooling"},
    "gas": {"code": "M-G", "label": "گاز", "system": "gas"},
    "ventilation_exhaust": {"code": "M-V", "label": "تهویه و اگزاست", "system": "ventilation"},
}


def _unique_levels(levels):
    return list(dict.fromkeys(str(x) for x in (levels or []) if str(x).strip()))


def _system_scopes(scope):
    mappings = {
        "cooling": scope.get("conditioned_levels", []),
        "heating": scope.get("heated_levels", []),
        "water_supply": scope.get("wet_fixture_levels", []),
        "sanitary": scope.get("sanitary_fixture_levels", []),
        "ventilation": scope.get("ventilation_required_levels", []),
        "gas": scope.get("gas_consumer_levels", []),
    }
    systems = {}
    for system, levels in mappings.items():
        levels = _unique_levels(levels)
        systems[system] = {"count": len(levels), "levels": levels}
    systems["roof_drainage"] = {
        "count": 1 if scope.get("roof_exists") else 0,
        "levels": [scope.get("roof_level_name") or "Roof"] if scope.get("roof_exists") else [],
    }
    systems["riser"] = {
        "count": 1 if scope.get("vertical_systems") else 0,
        "levels": ["Vertical systems"] if scope.get("vertical_systems") else [],
    }
    return systems


def _normalize_typical_groups(raw_groups):
    out = []
    if isinstance(raw_groups, dict):
        raw_groups = [{"name": name, "levels": levels} for name, levels in raw_groups.items()]
    for index, item in enumerate(raw_groups or [], 1):
        if isinstance(item, dict):
            levels = item.get("levels") or item.get("floors") or item.get("members") or []
            name = item.get("name") or item.get("label") or item.get("pattern") or f"Typical {index}"
        elif isinstance(item, (list, tuple, set)):
            levels = list(item)
            name = f"Typical {index}"
        else:
            continue
        levels = _unique_levels(levels)
        if levels:
            out.append({"name": str(name), "levels": levels})
    return out


def consolidate_effective_levels(levels, typical_groups=None):
    """Collapse only verified equivalent levels inside one system family."""
    levels = _unique_levels(levels)
    if not levels:
        return []
    groups = _normalize_typical_groups(typical_groups)
    consumed = set()
    patterns = []
    for group in groups:
        members = [x for x in levels if x in group["levels"] and x not in consumed]
        if len(members) >= 2:
            patterns.append({"name": group["name"], "levels": members, "typical": True})
            consumed.update(members)
    for level in levels:
        if level not in consumed:
            patterns.append({"name": level, "levels": [level], "typical": False})
    return patterns


def _add_family_sheets(deliverables, families, key, definition, levels, typical_groups):
    patterns = consolidate_effective_levels(levels, typical_groups)
    sheets = []
    for index, pattern in enumerate(patterns, 1):
        sheet = {
            "family": key,
            "code": f"{definition['code']}-{index:02d}",
            "label": definition["label"],
            "pattern": pattern["name"],
            "levels": pattern["levels"],
            "typical": pattern["typical"],
            "special": False,
        }
        sheets.append(sheet)
        deliverables.append(sheet)
    families[key] = {
        "code": definition["code"],
        "label": definition["label"],
        "systems": [definition["system"]],
        "effective_levels": _unique_levels(levels),
        "count": len(sheets),
        "sheets": sheets,
    }


def _append_special(deliverables, families, family_key, code, label, levels, reason):
    sheet = {
        "family": family_key,
        "code": code,
        "label": label,
        "pattern": "System special",
        "levels": _unique_levels(levels),
        "typical": False,
        "special": True,
        "reason": reason,
    }
    families[family_key]["sheets"].append(sheet)
    families[family_key]["count"] += 1
    deliverables.append(sheet)


def predict_drawing_set(scope):
    """Return the exact authority-submission drawing list shown to the customer."""
    systems = _system_scopes(scope)
    typical_groups = scope.get("typical_groups") or []
    families = {}
    deliverables = []

    for key, definition in AUTHORITY_FAMILIES.items():
        levels = systems[definition["system"]]["levels"]
        _add_family_sheets(deliverables, families, key, definition, levels, typical_groups)

    # In multi-level approval sets, water supply normally needs one additional
    # riser/equipment/schematic deliverable. It belongs to the water family and
    # is not counted as a generic extra mechanical sheet.
    if scope.get("water_supply_special_sheet") and systems["water_supply"]["levels"]:
        _append_special(
            deliverables, families, "water_supply", "M-W-SPECIAL",
            "آبرسانی — رایزر / تجهیزات / شماتیک",
            scope.get("all_levels") or systems["water_supply"]["levels"],
            "authority water-supply system special",
        )

    # Cooling systems with outdoor/roof equipment receive their own equipment
    # sheet when the resolved project scope requires it.
    if scope.get("cooling_special_sheet") and systems["cooling"]["levels"]:
        _append_special(
            deliverables, families, "cooling", "M-C-EQUIP",
            "سرمایش — تجهیزات / بام",
            [scope.get("roof_level_name") or "Roof"],
            "authority cooling equipment/roof special",
        )

    roof_sheets = []
    if scope.get("roof_exists"):
        roof = {
            "family": "roof_rainwater",
            "code": "M-R-01",
            "label": "بام / آب باران",
            "pattern": scope.get("roof_level_name") or "Roof",
            "levels": [scope.get("roof_level_name") or "Roof"],
            "typical": False,
            "special": True,
            "reason": "dedicated authority roof/rainwater plan",
        }
        roof_sheets.append(roof)
        deliverables.append(roof)
    families["roof_rainwater"] = {
        "code": "M-R",
        "label": "بام / آب باران",
        "systems": ["roof_drainage"],
        "effective_levels": systems["roof_drainage"]["levels"],
        "count": len(roof_sheets),
        "sheets": roof_sheets,
    }

    total = len(deliverables)
    system_scope_count = sum(item["count"] for item in systems.values())
    return {
        "approved": False,
        "approval_required": True,
        "systems": systems,
        "sheet_families": families,
        "deliverable_sheets": deliverables,
        "total_plans": total,
        "deliverable_sheet_count": total,
        "system_scope_count": system_scope_count,
        "count_semantics": "authority_separated_customer_deliverables",
        "submission_profile": "local_engineering_organization",
        "typical_groups_applied": _normalize_typical_groups(typical_groups),
    }


def requires_approval(proposal):
    return not bool((proposal or {}).get("approved"))
