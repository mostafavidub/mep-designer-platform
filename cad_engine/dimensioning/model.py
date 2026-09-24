"""Shared contracts for autonomous architectural dimensioning."""
from __future__ import annotations

PURPOSES = {
    "PROPERTY", "SETBACK", "BUILDING_OVERALL", "GRID", "STRUCTURAL_SETOUT",
    "WALL_SETOUT", "ROOM_CLEAR", "SHAFT", "STAIR_CORE", "OPENING",
    "CODE_CLEARANCE", "LOCAL_CONSTRUCTION", "CHECK",
}

SUBFEATURES = {
    "OUTER_FACE", "INNER_FACE", "FINISH_FACE", "CORE_FACE", "CENTERLINE",
    "GRID_AXIS", "COLUMN_CENTER", "OPENING_JAMB_LEFT", "OPENING_JAMB_RIGHT",
    "OPENING_CENTER", "SHAFT_FACE", "STAIR_EDGE", "LANDING_EDGE",
    "PROPERTY_EDGE",
}

DRAWING_PROFILES = {
    "ARCHITECTURAL_FLOOR_PLAN", "SITE_PLAN", "PARKING_PLAN", "ROOF_PLAN",
    "OPENING_LINTEL_PLAN", "FURNITURE_PLAN",
}

REFERENCE_CLASSES = {
    "FINISH_FACE": "FINISH",
    "OUTER_FACE": "FINISH",
    "INNER_FACE": "FINISH",
    "CORE_FACE": "CORE",
    "CENTERLINE": "CENTERLINE",
    "GRID_AXIS": "GRID",
    "COLUMN_CENTER": "GRID",
    "OPENING_JAMB_LEFT": "OPENING",
    "OPENING_JAMB_RIGHT": "OPENING",
    "OPENING_CENTER": "OPENING",
    "SHAFT_FACE": "SHAFT_CLEAR",
    "STAIR_EDGE": "STAIR",
    "LANDING_EDGE": "STAIR",
    "PROPERTY_EDGE": "PROPERTY",
}


def reference_class(ref: dict | None) -> str:
    ref = ref or {}
    return str(ref.get("reference_class") or REFERENCE_CLASSES.get(ref.get("subfeature"), ref.get("kind") or "UNKNOWN"))


def intent(
    intent_id: str,
    purpose: str,
    reference_a: dict,
    reference_b: dict,
    p1,
    p2,
    *,
    required: bool = True,
    source_kind: str = "PLANHA_GENERATED",
    priority: int = 50,
    chain_id: str | None = None,
    check_group_id: str | None = None,
    coordinate_frame_id: str | None = None,
    zone_id: str | None = None,
    rule_id: str | None = None,
    tier: int | None = None,
    metadata: dict | None = None,
) -> dict:
    import math
    purpose = str(purpose or "").upper()
    if purpose not in PURPOSES:
        raise ValueError("unsupported dimension purpose: " + purpose)
    p1 = (float(p1[0]), float(p1[1])); p2 = (float(p2[0]), float(p2[1]))
    measured = math.dist(p1, p2)
    return {
        "id": str(intent_id),
        "purpose": purpose,
        "reference_a": dict(reference_a or {}),
        "reference_b": dict(reference_b or {}),
        "world_p1": p1,
        "world_p2": p2,
        "measured_value": measured,
        "displayed_value": _display(measured),
        "required": bool(required),
        "source_kind": source_kind,
        "priority": int(priority),
        "chain_id": chain_id,
        "check_group_id": check_group_id,
        "coordinate_frame_id": coordinate_frame_id,
        "zone_id": zone_id,
        "governance_rule_id": rule_id,
        "tier": tier,
        "qa_status": "PENDING",
        "metadata": dict(metadata or {}),
        "angle_deg": math.degrees(math.atan2(p2[1]-p1[1], p2[0]-p1[0])),
    }


def _display(value: float) -> str:
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"
