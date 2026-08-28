"""Reusable sheet cleanup policy for EngiTools CAD outputs.

Purpose:
- Reserve the strip between plan body and title block for EngiTools-generated subtitle/scale only.
- Remove imported architectural footer clutter such as decorative separator lines, old dimensions,
  stale notes, Arc labels, and legacy title-band remnants.
- Preserve all EngiTools-generated engineering content.

This policy is project-agnostic and intended to run on every generated plan sheet before final QA.
"""

from dataclasses import dataclass
from typing import Optional


PLAN_FAMILIES = {
    "ROOF",
    "SANITARY_VENT",
    "WATER",
    "HEATING",
    "GAS",
    "SPLIT_AC",
    "SPLIT_ROOF",
    "EXHAUST",
}

KNOWN_LEGACY_FOOTER_LAYERS = {
    "EL2",
    "MEN",
    "construction",
    "suport",
    "f n",
    "DAM--PLAN",
}

PRESERVE_PREFIXES = ("ENGITOOLS-",)
PRESERVE_ARCH_LAYERS = {"WALL", "DOOR", "WINDOW", "0"}


@dataclass(frozen=True)
class FooterCleanupBand:
    """Footer cleanup band relative to owning sheet model bounds."""

    y1_offset: float = 5.55
    y2_offset: float = 8.65
    x_inset: float = 0.80


def should_remove_footer_entity(
    *,
    family: str,
    layer: str,
    entity_type: str,
    bbox_center_x: float,
    bbox_center_y: float,
    bbox_width: float,
    bbox_height: float,
    sheet_bounds: tuple[float, float, float, float],
    text: Optional[str] = None,
    band: FooterCleanupBand = FooterCleanupBand(),
) -> bool:
    """Return True when an imported entity is non-engineering footer clutter.

    This function is intentionally conservative: it only acts inside the reserved footer band,
    never removes EngiTools layers, and preserves core architectural layers.
    """

    if family not in PLAN_FAMILIES:
        return False

    if layer.startswith(PRESERVE_PREFIXES):
        return False

    x1, y1, x2, _ = sheet_bounds
    in_band = (
        x1 + band.x_inset <= bbox_center_x <= x2 - band.x_inset
        and y1 + band.y1_offset <= bbox_center_y <= y1 + band.y2_offset
    )
    if not in_band:
        return False

    et = entity_type.upper()
    txt = (text or "").strip()

    if layer in KNOWN_LEGACY_FOOTER_LAYERS and et in {
        "LINE",
        "LWPOLYLINE",
        "POLYLINE",
        "DIMENSION",
        "TEXT",
        "MTEXT",
    }:
        return True

    if et == "DIMENSION":
        return True

    if et in {"TEXT", "MTEXT"} and layer not in PRESERVE_ARCH_LAYERS:
        return True

    if et == "LINE" and layer not in PRESERVE_ARCH_LAYERS:
        return bbox_width > 0.70 or bbox_height > 0.70

    if et in {"LWPOLYLINE", "POLYLINE"} and layer not in PRESERVE_ARCH_LAYERS:
        return bbox_height < 0.70 and bbox_width > 0.70

    # Explicit stale labels are always forbidden inside the reserved band.
    stale_markers = ("پلان معماری", "Arc -", "DETAIL REFERENCES:")
    return any(marker in txt for marker in stale_markers)


def qa_footer_band_clean(remaining_legacy_count: int, generated_subtitle_count: int) -> bool:
    """Final QA gate for every plan sheet."""
    return remaining_legacy_count == 0 and generated_subtitle_count >= 2
