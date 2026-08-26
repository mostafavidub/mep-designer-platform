"""System-specific Typical Floor policy.

Keeps the existing high-confidence architectural grouping as the baseline, then
requires system-relevant evidence to match before a family is allowed to share
one authority sheet.  The wrapper is conservative: uncertainty means separate
sheets.  ContextVar keeps concurrent proposal requests isolated.
"""
from collections import Counter
from contextvars import ContextVar


_ACTIVE_GROUPS = ContextVar("engitools_system_typical_groups", default=None)

FAMILY_TO_SYSTEM_KEY = {
    "water_supply": "water_supply",
    "sanitary_vent": "sanitary_vent",
    "heating": "heating",
    "cooling": "cooling",
    "gas": "gas",
    "ventilation_exhaust": "ventilation_exhaust",
}


def _profile_map(auto):
    return {str(p.get("name") or ""): p for p in (auto.get("level_profiles") or []) if p.get("name")}


def _counts_by_level(rows, accepted_status="detected"):
    result = {}
    for row in rows or []:
        if accepted_status and row.get("status") != accepted_status:
            continue
        level = str(row.get("level") or "")
        kind = str(row.get("type") or row.get("kind") or "")
        if not level or not kind:
            continue
        result.setdefault(level, Counter())[kind] += 1
    return result


def _same(values):
    values = list(values)
    return bool(values) and all(value == values[0] for value in values[1:])


def _system_signature(family, profile, fixture_counts, equipment_counts):
    """Return only evidence relevant to one system family.

    The generic architectural signature remains part of every family so rooms,
    wet cores and shaft positions cannot be consolidated when their geometry
    differs.  Family-specific fixture/equipment evidence is then added.
    """
    name = str(profile.get("name") or "")
    base = profile.get("typical_signature")
    if base is None or profile.get("typical_confidence") != "high" or profile.get("roof"):
        return None
    if family in {"water_supply", "sanitary_vent"}:
        return (
            base,
            bool(profile.get("wet_fixture_candidate")),
            bool(profile.get("sanitary_candidate")),
            tuple(sorted((fixture_counts.get(name) or {}).items())),
        )
    if family in {"heating", "cooling"}:
        return (
            base,
            bool(profile.get("conditioned_candidate")),
            tuple(sorted((equipment_counts.get(name) or {}).items())),
        )
    if family == "gas":
        gas_fixtures = tuple(sorted((k, v) for k, v in (fixture_counts.get(name) or {}).items() if k == "gas"))
        gas_equipment = tuple(sorted((k, v) for k, v in (equipment_counts.get(name) or {}).items() if k in {"boiler", "water_heater", "stove"}))
        return base, bool(profile.get("gas_candidate")), gas_fixtures, gas_equipment
    if family == "ventilation_exhaust":
        ventilation_equipment = tuple(sorted((k, v) for k, v in (equipment_counts.get(name) or {}).items() if k in {"fan", "exhaust_fan", "hood"}))
        return base, bool(profile.get("ventilation_candidate")), ventilation_equipment
    return None


def build_system_typical_groups(auto):
    auto = auto or {}
    profiles = _profile_map(auto)
    base_groups = [g for g in (auto.get("typical_groups") or []) if str(g.get("confidence") or "high") == "high"]
    fixture_counts = _counts_by_level(auto.get("fixture_detections") or [])
    equipment_counts = _counts_by_level(auto.get("equipment_detections") or [])
    output = {family: [] for family in FAMILY_TO_SYSTEM_KEY}

    for family in output:
        for group in base_groups:
            members = [str(x) for x in (group.get("levels") or []) if str(x) in profiles]
            if len(members) < 2:
                continue
            signatures = [
                _system_signature(family, profiles[member], fixture_counts, equipment_counts)
                for member in members
            ]
            if any(signature is None for signature in signatures) or not _same(signatures):
                continue
            output[family].append({
                "name": str(group.get("name") or "Typical: " + " / ".join(members)),
                "levels": members,
                "confidence": "high",
                "basis": "system-specific architecture + fixture/equipment evidence",
                "system_family": family,
            })
    return output


def install(workflow_module, planner_module):
    if getattr(workflow_module, "_system_typical_v1_installed", False):
        return

    original_build_scope = workflow_module.build_scope
    original_make_family = planner_module._make_family
    original_predict = planner_module.predict_drawing_set

    def build_scope_system_typical(project):
        scope = original_build_scope(project)
        auto = (project.analysis or {}).get("architectural_auto") or {}
        scope["system_typical_groups"] = build_system_typical_groups(auto)
        return scope

    def make_family_system_typical(definition, key, levels, fallback_groups):
        active = _ACTIVE_GROUPS.get() or {}
        groups = active.get(key)
        if groups is None:
            groups = fallback_groups
        return original_make_family(definition, key, levels, groups)

    def predict_system_typical(scope):
        token = _ACTIVE_GROUPS.set((scope or {}).get("system_typical_groups") or {})
        try:
            result = original_predict(scope)
            result["system_typical_groups_applied"] = {
                family: [dict(group) for group in groups]
                for family, groups in ((scope or {}).get("system_typical_groups") or {}).items()
            }
            return result
        finally:
            _ACTIVE_GROUPS.reset(token)

    planner_module._make_family = make_family_system_typical
    planner_module.predict_drawing_set = predict_system_typical
    workflow_module.build_scope = build_scope_system_typical
    # create_proposal resolves this imported global when called.
    workflow_module.predict_drawing_set = predict_system_typical
    workflow_module._system_typical_v1_installed = True
