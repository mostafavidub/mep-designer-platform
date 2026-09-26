#!/usr/bin/env python3
"""Independent QA scorer for canonical architectural reconstruction.

Golden files are never imported by the runtime package.  This command accepts
an already generated canonical model and a separately reviewed annotation file.
Incomplete or unreviewed truth fails closed instead of fabricating a score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.geometry import Polygon


def _polygon(row):
    return Polygon(row["polygon"], row.get("interior_rings") or [])


def _iou(left, right):
    union=left.union(right).area
    return left.intersection(right).area/union if union else 0.0


def _space_matches(expected, detected, threshold=.5):
    candidates=[]
    for expected_index,expected_row in enumerate(expected):
        expected_poly=_polygon(expected_row)
        for detected_index,detected_row in enumerate(detected):
            score=_iou(expected_poly,_polygon(detected_row))
            if score>=threshold: candidates.append((score,expected_index,detected_index))
    matches=[]; used_expected=set(); used_detected=set()
    for score,expected_index,detected_index in sorted(candidates,reverse=True):
        if expected_index in used_expected or detected_index in used_detected: continue
        used_expected.add(expected_index); used_detected.add(detected_index)
        matches.append((expected_index,detected_index,score))
    return matches,used_expected,used_detected


def _edge_set(rows):
    return {tuple(sorted(edge)) for edge in rows if len(edge)==2}


def _ratio(correct,total):
    return correct/total if total else None


def _portal_metrics(kind, golden, model):
    expected=[row for row in golden.get("portals",[]) if row.get("kind")==kind and row.get("status")!="UNKNOWN"]
    detected=[row for row in model.get("openings",[]) if row.get("kind")==kind and row.get("status")=="VERIFIED"]
    pairs=[]
    for expected_index,expected_row in enumerate(expected):
        point=expected_row.get("point")
        if not point: continue
        for detected_index,detected_row in enumerate(detected):
            geometry=detected_row.get("opening_geometry") or detected_row.get("geometry") or {}
            other=geometry.get("point")
            if not other: continue
            distance=((point[0]-other[0])**2+(point[1]-other[1])**2)**.5
            tolerance=float(expected_row.get("position_tolerance") or golden.get("portal_position_tolerance") or .15)
            if distance<=tolerance: pairs.append((distance,expected_index,detected_index))
    used_expected=set(); used_detected=set()
    for _,expected_index,detected_index in sorted(pairs):
        if expected_index in used_expected or detected_index in used_detected: continue
        used_expected.add(expected_index); used_detected.add(detected_index)
    return {"expected":len(expected),"detected":len(detected),"matched":len(used_expected),
            "precision":_ratio(len(used_detected),len(detected)),"recall":_ratio(len(used_expected),len(expected))}


def score(golden, model):
    if golden.get("review_status")!="APPROVED":
        return {"status":"INCOMPLETE_GOLDEN","errors":["golden_review_not_approved"]}
    expected=[row for row in golden.get("spaces",[]) if row.get("status")!="UNKNOWN"]
    if not expected:
        return {"status":"INCOMPLETE_GOLDEN","errors":["no_reviewed_space_polygons"]}
    frame_id=golden["frame"]["runtime_frame_id"]
    detected=[row for row in model.get("physical_spaces",[]) if row.get("frame_id")==frame_id]
    matches,used_expected,used_detected=_space_matches(expected,detected,float(golden.get("space_match_iou") or .5))
    ious=[score for _,_,score in matches]
    semantic=[]
    expected_to_detected={expected_index:detected_index for expected_index,detected_index,_ in matches}
    for expected_index,detected_index,_ in matches:
        category=expected[expected_index].get("category")
        if category and category!="UNKNOWN": semantic.append(category==detected[detected_index].get("category"))
    golden_edges=_edge_set(golden.get("adjacency",[]))
    detected_edges=set()
    expected_ids={row.get("golden_space_id"):index for index,row in enumerate(expected)}
    reverse={detected_index:expected[expected_index].get("golden_space_id") for expected_index,detected_index,_ in matches}
    for detected_index,row in enumerate(detected):
        if detected_index not in reverse: continue
        for adjacent in row.get("adjacent_space_ids") or []:
            other=next((index for index,item in enumerate(detected) if item.get("physical_space_id")==adjacent),None)
            if other in reverse: detected_edges.add(tuple(sorted((reverse[detected_index],reverse[other]))))
    edge_union=golden_edges|detected_edges
    envelope=_polygon({"polygon":golden["building_envelope"]["outer_ring"],
                       "interior_rings":golden["building_envelope"].get("interior_voids") or []})
    detected_union=None
    for row in detected:
        detected_union=_polygon(row) if detected_union is None else detected_union.union(_polygon(row))
    unexplained=envelope.area-(envelope.intersection(detected_union).area if detected_union is not None else 0.0)
    return {"status":"PASS","space_precision":_ratio(len(matches),len(detected)),
            "space_recall":_ratio(len(matches),len(expected)),"mean_matched_iou":sum(ious)/len(ious) if ious else None,
            "minimum_matched_iou":min(ious) if ious else None,"phantom_space_count":len(detected)-len(used_detected),
            "missing_space_count":len(expected)-len(used_expected),"semantic_accuracy":_ratio(sum(semantic),len(semantic)),
            "adjacency_accuracy":_ratio(len(golden_edges&detected_edges),len(edge_union)),
            "unexplained_interior_area":max(0.0,unexplained),
            "doors":_portal_metrics("door",golden,model),"windows":_portal_metrics("window",golden,model),
            "open_passages":_portal_metrics("open_passage",golden,model),
            "matches":[{"golden_space_id":expected[e].get("golden_space_id"),
                        "detected_space_id":detected[d].get("physical_space_id"),"iou":value} for e,d,value in matches],
            "unmatched_expected":[expected[i].get("golden_space_id") for i in range(len(expected)) if i not in used_expected],
            "unmatched_detected":[detected[i].get("physical_space_id") for i in range(len(detected)) if i not in used_detected]}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--golden",required=True); parser.add_argument("--model",required=True); parser.add_argument("--output")
    args=parser.parse_args(); golden=json.loads(Path(args.golden).read_text(encoding="utf-8")); model=json.loads(Path(args.model).read_text(encoding="utf-8"))
    report=score(golden,model); rendered=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(rendered+"\n",encoding="utf-8")
    print(rendered); return 0 if report["status"]=="PASS" else 2


if __name__=="__main__": raise SystemExit(main())
