"""Source-backed structural-obstacle identity without wall or release authority."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math

from shapely.geometry import Polygon


SCHEMA = "planha-structural-obstacle/1.0"


def _canonical_ring(points):
    """Return an orientation/start-point invariant open polygon ring."""
    ring = [[float(point[0]), float(point[1])] for point in points or []]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3 or any(not math.isfinite(value) for point in ring for value in point):
        return None
    variants = []
    for candidate in (ring, list(reversed(ring))):
        for index in range(len(candidate)):
            variants.append(candidate[index:] + candidate[:index])
    return min(variants, key=lambda row: json.dumps(row, separators=(",", ":")))


def _fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(raw.encode("utf-8")).hexdigest()


def project_structural_obstacles(source_role_diagnostics, frames, source_sha256):
    """Project already-qualified columns; never recognize or invent geometry here."""
    frame_by_id = {row.get("frame_id"): row for row in frames or []}
    rows = []
    for diagnostic in (source_role_diagnostics or {}).get("items") or []:
        if diagnostic.get("object_class") != "COLUMN":
            continue
        footprint = _canonical_ring(diagnostic.get("geometry"))
        if footprint is None:
            continue
        polygon = Polygon(footprint)
        if not diagnostic.get("closed") or not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
            continue
        frame_ids = diagnostic.get("frame_ids") or []
        frame_id = frame_ids[0] if len(frame_ids) == 1 else None
        frame = frame_by_id.get(frame_id) or {}
        occurrence_identity = {
            "source_sha256": source_sha256,
            "source_occurrence_id": diagnostic.get("source_occurrence_id"),
            "source_handle": diagnostic.get("source_handle"),
            "source_block_path": diagnostic.get("source_block_path") or [],
            "source_insert_handle": diagnostic.get("source_insert_handle"),
            "source_transform": diagnostic.get("source_transform"),
            "world_footprint": footprint,
        }
        geometry_fingerprint = "COL-GEO-" + _fingerprint(footprint)[:20].upper()
        column_id = "COLUMN-" + _fingerprint(occurrence_identity)[:20].upper()
        rows.append({
            "structural_obstacle_id": column_id,
            "obstacle_type": "COLUMN",
            "frame_id": frame_id,
            "level_id": frame.get("level_candidate") if frame_id else None,
            "footprint": footprint,
            "world_coordinates": deepcopy(footprint),
            "source_handle": diagnostic.get("source_handle"),
            "source_occurrence_id": diagnostic.get("source_occurrence_id"),
            "entity_type": diagnostic.get("entity_type"),
            "source_layer": diagnostic.get("source_layer"),
            "source_block": diagnostic.get("source_block"),
            "source_block_path": deepcopy(diagnostic.get("source_block_path") or []),
            "source_insert_handle": diagnostic.get("source_insert_handle"),
            "source_transform": deepcopy(diagnostic.get("source_transform")),
            "source_geometry_fingerprint": geometry_fingerprint,
            "source_classification_evidence": deepcopy(diagnostic.get("evidence") or []),
            "geometry_qualification": "SOURCE_BACKED",
            "obstacle_classification": "OBSTACLE_EVIDENCE_ONLY",
            "source_lineage": occurrence_identity,
            "authority": {
                "status": "SUPPORTED",
                "origins": ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                "material_geometry": False,
                "wall": False,
                "portal": False,
                "access": False,
                "routing": False,
                "release": False,
                "envelope": False,
            },
        })
    return {"schema": SCHEMA, "items": sorted(rows, key=lambda row: row["structural_obstacle_id"]),
            "legacy_projection_enabled": False, "envelope_authority": "NONE",
            "routing_authority": "NONE"}
