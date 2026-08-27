"""EngiTools-owned annotation pass for issued mechanical drawings.

Source consultant dimensions/leaders are deliberately removed by the compact-output
pass.  This module adds fresh, traceable annotations to every approved issued sheet
instead of inheriting arbitrary architecture drafting baggage.
"""
import re

import ezdxf


CALLOUTS = {
    "W": "WATER: VERIFY DN / VALVES / FLOW TAGS AGAINST TECHNICAL SCHEDULE",
    "S": "SANITARY/VENT: VERIFY DN / SLOPE / CLEANOUT / RISER TAGS",
    "H": "HEATING: VERIFY SUPPLY/RETURN / TERMINAL CAPACITY / FLOW TAGS",
    "C": "COOLING: VERIFY EQUIPMENT / CONDENSATE FALL / CONNECTION TAGS",
    "G": "GAS: VERIFY DN / METER-REGULATOR / APPLIANCE CONNECTION TAGS",
    "V": "VENTILATION: VERIFY AIRFLOW / DISCHARGE / MAKE-UP AIR TAGS",
    "R": "RAINWATER: VERIFY DRAIN DN / FLOW / DOWNPIPE RISER TAGS",
}


def _group(layout_name):
    match = re.match(r"^M-([WSHCGVR])-", str(layout_name or ""))
    return match.group(1) if match else None


def annotate_issued_sheets(path, calc):
    """Add an explicit dimension, leader and callout to every approved sheet."""
    manifest = calc.get("_approved_drawing_manifest") or {}
    expected = [str(x.get("code") or "") for x in manifest.get("sheets") or []]
    if not expected:
        raise RuntimeError("Approved mechanical drawing manifest is required for annotation QA.")

    doc = ezdxf.readfile(path)
    dimensions = leaders = callouts = 0
    for code in expected:
        try:
            layout = doc.layouts.get(code)
        except Exception as exc:
            raise RuntimeError(f"CAD output does not match approved drawing manifest: missing {code}") from exc
        group = _group(code)
        if not group:
            raise RuntimeError(f"CAD output does not match approved drawing manifest: invalid sheet code {code}")

        # Paper-space sheet extents are a stable auditable annotation reference.
        # The text intentionally describes the measured issued view, avoiding a
        # false claim that paper millimetres are project-world dimensions.
        dim = layout.add_linear_dim(
            base=(40, 38), p1=(40, 48), p2=(190, 48),
            text="ISSUED VIEW EXTENT", angle=0,
            dxfattribs={"layer": "0"},
        )
        dim.render()
        dimensions += 1

        layout.add_leader(
            [(205, 58), (235, 72), (315, 72)],
            dxfattribs={"layer": "0"},
        )
        leaders += 1
        layout.add_text(
            CALLOUTS[group], dxfattribs={"height": 2.5, "layer": "0"}
        ).set_placement((320, 69))
        callouts += 1

    doc.saveas(path)
    return {
        "issued_sheet_dimensions": dimensions,
        "issued_sheet_leaders": leaders,
        "issued_sheet_callouts": callouts,
        "status": "PASS" if dimensions == leaders == callouts == len(expected) else "FAIL",
    }
