"""Coordinate / Fixture / Equipment Isolation.

Binds every detected fixture/equipment to the architectural level authority that
owns its source file and coordinate frame. Cross-file coordinate coincidence is
never treated as evidence. If provenance is ambiguous, the assignment fails
closed instead of borrowing a level from another DXF.
"""
from collections import Counter
import math

ISOLATION_VERSION = "coordinate-isolation-v1"


def _as_point(row):
    try:
        return float(row.get("x")), float(row.get("y"))
    except (TypeError, ValueError):
        return None


def _inside(bounds, point):
    if not bounds or len(bounds) != 4 or point is None:
        return False
    try:
        return (
            float(bounds[0]) <= point[0] <= float(bounds[2])
            and float(bounds[1]) <= point[1] <= float(bounds[3])
        )
    except (TypeError, ValueError):
        return False


def _diag(level):
    bounds = level.get("region_bounds") or []
    try:
        return max(math.hypot(float(bounds[2]) - float(bounds[0]), float(bounds[3]) - float(bounds[1])), 1.0)
    except (TypeError, ValueError, IndexError):
        return 1.0


def _authority(level):
    return str(level.get("authority_id") or level.get("level_authority_id") or "").strip()


def _source_file(level):
    return str(level.get("source_file") or "").strip()


def _local_position(level, point):
    transform = level.get("local_transform") or {}
    translation = transform.get("translation") or []
    try:
        return [
            round(point[0] + float(translation[0]), 6),
            round(point[1] + float(translation[1]), 6),
        ]
    except (TypeError, ValueError, IndexError):
        title = level.get("title_point") or []
        try:
            return [round(point[0] - float(title[0]), 6), round(point[1] - float(title[1]), 6)]
        except (TypeError, ValueError, IndexError):
            return None


def _source_compatible_candidates(row, levels):
    """Return candidate levels plus whether the source boundary is trusted.

    A row with explicit source_file can never leave that file. Legacy rows that
    lack source_file are allowed only when the architecture itself contains a
    single file, or when source container evidence uniquely identifies one file.
    """
    row_file = str(row.get("source_file") or "").strip()
    if row_file:
        return [level for level in levels if _source_file(level) == row_file], True

    files = {value for value in (_source_file(level) for level in levels) if value}
    if len(files) <= 1:
        return list(levels), True

    source_type = str(row.get("source_type") or "").strip()
    source_name = str(row.get("source_name") or "").strip()
    if source_type or source_name:
        matched = [
            level for level in levels
            if (not source_type or str(level.get("source_type") or "") == source_type)
            and (not source_name or str(level.get("source_name") or "") == source_name)
        ]
        matched_files = {_source_file(level) for level in matched if _source_file(level)}
        if matched and len(matched_files) == 1:
            return matched, True
    return [], False


def _choose_level(row, levels):
    point = _as_point(row)
    if point is None or not levels:
        return None, "unassigned_missing_coordinate"

    explicit_authority = str(row.get("level_authority_id") or "").strip()
    if explicit_authority:
        exact = [level for level in levels if _authority(level) == explicit_authority]
        if len(exact) == 1:
            row_file = str(row.get("source_file") or "").strip()
            if not row_file or not _source_file(exact[0]) or _source_file(exact[0]) == row_file:
                return exact[0], "assigned_explicit_authority"
        return None, "unassigned_invalid_authority"

    candidates, source_trusted = _source_compatible_candidates(row, levels)
    if not source_trusted or not candidates:
        return None, "unassigned_ambiguous_source"

    source_type = str(row.get("source_type") or "").strip()
    source_name = str(row.get("source_name") or "").strip()
    container = [
        level for level in candidates
        if (not source_type or str(level.get("source_type") or "") == source_type)
        and (not source_name or str(level.get("source_name") or "") == source_name)
    ]
    if container:
        candidates = container

    hinted_name = str(row.get("level") or "").strip()
    if hinted_name:
        named = [level for level in candidates if str(level.get("name") or "") == hinted_name]
        if len(named) == 1:
            return named[0], "assigned_source_and_name"
        if len(named) > 1:
            candidates = named

    contained = [level for level in candidates if _inside(level.get("region_bounds"), point)]
    if len(contained) == 1:
        return contained[0], "assigned_region_containment"
    if len(contained) > 1:
        contained = sorted(contained, key=_diag)
        if _diag(contained[0]) < _diag(contained[1]) * 0.98:
            return contained[0], "assigned_smallest_containing_region"
        return None, "unassigned_overlapping_regions"

    titled = [level for level in candidates if level.get("title_point")]
    if not titled:
        return None, "unassigned_no_level_geometry"
    distances = sorted(
        ((math.dist(point, tuple(level["title_point"])), level) for level in titled),
        key=lambda item: item[0],
    )
    nearest_distance, nearest = distances[0]
    if len(distances) > 1 and abs(distances[1][0] - nearest_distance) <= max(1e-6, nearest_distance * 0.01):
        return None, "unassigned_equidistant_levels"
    # Preserve safe single-file legacy nearest-title behavior, but prevent an
    # unbounded jump across a plan sheet/frame.
    if nearest_distance <= max(_diag(nearest) * 1.5, 5.0):
        return nearest, "assigned_bounded_nearest_title"
    return None, "unassigned_outside_level_frame"


def _copy_with_file(rows, file_name):
    copied = []
    for raw in rows or []:
        row = dict(raw)
        if file_name:
            row.setdefault("source_file", file_name)
        copied.append(row)
    return copied


def isolate_detections(auto, analysis):
    auto = dict(auto or {})
    model = auto.get("architecture_model") or {}
    levels = list(model.get("levels") or [])

    fixtures = []
    equipment = []
    for file_info in (analysis or {}).get("files") or []:
        file_name = str(file_info.get("file") or "").strip()
        fixtures.extend(_copy_with_file(file_info.get("fixture_detections"), file_name))
        equipment.extend(_copy_with_file(file_info.get("equipment_detections"), file_name))

    # Backward compatibility for callers/tests that pass only auto detections.
    if not fixtures and auto.get("fixture_detections"):
        fixtures = [dict(row) for row in auto.get("fixture_detections") or []]
    if not equipment and auto.get("equipment_detections"):
        equipment = [dict(row) for row in auto.get("equipment_detections") or []]

    status_counts = Counter()
    for row in fixtures + equipment:
        level, status = _choose_level(row, levels)
        row["coordinate_isolation_status"] = status
        row["coordinate_isolation_version"] = ISOLATION_VERSION
        status_counts[status] += 1
        if level is None:
            row.pop("level_authority_id", None)
            # Do not retain a heuristic legacy level when the new authority
            # model cannot prove that assignment.
            row.pop("level", None)
            row.pop("level_local_position", None)
            continue
        point = _as_point(row)
        row["level"] = level.get("name")
        row["level_authority_id"] = _authority(level) or None
        row["source_file"] = str(row.get("source_file") or _source_file(level) or "") or None
        local = _local_position(level, point)
        if local is not None:
            row["level_local_position"] = local

    auto["fixture_detections"] = fixtures
    auto["equipment_detections"] = equipment
    auto["equipment"] = [row for row in equipment if row.get("status") == "detected"]
    auto["fixture_counts"] = dict(Counter(row.get("type") for row in fixtures if row.get("status") == "detected"))
    auto["equipment_counts"] = dict(Counter(row.get("type") for row in equipment if row.get("status") == "detected"))
    auto["fixture_blocks_detected"] = sum(auto["fixture_counts"].values())
    auto["equipment_detected"] = sum(auto["equipment_counts"].values())
    auto["coordinate_isolation"] = {
        "version": ISOLATION_VERSION,
        "status_counts": dict(status_counts),
        "unassigned_count": sum(count for status, count in status_counts.items() if status.startswith("unassigned_")),
    }
    diagnostics = list(auto.get("evidence_diagnostics") or [])
    if auto["coordinate_isolation"]["unassigned_count"]:
        code = f"coordinate_isolation_unassigned:{auto['coordinate_isolation']['unassigned_count']}"
        if code not in diagnostics:
            diagnostics.append(code)
    auto["evidence_diagnostics"] = diagnostics
    return auto


def install(main_auto_module):
    if getattr(main_auto_module, "_coordinate_isolation_installed", False):
        return
    base_infer = main_auto_module.infer_architecture_facts

    def infer(analysis, discipline):
        return isolate_detections(base_infer(analysis, discipline), analysis)

    main_auto_module.infer_architecture_facts = infer

    # Preserve provenance in PMM only when the provenance actually exists, so
    # legacy exact-shape consumers do not gain meaningless None-valued fields.
    from . import project_mechanical_model as pmm
    old_fixture_rows = pmm._fixture_rows

    def fixture_rows_isolated(auto):
        rows = old_fixture_rows(auto)
        detections = auto.get("fixture_detections") or []
        if len(rows) == len(detections):
            for row, detection in zip(rows, detections):
                for key in (
                    "source_file",
                    "level_authority_id",
                    "level_local_position",
                    "coordinate_isolation_status",
                ):
                    if detection.get(key) is not None:
                        row[key] = detection.get(key)
        return rows

    pmm._fixture_rows = fixture_rows_isolated
    main_auto_module._coordinate_isolation_installed = True
