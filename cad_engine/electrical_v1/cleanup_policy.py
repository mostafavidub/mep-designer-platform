from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PLAN_FAMILIES = {"LIGHTING", "POWER", "FIRE_ALARM", "LOW_CURRENT", "GROUNDING"}
PRESERVE_PREFIXES = ("ENGITOOLS-E-",)
PRESERVE_ARCH_LAYERS = {
    "0", "WALL", "DOOR", "WINDOW", "OPENING", "SHAFT", "COLUMN", "GRID",
    "AXIS", "STAIR", "RAMP", "SLAB", "STRUCTURE", "DIMENSION",
}
KNOWN_LEGACY_FOOTER_LAYERS = {"EL2", "MEN", "construction", "suport", "support", "f n", "DAM--PLAN"}
STALE_TEXT_MARKERS = ("پلان معماری", "Arc -", "DETAIL REFERENCES:")


@dataclass(frozen=True)
class FooterCleanupBand:
    y1_offset: float = 5.55
    y2_offset: float = 8.65
    x_inset: float = 0.80


def _in_band(x: float, y: float, sheet_bounds, band: FooterCleanupBand) -> bool:
    x1, y1, x2, _ = sheet_bounds
    return x1 + band.x_inset <= x <= x2 - band.x_inset and y1 + band.y1_offset <= y <= y1 + band.y2_offset


def should_remove_footer_entity(*, family: str, layer: str, entity_type: str,
                                bbox_center_x: float, bbox_center_y: float,
                                bbox_width: float, bbox_height: float,
                                sheet_bounds: tuple[float, float, float, float],
                                text: Optional[str] = None,
                                band: FooterCleanupBand = FooterCleanupBand()) -> bool:
    """Delete only positively identified stale presentation artifacts.

    Unknown layers and architectural geometry default to PRESERVE. This mirrors
    the preservation-first policy proven in Mechanical v15.2.
    """
    if family not in PLAN_FAMILIES: return False
    layer = str(layer or ""); et = str(entity_type or "").upper(); txt = (text or "").strip()
    if layer.startswith(PRESERVE_PREFIXES): return False
    if not _in_band(bbox_center_x, bbox_center_y, sheet_bounds, band): return False
    if et in {"TEXT", "MTEXT"}: return any(marker in txt for marker in STALE_TEXT_MARKERS)
    if layer.upper() in {x.upper() for x in PRESERVE_ARCH_LAYERS}: return False
    if et in {"DIMENSION", "INSERT", "HATCH", "SOLID", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}: return False
    if layer in KNOWN_LEGACY_FOOTER_LAYERS:
        if et == "LINE": return min(abs(bbox_width), abs(bbox_height)) <= 0.10 and max(abs(bbox_width), abs(bbox_height)) >= 0.70
        if et in {"LWPOLYLINE", "POLYLINE"}: return (abs(bbox_height) <= 0.12 or abs(bbox_width) <= 0.12) and max(abs(bbox_width), abs(bbox_height)) >= 0.70
    return False


def qa_footer_band_clean(remaining_legacy_count: int, generated_title_count: int) -> bool:
    return remaining_legacy_count == 0 and generated_title_count >= 2
