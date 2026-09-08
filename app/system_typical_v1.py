"""System-specific Typical Floor policy.

Architectural similarity is only a candidate relationship.  A mechanical
family may consolidate floors only when system-relevant evidence agrees as
well.  The policy is deliberately fail-closed: missing/uncertain family
evidence means separate sheets.  A large architectural typical group may be
partitioned into smaller family-specific groups (for example cooling floors
1-3 and 4-5) when its mechanical evidence separates that way.
"""
from collections import defaultdict
from contextvars import ContextVar


_ACTIVE_GROUPS = ContextVar("engitools_system_typical_groups", default=None)
SYSTEM_TYPICAL_VERSION = "system-typical-v1.1"

FAMILY_TO_SYSTEM_KEY = {
    "water_supply": "water_supply",
    "sanitary_vent": "sanitary_vent",
    "heating": "heating",
    "cooling": "cooling",
    "gas": "gas",
    "ventilation_exhaust": "ventilation_exhaust",
}

FAMILY_EQUIPMENT_TYPES = {
    "heating": {"radiator", "fan_coil", "boiler", "water_heater"},
    "cooling": {"split_indoor", "split_outdoor", "fan_coil", "ahu", "chiller"},
    "gas": {"gas_cooker", "boiler", "water_heater"},
    "ventilation_exhaust": {"exhaust_fan", "kitchen_hood", "ahu"},
}


def _profile_map(auto):
    return {str(p.get("name") or ""): p for p in (auto.get("level_profiles") or []) if p.get("name")}


def _architecture_level_map(auto):
    model = (auto or {}).get("architecture_model") or {}
    return {str(row.get("name") or ""): row for row in (model.get("levels") or []) if row.get("name")}


def _accepted_by_level(rows, allowed_types=None):
    result = defaultdict(list)
    for row in rows or []:
        if str(row.get("status") or "") != "detected":
            continue
        level = str(row.get("level") or "")
        kind = str(row.get("type") or row.get("kind") or "")
        if not level or not kind:
            continue
        if allowed_types is not None and kind not in allowed_types:
            continue
        result[level].append(row)
    return result


def _bounds(level_row):
    values = (level_row or {}).get("region_bounds") or []
    try:
        if len(values) != 4:
            return None
        x1, y1, x2, y2 = map(float, values)
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    except (TypeError, ValueError):
        return None


def _normalized_xy(level_row, row):
    b = _bounds(level_row)
    if b is None:
        return None
    try:
        x = float(row.get("x")); y = float(row.get("y"))
    except (TypeError, ValueError):
        position = row.get("position") or []
        try:
            x, y = float(position[0]), float(position[1])
        except (TypeError, ValueError, IndexError):
            return None
    x1, y1, x2, y2 = b
    return round((x-x1)/(x2-x1), 2), round((y-y1)/(y2-y1), 2)


def _detection_signature(level, level_row, rows):
    if not rows:
        return None
    values = []
    for row in rows:
        kind = str(row.get("type") or row.get("kind") or "")
        point = _normalized_xy(level_row, row)
        # Position is part of the contract. If it cannot be normalized, the
        # family evidence is insufficient for a Typical decision.
        if not kind or point is None:
            return None
        values.append((kind, point[0], point[1]))
    return tuple(sorted(values))


def _shaft_signature(level_row):
    b = _bounds(level_row)
    if b is None:
        return None
    shafts = (level_row or {}).get("shafts") or []
    values = []
    for shaft in shafts:
        centroid = shaft.get("centroid") or []
        try:
            row = {"x": centroid[0], "y": centroid[1]}
        except (TypeError, IndexError):
            return None
        point = _normalized_xy(level_row, row)
        if point is None:
            return None
        values.append(point)
    return tuple(sorted(values))


def _system_signature(family, profile, level_row, fixture_rows, equipment_rows):
    """Return a family-specific, translation-invariant signature or ``None``.

    ``None`` means there is not enough system evidence to safely consolidate
    this level.  Geometry alone never proves mechanical equivalence.
    """
    base = profile.get("typical_signature")
    if base is None or profile.get("typical_confidence") != "high" or profile.get("roof"):
        return None
    if not level_row or _bounds(level_row) is None:
        return None
    shafts = _shaft_signature(level_row)
    if shafts is None:
        return None

    if family in {"water_supply", "sanitary_vent"}:
        detected = _detection_signature(profile.get("name"), level_row, fixture_rows)
        if detected is None:
            return None
        return (
            base, shafts,
            bool(profile.get("wet_fixture_candidate")),
            bool(profile.get("sanitary_candidate")),
            detected,
        )

    allowed = FAMILY_EQUIPMENT_TYPES.get(family)
    relevant = [r for r in equipment_rows if str(r.get("type") or r.get("kind") or "") in (allowed or set())]
    detected = _detection_signature(profile.get("name"), level_row, relevant)
    if detected is None:
        return None

    if family in {"heating", "cooling"}:
        return base, shafts, bool(profile.get("conditioned_candidate")), detected
    if family == "gas":
        return base, shafts, bool(profile.get("gas_candidate")), detected
    if family == "ventilation_exhaust":
        return base, shafts, bool(profile.get("ventilation_candidate")), detected
    return None


def _partition_group(family, group, profiles, level_rows, fixture_by_level, equipment_by_level):
    members = [str(x) for x in (group.get("levels") or []) if str(x) in profiles]
    if len(members) < 2:
        return []
    buckets = defaultdict(list)
    for member in members:
        signature = _system_signature(
            family,
            profiles[member],
            level_rows.get(member),
            fixture_by_level.get(member, []),
            equipment_by_level.get(member, []),
        )
        if signature is None:
            continue
        buckets[repr(signature)].append(member)

    out = []
    for partition in buckets.values():
        if len(partition) < 2:
            continue
        whole_group = partition == members
        out.append({
            "name": str(group.get("name") or "Typical: " + " / ".join(members)) if whole_group
                    else f"{family} Typical: " + " / ".join(partition),
            "levels": partition,
            "confidence": "high",
            "basis": "system-specific architecture + normalized fixture/equipment placement + shaft evidence",
            "system_family": family,
            "parent_typical_group": str(group.get("name") or "Typical: " + " / ".join(members)),
            "partitioned": not whole_group,
            "version": SYSTEM_TYPICAL_VERSION,
        })
    return out


def build_system_typical_groups(auto):
    auto = auto or {}
    profiles = _profile_map(auto)
    level_rows = _architecture_level_map(auto)
    base_groups = [g for g in (auto.get("typical_groups") or []) if str(g.get("confidence") or "high") == "high"]
    fixture_by_level = _accepted_by_level(auto.get("fixture_detections") or [])
    equipment_by_level = _accepted_by_level(auto.get("equipment_detections") or [])
    output = {family: [] for family in FAMILY_TO_SYSTEM_KEY}

    for family in output:
        for group in base_groups:
            output[family].extend(_partition_group(
                family, group, profiles, level_rows, fixture_by_level, equipment_by_level
            ))
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
        scope["system_typical_version"] = SYSTEM_TYPICAL_VERSION
        return scope

    def make_family_system_typical(definition, key, levels, fallback_groups):
        active = _ACTIVE_GROUPS.get()
        if active is None:
            groups = fallback_groups
        else:
            # Once the system-specific policy is active, an empty family list
            # is authoritative and must NOT fall back to generic architecture
            # grouping. Missing system evidence therefore stays fail-closed.
            groups = active.get(key, [])
        return original_make_family(definition, key, levels, groups)

    def predict_system_typical(scope):
        token = _ACTIVE_GROUPS.set((scope or {}).get("system_typical_groups") or {})
        try:
            result = original_predict(scope)
            result["system_typical_groups_applied"] = {
                family: [dict(group) for group in groups]
                for family, groups in ((scope or {}).get("system_typical_groups") or {}).items()
            }
            result["system_typical_version"] = (scope or {}).get("system_typical_version") or SYSTEM_TYPICAL_VERSION
            return result
        finally:
            _ACTIVE_GROUPS.reset(token)

    planner_module._make_family = make_family_system_typical
    planner_module.predict_drawing_set = predict_system_typical
    workflow_module.build_scope = build_scope_system_typical
    # create_proposal resolves this imported global when called.
    workflow_module.predict_drawing_set = predict_system_typical
    workflow_module._system_typical_v1_installed = True
