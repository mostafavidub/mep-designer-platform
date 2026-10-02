"""Deterministic Architecture Understanding Benchmark foundation."""
from __future__ import annotations

from shapely.geometry import Polygon

from .architecture_contract import SCHEMA, content_hash


TRUTH_SCHEMA = "planha-architecture-truth/1.0"
BENCHMARK_SCHEMA = "planha-architecture-benchmark-report/1.0"
COHORTS = {"DEVELOPMENT", "VALIDATION", "EVALUATION_HELD_OUT"}
HARD_GATE_FIELDS = ("false_authoritative_material_geometry", "false_portal_authority",
                    "false_access_edges", "false_void_authority", "illegal_space_overlap",
                    "cross_level_topology_errors", "unsupported_downstream_release")


def _polygons(rows, id_key):
    result = {}
    for row in rows or []:
        try:
            polygon = Polygon(row.get("polygon") or row.get("boundary") or [], row.get("interior_rings") or [])
        except Exception:
            continue
        if polygon.is_valid and polygon.area > 0:
            result[row.get(id_key)] = polygon
    return result


def _precision_recall(predicted, reviewed):
    predicted = set(predicted); reviewed = set(reviewed)
    matched = len(predicted & reviewed)
    return (matched / len(predicted) if predicted else 1.0,
            matched / len(reviewed) if reviewed else 1.0)


def compare_architecture(prediction, truth):
    if prediction.get("schema") != SCHEMA:
        raise ValueError("PREDICTION_SCHEMA_MISMATCH")
    if truth.get("schema") != TRUTH_SCHEMA:
        raise ValueError("TRUTH_SCHEMA_MISMATCH")
    cohort = truth.get("cohort")
    if cohort not in COHORTS:
        raise ValueError("TRUTH_COHORT_INVALID")
    if cohort == "EVALUATION_HELD_OUT" and not truth.get("blind_output_sealed"):
        raise ValueError("HELD_OUT_BLIND_OUTPUT_NOT_SEALED")
    pred_spaces = _polygons(prediction.get("physical_spaces"), "physical_space_id")
    true_spaces = _polygons(truth.get("physical_spaces"), "truth_space_id")
    ious = []
    for true_polygon in true_spaces.values():
        best = 0.0
        for pred_polygon in pred_spaces.values():
            union = true_polygon.union(pred_polygon).area
            best = max(best, true_polygon.intersection(pred_polygon).area / union if union else 0.0)
        ious.append(best)
    truth_portals = {(p.get("type"), p.get("host_wall_id"), p.get("host_aperture_id"))
                     for p in truth.get("portals") or [] if p.get("status") != "AMBIGUOUS"}
    pred_portals = {(p.get("type"), p.get("host_wall_id"), p.get("host_aperture_id"))
                    for p in prediction.get("portals") or [] if p.get("status") == "VERIFIED"}
    false_portals = pred_portals - truth_portals
    true_access = {(e.get("space_a"), e.get("space_b"), e.get("portal_id")) for e in truth.get("access_graph") or []}
    pred_access = {(e.get("space_a"), e.get("space_b"), e.get("portal_id"))
                   for e in (prediction.get("graphs") or {}).get("access") or []}
    truth_voids = _polygons(truth.get("voids"), "truth_void_id")
    pred_voids = _polygons(prediction.get("voids"), "void_id")
    false_voids = max(0, len(pred_voids) - len(truth_voids))
    pred_levels = {x.get("level_id") for x in prediction.get("levels") or []}
    true_levels = {x.get("level_id") for x in truth.get("levels") or []}
    level_precision, level_recall = _precision_recall(pred_levels, true_levels)
    pred_semantics = {x.get("category") for x in prediction.get("physical_spaces") or [] if x.get("category")}
    true_semantics = {x.get("category") for x in truth.get("physical_spaces") or [] if x.get("category")}
    semantic_precision, semantic_recall = _precision_recall(pred_semantics, true_semantics)
    pred_zones = {x.get("category") for x in prediction.get("functional_zones") or [] if x.get("category")}
    true_zones = {x.get("category") for x in truth.get("functional_zones") or [] if x.get("category")}
    zone_precision, zone_recall = _precision_recall(pred_zones, true_zones)
    pred_walls = {x.get("wall_id") for x in prediction.get("walls") or [] if x.get("wall_id")}
    true_walls = {x.get("wall_id") for x in truth.get("walls") or [] if x.get("wall_id")}
    _, wall_recall = _precision_recall(pred_walls, true_walls)
    pred_adjacency = {(x.get("space_a"), x.get("space_b")) for x in (prediction.get("graphs") or {}).get("adjacency") or []}
    true_adjacency = {(x.get("space_a"), x.get("space_b")) for x in truth.get("adjacency_graph") or []}
    pred_enclosure = {tuple(x) if isinstance(x, list) else (x.get("space_a"), x.get("space_b"))
                      for x in (prediction.get("graphs") or {}).get("enclosure") or []}
    true_enclosure = {tuple(x) if isinstance(x, list) else (x.get("space_a"), x.get("space_b"))
                      for x in truth.get("enclosure_graph") or []}
    space_overlap = 0.0
    pred_space_rows = prediction.get("physical_spaces") or []
    for index, left in enumerate(pred_space_rows):
        for right in pred_space_rows[index + 1:]:
            if left.get("frame_id") == right.get("frame_id"):
                lp = pred_spaces.get(left.get("physical_space_id")); rp = pred_spaces.get(right.get("physical_space_id"))
                if lp is not None and rp is not None:
                    space_overlap += lp.intersection(rp).area
    frame_by_space = {x.get("physical_space_id"): x.get("frame_id") for x in pred_space_rows}
    cross_level = sum(1 for p in prediction.get("portals") or []
                      if p.get("status") == "VERIFIED" and p.get("space_a") != "EXTERIOR" and
                      p.get("space_b") != "EXTERIOR" and
                      frame_by_space.get(p.get("space_a")) != frame_by_space.get(p.get("space_b")))
    hard = {field: 0 for field in HARD_GATE_FIELDS}
    hard["false_portal_authority"] = len(false_portals)
    hard["false_access_edges"] = len(pred_access - true_access)
    hard["false_void_authority"] = false_voids
    hard["false_authoritative_material_geometry"] = (len(pred_walls - true_walls) if true_walls else 0)
    hard["illegal_space_overlap"] = int(space_overlap > 1e-9)
    hard["cross_level_topology_errors"] = cross_level
    hard["unsupported_downstream_release"] = int(bool(prediction.get("release", {}).get("release_allowed")) and
                                                  truth.get("release_allowed") is not True)
    hard_pass = not any(hard.values())
    metrics = {"level_precision": level_precision, "level_recall": level_recall,
               "level_count_error": abs(len(prediction.get("levels") or []) - len(truth.get("levels") or [])),
               "physical_space_precision": min(1.0, len(true_spaces) / len(pred_spaces)) if pred_spaces else 0.0,
               "physical_space_recall": min(1.0, len(pred_spaces) / len(true_spaces)) if true_spaces else 1.0,
               "mean_space_iou": sum(ious) / len(ious) if ious else 1.0,
               "mean_space_area_error": (sum(abs(p.area - min((t.area for t in true_spaces.values()),
                                                               key=lambda area: abs(area - p.area), default=p.area))
                                                 for p in pred_spaces.values()) / len(pred_spaces) if pred_spaces else 0.0),
               "boundary_distance_metric": None,
               "space_semantic_precision": semantic_precision, "space_semantic_recall": semantic_recall,
               "functional_zone_precision": zone_precision, "functional_zone_recall": zone_recall,
               "relevant_wall_recall": wall_recall,
               "false_authoritative_wall_count": hard["false_authoritative_material_geometry"],
               "portal_precision": len(pred_portals & truth_portals) / len(pred_portals) if pred_portals else 1.0,
               "portal_recall": len(pred_portals & truth_portals) / len(truth_portals) if truth_portals else 1.0,
               "door_precision_recall": _precision_recall({x for x in pred_portals if x[0] == "DOOR"},
                                                            {x for x in truth_portals if x[0] == "DOOR"}),
               "window_precision_recall": _precision_recall({x for x in pred_portals if x[0] == "WINDOW"},
                                                              {x for x in truth_portals if x[0] == "WINDOW"}),
               "open_passage_precision_recall": _precision_recall({x for x in pred_portals if x[0] == "OPEN_PASSAGE"},
                                                                    {x for x in truth_portals if x[0] == "OPEN_PASSAGE"}),
               "void_precision": min(1.0, len(truth_voids) / len(pred_voids)) if pred_voids else 1.0,
               "void_recall": min(1.0, len(pred_voids) / len(truth_voids)) if truth_voids else 1.0,
               "false_void_count": false_voids,
               "adjacency_accuracy": 1.0 if pred_adjacency == true_adjacency else 0.0,
               "enclosure_accuracy": 1.0 if pred_enclosure == true_enclosure else 0.0,
               "access_accuracy": 1.0 if pred_access == true_access else 0.0,
               "false_authority_count": sum(hard.values()),
               "unsupported_geometry_authority_count": hard["false_authoritative_material_geometry"] + hard["false_void_authority"],
               "synthetic_access_count": hard["false_access_edges"],
               "unresolved_item_count": len(prediction.get("unresolved_items") or []),
               "human_review_item_count": len((prediction.get("review_registry") or {}).get("decisions") or []),
               "critical_review_item_count": sum(1 for x in prediction.get("unresolved_items") or []
                                                   if x.get("downstream_impact") == "BLOCKS_RELEASE"),
               "determinism_identity": prediction.get("canonical_model_hash")}
    identity = {"prediction_hash": prediction.get("canonical_model_hash"),
                "truth_hash": content_hash(truth), "hard_gates": hard, "metrics": metrics}
    return {"schema": BENCHMARK_SCHEMA, "status": "PASS" if hard_pass else "FAIL",
            "cohort": cohort, "hard_gates": hard, "hard_gates_pass": hard_pass,
            "critical_score_masking": False, "metrics": metrics,
            "report_hash": content_hash(identity)}
