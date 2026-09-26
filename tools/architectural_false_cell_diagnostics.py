"""Blind diagnostics for false architectural cells.

This tool is evaluation-only.  It never contributes labels, coordinates or
expected answers to production inference.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json

from shapely.geometry import Polygon
from shapely.strtree import STRtree

from cad_engine.architectural_space_engine import _extract, _ingest, normalize_text, reconstruct_architecture


TOKENS = {
    "DIMENSION": ("dim", "dimension", "اندازه", "dime arch"),
    "ANNOTATION": ("text", "anno", "leader", "callout", "note"),
    "FURNITURE": ("furn", "furniture", "مبلمان", "sofa", "bed", "table"),
    "FIXTURE": ("fixture", "sanitary", "toilet", "wc", "sink", "bath"),
    "CABINET": ("cabinet", "kitchen", "کابینت"),
    "STAIR_GRAPHIC": ("stair", "step", "tread", "riser", "پله"),
    "GRID": ("grid", "axis", "محور", "آکس"),
    "HATCH_GRAPHIC": ("hatch",),
    "TEXT_GLYPH": ("shx", "glyph"),
    "SITE_BOUNDARY": ("site", "property", "yard", "حیاط"),
    "WALL_FACE": ("wall", "a wall", "دیوار", "partition"),
}


def classify(meta, extracted):
    context = normalize_text(meta.get("layer"))
    for semantic, tokens in TOKENS.items():
        if any(normalize_text(token) in context for token in tokens):
            return semantic
    primitive = next((p for p in extracted["primitives"] if p.get("handle") == meta.get("handle")), None)
    if primitive and primitive.get("source_block"):
        block = normalize_text(primitive["source_block"])
        for semantic, tokens in TOKENS.items():
            if any(normalize_text(token) in block for token in tokens): return semantic
        return "BLOCK_GRAPHIC"
    return "UNKNOWN_GEOMETRY"


def diagnose(path):
    doc, _ = _ingest(path); extracted = _extract(doc); model = reconstruct_architecture(path)
    lines = extracted["boundary_lines"]; metas = extracted["boundary_meta"]
    tree = STRtree(lines) if lines else None
    tolerance = float(model["diagnostics"].get("adaptive_tolerance") or .001) * 1.25
    unresolved = [s for s in model["physical_spaces"] if s["status"] not in {"VERIFIED", "HIGH_CONFIDENCE"}]
    dominant = Counter(); contributing = Counter(); unknown_layers=Counter(); unknown_types=Counter(); unknown_lengths=[]; cell_rows=[]
    for space in unresolved:
        poly = Polygon(space["polygon"], space.get("interior_rings") or [])
        boundary = poly.boundary; indexes = tree.query(boundary.buffer(tolerance)) if tree else []
        evidence = Counter()
        for index in indexes:
            idx = int(index); line = lines[idx]
            if line.distance(boundary) <= tolerance:
                semantic=classify(metas[idx], extracted); evidence[semantic] += 1
                if semantic=="UNKNOWN_GEOMETRY":
                    unknown_layers[metas[idx].get("layer") or "0"] += 1
                    unknown_types[metas[idx].get("entity_type") or "UNKNOWN"] += 1
                    unknown_lengths.append(line.length)
        winner = evidence.most_common(1)[0][0] if evidence else "UNTRACED"
        dominant[winner] += 1; contributing.update(evidence)
        cell_rows.append({"space_id":space["physical_space_id"],"frame_id":space["frame_id"],
                          "area":space["geometric_area_drawing_units"],"dominant_source_class":winner,
                          "boundary_source_counts":dict(evidence)})
    total=max(len(unresolved),1)
    ordered_lengths=sorted(unknown_lengths)
    quantiles={}
    if ordered_lengths:
        quantiles={name:ordered_lengths[int((len(ordered_lengths)-1)*fraction)] for name,fraction in
                   (("min",0),("p25",.25),("median",.5),("p75",.75),("p95",.95),("max",1))}
    return {"source":str(Path(path).name),"status":model["completeness"]["status"],
            "raw_boundary_segments":len(lines),"candidate_spaces":len(model["physical_spaces"]),
            "verified_spaces":sum(s["status"]=="VERIFIED" for s in model["physical_spaces"]),
            "unresolved_spaces":len(unresolved),"excluded_glyph_layers":extracted["excluded_graphic_glyph_layers"],
            "dominant_false_cell_origin":[{"class":kind,"count":count,"percent":round(100*count/total,2)}
                                          for kind,count in dominant.most_common()],
            "all_boundary_contributions":dict(contributing),
            "unknown_geometry_profile":{"top_layers":unknown_layers.most_common(15),
                                        "entity_types":dict(unknown_types),"length_quantiles":quantiles},
            "cells":cell_rows,
            "coverage":model["coverage"],"runtime":model["diagnostics"]}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("paths",nargs="+"); parser.add_argument("--output")
    args=parser.parse_args(); report={"schema":"architectural-false-cell-diagnostics/1.0",
                                     "projects":[diagnose(path) for path in args.paths]}
    payload=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(payload,encoding="utf-8")
    print(payload)


if __name__ == "__main__": main()
