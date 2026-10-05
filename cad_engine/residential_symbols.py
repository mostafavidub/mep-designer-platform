"""Original metre-based vector references; dimensions are always caller supplied."""
from __future__ import annotations

import math
from cad_engine.residential_foundation import finite_number, load_catalog, stable_hash
from cad_engine.build_identity import build_identity


def create_symbol(symbol_id, *, width_m, depth_m, origin_m, rotation_deg,
                  dimension_basis, usage_clearance_m=None, clearance_source=None, steps=None):
    catalog = load_catalog("symbols")
    row = next((s for s in catalog["symbols"] if s["symbol_id"] == symbol_id), None)
    if row is None:
        raise ValueError("Unknown symbol")
    if any(not finite_number(v) or v <= 0 for v in [width_m, depth_m]):
        raise ValueError("Positive finite metre dimensions required")
    if not isinstance(origin_m, (list, tuple)) or len(origin_m) != 2 or any(not finite_number(v) for v in origin_m) or not finite_number(rotation_deg):
        raise ValueError("Invalid placement")
    if dimension_basis not in {"MANUFACTURER", "OWNER_MEASURED", "VISUALIZATION_ONLY"}:
        raise ValueError("Explicit dimension basis required")
    if usage_clearance_m is not None and (not finite_number(usage_clearance_m) or usage_clearance_m < 0 or not clearance_source):
        raise ValueError("Clearance requires a finite nonnegative distance and provenance")
    w, d = width_m, depth_m
    a = math.radians(rotation_deg % 360)
    def point(x, y):
        return [round(origin_m[0] + x*math.cos(a)-y*math.sin(a), 12),
                round(origin_m[1] + x*math.sin(a)+y*math.cos(a), 12)]
    def polygon(points):
        return [point(x, y) for x, y in points]
    footprint = polygon([(0, 0), (w, 0), (w, d), (0, d), (0, 0)])
    lines = [footprint]
    kind = row["representation"]["primitive"]
    operating = None
    if kind == "BED":
        lines.append(polygon([(0, d*.75), (w, d*.75)]))
    elif kind == "SANITARY":
        lines.append(polygon([(w*.2, d*.2), (w*.8, d*.2), (w*.8, d*.8), (w*.2, d*.8), (w*.2, d*.2)]))
    elif kind == "WINDOW":
        lines.append(polygon([(0, d*.5), (w, d*.5)]))
    elif kind == "STAIR_FLIGHT":
        if type(steps) is not int or not 2 <= steps <= 100:
            raise ValueError("Explicit bounded tread count required; not a stair-design rule")
        lines.extend(polygon([(0, d*i/steps), (w, d*i/steps)]) for i in range(1, steps))
    elif kind == "DOOR_SWING":
        lines.append(polygon([(0, 0), (0, w)]))
        lines.append(polygon([(w*math.cos(math.pi*i/32), w*math.sin(math.pi*i/32)) for i in range(17)]))
        # Conservative full sweep bound; separate from closed-leaf footprint and user clearance.
        operating = polygon([(0, 0), (w, 0), (w, w), (0, w), (0, 0)])
    else:
        lines.append(polygon([(0, 0), (w, d)]))
    usage = None if usage_clearance_m is None else polygon([(0, d), (w, d), (w, d+usage_clearance_m), (0, d+usage_clearance_m), (0, d)])
    result = {"symbol_id": symbol_id, "units": "m", "footprint": footprint,
              "operating_envelope": operating,
              "usage_envelope": usage, "usage_source": clearance_source, "lines": lines,
              "dimension_basis": dimension_basis, "catalog_hash": stable_hash(catalog),
              "fit_status": "REVIEW_REQUIRED" if usage is not None and dimension_basis != "VISUALIZATION_ONLY" else "INPUT_REQUIRED",
              "build_identity": build_identity(), "mep_ports": [],
              "note": "Generic reference only. Product outline, operating sweeps and ports require project evidence."}
    result["parameter_hash"] = stable_hash({"symbol":symbol_id,"width":w,"depth":d,"origin":origin_m,
                                            "rotation":rotation_deg%360,"basis":dimension_basis,
                                            "clearance":usage_clearance_m,"source":clearance_source,"steps":steps})
    return result


def symbol_svg(symbol):
    import html
    points = [p for line in symbol["lines"] for p in line] + (symbol["usage_envelope"] or [])
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pad = .05
    view = f'{min(xs)-pad} {min(ys)-pad} {max(xs)-min(xs)+2*pad} {max(ys)-min(ys)+2*pad}'
    def path(points, color, dash=""):
        coords = " ".join(f"{x},{y}" for x,y in points)
        return f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="0.012" {dash}/>'
    identity = html.escape(str(symbol["build_identity"]))
    content = ''.join(path(line,"#183247") for line in symbol["lines"])
    if symbol["usage_envelope"]:
        content += path(symbol["usage_envelope"],"#b45309",'stroke-dasharray="0.04 0.02"')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}"><metadata>{identity}</metadata>{content}</svg>'
