"""Drawing-profile-specific architectural dimension requirements."""
from __future__ import annotations

PROFILE_REQUIREMENTS = {
    "ARCHITECTURAL_FLOOR_PLAN": {
        "BUILDING_OVERALL", "GRID", "WALL_SETOUT", "ROOM_CLEAR",
        "STAIR_CORE", "SHAFT", "OPENING", "CODE_CLEARANCE", "CHECK",
    },
    "SITE_PLAN": {"PROPERTY", "BUILDING_OVERALL", "SETBACK", "CODE_CLEARANCE", "CHECK"},
    "PARKING_PLAN": {
        "BUILDING_OVERALL", "GRID", "STRUCTURAL_SETOUT", "STAIR_CORE",
        "SHAFT", "CODE_CLEARANCE", "LOCAL_CONSTRUCTION", "CHECK",
    },
    "ROOF_PLAN": {"BUILDING_OVERALL", "GRID", "STAIR_CORE", "SHAFT", "LOCAL_CONSTRUCTION"},
    "OPENING_LINTEL_PLAN": {"OPENING", "STRUCTURAL_SETOUT", "LOCAL_CONSTRUCTION"},
    "FURNITURE_PLAN": {"BUILDING_OVERALL", "LOCAL_CONSTRUCTION"},
}

MANDATORY_BY_PROFILE = {
    "ARCHITECTURAL_FLOOR_PLAN": {"BUILDING_OVERALL"},
    "SITE_PLAN": {"PROPERTY", "SETBACK"},
    "PARKING_PLAN": {"BUILDING_OVERALL"},
    "ROOF_PLAN": {"BUILDING_OVERALL"},
    "OPENING_LINTEL_PLAN": {"OPENING"},
    "FURNITURE_PLAN": set(),
}


def normalize_profile(value: str) -> str:
    aliases = {
        "ARCHITECTURAL_PLAN": "ARCHITECTURAL_FLOOR_PLAN",
        "ARCHITECTURE": "ARCHITECTURAL_FLOOR_PLAN",
        "FLOOR_PLAN": "ARCHITECTURAL_FLOOR_PLAN",
        "SITE": "SITE_PLAN",
        "PARKING": "PARKING_PLAN",
        "ROOF": "ROOF_PLAN",
        "OPENING": "OPENING_LINTEL_PLAN",
        "LINTEL": "OPENING_LINTEL_PLAN",
        "FURNITURE": "FURNITURE_PLAN",
    }
    key = str(value or "").upper().strip()
    return aliases.get(key, key)


def requirements_for(profile: str) -> set[str]:
    return set(PROFILE_REQUIREMENTS.get(normalize_profile(profile), set()))


def mandatory_for(profile: str) -> set[str]:
    return set(MANDATORY_BY_PROFILE.get(normalize_profile(profile), set()))
