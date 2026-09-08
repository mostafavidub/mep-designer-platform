"""Authority v14 equipment representation and Step 5 integrity contracts.

Equipment is not proven by a schedule tag alone.  Release-grade geometry must
carry finite coordinates, remain spatially non-degenerate inside its owning
source/level scope, and preserve explicit split-system indoor/outdoor evidence.
"""
from __future__ import annotations

from collections import defaultdict
import math

INDOOR_BLOCK = "ENGI_AC_INDOOR"
OUTDOOR_BLOCK = "ENGI_AC_OUTDOOR"
AIRFLOW_BLOCK = "ENGI_AC_AIRFLOW"

REQUIRED_SPLIT_FIELDS = {
    "tag", "odu_tag", "level", "sheet", "equipment_type", "mode",
    "capacity_status", "refrigerant_size_source",
    "condensate_nominal_diameter_mm", "condensate_min_slope_percent",
}


def _kind(row: dict) -> str:
    raw = row.get("kind") or row.get("type") or row.get("equipment_type") or ""
    value = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "indoor_split": "split_indoor", "indoor_unit": "split_indoor", "idu": "split_indoor",
        "outdoor_split": "split_outdoor", "outdoor_unit": "split_outdoor", "odu": "split_outdoor",
        "condensing_unit": "split_outdoor",
    }
    return aliases.get(value, value)


def _identity(row: dict):
    value = row.get("id") or row.get("tag") or row.get("equipment_id")
    return str(value) if value not in (None, "") else None


def _point(row: dict):
    value = row.get("point")
    if value is None and row.get("x") is not None and row.get("y") is not None:
        value = (row.get("x"), row.get("y"))
    try:
        x, y = float(value[0]), float(value[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return x, y
    except (TypeError, ValueError, IndexError):
        return None


def _scope(row: dict) -> tuple[str, str]:
    # A coordinate in another DXF/container is never evidence of collision in
    # this source.  Step 3 provenance is therefore the first partition key.
    source = str(row.get("source_file") or "__generated__")
    authority = row.get("level_authority_id") or row.get("plan_id") or row.get("level") or "__unscoped__"
    return source, str(authority)


def _tolerance(rows: list[dict], scope_bounds: dict | None) -> float:
    scope_bounds = scope_bounds or {}
    bounds = None
    for row in rows:
        key = row.get("plan_id") or row.get("level_authority_id") or row.get("level")
        candidate = scope_bounds.get(key)
        if candidate and len(candidate) == 4:
            bounds = candidate
            break
    if bounds:
        diagonal = math.hypot(float(bounds[2]) - float(bounds[0]), float(bounds[3]) - float(bounds[1]))
        return max(diagonal * 0.00015, 1e-6)
    points = [p for p in (_point(row) for row in rows) if p is not None]
    if len(points) > 1:
        diagonal = math.hypot(max(p[0] for p in points) - min(p[0] for p in points),
                             max(p[1] for p in points) - min(p[1] for p in points))
        return max(diagonal * 0.00015, 1e-6)
    return 1e-6


def _cluster_count(points: list[tuple[float, float]], tolerance: float) -> int:
    clusters: list[tuple[float, float]] = []
    for point in points:
        if not any(math.dist(point, existing) <= tolerance for existing in clusters):
            clusters.append(point)
    return len(clusters)


def validate_equipment_integrity(equipment: list[dict], *, scope_bounds: dict | None = None,
                                 require_split_pairs: bool = True) -> dict:
    """Validate physical equipment evidence without guessing missing geometry.

    Severe coordinate collapse is evaluated only inside the same source-file +
    level/plan authority scope, so identical coordinates in separate DXFs remain
    independent records.  For generated split systems, pairing must be explicit
    (`ODU.serves`, `IDU.odu_id` or `IDU.odu_tag`); nearest-neighbour guessing is
    intentionally forbidden.
    """
    rows = list(equipment or [])
    hard_errors: list[str] = []
    unresolved: list[str] = []

    identities = [_identity(row) for row in rows]
    seen: set[str] = set()
    for identity in identities:
        if not identity:
            continue
        if identity in seen:
            hard_errors.append(f"duplicate_equipment_id:{identity}")
        seen.add(identity)

    valid_points: dict[int, tuple[float, float]] = {}
    for index, row in enumerate(rows):
        point = _point(row)
        if point is None:
            unresolved.append(f"invalid_equipment_point:{_identity(row) or index + 1}")
        else:
            valid_points[index] = point

    groups: dict[tuple[str, str, str], list[tuple[int, dict]]] = defaultdict(list)
    for index, row in enumerate(rows):
        source, authority = _scope(row)
        groups[(source, authority, _kind(row))].append((index, row))

    collapsed_groups = []
    for key, members in groups.items():
        point_rows = [row for index, row in members if index in valid_points]
        points = [valid_points[index] for index, _row in members if index in valid_points]
        if len(points) < 4:
            continue
        tolerance = _tolerance(point_rows, scope_bounds)
        unique = _cluster_count(points, tolerance)
        if unique / len(points) < 0.5:
            source, authority, kind = key
            code = f"equipment_coordinate_collapse:{kind}:source={source}:authority={authority}:raw={len(points)}:unique={unique}"
            hard_errors.append(code)
            collapsed_groups.append({"source_file": source, "authority": authority, "kind": kind,
                                     "raw": len(points), "unique": unique, "tolerance": tolerance})

    indoors = [row for row in rows if _kind(row) == "split_indoor"]
    outdoors = [row for row in rows if _kind(row) == "split_outdoor"]
    indoor_ids = {_identity(row) for row in indoors if _identity(row)}

    if indoors and not outdoors:
        unresolved.append("split_outdoor_entity_required")

    for outdoor in outdoors:
        serves = outdoor.get("serves") or outdoor.get("indoor_id") or outdoor.get("idu_id")
        if serves and str(serves) not in indoor_ids:
            hard_errors.append(f"outdoor_serves_unknown_indoor:{_identity(outdoor) or 'UNKNOWN'}:{serves}")

    paired_outdoors: list[str] = []
    paired_count = 0
    if require_split_pairs and indoors:
        for indoor in indoors:
            indoor_id = _identity(indoor)
            if not indoor_id:
                unresolved.append("split_indoor_missing_identifier")
                continue
            requested_outdoor = indoor.get("odu_id") or indoor.get("odu_tag")
            candidates = []
            for outdoor in outdoors:
                outdoor_id = _identity(outdoor)
                tokens = {str(x) for x in (outdoor_id, outdoor.get("tag")) if x not in (None, "")}
                serves = outdoor.get("serves") or outdoor.get("indoor_id") or outdoor.get("idu_id")
                if (serves and str(serves) == indoor_id) or (requested_outdoor and str(requested_outdoor) in tokens):
                    candidates.append(outdoor)
            if not candidates:
                unresolved.append(f"split_pair_missing:{indoor_id}")
                continue
            if len(candidates) > 1:
                hard_errors.append(f"split_pair_ambiguous:{indoor_id}:{len(candidates)}")
                continue
            outdoor = candidates[0]
            outdoor_id = _identity(outdoor) or "UNKNOWN"
            paired_outdoors.append(outdoor_id)
            paired_count += 1
            indoor_point, outdoor_point = _point(indoor), _point(outdoor)
            if indoor_point is not None and outdoor_point is not None:
                tolerance = _tolerance([indoor, outdoor], scope_bounds)
                if math.dist(indoor_point, outdoor_point) <= tolerance:
                    hard_errors.append(f"split_pair_coincident:{indoor_id}:{outdoor_id}")

    if require_split_pairs:
        usage = {oid: paired_outdoors.count(oid) for oid in set(paired_outdoors)}
        for outdoor_id, count in usage.items():
            if count > 1:
                hard_errors.append(f"outdoor_shared_by_multiple_indoor:{outdoor_id}:{count}")

    if hard_errors:
        status = "FAIL"
    elif unresolved:
        status = "INPUT_REQUIRED"
    else:
        status = "PASS"
    return {
        "version": "equipment-integrity-v14.3",
        "status": status,
        "errors": sorted(set(hard_errors)),
        "missing_inputs": sorted(set(unresolved)),
        "metrics": {
            "equipment": len(rows), "split_indoor": len(indoors), "split_outdoor": len(outdoors),
            "paired_split_units": paired_count, "collapsed_groups": len(collapsed_groups),
            "invalid_points": len([x for x in unresolved if x.startswith("invalid_equipment_point:")]),
        },
        "collapsed_groups": collapsed_groups,
        "policy": "SOURCE_SCOPED_FAIL_CLOSED_NO_NEAREST_NEIGHBOUR_PAIR_GUESS",
    }


def validate_split_representation(units: list[dict], equipment_entities: list[dict] | None = None) -> dict:
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

    integrity = None
    if equipment_entities is not None:
        integrity = validate_equipment_integrity(equipment_entities, require_split_pairs=False)
        errors.extend(f"equipment_integrity:{code}" for code in integrity.get("errors") or [])
        errors.extend(f"equipment_integrity:{code}" for code in integrity.get("missing_inputs") or [])
        indoor_tokens, outdoor_tokens = set(), set()
        for row in equipment_entities:
            identity = _identity(row)
            tokens = {str(x) for x in (identity, row.get("tag")) if x not in (None, "")}
            if _kind(row) == "split_indoor":
                indoor_tokens.update(tokens)
            elif _kind(row) == "split_outdoor":
                outdoor_tokens.update(tokens)
        for unit in units:
            tag = unit.get("tag") or "UNKNOWN"
            if str(unit.get("tag")) not in indoor_tokens:
                errors.append(f"{tag}:tag_without_plan_indoor_entity")
            if str(unit.get("odu_tag")) not in outdoor_tokens:
                errors.append(f"{tag}:odu_tag_without_plan_outdoor_entity")

    result = {
        "version": "equipment-representation-contract-v14.3",
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(set(errors)),
        "metrics": {"units": len(units), "unique_ac_tags": len(set(tags)), "unique_odu_tags": len(set(odu_tags))},
    }
    if integrity is not None:
        result["equipment_integrity"] = integrity
    return result
