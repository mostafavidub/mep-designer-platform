#!/usr/bin/env python3
"""Evidence-only audit of physical-space candidates; never changes inference."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import json

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from cad_engine.architectural_space_engine import _extract, _ingest, reconstruct_architecture
from cad_engine.pre_topology_object_classifier import classify_source_record


FAMILY_BY_CLASS = {
    "COLUMN":"Column-derived", "GRID_AXIS":"Grid/Axis-derived", "DIMENSION_CHAIN":"Dimension-derived",
    "STAIR_ASSEMBLY":"Stair-derived", "DINING_TABLE_ASSEMBLY":"Furniture-derived",
    "GENERIC_NON_ENCLOSURE_OBJECT":"Furniture-derived", "VEHICLE":"Vehicle/Parking-derived",
    "PARKING_BAY":"Vehicle/Parking-derived", "SECTION_CUT":"Section-marker-derived",
    "SHEET_FRAME":"Sheet/presentation-derived", "WINDOW_ASSEMBLY":"Portal/opening artifact",
    "DOOR_ASSEMBLY":"Portal/opening artifact", "DOUBLE_DOOR_ASSEMBLY":"Portal/opening artifact",
    "OPEN_PASSAGE":"Portal/opening artifact",
}


def _family(poly, contributors, labels, objects, openings, scale):
    classes=Counter(row["pre_topology_classification"]["object_class"] for row in contributors)
    explicit=[FAMILY_BY_CLASS[name] for name in classes if name in FAMILY_BY_CLASS]
    if explicit:
        return Counter(explicit).most_common(1)[0][0], "EXPLICIT_SOURCE_CLASS"
    if labels:
        return "Real physical-space candidate", "HOSTED_SEMANTIC_LABEL"
    if any(poly.buffer(.01/max(scale,1e-12)).intersects(LineString(row["geometry"])) for row in openings if len(row.get("geometry") or [])>=2):
        return "Portal/opening artifact", "OPENING_GEOMETRY_CONTACT"
    rectangle=poly.minimum_rotated_rectangle; coords=list(rectangle.exterior.coords)
    sides=sorted(LineString([a,b]).length*scale for a,b in zip(coords,coords[1:]) if a!=b)
    if sides and (poly.area*scale*scale<1.5 or sides[-1]/max(sides[0],1e-12)>=2.5):
        return "Wall-solid/sliver-derived", "UNLABELLED_COMPACT_OR_SLENDER_CELL"
    if objects:
        return "Furniture-derived", "HOSTED_OBJECT_WITHOUT_SPACE_LABEL"
    return "Unknown", "INSUFFICIENT_CLASS_EVIDENCE"


def audit(path, frame_id=None):
    doc,source=_ingest(path); extracted=_extract(doc); model=reconstruct_architecture(path)
    scale=float(model["source"].get("metres_per_unit") or 1.0)
    segments=[row for row in model["architectural_segments"] if row.get("status")=="ACCEPTED"]
    lines=[LineString(row["geometry"]) for row in segments]; tree=STRtree(lines) if lines else None
    openings=model.get("openings") or []; rows=[]; totals=Counter()
    for space in model["physical_spaces"]:
        if frame_id and space.get("frame_id")!=frame_id: continue
        poly=Polygon(space["polygon"],space.get("interior_rings") or [])
        indexes=tree.query(poly.boundary.buffer(model["diagnostics"]["adaptive_tolerance"]*1.5)) if tree else []
        contributors=[]
        for raw in indexes:
            index=int(raw); segment=segments[index]
            if lines[index].distance(poly.boundary)>model["diagnostics"]["adaptive_tolerance"]*1.5: continue
            context=segment.get("source_context") or {}
            pre=segment.get("pre_topology_classification") or classify_source_record({
                "handle":segment.get("source_handle"),"entity_type":context.get("entity_type"),
                "layer":context.get("layer")})
            contributors.append({"segment_id":segment.get("segment_id"),"source_handle":segment.get("source_handle"),
                "geometry":segment.get("geometry"),"semantic_class":segment.get("semantic_class"),
                "wall_evidence_state":segment.get("wall_evidence_state"),"wall_probability":segment.get("wall_probability"),
                "evidence":segment.get("evidence") or [],"negative_evidence":segment.get("negative_evidence") or [],
                "classification_path":"EXTRACTION -> PRE_TOPOLOGY -> WALL_ADMISSION -> POLYGONIZATION",
                "pre_topology_classification":pre,
                "polygonization_entry_reason":"ACCEPTED_WALL_SEGMENT:"+str(segment.get("wall_evidence_state")),
                "gate_miss_reason":"SOURCE_CLASS_REMAINED_UNKNOWN_AND_GEOMETRIC_WALL_EVIDENCE_PROMOTED_SEGMENT"
                    if pre["object_class"]=="UNKNOWN" else "CLASS_WAS_NOT_HARD_EXCLUDED"})
        labels=[row for row in extracted["texts"] if row.get("point") and poly.covers(Point(row["point"]))]
        objects=[row for row in extracted["objects"] if row.get("point") and poly.covers(Point(row["point"]))]
        family,basis=_family(poly,contributors,labels,objects,openings,scale); totals[family]+=1
        rows.append({"physical_space_id":space["physical_space_id"],"frame_id":space["frame_id"],
            "status":space["status"],"family":family,"family_basis":basis,"area_drawing_units":poly.area,
            "area_m2":poly.area*scale*scale,"geometry":space["polygon"],"source_handles":sorted({str(r["source_handle"]) for r in contributors if r["source_handle"]}),
            "hosted_text":[{"handle":r.get("handle"),"text":r.get("text"),"point":r.get("point")} for r in labels],
            "hosted_objects":[{"handle":r.get("handle"),"name":r.get("name"),"point":r.get("point")} for r in objects],
            "boundary_contributors":contributors})
    return {"schema":"pre-topology-candidate-root-cause-audit/1.0","source_sha256":source["source_sha256"],
        "frame_id":frame_id,"candidate_count":len(rows),"family_counts":dict(sorted(totals.items())),
        "completeness_status":model["completeness"]["status"],"coverage":model["coverage"],
        "accepted_wall_segments":model["diagnostics"]["accepted_wall_segment_count"],"overlap_area":sum(r.get("overlap_area") or 0 for r in model["coverage"]["frames"]),
        "candidates":sorted(rows,key=lambda r:r["physical_space_id"])}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("dxf"); parser.add_argument("--frame-id"); parser.add_argument("--output",required=True)
    args=parser.parse_args(); payload=audit(args.dxf,args.frame_id)
    Path(args.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({key:payload[key] for key in ("candidate_count","family_counts","completeness_status","accepted_wall_segments","overlap_area")},ensure_ascii=False))


if __name__=="__main__": main()
