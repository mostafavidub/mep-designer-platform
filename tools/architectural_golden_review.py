#!/usr/bin/env python3
"""Prediction export and deterministic topology helpers for Golden Review v2.

This module is deliberately downstream-only: it reads a canonical model and
never imports or invokes architectural reconstruction.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date

from shapely.geometry import LineString, Point, Polygon

METHOD = "HUMAN_CURATED_PREDICTION_ASSISTED_GOLDEN"
DISPOSITIONS = {"UNREVIEWED", "CORRECT", "WRONG", "EDITED", "UNSURE"}
SECTORS = tuple(f"R{row}C{col}" for row in range(1, 4) for col in range(1, 4))


def _stable(prefix: str, payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}-{hashlib.sha256(raw.encode()).hexdigest()[:12].upper()}"


def _closed(points: list) -> list:
    ring = [list(map(float, p[:2])) for p in points or []]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def export_proposals(model: dict, frame_id: str) -> dict:
    """Copy current canonical proposals without changing inference or geometry."""
    envelopes = [x for x in model.get("building_envelopes", []) if x.get("frame_id") == frame_id]
    spaces = [x for x in model.get("physical_spaces", []) if x.get("frame_id") == frame_id]
    space_ids = {x.get("physical_space_id") for x in spaces}
    openings = [x for x in model.get("openings", []) if x.get("frame_id") == frame_id or
                x.get("space_a") in space_ids or x.get("space_b") in space_ids]
    frame = next((x for x in model.get("frames", []) if x.get("frame_id") == frame_id), {})
    bounds = frame.get("bounds") or []
    def in_frame(row):
        point = row.get("point") or []
        return (len(bounds) == 4 and len(point) >= 2 and
                bounds[0] <= float(point[0]) <= bounds[2] and bounds[1] <= float(point[1]) <= bounds[3])
    labels = [x for x in model.get("label_bindings", [])
              if x.get("host_space_id") in space_ids or set(x.get("candidate_space_ids") or []).intersection(space_ids)
              or in_frame(x)]
    exported_spaces = []
    zones = model.get("functional_zones") or []
    for display_index, source in enumerate(spaces, 1):
        proposal_id = _stable("SPACE-PROP", [frame_id, source.get("physical_space_id")])
        ring = _closed(source.get("polygon") or [])
        try:
            polygon = Polygon(ring, source.get("interior_rings") or [])
            area = float(polygon.area)
            centroid = [float(polygon.centroid.x), float(polygon.centroid.y)]
            inside_labels = [deepcopy(x) for x in labels if x.get("point") and polygon.covers(Point(x["point"]))]
            nearby_labels = [deepcopy(x) for x in labels if x.get("point") and not polygon.covers(Point(x["point"]))
                             and polygon.boundary.distance(Point(x["point"])) <= max(polygon.length * .015, 0.05)]
        except (TypeError, ValueError):
            area, centroid, inside_labels, nearby_labels = None, None, [], []
        semantic_hints = [deepcopy(x) for x in zones if x.get("physical_space_id") == source.get("physical_space_id")]
        exported_spaces.append({
            "proposal_id": proposal_id, "review_item_id": proposal_id,
            "source_id": source.get("physical_space_id"),
            "source_candidate_id": source.get("physical_space_id"), "source_type": "CANONICAL_PHYSICAL_SPACE",
            "source_status": source.get("status"),
            "proposal_status": source.get("status"), "frame_id": frame_id,
            "source_handles": deepcopy(source.get("source_handles") or []),
            "engine_version": model.get("version"), "source_sha256": (model.get("source") or {}).get("source_sha256"),
            "display_index": display_index, "display_name_fa": f"فضای {display_index}",
            "polygon": ring, "original_geometry": deepcopy(ring),
            "final_geometry": None,
            "interior_rings": [_closed(x) for x in source.get("interior_rings") or []],
            "category": source.get("category") or "UNKNOWN",
            "display_name": source.get("display_name"),
            "area_drawing_units": area, "centroid": centroid,
            "exact_labels_inside": inside_labels, "exact_labels_near_boundary": nearby_labels,
            "semantic_hints": semantic_hints,
            "boundary_evidence_summary": f"{len(source.get('source_handles') or [])} منبع مرزی",
            "touching_portal_candidate_ids": [], "unresolved_issues": deepcopy(source.get("issues") or []),
            "evidence": deepcopy(source.get("evidence") or []),
            "disposition": "UNREVIEWED",
            "review_note": "",
        })
    exported_portals = []
    for source in openings:
        proposal_id = _stable("PORTAL-PROP", [frame_id, source.get("opening_id")])
        exported_portals.append({
            "proposal_id": proposal_id, "review_item_id": proposal_id,
            "source_id": source.get("opening_id"),
            "source_candidate_id": source.get("opening_id"), "source_type": "CANONICAL_PORTAL",
            "source_status": source.get("status"),
            "proposal_status": source.get("status"), "frame_id": frame_id,
            "source_handles": [x for x in [source.get("source_handle")] if x],
            "engine_version": model.get("version"), "source_sha256": (model.get("source") or {}).get("source_sha256"),
            "kind": source.get("kind") or "UNKNOWN",
            "point": deepcopy(source.get("point")),
            "opening_segment": deepcopy(source.get("opening_segment") or source.get("geometry") or []),
            "space_a": source.get("space_a"), "space_b": source.get("space_b"),
            "evidence": deepcopy(source.get("evidence") or []),
            "original_geometry": deepcopy(source.get("opening_segment") or source.get("geometry") or []),
            "final_geometry": None, "disposition": "UNREVIEWED", "review_note": "",
        })
    for row in exported_spaces:
        row["touching_portal_candidate_ids"] = [p["proposal_id"] for p in exported_portals
                                                  if row["source_id"] in {p.get("space_a"), p.get("space_b")}]
    envelope = envelopes[0] if envelopes else {}
    envelope_proposal = {
        "proposal_id": _stable("ENVELOPE-PROP", [frame_id, envelope.get("envelope_id")]),
        "review_item_id": _stable("ENVELOPE-PROP", [frame_id, envelope.get("envelope_id")]),
        "source_id": envelope.get("envelope_id"), "source_status": envelope.get("status"),
        "source_candidate_id": envelope.get("envelope_id"), "source_type": "CANONICAL_BUILDING_ENVELOPE",
        "proposal_status": envelope.get("status"), "frame_id": frame_id,
        "source_handles": deepcopy(envelope.get("source_handles") or []),
        "engine_version": model.get("version"), "source_sha256": (model.get("source") or {}).get("source_sha256"),
        "outer_ring": _closed(envelope.get("outer_ring") or envelope.get("polygon") or []),
        "original_geometry": _closed(envelope.get("outer_ring") or envelope.get("polygon") or []),
        "final_geometry": None,
        "interior_voids": [_closed(x) for x in envelope.get("interior_voids") or []],
        "evidence": deepcopy(envelope.get("evidence") or []),
        "disposition": "UNREVIEWED", "review_note": "",
    }
    return {
        "schema": "architectural-golden-proposals/1.0", "frame_id": frame_id,
        "authority": "REVIEW_INPUT_ONLY", "generated_without_new_inference": True,
        "building_envelope": envelope_proposal, "spaces": exported_spaces,
        "portals": exported_portals, "label_bindings": deepcopy(labels),
        "proposal_counts": {"envelopes": int(bool(envelope)), "spaces": len(exported_spaces),
                            "portals": len(exported_portals), "labels": len(labels)},
    }


def new_golden(*, case_id: str, source_sha256: str, frame_id: str, level: str,
               bounds: list[float], proposals: dict | None, build: dict | None = None) -> dict:
    proposals = proposals or {"building_envelope": {}, "spaces": [], "portals": [], "label_bindings": []}
    return {
        "schema": "architectural-topology-golden/1.0", "schema_version": "1.0", "case_id": case_id,
        "golden_id": _stable("GOLDEN", [case_id, source_sha256, frame_id]),
        "project_reference": case_id,
        "source_sha256": source_sha256, "review_status": "DRAFT",
        "annotation_status": "DRAFT",
        "annotation_method": METHOD if proposals.get("spaces") or proposals.get("portals") else "INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW",
        "review": {"method": METHOD if proposals.get("spaces") or proposals.get("portals") else "INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW",
                   "annotator": None, "annotation_date": None, "reviewer": None,
                   "reviewed_at": None, "approved_at": None,
                   "runtime_output_visible_during_annotation": bool(proposals.get("spaces") or proposals.get("portals")),
                   "independent_source_only_pass_completed": False},
        "frame": {"runtime_frame_id": frame_id, "level": level, "bounds": list(bounds)},
        "space_match_iou": .5, "build": build or {}, "proposals": deepcopy(proposals),
        "proposal_review_log": [], "human_added_items": [], "rejected_proposals": [],
        "unresolved_items": [], "approval": {"approved": False},
        "building_envelope": {"status": "UNKNOWN", "outer_ring": [], "interior_voids": []},
        "spaces": [], "functional_zones": [], "portals": [],
        "geometric_adjacency": [], "access_connectivity": [],
        "completeness": {"mode_completed": False, "sectors": {key: False for key in SECTORS},
                         "questions": {"missing_spaces": None, "missing_portals": None,
                                       "missing_voids": None, "source_labels_checked": None},
                         "unresolved_critical": []},
        "reviewer_completeness": {"completed": False, "sectors": {key: False for key in SECTORS},
                                  "unresolved_critical": []},
        "approval_gate": {"eligible": False, "errors": ["review_not_complete"]},
        "annotation_notes": ["Predictions are review input, never Golden truth.",
                             "UNKNOWN/UNSURE is preferred to guessing."],
    }


def regenerate_topology(golden: dict, tolerance: float = 1e-6) -> dict:
    """Regenerate adjacency and portal access; windows never create access."""
    rows = golden.get("spaces") or []
    polys = {}
    for row in rows:
        try:
            poly = Polygon(row.get("polygon") or [], row.get("interior_rings") or [])
            if poly.is_valid and not poly.is_empty and poly.area > 0:
                polys[row["golden_space_id"]] = poly
        except (TypeError, ValueError):
            continue
    edges = []
    ids = sorted(polys)
    for index, left in enumerate(ids):
        for right in ids[index + 1:]:
            shared = polys[left].boundary.intersection(polys[right].boundary)
            if not shared.is_empty and shared.length > tolerance:
                edges.append([left, right])
    access = []
    for portal in golden.get("portals") or []:
        if portal.get("status") != "VERIFIED" or portal.get("kind") not in {"door", "open_passage"}:
            continue
        a, b = portal.get("space_a"), portal.get("space_b")
        if a and b and a != b:
            access.append({"space_a": a, "space_b": b, "portal_id": portal.get("golden_portal_id")})
    golden["geometric_adjacency"] = edges
    golden["access_connectivity"] = access
    return golden


def approval_errors(golden: dict) -> list[str]:
    if golden.get("annotation_method") != METHOD and (golden.get("review") or {}).get("method") != METHOD:
        return []
    errors = []
    review = golden.get("review") or {}
    if not review.get("annotator"): errors.append("annotator_missing")
    if not review.get("reviewer"): errors.append("reviewer_missing")
    if review.get("annotator") and review.get("annotator") == review.get("reviewer"):
        errors.append("independent_reviewer_required")
    proposal_rows = [golden.get("proposals", {}).get("building_envelope", {})]
    proposal_rows += golden.get("proposals", {}).get("spaces", []) + golden.get("proposals", {}).get("portals", [])
    if any(row and row.get("disposition") not in DISPOSITIONS - {"UNREVIEWED"} for row in proposal_rows):
        errors.append("proposal_review_incomplete")
    complete = golden.get("completeness") or {}
    if not complete.get("mode_completed") or not all((complete.get("sectors") or {}).values()):
        errors.append("source_only_completeness_incomplete")
    if any(value is not False for value in (complete.get("questions") or {}).values()):
        errors.append("completeness_questions_unresolved")
    if complete.get("unresolved_critical"): errors.append("critical_issue_unresolved")
    reviewer = golden.get("reviewer_completeness") or {}
    if not reviewer.get("completed") or not all((reviewer.get("sectors") or {}).values()):
        errors.append("independent_completeness_incomplete")
    if reviewer.get("unresolved_critical"): errors.append("reviewer_critical_issue_unresolved")
    if not golden.get("spaces"): errors.append("approved_golden_requires_spaces")
    return sorted(set(errors))


def refresh_approval_gate(golden: dict) -> dict:
    errors = approval_errors(golden)
    golden["approval_gate"] = {"eligible": not errors, "errors": errors,
                               "checked_at": date.today().isoformat()}
    return golden
