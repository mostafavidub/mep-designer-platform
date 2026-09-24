"""Local coordinate frame detection for rotated and multi-axis architecture."""
from __future__ import annotations
import math


def _axis_delta(a, b):
    diff = abs((a-b) % math.pi)
    return min(diff, math.pi-diff)


def _segment(row):
    a = row.get("a"); b = row.get("b")
    if not a or not b:
        return None
    a=(float(a[0]),float(a[1])); b=(float(b[0]),float(b[1]))
    length=math.dist(a,b)
    if length <= 1e-9:
        return None
    return a,b,length,math.atan2(b[1]-a[1],b[0]-a[0]) % math.pi


def detect_local_coordinate_frames(references, *, zone_id="ZONE-1", angular_tolerance_deg=6.0):
    candidates=[]
    for ref in references or []:
        if ref.get("kind") not in {"GRID_AXIS","WALL_FACE","STRUCTURAL_FACE","SHAFT_FACE","STAIR_EDGE","PROPERTY_BOUNDARY"}:
            continue
        seg=_segment(ref)
        if seg:
            candidates.append((ref,seg))
    if not candidates:
        return [{
            "id": f"FRAME-{zone_id}-0", "zone_id": zone_id, "origin": (0.0,0.0),
            "primary_axis": (1.0,0.0), "secondary_axis": (0.0,1.0),
            "angle_deg": 0.0, "confidence": 0.0, "semantic_evidence": [],
            "status": "HUMAN_REVIEW",
        }]

    tol=math.radians(float(angular_tolerance_deg))
    groups=[]
    for ref,(a,b,length,angle) in sorted(candidates,key=lambda x:-x[1][2]):
        placed=False
        for group in groups:
            if _axis_delta(angle,group["angle"]) <= tol or _axis_delta(angle,group["angle"]+math.pi/2) <= tol:
                group["rows"].append((ref,a,b,length,angle)); group["weight"]+=length; placed=True; break
        if not placed:
            groups.append({"angle":angle,"rows":[(ref,a,b,length,angle)],"weight":length})
    total=sum(g["weight"] for g in groups) or 1.0
    frames=[]
    for idx,g in enumerate(sorted(groups,key=lambda x:-x["weight"])):
        # Fold perpendicular members into one orthogonal frame; estimate primary
        # from members closest to the seed angle.
        primary=[r for r in g["rows"] if _axis_delta(r[4],g["angle"]) <= tol]
        weight=sum(r[3] for r in primary) or g["weight"]
        sx=sum(math.cos(2*r[4])*r[3] for r in primary)
        sy=sum(math.sin(2*r[4])*r[3] for r in primary)
        angle=(0.5*math.atan2(sy,sx)) % math.pi if abs(sx)+abs(sy)>1e-12 else g["angle"]
        points=[p for _,a,b,_,_ in g["rows"] for p in (a,b)]
        origin=(sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points))
        confidence=min(1.0,g["weight"]/total)
        frames.append({
            "id":f"FRAME-{zone_id}-{idx}", "zone_id":zone_id, "origin":origin,
            "primary_axis":(math.cos(angle),math.sin(angle)),
            "secondary_axis":(-math.sin(angle),math.cos(angle)),
            "angle_deg":math.degrees(angle), "confidence":confidence,
            "semantic_evidence":[str(r[0].get("id")) for r in g["rows"]],
            "status":"PASS" if confidence >= 0.20 else "HUMAN_REVIEW",
        })
    return frames


def project(point, frame):
    ox,oy=frame["origin"]; ux,uy=frame["primary_axis"]; vx,vy=frame["secondary_axis"]
    dx=float(point[0])-ox; dy=float(point[1])-oy
    return (dx*ux+dy*uy, dx*vx+dy*vy)


def unproject(local, frame):
    ox,oy=frame["origin"]; ux,uy=frame["primary_axis"]; vx,vy=frame["secondary_axis"]
    return (ox+local[0]*ux+local[1]*vx, oy+local[0]*uy+local[1]*vy)
