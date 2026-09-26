#!/usr/bin/env python3
"""Read-only structural validation for human architectural Golden files."""
from __future__ import annotations
import argparse, json
from hashlib import sha256
from pathlib import Path
from shapely.geometry import Point, Polygon, box


STATES=("DRAFT","REVIEWED","APPROVED")


def validate(golden,source_bytes=None):
    errors=[]; warnings=[]
    required=("schema","case_id","source_sha256","review_status","review","frame","building_envelope","spaces","functional_zones","portals","geometric_adjacency","access_connectivity")
    errors.extend(f"missing_required:{name}" for name in required if name not in golden)
    if errors: return {"status":"FAIL","errors":errors,"warnings":warnings}
    if golden.get("schema")!="architectural-topology-golden/1.0": errors.append("invalid_schema_identity")
    if not isinstance(golden.get("case_id"),str) or not golden["case_id"].strip(): errors.append("invalid_case_id")
    source_hash=golden.get("source_sha256")
    if not isinstance(source_hash,str) or len(source_hash)!=64 or any(char not in "0123456789abcdef" for char in source_hash): errors.append("invalid_source_sha256")
    state=golden["review_status"]
    if state not in STATES: errors.append("invalid_review_status")
    if source_bytes is not None and sha256(source_bytes).hexdigest()!=source_hash: errors.append("source_hash_mismatch")
    bounds=golden["frame"].get("bounds") or []
    if len(bounds)!=4 or bounds[2]<=bounds[0] or bounds[3]<=bounds[1]: errors.append("invalid_frame_bounds"); frame=None
    else: frame=box(*bounds)
    review=golden["review"]
    if review.get("method")!="INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW": errors.append("invalid_review_method")
    if review.get("runtime_output_visible_during_annotation") is not False: errors.append("independence_violation")
    if state in {"REVIEWED","APPROVED"} and (not review.get("annotator") or not review.get("annotation_date")): errors.append("annotation_identity_missing")
    if state=="APPROVED" and (not review.get("reviewer") or not review.get("reviewed_at") or not review.get("approved_at")): errors.append("approval_identity_missing")
    ids=[]; polygons={}
    for row in golden["spaces"]:
        identifier=row.get("golden_space_id")
        if not identifier: errors.append("space_id_missing"); continue
        if identifier in ids: errors.append(f"duplicate_space_id:{identifier}")
        ids.append(identifier); ring=row.get("polygon") or []
        if row.get("status")!="UNKNOWN" or ring:
            if len(ring)<4: errors.append(f"space_polygon_missing:{identifier}"); continue
            poly=Polygon(ring,row.get("interior_rings") or [])
            if not poly.is_valid or poly.is_empty or poly.area<=0: errors.append(f"space_polygon_invalid:{identifier}")
            elif frame is not None and not frame.covers(poly): errors.append(f"space_outside_frame:{identifier}")
            else: polygons[identifier]=poly
    envelope=golden["building_envelope"]; outer=envelope.get("outer_ring") or []
    if envelope.get("status")=="VERIFIED" or outer:
        if len(outer)<4: errors.append("building_envelope_missing")
        else:
            poly=Polygon(outer,envelope.get("interior_voids") or [])
            if not poly.is_valid or poly.is_empty or poly.area<=0: errors.append("building_envelope_invalid")
            elif frame is not None and not frame.covers(poly): errors.append("building_envelope_outside_frame")
    elif state=="APPROVED": errors.append("approved_golden_requires_envelope")
    known=set(ids)|{"EXTERIOR","UNKNOWN"}; portal_ids=set()
    for portal in golden["portals"]:
        identifier=portal.get("golden_portal_id")
        if not identifier: errors.append("portal_id_missing"); continue
        if identifier in portal_ids: errors.append(f"duplicate_portal_id:{identifier}")
        portal_ids.add(identifier)
        for field in ("space_a","space_b"):
            if portal.get(field) is not None and portal[field] not in known: errors.append(f"portal_unknown_space:{identifier}:{portal[field]}")
        point=portal.get("point")
        if point and frame is not None and not frame.covers(Point(point)): errors.append(f"portal_outside_frame:{identifier}")
    for edge in golden["geometric_adjacency"]:
        if len(edge)!=2 or any(identifier not in ids for identifier in edge): errors.append(f"invalid_geometric_adjacency:{edge}")
    for edge in golden["access_connectivity"]:
        if edge.get("space_a") not in known or edge.get("space_b") not in known: errors.append(f"invalid_access_spaces:{edge}")
        if edge.get("portal_id") not in portal_ids: errors.append(f"invalid_access_portal:{edge.get('portal_id')}")
    for zone in golden["functional_zones"]:
        if zone.get("physical_space_id") not in ids: errors.append(f"zone_unknown_space:{zone.get('golden_zone_id')}")
    if state in {"DRAFT","REVIEWED"}: warnings.append("official_scoring_disabled_until_approved")
    if state=="APPROVED" and not golden["spaces"]: errors.append("approved_golden_requires_spaces")
    return {"status":"PASS" if not errors else "FAIL","review_status":state,"official_scoring_enabled":state=="APPROVED" and not errors,
            "errors":errors,"warnings":warnings,"counts":{"spaces":len(golden["spaces"]),"zones":len(golden["functional_zones"]),"portals":len(golden["portals"])}}


def main():
    p=argparse.ArgumentParser(); p.add_argument("golden"); p.add_argument("--source"); a=p.parse_args()
    golden=json.loads(Path(a.golden).read_text(encoding="utf-8")); source=Path(a.source).read_bytes() if a.source else None
    report=validate(golden,source); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report["status"]=="PASS" else 1


if __name__=="__main__": raise SystemExit(main())
