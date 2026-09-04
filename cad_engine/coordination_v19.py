"""Fail-closed structural/RCP coordination and 2.5D routing (v19).

Coordinates are metres in a common project datum.  The engine intentionally
does not infer structural or reflected-ceiling geometry from architecture.
Missing authoritative inputs produce INPUT_REQUIRED, never CLASH_FREE.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import math
from typing import Iterable


REQUIRED_KINDS = {"slab", "ceiling"}
OBSTACLE_KINDS = {"beam", "column", "slab", "forbidden_zone"}


@dataclass(frozen=True)
class Box:
    id: str
    kind: str
    level_id: str
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float
    source_id: str

    def __post_init__(self):
        if not self.source_id:
            raise ValueError("authoritative source_id is required")
        if self.kind not in {"beam", "column", "slab", "ceiling", "shaft", "service_zone", "forbidden_zone"}:
            raise ValueError(f"unsupported coordination kind: {self.kind}")
        if self.xmin >= self.xmax or self.ymin >= self.ymax or self.zmin >= self.zmax:
            raise ValueError(f"invalid 3D bounds: {self.id}")

    def expanded(self, clearance: float) -> "Box":
        return Box(self.id, self.kind, self.level_id, self.xmin-clearance,
                   self.ymin-clearance, self.zmin-clearance,
                   self.xmax+clearance, self.ymax+clearance,
                   self.zmax+clearance, self.source_id)


def _point_in_box(point: tuple[float, float, float], box: Box) -> bool:
    x, y, z = point
    return box.xmin <= x <= box.xmax and box.ymin <= y <= box.ymax and box.zmin <= z <= box.zmax


def _segment_samples(a: tuple[float, float, float], b: tuple[float, float, float], step: float = .05):
    length = math.dist(a, b)
    count = max(1, math.ceil(length / step))
    for i in range(count + 1):
        t = i / count
        yield tuple(a[j] + (b[j] - a[j]) * t for j in range(3))


def _polyline_length(points: list[tuple[float, float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def build_coordination_model(project: dict) -> dict:
    """Normalize only supplied, provenance-bearing Structural/RCP geometry."""
    raw = project.get("coordination_inputs") or {}
    documents = raw.get("documents") or []
    entities = raw.get("entities") or []
    missing = []
    doc_types = {d.get("type") for d in documents if d.get("sha256") and d.get("revision")}
    if "STRUCTURAL" not in doc_types:
        missing.append("STRUCTURAL_MODEL")
    if "RCP" not in doc_types:
        missing.append("RCP_MODEL")
    boxes = []
    errors = []
    for item in entities:
        try:
            boxes.append(Box(**item))
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
    kinds = {b.kind for b in boxes}
    for required in REQUIRED_KINDS - kinds:
        missing.append(required.upper())
    levels = sorted({b.level_id for b in boxes})
    status = "PASS" if not missing and not errors else ("FAIL" if errors else "INPUT_REQUIRED")
    return {
        "schema": "coordination-model/1.0",
        "status": status,
        "documents": documents,
        "entities": [asdict(b) for b in boxes],
        "levels": levels,
        "missing_inputs": sorted(set(missing)),
        "errors": errors,
        "claim": "COORDINATED" if status == "PASS" else "NOT_COORDINATED",
    }


def _candidate_paths(start, end, elevations: Iterable[float]):
    sx, sy, sz = start
    ex, ey, ez = end
    for index, z in enumerate(sorted(set(float(x) for x in elevations))):
        # Two orthogonal alternatives at every permitted service elevation.
        yield {"id": f"C{index+1:02d}A", "points": [(sx, sy, sz), (sx, sy, z), (ex, sy, z), (ex, ey, z), (ex, ey, ez)]}
        yield {"id": f"C{index+1:02d}B", "points": [(sx, sy, sz), (sx, sy, z), (sx, ey, z), (ex, ey, z), (ex, ey, ez)]}


def _clashes(points, boxes, clearance):
    hits = set()
    expanded = [(box, box.expanded(clearance)) for box in boxes if box.kind in OBSTACLE_KINDS]
    for a, b in zip(points, points[1:]):
        for point in _segment_samples(a, b):
            for original, volume in expanded:
                if _point_in_box(point, volume):
                    hits.add(original.id)
    return sorted(hits)


def _penetrations(points, boxes):
    penetrations = []
    for box in boxes:
        if box.kind not in {"beam", "slab"}:
            continue
        for a, b in zip(points, points[1:]):
            samples = list(_segment_samples(a, b))
            if any(_point_in_box(p, box) for p in samples):
                penetrations.append({
                    "id": f"PEN-{box.id}", "host_id": box.id,
                    "host_kind": box.kind, "status": "STRUCTURAL_APPROVAL_REQUIRED",
                    "geometry": {"center": list(samples[len(samples)//2]), "shape": "ROUND"},
                })
                break
    return penetrations


def route_25d(request: dict, coordination_model: dict) -> dict:
    if coordination_model.get("status") != "PASS":
        return {"status": "INPUT_REQUIRED", "claim": "NOT_ROUTED", "candidates": [],
                "selected": None, "warnings": [],
                "missing_inputs": coordination_model.get("missing_inputs", [])}
    level_id = request["level_id"]
    boxes = [Box(**x) for x in coordination_model["entities"] if x["level_id"] == level_id]
    elevations = request.get("allowed_elevations") or []
    if not elevations:
        return {"status": "INPUT_REQUIRED", "claim": "NOT_ROUTED", "candidates": [],
                "selected": None, "warnings": [], "missing_inputs": ["ALLOWED_SERVICE_ELEVATIONS"]}
    clearance = float(request.get("clearance_m", .05))
    candidates = []
    for candidate in _candidate_paths(tuple(request["start"]), tuple(request["end"]), elevations):
        points = candidate["points"]
        hits = _clashes(points, boxes, clearance)
        penetrations = _penetrations(points, boxes)
        horizontal = sum(math.dist(a[:2], b[:2]) for a, b in zip(points, points[1:]))
        fall = float(request.get("required_slope", 0)) * horizontal
        available_fall = max(0.0, points[0][2] - points[-1][2])
        slope_ok = request.get("system") not in {"sanitary", "rainwater"} or available_fall + 1e-9 >= fall
        candidate.update({
            "points": [list(p) for p in points], "length_m": round(_polyline_length(points), 4),
            "clashes": hits, "penetrations": penetrations, "slope_ok": slope_ok,
            "score": round(_polyline_length(points) + 1000*len(hits) + 100*len(penetrations) + (0 if slope_ok else 10000), 4),
            "status": "PASS" if not hits and not penetrations and slope_ok else "FAIL",
        })
        candidates.append(candidate)
    passing = [c for c in candidates if c["status"] == "PASS"]
    selected = min(passing, key=lambda c: (c["score"], c["id"])) if passing else None
    return {
        "status": "PASS" if selected else "FAIL", "claim": "COORDINATED_ROUTE" if selected else "NO_VALID_ROUTE",
        "candidates": candidates, "selected": selected, "warnings": [],
        "penetration_entities": [p for c in candidates for p in c["penetrations"]],
        "qa": {"zero_warnings": bool(selected) and not any(c["status"] == "PASS" and c["clashes"] for c in candidates)},
    }


def stable_hash(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
