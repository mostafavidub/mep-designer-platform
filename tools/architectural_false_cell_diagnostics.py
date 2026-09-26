"""Blind diagnostics for false architectural cells.

This tool is evaluation-only.  It never contributes labels, coordinates or
expected answers to production inference.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json

from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree

from cad_engine.architectural_space_engine import (
    _classify_text, _extract, _ingest, _polygonize_spaces, normalize_text,
    reconstruct_architecture,
)


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
    frame_rows=[]
    for frame in model["frames"]:
        if frame.get("scope_relevance")=="REFERENCE_ONLY": continue
        bounds=frame.get("bounds"); frame_box=box(*bounds) if bounds else None
        raw=[line for line in lines if frame_box is None or line.intersects(frame_box)]
        segments=[row for row in model.get("architectural_segments",[]) if row.get("frame_id")==frame["frame_id"]]
        accepted=[row for row in segments if row.get("status")=="ACCEPTED"]
        secondary=[row for row in accepted if row.get("semantic_class")=="PARTITION_FACE"]
        spaces=[row for row in model["physical_spaces"] if row.get("frame_id")==frame["frame_id"]]
        coverage=next((row for row in model["coverage"]["frames"] if row["frame_id"]==frame["frame_id"]),{})
        labels=[]
        for text in extracted["texts"]:
            category,_=_classify_text(text.get("text")); point=text.get("point")
            if not category or not point or (frame_box is not None and not frame_box.covers(Point(point))): continue
            hosted=next((space["physical_space_id"] for space in spaces if Polygon(space["polygon"],space.get("interior_rings") or []).covers(Point(point))),None)
            labels.append({"handle":text.get("handle"),"category":category,"host_space_id":hosted,"status":"HOSTED" if hosted else "UNHOSTED"})
        initial=_polygonize_spaces([LineString(row["geometry"]) for row in accepted],frame,tolerance)
        ratio=float(coverage.get("coverage_ratio") or 0)
        unknown=sum(space.get("status")=="INPUT_REQUIRED" for space in spaces)
        failure=[]
        if ratio<.4: failure.append("ENVELOPE_FAILURE")
        if len(spaces)>max(20,len(labels)*4): failure.append("OVER_SEGMENTATION")
        if ratio>.85 and unknown>len(labels)*2: failure.append("SEMANTIC_BINDING_FAILURE")
        if not any(opening.get("status")=="VERIFIED" for opening in model.get("openings",[])): failure.append("PORTAL_FAILURE")
        frame_rows.append({"frame_id":frame["frame_id"],"level":frame.get("level_candidate"),"frame_bounds":bounds,
                           "inferred_building_footprint":None,"footprint_status":"NOT_IMPLEMENTED",
                           "raw_source_segments":len(raw),"accepted_high_confidence_wall_segments":len(accepted)-len(secondary),
                           "accepted_secondary_partition_segments":len(secondary),"rejected_geometry":len(segments)-len(accepted),
                           "wall_objects":sum(1 for wall in model.get("canonical_walls",[]) if frame_box is None or frame_box.intersects(LineString(wall["geometry"]))),
                           "initial_polygons":len(initial),"merged_polygons":None,"remaining_spaces":len(spaces),
                           "hosted_labels":sum(row["status"]=="HOSTED" for row in labels),"unhosted_labels":sum(row["status"]=="UNHOSTED" for row in labels),
                           "unresolved_interior_area":coverage.get("unresolved_area"),"unexplained_frame_area":coverage.get("unexplained_frame_area"),
                           "failure_modes":failure})
    return {"source":str(Path(path).name),"status":model["completeness"]["status"],
            "raw_boundary_segments":len(lines),"candidate_spaces":len(model["physical_spaces"]),
            "verified_spaces":sum(s["status"]=="VERIFIED" for s in model["physical_spaces"]),
            "unresolved_spaces":len(unresolved),"excluded_glyph_layers":extracted["excluded_graphic_glyph_layers"],
            "dominant_false_cell_origin":[{"class":kind,"count":count,"percent":round(100*count/total,2)}
                                          for kind,count in dominant.most_common()],
            "all_boundary_contributions":dict(contributing),
            "unknown_geometry_profile":{"top_layers":unknown_layers.most_common(15),
                                        "entity_types":dict(unknown_types),"length_quantiles":quantiles},
            "cells":cell_rows,"authoritative_frames":frame_rows,
            "coverage":model["coverage"],"runtime":model["diagnostics"]}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("paths",nargs="+"); parser.add_argument("--output")
    args=parser.parse_args(); report={"schema":"architectural-false-cell-diagnostics/1.0",
                                     "projects":[diagnose(path) for path in args.paths]}
    payload=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(payload,encoding="utf-8")
    print(payload)


if __name__ == "__main__": main()
