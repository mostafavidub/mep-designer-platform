"""Mechanical Engineering v13 — reference-driven detailed drawing pipeline.

This module converts architectural analysis into a structured building model and
then incrementally enriches it through fixture recognition, system requirements,
calculations, topology, routing, sizing, annotation, details/schedules and final
sheet QA.  Each stage is deterministic and testable; later stages fail closed
when prerequisite evidence is missing.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Room:
    id: str
    level: str
    kind: str
    polygon: list[list[float]]
    doors: list[dict[str, Any]]
    fixtures: list[dict[str, Any]]
    nearest_shaft: str | None = None


def _as_xy(point: Any) -> list[float] | None:
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        try:
            return [float(point[0]), float(point[1])]
        except (TypeError, ValueError):
            return None
    return None


def _poly_centroid(poly: list[list[float]]) -> list[float] | None:
    if not poly:
        return None
    xs = [p[0] for p in poly if len(p) >= 2]
    ys = [p[1] for p in poly if len(p) >= 2]
    if not xs or not ys:
        return None
    return [sum(xs) / len(xs), sum(ys) / len(ys)]


def _dist(a: list[float], b: list[float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def reconstruct_architecture(analysis: dict[str, Any]) -> dict[str, Any]:
    """Create a level/room/shaft model from analyzer evidence.

    The function intentionally preserves evidence rather than inventing missing
    geometry.  Every room gets a stable ID, level, polygon, doors, fixtures and
    nearest shaft when one can be established from real coordinates.
    """
    analysis = analysis or {}
    levels_in = analysis.get("levels") or analysis.get("level_profiles") or []
    rooms_in = analysis.get("rooms") or []
    shafts_in = analysis.get("shafts") or []
    walls = list(analysis.get("walls") or [])
    doors = list(analysis.get("doors") or [])
    windows = list(analysis.get("windows") or [])
    columns = list(analysis.get("columns") or [])

    levels: list[dict[str, Any]] = []
    level_names: list[str] = []
    for idx, item in enumerate(levels_in, 1):
        if isinstance(item, str):
            name, payload = item, {}
        else:
            payload = dict(item or {})
            name = str(payload.get("name") or payload.get("level") or f"Level {idx}")
        if name not in level_names:
            level_names.append(name)
            levels.append({"name": name, "elevation": payload.get("elevation"), "source": payload})

    shafts: list[dict[str, Any]] = []
    for idx, shaft in enumerate(shafts_in, 1):
        row = dict(shaft or {})
        point = _as_xy(row.get("point") or row.get("center") or row.get("centroid"))
        if point is None and row.get("polygon"):
            polygon = [_as_xy(p) for p in row.get("polygon") or []]
            point = _poly_centroid([p for p in polygon if p])
        shafts.append({"id": str(row.get("id") or f"SHAFT-{idx:02d}"), "level": row.get("level"), "point": point, "source": row})

    rooms: list[dict[str, Any]] = []
    for idx, raw in enumerate(rooms_in, 1):
        row = dict(raw or {})
        level = str(row.get("level") or row.get("floor") or (level_names[0] if len(level_names) == 1 else ""))
        kind = str(row.get("type") or row.get("kind") or row.get("name") or "unknown").lower()
        polygon = [_as_xy(p) for p in row.get("polygon") or row.get("vertices") or []]
        polygon = [p for p in polygon if p]
        room_doors = list(row.get("doors") or [])
        room_fixtures = list(row.get("fixtures") or [])
        centroid = _poly_centroid(polygon) or _as_xy(row.get("center"))
        nearest = None
        if centroid:
            candidates = [s for s in shafts if s.get("point") and (not s.get("level") or not level or str(s.get("level")) == level)]
            if candidates:
                nearest = min(candidates, key=lambda s: _dist(centroid, s["point"]))["id"]
        room = Room(
            id=str(row.get("id") or f"ROOM-{idx:03d}"),
            level=level,
            kind=kind,
            polygon=polygon,
            doors=room_doors,
            fixtures=room_fixtures,
            nearest_shaft=nearest,
        )
        rooms.append(asdict(room))

    return {
        "schema_version": "13.1",
        "levels": levels,
        "rooms": rooms,
        "shafts": shafts,
        "walls": walls,
        "doors": doors,
        "windows": windows,
        "columns": columns,
        "roof": dict(analysis.get("roof") or {}),
        "evidence_complete": bool(levels and rooms),
        "diagnostics": [] if levels and rooms else ["architecture_model_missing_levels_or_rooms"],
    }
