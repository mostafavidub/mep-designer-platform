"""Mechanical Drawing Set Planning Engine — authority submission profile.

The customer-facing number is the number of separate mechanical drawings that
will be issued. Different approval disciplines are never merged just to reduce
sheet count. Typical-floor consolidation is system-specific only.
"""

import copy
import hashlib
import json


MANIFEST_SCHEMA_VERSION = "3.0"

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
        "cooling": scope.get("conditioned_levels", []), "heating": scope.get("heated_levels", []),
        "water_supply": scope.get("wet_fixture_levels", []), "sanitary": scope.get("sanitary_fixture_levels", []),
        "ventilation": scope.get("ventilation_required_levels", []), "gas": scope.get("gas_consumer_levels", []),
    }
    systems = {}
    for name, levels in mapping.items():
        levels = _unique_levels(levels); systems[name] = {"count": len(levels), "levels": levels}
    roof_name = scope.get("roof_level_name") or "Roof"
    systems["roof_drainage"] = {"count": 1 if scope.get("roof_exists") else 0, "levels": [roof_name] if scope.get("roof_exists") else []}
    systems["riser"] = {"count": 1 if scope.get("vertical_systems") else 0, "levels": ["Vertical systems"] if scope.get("vertical_systems") else []}
    return systems


def _normalize_typical_groups(raw_groups):
    out = []
    if isinstance(raw_groups, dict): raw_groups = [{"name": name, "levels": levels} for name, levels in raw_groups.items()]
    for index, item in enumerate(raw_groups or [], 1):
        if isinstance(item, dict):
            levels = item.get("levels") or item.get("floors") or item.get("members") or []
            name = item.get("name") or item.get("label") or item.get("pattern") or f"Typical {index}"
        elif isinstance(item, (list, tuple, set)): levels = list(item); name = f"Typical {index}"
        else: continue
        levels = _unique_levels(levels)
        if levels: out.append({"name": str(name), "levels": levels})
    return out


def consolidate_effective_levels(levels, typical_groups=None):
    levels = _unique_levels(levels)
    if not levels: return []
    consumed, patterns = set(), []
    for group in _normalize_typical_groups(typical_groups):
        members = [x for x in levels if x in group["levels"] and x not in consumed]
        if len(members) >= 2:
            patterns.append({"name": group["name"], "levels": members, "typical": True}); consumed.update(members)
    for level in levels:
        if level not in consumed: patterns.append({"name": level, "levels": [level], "typical": False})
    return patterns


def _make_family(definition, key, levels, typical_groups):
    sheets = []
    for index, pattern in enumerate(consolidate_effective_levels(levels, typical_groups), 1):
        sheets.append({"family": key, "code": f"{definition['code']}-{index:02d}", "label": definition["label"],
                       "pattern": pattern["name"], "levels": pattern["levels"], "typical": pattern["typical"], "special": False,
                       "drawing_type": "floor_plan"})
    return {"code": definition["code"], "label": definition["label"], "systems": [definition["system"]],
            "effective_levels": _unique_levels(levels), "count": len(sheets), "sheets": sheets}


def _append_special(family, code, label, levels, reason, drawing_type="detail_sheet"):
    sheet = {"family": None, "code": code, "label": label, "pattern": "System special", "levels": _unique_levels(levels),
             "typical": False, "special": True, "reason": reason, "drawing_type": drawing_type}
    family["sheets"].append(sheet); family["count"] += 1; return sheet


def _append_family_roles(family, family_key, levels, roles):
    """Add authority-required non-floor drawing roles to one family."""
    type_by_suffix = {"RISER": "riser_diagram", "EQUIP": "equipment_plan", "RETURN": "schematic",
                      "DETAIL": "detail_sheet", "RAIN": "roof_plan", "PARK": "ventilation_plan"}
    for suffix, label, reason in roles:
        sheet = _append_special(family, f"{family['code']}-{suffix}", label, levels, reason, type_by_suffix.get(suffix, "detail_sheet"))
        sheet['family'] = family_key; yield sheet


def _build_manifest(deliverables):
    sheets = copy.deepcopy(deliverables)
    payload = {"schema_version": MANIFEST_SCHEMA_VERSION, "discipline": "mechanical", "total_sheets": len(sheets), "sheets": sheets}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["manifest_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest(); return payload


def is_current_manifest(manifest):
    manifest = manifest or {}; sheets = manifest.get("sheets") or []
    try: total = int(manifest.get("total_sheets") or -1)
    except (TypeError, ValueError): return False
    codes = [str(x.get("code") or "") for x in sheets]
    return manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION and total > 0 and total == len(sheets) and bool(codes) and all(codes) and len(codes) == len(set(codes))


def approve_drawing_set(proposal):
    proposal = copy.deepcopy(proposal or {}); manifest = proposal.get("drawing_manifest")
    if not manifest: raise ValueError("Drawing manifest is missing.")
    if not is_current_manifest(manifest): raise ValueError("Drawing manifest is stale or structurally invalid; recalculate the proposal.")
    sheets = manifest.get("sheets") or []
    if int(manifest.get("total_sheets") or -1) != len(sheets): raise ValueError("Drawing manifest count is internally inconsistent.")
    codes = [str(x.get("code") or "") for x in sheets]
    if not codes or any(not x for x in codes) or len(codes) != len(set(codes)): raise ValueError("Drawing manifest sheet codes must be present and unique.")
    proposal["approved_manifest"] = copy.deepcopy(manifest); proposal["approved"] = True; proposal["approval_required"] = False; return proposal


def _full_authority_documentation_required(scope, families, typical_groups):
    """Select full detail/support package from project complexity, never project name.

    The approved non-typical multi-level benchmark has three independent occupied
    levels, a roof, vertical services and all principal mechanical families.  Such
    projects require separate riser/equipment/detail sheets.  Verified Typical
    groups remain consolidated and do not inherit this expanded package blindly.
    """
    explicit = scope.get("full_authority_documentation")
    if explicit is not None: return bool(explicit)
    principal = ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust")
    return (
        not _normalize_typical_groups(typical_groups)
        and bool(scope.get("roof_exists")) and bool(scope.get("vertical_systems"))
        and all(families.get(key, {}).get("count", 0) >= 3 for key in principal)
    )


def predict_drawing_set(scope):
    systems = _system_scopes(scope); typical_groups = scope.get("typical_groups") or []; families, deliverables = {}, []
    for key, definition in AUTHORITY_FAMILIES.items():
        family = _make_family(definition, key, systems[definition["system"]]["levels"], typical_groups)
        families[key] = family; deliverables.extend(family["sheets"])

    water_patterns = families['water_supply']['count']; water_roles = [('RISER', 'آبرسانی — رایزر', 'authority water riser')]
    single_effective_level = water_patterns == 1 and not _normalize_typical_groups(typical_groups)
    water_service_required = bool(water_patterns and (scope.get('central_water_equipment') or len(systems['water_supply']['levels']) >= 2))
    if water_service_required:
        water_roles.append(('EQUIP', 'آبرسانی — پمپ / مخزن / تجهیزات', 'approved water service scope'))
    if scope.get('hot_water_return_required'):
        water_roles.append(('RETURN', 'آب گرم — برگشت و بالانس', 'approved hot-water return scope'))
    if water_patterns:
        added = list(_append_family_roles(families['water_supply'], 'water_supply', scope.get('all_levels') or systems['water_supply']['levels'], water_roles)); deliverables.extend(added)

    if families['sanitary_vent']['count'] and not _normalize_typical_groups(typical_groups) and not scope.get('roof_exists'):
        sanitary_roles = [('RISER', 'فاضلاب و ونت — رایزر', 'authority sanitary riser'), ('RAIN', 'فاضلاب و ونت — آب باران / دیتیل', 'authority rainwater and vent detail')]
        if families['sanitary_vent']['count'] == 1: sanitary_roles.append(('DETAIL', 'فاضلاب و ونت — جزئیات اجرایی', 'authority single-level sanitary details'))
        added = list(_append_family_roles(families['sanitary_vent'], 'sanitary_vent', scope.get('all_levels') or systems['sanitary']['levels'], sanitary_roles)); deliverables.extend(added)

    if single_effective_level:
        for family_key, suffix, label, reason in (
            ('heating', 'EQUIP', 'گرمایش — تجهیزات و جزئیات', 'authority single-level heating equipment'),
            ('cooling', 'EQUIP', 'سرمایش — تجهیزات و درین', 'authority single-level cooling equipment'),
            ('ventilation_exhaust', 'DETAIL', 'تهویه — جزئیات تخلیه و هوای جبران', 'authority single-level ventilation details')):
            family = families[family_key]
            if family['count']:
                added = list(_append_family_roles(family, family_key, family['effective_levels'], [(suffix, label, reason)])); deliverables.extend(added)

    if scope.get('roof_exists') and families['cooling']['count']:
        added = list(_append_family_roles(families['cooling'], 'cooling', systems['roof_drainage']['levels'], [('EQUIP', 'سرمایش — جانمایی تجهیزات بام', 'authority roof cooling equipment')])); deliverables.extend(added)

    if scope.get('enclosed_parking') and families['ventilation_exhaust']['count']:
        added = list(_append_family_roles(families['ventilation_exhaust'], 'ventilation_exhaust', systems['ventilation']['levels'], [('PARK', 'تهویه — اگزاست پارکینگ', 'authority enclosed parking exhaust')])); deliverables.extend(added)

    full_documentation = _full_authority_documentation_required(scope, families, typical_groups)
    if full_documentation:
        support_roles = {
            'water_supply': [('EQUIP', 'آبرسانی — پمپ / مخزن / تجهیزات', 'full authority equipment drawing'), ('RETURN', 'آبرسانی — برگشت آب گرم و بالانس', 'full authority return schematic')],
            'sanitary_vent': [('RISER', 'فاضلاب و ونت — رایزر', 'full authority sanitary riser'), ('DETAIL', 'فاضلاب و ونت — جزئیات اجرایی', 'full authority sanitary detail')],
            'heating': [('EQUIP', 'گرمایش — تجهیزات و جزئیات', 'full authority heating equipment')],
            'gas': [('DETAIL', 'گاز — جزئیات اجرایی و اتصالات', 'full authority gas detail')],
            'cooling': [('DETAIL', 'سرمایش — جزئیات تجهیزات و درین', 'full authority cooling detail')],
            'ventilation_exhaust': [('DETAIL', 'تهویه — جزئیات تخلیه و هوای جبران', 'full authority ventilation detail')],
        }
        existing_codes = {s['code'] for s in deliverables}
        for family_key, roles in support_roles.items():
            family = families[family_key]
            unique_roles = [role for role in roles if f"{family['code']}-{role[0]}" not in existing_codes]
            if unique_roles:
                added = list(_append_family_roles(family, family_key, scope.get('all_levels') or family['effective_levels'], unique_roles))
                deliverables.extend(added); existing_codes.update(s['code'] for s in added)

    # A water equipment sheet and its calculation sheet are separate issued
    # deliverables. Do not hide the calculation sheet behind the equipment role;
    # the customer must approve the exact additional drawing before CAD release.
    water_family = families['water_supply']
    has_water_equipment = any(s.get('drawing_type') == 'equipment_plan' for s in water_family['sheets'])
    has_water_calc = any(s.get('drawing_type') == 'calculation_sheet' for s in water_family['sheets'])
    if has_water_equipment and not has_water_calc:
        calc_sheet = _append_special(
            water_family, 'M-W-CALC', 'آبرسانی — محاسبات پمپ / افت فشار',
            systems['water_supply']['levels'], 'approved water-service calculation deliverable',
            'calculation_sheet',
        )
        calc_sheet['family'] = 'water_supply'; deliverables.append(calc_sheet)

    roof_sheets = []
    if scope.get('roof_exists'):
        roof_sheets.append({'family': 'roof_rainwater', 'code': 'M-R-01', 'label': 'بام / آب باران',
                            'pattern': systems['roof_drainage']['levels'][0], 'levels': systems['roof_drainage']['levels'],
                            'typical': False, 'special': False, 'drawing_type': 'roof_plan'})
        deliverables.extend(roof_sheets)
    families["roof_rainwater"] = {"code": "M-R", "label": "بام / آب باران", "systems": ["roof_drainage"],
                                   "effective_levels": systems["roof_drainage"]["levels"], "count": len(roof_sheets), "sheets": roof_sheets}

    total = len(deliverables); manifest = _build_manifest(deliverables)
    return {"approved": False, "approval_required": True, "systems": systems, "sheet_families": families,
            "deliverable_sheets": deliverables, "drawing_manifest": manifest, "approved_manifest": None,
            "total_plans": total, "deliverable_sheet_count": total, "system_scope_count": sum(item["count"] for item in systems.values()),
            "count_semantics": "authority_separated_customer_deliverables", "submission_profile": "local_engineering_organization",
            "full_authority_documentation": full_documentation, "typical_groups_applied": _normalize_typical_groups(typical_groups)}


def requires_approval(proposal): return not bool((proposal or {}).get("approved"))
