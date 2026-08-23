"""Mechanical Drawing Set Planning Engine.

The customer-facing proposal MUST count deliverable CAD sheets, not internal
system scopes. The sheet families here mirror the current mechanical CAD
output convention:

- M-P: cold/hot water + gas
- M-S: sanitary + vent + rainwater
- M-H: heating + cooling + condensate
- M-V: ventilation + exhaust
- M-RISER-CALC: risers + calculations/legend

Effective levels are consolidated through typical-floor groups before the
customer-facing count is calculated.
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

SHEET_FAMILIES = {
    "plumbing_gas": {
        "code": "M-P",
        "label": "آب سرد و گرم + گاز",
        "systems": ("water_supply", "gas"),
    },
    "sanitary_vent_rain": {
        "code": "M-S",
        "label": "فاضلاب + ونت + آب باران",
        "systems": ("sanitary", "roof_drainage"),
    },
    "heating_cooling_condensate": {
        "code": "M-H",
        "label": "گرمایش + سرمایش + درین کندانس",
        "systems": ("heating", "cooling"),
    },
    "ventilation_exhaust": {
        "code": "M-V",
        "label": "تهویه + اگزاست",
        "systems": ("ventilation",),
    },
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
        "levels": ["Roof"] if scope.get("roof_exists") else [],
    }
    systems["riser"] = {
        "count": 1 if scope.get("vertical_systems") else 0,
        "levels": ["Riser Diagram"] if scope.get("vertical_systems") else [],
    }
    return systems


def _normalize_typical_groups(raw_groups):
    """Return [{name, levels}] from several architecture-analysis shapes."""
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
    """Collapse effective levels into actual deliverable level patterns.

    A typical group becomes one sheet only when at least two effective levels of
    that system/family belong to the group. Uncovered levels remain singleton
    sheets. No floor is silently dropped.
    """
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


def _union_levels(*groups):
    values = []
    for group in groups:
        for level in group or []:
            if level not in values:
                values.append(level)
    return values


def _family_levels(family, systems, scope):
    if family == "plumbing_gas":
        return _union_levels(systems["water_supply"]["levels"], systems["gas"]["levels"])
    if family == "sanitary_vent_rain":
        # Rainwater is carried on the sanitary/vent family in the current CAD
        # deliverable. It does not create a second customer-counted roof sheet
        # unless the CAD engine explicitly requests a dedicated roof sheet.
        levels = list(systems["sanitary"]["levels"])
        if scope.get("roof_requires_dedicated_plan"):
            levels = _union_levels(levels, [scope.get("roof_level_name") or "Roof"])
        return levels
    if family == "heating_cooling_condensate":
        return _union_levels(systems["heating"]["levels"], systems["cooling"]["levels"])
    if family == "ventilation_exhaust":
        return list(systems["ventilation"]["levels"])
    return []


def predict_drawing_set(scope):
    """Create the approval proposal before mechanical generation.

    `total_plans` is the number of sheets the customer is expected to receive.
    `system_scope_count` remains available only for engineering traceability and
    must not be presented as the deliverable sheet count.
    """
    systems = _system_scopes(scope)
    typical_groups = scope.get("typical_groups") or []
    sheet_families = {}
    deliverable_sheets = []

    for key, definition in SHEET_FAMILIES.items():
        effective = _family_levels(key, systems, scope)
        patterns = consolidate_effective_levels(effective, typical_groups)
        sheets = []
        for index, pattern in enumerate(patterns, 1):
            sheet = {
                "family": key,
                "code": f"{definition['code']}-{index:02d}",
                "label": definition["label"],
                "pattern": pattern["name"],
                "levels": pattern["levels"],
                "typical": pattern["typical"],
            }
            sheets.append(sheet)
            deliverable_sheets.append(sheet)
        sheet_families[key] = {
            "code": definition["code"],
            "label": definition["label"],
            "systems": list(definition["systems"]),
            "effective_levels": effective,
            "count": len(sheets),
            "sheets": sheets,
        }

    if scope.get("vertical_systems"):
        riser_sheet = {
            "family": "riser_calc",
            "code": "M-RISER-CALC",
            "label": "رایزر + محاسبات + Legend",
            "pattern": "Building",
            "levels": _unique_levels(scope.get("all_levels") or []),
            "typical": False,
        }
        sheet_families["riser_calc"] = {
            "code": "M-RISER-CALC",
            "label": "رایزر + محاسبات + Legend",
            "systems": ["riser"],
            "effective_levels": riser_sheet["levels"],
            "count": 1,
            "sheets": [riser_sheet],
        }
        deliverable_sheets.append(riser_sheet)
    else:
        sheet_families["riser_calc"] = {
            "code": "M-RISER-CALC",
            "label": "رایزر + محاسبات + Legend",
            "systems": ["riser"],
            "effective_levels": [],
            "count": 0,
            "sheets": [],
        }

    system_scope_count = sum(item["count"] for item in systems.values())
    total = len(deliverable_sheets)
    return {
        "approved": False,
        "approval_required": True,
        "systems": systems,
        "sheet_families": sheet_families,
        "deliverable_sheets": deliverable_sheets,
        "total_plans": total,
        "deliverable_sheet_count": total,
        "system_scope_count": system_scope_count,
        "count_semantics": "customer_deliverable_sheets",
        "typical_groups_applied": _normalize_typical_groups(typical_groups),
    }


def requires_approval(proposal):
    return not bool((proposal or {}).get("approved"))
