"""Fail-closed architecture space and equipment recognition acceptance."""
from __future__ import annotations

from hashlib import sha256
import json


CONTRACT_VERSION = "architecture-space-equipment-recognition/1"
CONTROL_WEIGHTS = {
    "immutable_source_identity": 4, "units_scale_orientation_bounds": 5,
    "deterministic_frame_separation": 7, "level_view_binding": 5,
    "wall_geometry_reconstruction": 6, "opening_vertical_obstruction_typing": 5,
    "closed_space_boundaries": 8, "multilingual_label_binding": 6,
    "space_use_classification": 7, "shaft_wet_core_recognition": 6,
    "multi_signal_object_recognition": 6, "object_status_confidence": 5,
    "object_type_orientation": 5, "host_and_port_binding": 6,
    "view_aware_deduplication": 4, "semantic_spatial_consistency": 5,
    "frame_visual_overlay_qa": 5, "exact_source_reopen_and_completeness": 5,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100


def _stable(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def _confidence(value):
    try:
        return 0 < float(value) <= 1
    except (TypeError, ValueError):
        return False


def exact_architecture_source_evidence(path, expected_sha256=None):
    try:
        import ezdxf
        raw = path.read_bytes(); actual = sha256(raw).hexdigest()
        doc = ezdxf.readfile(str(path))
        return {"reopened": True, "sha256": actual, "hash_matches": expected_sha256 in (None, actual),
                "modelspace_entities": len(doc.modelspace())}
    except Exception as exc:
        return {"reopened": False, "sha256": "", "hash_matches": False,
                "modelspace_entities": 0, "error": type(exc).__name__}


def evaluate_architecture_space_equipment(context, exact_source=None):
    context = context or {}; exact_source = exact_source or {}
    missing = {key: [] for key in CONTROL_WEIGHTS}; errors = {key: [] for key in CONTROL_WEIGHTS}

    identity = context.get("source_identity") or {}
    if len(str(identity.get("sha256") or "")) != 64 or not identity.get("approved_revision"):
        missing["immutable_source_identity"].append("APPROVED_ARCHITECTURE_SHA256_REQUIRED")
    elif identity.get("mechanical_reference_used") is True:
        errors["immutable_source_identity"].append("MECHANICAL_REFERENCE_INPUT_FORBIDDEN")

    calibration = context.get("calibration") or {}
    for key in ("units", "scale", "north", "origin", "valid_bounds"):
        if calibration.get(key) in (None, "", "UNKNOWN"):
            missing["units_scale_orientation_bounds"].append("CALIBRATION_REQUIRED:" + key)

    frames = context.get("frames") or []
    if not frames:
        missing["deterministic_frame_separation"].append("FRAME_INVENTORY_REQUIRED")
    elif any(row.get("type") not in {"PLAN", "ROOF_PLAN", "SECTION", "ELEVATION", "DETAIL", "SCHEDULE"}
             or row.get("ambiguous") for row in frames):
        errors["deterministic_frame_separation"].append("UNCLASSIFIED_OR_AMBIGUOUS_FRAME")

    plan_frames = [row for row in frames if row.get("type") in {"PLAN", "ROOF_PLAN"}]
    if any(not row.get("level_id") or not row.get("view_id") for row in plan_frames):
        errors["level_view_binding"].append("PLAN_LEVEL_VIEW_BINDING_FAILED")
    if not plan_frames:
        missing["level_view_binding"].append("ARCHITECTURAL_PLAN_REQUIRED")

    geometry = context.get("geometry") or {}
    if not geometry:
        missing["wall_geometry_reconstruction"].append("ARCHITECTURAL_GEOMETRY_REQUIRED")
    elif not geometry.get("wall_ids") or geometry.get("open_wall_chains"):
        errors["wall_geometry_reconstruction"].append("WALL_RECONSTRUCTION_INCOMPLETE")
    for key in ("opening_ids", "door_ids", "window_ids", "column_ids", "stair_ids", "elevator_ids", "obstruction_ids"):
        if key not in geometry:
            missing["opening_vertical_obstruction_typing"].append("GEOMETRY_INVENTORY_REQUIRED:" + key)

    spaces = context.get("spaces") or []
    if not spaces:
        missing["closed_space_boundaries"].append("SPACE_INVENTORY_REQUIRED")
    for room in spaces:
        rid = str(room.get("id"))
        if not room.get("closed_boundary") or not room.get("polygon") or not room.get("level_id"):
            errors["closed_space_boundaries"].append("OPEN_OR_UNBOUND_SPACE:" + rid)
        if not room.get("label") or not room.get("label_source") or room.get("label_inside") is not True:
            errors["multilingual_label_binding"].append("SPACE_LABEL_BINDING_FAILED:" + rid)
        if not room.get("use") or not _confidence(room.get("classification_confidence")):
            errors["space_use_classification"].append("SPACE_USE_UNCLASSIFIED:" + rid)
        for key in ("area_m2", "height_m", "centroid", "entrance_ids", "adjacent_space_ids"):
            if room.get(key) is None:
                missing["exact_source_reopen_and_completeness"].append(f"SPACE_FIELD:{rid}:{key}")

    verticals = context.get("vertical_spaces")
    if verticals is None:
        missing["shaft_wet_core_recognition"].append("SHAFT_WET_CORE_INVENTORY_REQUIRED")
    elif any(not row.get("id") or not row.get("kind") or not row.get("level_ids") or not row.get("evidence") for row in verticals):
        errors["shaft_wet_core_recognition"].append("UNTYPED_VERTICAL_SPACE")

    objects = context.get("objects") or []
    if context.get("object_inventory_complete") is not True:
        missing["multi_signal_object_recognition"].append("COMPLETE_OBJECT_INVENTORY_REQUIRED")
    for item in objects:
        oid = str(item.get("id"))
        if not item.get("evidence") or not set(item.get("evidence") or []).intersection({"block", "geometry", "layer", "text", "spatial_relation"}):
            errors["multi_signal_object_recognition"].append("OBJECT_EVIDENCE_MISSING:" + oid)
        if item.get("status") not in {"EXISTING", "PROPOSED", "NOT_EQUIPMENT"} or not _confidence(item.get("confidence")):
            errors["object_status_confidence"].append("OBJECT_STATUS_OR_CONFIDENCE_INVALID:" + oid)
        if item.get("status") != "NOT_EQUIPMENT":
            if not item.get("type") or item.get("orientation") is None:
                errors["object_type_orientation"].append("OBJECT_TYPE_ORIENTATION_REQUIRED:" + oid)
            if not item.get("level_id") or not item.get("space_id") or item.get("inside_host") is not True or item.get("point") is None or item.get("ports") is None:
                errors["host_and_port_binding"].append("OBJECT_HOST_PORT_BINDING_FAILED:" + oid)

    duplicate = context.get("deduplication") or {}
    if not duplicate:
        missing["view_aware_deduplication"].append("DEDUPLICATION_EVIDENCE_REQUIRED")
    elif duplicate.get("status") != "PASS" or duplicate.get("false_merges") or duplicate.get("remaining_duplicates"):
        errors["view_aware_deduplication"].append("VIEW_AWARE_DEDUPLICATION_FAILED")
    consistency = context.get("semantic_consistency") or {}
    if not consistency:
        missing["semantic_spatial_consistency"].append("SEMANTIC_CONSISTENCY_EVIDENCE_REQUIRED")
    elif consistency.get("status") != "PASS" or consistency.get("outside_space") or consistency.get("inside_wall") or consistency.get("wrong_level"):
        errors["semantic_spatial_consistency"].append("SEMANTIC_SPATIAL_CONSISTENCY_FAILED")
    visual = context.get("visual_overlay_qa") or {}
    if not visual:
        missing["frame_visual_overlay_qa"].append("FRAME_OVERLAY_QA_REQUIRED")
    elif visual.get("status") != "PASS" or set(visual.get("frame_ids") or []) != {row.get("id") for row in plan_frames} or visual.get("critical_defects"):
        errors["frame_visual_overlay_qa"].append("FRAME_OVERLAY_QA_NOT_PASS")

    expected_hash = identity.get("sha256")
    if not exact_source:
        missing["exact_source_reopen_and_completeness"].append("EXACT_SOURCE_REOPEN_REQUIRED")
    elif exact_source.get("reopened") is not True or exact_source.get("hash_matches") is not True or exact_source.get("sha256") != expected_hash:
        errors["exact_source_reopen_and_completeness"].append("EXACT_SOURCE_IDENTITY_FAILED")

    controls=[]
    for name, weight in CONTROL_WEIGHTS.items():
        status="FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
        controls.append({"id":name,"weight":weight,"status":status,"errors":errors[name],"missing_inputs":missing[name]})
    score=sum(row["weight"] for row in controls if row["status"]=="PASS")
    status="FAIL" if any(row["status"]=="FAIL" for row in controls) else ("INPUT_REQUIRED" if any(row["status"]=="INPUT_REQUIRED" for row in controls) else "PASS")
    return {"contract":CONTRACT_VERSION,"status":status,"score":score,"controls":controls,
            "all_controls_pass":all(row["status"]=="PASS" for row in controls),
            "release_allowed":status=="PASS" and score==100,
            "errors":sorted({x for row in controls for x in row["errors"]}),
            "missing_inputs":sorted({x for row in controls for x in row["missing_inputs"]}),
            "evidence_hash":_stable({"context":context,"exact_source":exact_source})}
