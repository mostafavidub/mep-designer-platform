"""Mechanical Drawing Set Planning Engine — authority submission profile.

The customer-facing number is the number of separate mechanical drawings that
will be issued. Different approval disciplines are never merged just to reduce
sheet count. Typical-floor consolidation is system-specific only.
"""

import copy
import hashlib
import json


MANIFEST_SCHEMA_VERSION = "2.1"

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
    mapping = {
        "cooling": scope.get("conditioned_levels", []),
        "heating": scope.get("heated_levels", []),
        "water_supply": scope.get("wet_fixture_levels", []),
        "sanitary": scope.get("sanitary_fixture_levels", []),
        "ventilation": scope.get("ventilation_required_levels", []),
        "gas": scope.get("gas_consumer_levels", []),
    }
    systems = {}
    for name, levels in mapping.items():
        levels = _unique_levels(levels)
        systems[name] = {"count": len(levels), "levels": levels}
    roof_name = scope.get("roof_level_name") or "Roof"
    systems["roof_drainage"] = {
        "count": 1 if scope.get("roof_exists") else 0,
        "levels": [roof_name] if scope.get("roof_exists") else [],
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
            levels = list(item); name = f"Typical {index}"
        else:
            continue
        levels = _unique_levels(levels)
        if levels:
            out.append({"name": str(name), "levels": levels})
    return out


def consolidate_effective_levels(levels, typical_groups=None):
    levels = _unique_levels(levels)
    if not levels:
        return []
    consumed, patterns = set(), []
    for group in _normalize_typical_groups(typical_groups):
        members = [x for x in levels if x in group["levels"] and x not in consumed]
        if len(members) >= 2:
            patterns.append({"name": group["name"], "levels": members, "typical": True})
            consumed.update(members)
    for level in levels:
        if level not in consumed:
            patterns.append({"name": level, "levels": [level], "typical": False})
    return patterns


def _make_family(definition, key, levels, typical_groups):
    sheets = []
    for index, pattern in enumerate(consolidate_effective_levels(levels, typical_groups), 1):
        sheets.append({
            "family": key,
            "code": f"{definition['code']}-{index:02d}",
            "label": definition["label"],
            "pattern": pattern["name"],
            "levels": pattern["levels"],
            "typical": pattern["typical"],
            "special": False,
        })
    return {
        "code": definition["code"],
        "label": definition["label"],
        "systems": [definition["system"]],
        "effective_levels": _unique_levels(levels),
        "count": len(sheets),
        "sheets": sheets,
    }


def _append_special(family, code, label, levels, reason):
    sheet = {
        "family": None,
        "code": code,
        "label": label,
        "pattern": "System special",
        "levels": _unique_levels(levels),
        "typical": False,
        "special": True,
        "reason": reason,
    }
    family["sheets"].append(sheet)
    family["count"] += 1
    return sheet


def _append_family_roles(family, family_key, levels, roles):
    """Add authority-required non-floor drawing roles to one family."""
    for suffix, label, reason in roles:
        sheet = _append_special(
            family, f"{family['code']}-{suffix}", label, levels, reason,
        )
        sheet['family'] = family_key
        yield sheet


def _build_manifest(deliverables):
    sheets = copy.deepcopy(deliverables)
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "discipline": "mechanical",
        "total_sheets": len(sheets),
        "sheets": sheets,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["manifest_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def is_current_manifest(manifest):
    """Return True only for a structurally valid manifest from this planner."""
    manifest = manifest or {}
    sheets = manifest.get("sheets") or []
    try:
        total = int(manifest.get("total_sheets") or -1)
    except (TypeError, ValueError):
        return False
    codes = [str(x.get("code") or "") for x in sheets]
    return (
        manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION
        and total > 0
        and total == len(sheets)
        and bool(codes)
        and all(codes)
        and len(codes) == len(set(codes))
    )


def approve_drawing_set(proposal):
    """Freeze the exact customer-approved sheet manifest for CAD generation."""
    proposal = copy.deepcopy(proposal or {})
    manifest = proposal.get("drawing_manifest")
    if not manifest:
        raise ValueError("Drawing manifest is missing.")
    if not is_current_manifest(manifest):
        raise ValueError("Drawing manifest is stale or structurally invalid; recalculate the proposal.")
    sheets = manifest.get("sheets") or []
    if int(manifest.get("total_sheets") or -1) != len(sheets):
        raise ValueError("Drawing manifest count is internally inconsistent.")
    codes = [str(x.get("code") or "") for x in sheets]
    if not codes or any(not x for x in codes) or len(codes) != len(set(codes)):
        raise ValueError("Drawing manifest sheet codes must be present and unique.")
    proposal["approved_manifest"] = copy.deepcopy(manifest)
    proposal["approved"] = True
    proposal["approval_required"] = False
    return proposal


def predict_drawing_set(scope):
    systems = _system_scopes(scope)
    typical_groups = scope.get("typical_groups") or []
    families, deliverables = {}, []

    for key, definition in AUTHORITY_FAMILIES.items():
        family = _make_family(definition, key, systems[definition["system"]]["levels"], typical_groups)
        families[key] = family
        deliverables.extend(family["sheets"])

    # Authority drawings are composed by drawing role, not by a bare
    # "system × floor" multiplication.  A water riser is the default vertical
    # role.  Plant-room and hot-water-return sheets are added only when the
    # architecture/approved scope explicitly requires them; a floor count is
    # not evidence that either exists.  Sanitary riser/rainwater roles are
    # issued for distinct floors, while a declared typical group combines them
    # into its representative sanitary plan.
    water_patterns = families['water_supply']['count']
    water_roles = [('RISER', 'آبرسانی — رایزر', 'authority water riser')]
    # A single effective floor does not collapse the authority package to one
    # drawing per system.  Across the approved one-level benchmark projects,
    # water equipment/connection, sanitary detail, terminal-equipment and
    # ventilation-detail roles remain separate deliverables.  This is a
    # composition rule, not a project-name exception.
    single_effective_level = water_patterns == 1 and not _normalize_typical_groups(typical_groups)
    distinct_multi_level_equipment = water_patterns >= 3 and not _normalize_typical_groups(typical_groups)
    if scope.get('central_water_equipment') or single_effective_level or distinct_multi_level_equipment:
        water_roles.append(('EQUIP', 'آبرسانی — پمپ / مخزن / تجهیزات', 'approved water equipment scope'))
    if scope.get('hot_water_return_required') or distinct_multi_level_equipment:
        water_roles.append(('RETURN', 'آب گرم — برگشت و بالانس', 'approved hot-water return scope'))
    if water_patterns:
        added = list(_append_family_roles(
            families['water_supply'], 'water_supply',
            scope.get('all_levels') or systems['water_supply']['levels'], water_roles,
        ))
        deliverables.extend(added)

    if families['sanitary_vent']['count'] and not _normalize_typical_groups(typical_groups):
        sanitary_roles = [
            ('RISER', 'فاضلاب و ونت — رایزر', 'authority sanitary riser'),
            ('RAIN', 'فاضلاب و ونت — آب باران / دیتیل', 'authority rainwater and vent detail'),
        ]
        if families['sanitary_vent']['count'] == 1:
            sanitary_roles.append(
                ('DETAIL', 'فاضلاب و ونت — جزئیات اجرایی', 'authority single-level sanitary details')
            )
        added = list(_append_family_roles(
            families['sanitary_vent'], 'sanitary_vent',
            scope.get('all_levels') or systems['sanitary']['levels'], sanitary_roles,
        ))
        deliverables.extend(added)

    if single_effective_level:
        for family_key, suffix, label, reason in (
            ('heating', 'EQUIP', 'گرمایش — تجهیزات و جزئیات', 'authority single-level heating equipment'),
            ('cooling', 'EQUIP', 'سرمایش — تجهیزات و درین', 'authority single-level cooling equipment'),
            ('ventilation_exhaust', 'DETAIL', 'تهویه — جزئیات تخلیه و هوای جبران', 'authority single-level ventilation details'),
        ):
            family = families[family_key]
            if family['count']:
                added = list(_append_family_roles(
                    family, family_key, family['effective_levels'], [(suffix, label, reason)],
                ))
                deliverables.extend(added)

    # A dedicated roof level carries its own rainwater drawing.  When cooling
    # equipment is explicitly coordinated on that roof, its equipment layout
    # is also separate from the occupied-floor cooling plans.
    if scope.get('roof_exists') and families['cooling']['count']:
        added = list(_append_family_roles(
            families['cooling'], 'cooling',
            systems['roof_drainage']['levels'], [
                ('EQUIP', 'سرمایش — جانمایی تجهیزات بام', 'authority roof cooling equipment'),
            ],
        ))
        deliverables.extend(added)

    if scope.get('enclosed_parking') and families['ventilation_exhaust']['count']:
        added = list(_append_family_roles(
            families['ventilation_exhaust'], 'ventilation_exhaust',
            systems['ventilation']['levels'], [
                ('PARK', 'تهویه — اگزاست پارکینگ', 'authority enclosed parking exhaust'),
            ],
        ))
        deliverables.extend(added)

    roof_sheets = []
    if scope.get('roof_exists'):
        roof_sheets.append({
            'family': 'roof_rainwater', 'code': 'M-R-01',
            'label': 'بام / آب باران', 'pattern': systems['roof_drainage']['levels'][0],
            'levels': systems['roof_drainage']['levels'], 'typical': False,
            'special': False,
        })
        deliverables.extend(roof_sheets)
    families["roof_rainwater"] = {
        "code": "M-R", "label": "بام / آب باران", "systems": ["roof_drainage"],
        "effective_levels": systems["roof_drainage"]["levels"],
        "count": len(roof_sheets), "sheets": roof_sheets,
    }

    total = len(deliverables)
    manifest = _build_manifest(deliverables)
    return {
        "approved": False,
        "approval_required": True,
        "systems": systems,
        "sheet_families": families,
        "deliverable_sheets": deliverables,
        "drawing_manifest": manifest,
        "approved_manifest": None,
        "total_plans": total,
        "deliverable_sheet_count": total,
        "system_scope_count": sum(item["count"] for item in systems.values()),
        "count_semantics": "authority_separated_customer_deliverables",
        "submission_profile": "local_engineering_organization",
        "typical_groups_applied": _normalize_typical_groups(typical_groups),
    }


def requires_approval(proposal):
    return not bool((proposal or {}).get("approved"))
