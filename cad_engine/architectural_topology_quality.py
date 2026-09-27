"""Canonical wall, junction, envelope and portal-host topology.

Source segments remain provenance.  A wall is a continuous architectural axis
whose occupied intervals may be interrupted by openings.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import math
import time

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree


def _sid(prefix, value):
    return f"{prefix}-" + sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16].upper()


def _axis(line):
    a, b = list(line.coords)[0], list(line.coords)[-1]
    dx, dy = b[0]-a[0], b[1]-a[1]; length=max(math.hypot(dx,dy), 1e-12)
    ux, uy = dx/length, dy/length
    if ux < 0 or (abs(ux) < 1e-9 and uy < 0): ux, uy = -ux, -uy
    angle=(math.degrees(math.atan2(uy,ux))+180)%180
    return (ux,uy),(-uy,ux),angle,length


def reconstruct_canonical_walls(segment_records, *, frame_id, tolerance, metres_per_unit=None):
    started=time.perf_counter(); tol=max(float(tolerance or .001),1e-8)
    rows=[r for r in segment_records if r.get("frame_id")==frame_id and r.get("status")=="ACCEPTED"]
    lines=[LineString(r["geometry"]) for r in rows]
    tree=STRtree(lines) if lines else None
    pair_samples=[]
    for i,line in enumerate(lines):
        (u,n,angle,length)=_axis(line); radius=max(length*.35,tol*20)
        for raw in tree.query(line.buffer(radius)) if tree is not None else []:
            j=int(raw)
            if j<=i: continue
            other=lines[j]; (ou,on,oa,ol)=_axis(other)
            delta=min(abs(angle-oa),180-abs(angle-oa))
            if delta>2.0: continue
            distance=line.distance(other)
            if distance<=tol or distance>max(min(length,ol)*.35,tol*100): continue
            overlap=line.buffer(max(distance*.05,tol)).intersection(other.buffer(max(distance*.05,tol))).area
            # Projection overlap is independent of the normal separation.
            origin=list(line.coords)[0]
            p1=sorted((0.0,length)); vals=[(p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1] for p in other.coords]
            projected=max(0.0,min(p1[1],max(vals))-max(p1[0],min(vals)))
            ratio=projected/max(min(length,ol),1e-12)
            if ratio>=.45: pair_samples.append((i,j,distance,ratio))
    # Frame-local, repeated geometric thickness clusters; never fixed values.
    quantum=max(tol*2,1e-6); buckets=defaultdict(list)
    for i,j,d,o in pair_samples: buckets[round(d/quantum)].append((i,j,d,o))
    clusters=[]
    for bucket,samples in sorted(buckets.items()):
        if len(samples)<2: continue
        values=sorted(s[2] for s in samples); median=values[len(values)//2]
        clusters.append({"thickness_cluster_id":_sid("THK",[frame_id,bucket]),"median_thickness":median,
                         "median_thickness_m":median*metres_per_unit if metres_per_unit else None,
                         "spread":max(values)-min(values),"sample_count":len(samples),
                         "source_pairs":[[rows[i]["segment_id"],rows[j]["segment_id"]] for i,j,_,_ in samples],
                         "confidence":min(.99,.65+.05*len(samples))})
    typical=min((c["median_thickness"] for c in clusters),default=max(tol*8,1e-5))
    # Orientation/offset buckets prevent global O(N²) stitching.
    families=defaultdict(list)
    for i,line in enumerate(lines):
        (u,n,angle,length)=_axis(line); mid=line.interpolate(.5,normalized=True)
        families[(round(angle/2.0),round((mid.x*n[0]+mid.y*n[1])/max(typical*.35,tol*3)))].append(i)
    walls=[]
    for family,indexes in families.items():
        remaining=set(indexes)
        while remaining:
            seed=remaining.pop(); group=[seed]; changed=True
            while changed:
                changed=False
                base=unary_union([lines[i] for i in group])
                for i in list(remaining):
                    gap=base.distance(lines[i]); local_gap=max(typical*8,tol*20)
                    if gap<=local_gap:
                        group.append(i);remaining.remove(i);changed=True
            member_lines=[lines[i] for i in group]; longest=max(member_lines,key=lambda x:x.length)
            (u,n,angle,_)=_axis(longest); origin=list(longest.coords)[0]
            intervals=[]
            for i in group:
                vals=[(p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1] for p in lines[i].coords]
                intervals.append((min(vals),max(vals),i))
            intervals.sort(); lo=min(x[0] for x in intervals); hi=max(x[1] for x in intervals)
            merged=[]
            for start,end,i in intervals:
                if not merged or start-merged[-1][1]>max(tol*4,typical*.2): merged.append([start,end,[i]])
                else: merged[-1][1]=max(merged[-1][1],end);merged[-1][2].append(i)
            gaps=[]
            for left,right in zip(merged,merged[1:]):
                width=right[0]-left[1]
                if width>max(tol*4,typical*.2): gaps.append([left[1],right[0]])
            center=LineString([(origin[0]+lo*u[0],origin[1]+lo*u[1]),(origin[0]+hi*u[0],origin[1]+hi*u[1])])
            handles=sorted({rows[i].get("source_handle") for i in group if rows[i].get("source_handle")})
            wid=_sid("WALL",[frame_id,round(angle,3),[(round(a,6),round(b,6)) for a,b,_ in merged],handles])
            thickness=min((c["median_thickness"] for c in clusters),key=lambda v:abs(v-typical),default=None)
            walls.append({"wall_id":wid,"frame_id":frame_id,"level_id":None,"wall_type":"UNKNOWN",
                          "representation":"COMPOSITE" if len(group)>1 else "SINGLE_LINE",
                          "centerline":[list(p) for p in center.coords],"face_a":None,"face_b":None,
                          "wall_solid":{"occupied_intervals":[[a,b] for a,b,_ in merged],"axis_origin":list(origin),"axis_direction":[u[0],u[1]]},
                          "thickness":thickness,"thickness_status":"INFERRED" if thickness else "UNKNOWN",
                          "orientation":angle,"length":center.length,"source_fragments":[rows[i]["segment_id"] for i in group],
                          "source_handles":handles,"junction_start":None,"junction_end":None,"junctions":[],
                          "interruptions":[{"interval":g,"kind":"UNKNOWN_OPENING"} for g in gaps],"candidate_openings":[],
                          "confidence":.8 if len(group)>1 else .65,"status":"HIGH_CONFIDENCE" if len(group)>1 else "AMBIGUOUS",
                          "evidence":[{"class":"COLLINEAR_FRAGMENT_STITCHING","source_interval_count":len(merged),"gap_count":len(gaps)}],
                          "derived_geometry_provenance":{"method":"ORIENTATION_OFFSET_BUCKET_AND_PROJECTED_INTERVALS","tolerance":tol}})
    # Junction graph from wall axes.
    axes=[LineString(w["centerline"]) for w in walls]; atree=STRtree(axes) if axes else None;junctions=[]
    for i,line in enumerate(axes):
        for raw in atree.query(line.buffer(max(tol*4,typical*.25))) if atree is not None else []:
            j=int(raw)
            if j<=i: continue
            inter=line.intersection(axes[j].buffer(max(tol*2,typical*.1)))
            if inter.is_empty: continue
            point=inter.centroid; jid=_sid("JUNC",[frame_id,round(point.x,6),round(point.y,6)])
            kind="X" if line.crosses(axes[j]) else ("T" if line.distance(Point(axes[j].coords[0]))>tol else "L")
            junctions.append({"junction_id":jid,"frame_id":frame_id,"point":[point.x,point.y],"type":kind,
                              "wall_ids":[walls[i]["wall_id"],walls[j]["wall_id"]],"status":"HIGH_CONFIDENCE"})
            for k in (i,j): walls[k]["junctions"].append(jid)
    return {"walls":walls,"thickness_clusters":clusters,"junctions":junctions,
            "runtime_seconds":round(time.perf_counter()-started,6)}


def building_envelope_from_walls(walls, *, frame_id, tolerance):
    lines=[LineString(w["centerline"]) for w in walls]
    polys=list(polygonize(unary_union(lines))) if lines else []
    if not polys:
        return {"building_envelope_id":_sid("ENV",[frame_id,"UNKNOWN"]),"frame_id":frame_id,
                "outer_ring":[],"interior_voids":[],"exterior_wall_ids":[],"source_handles":[],
                "area":0.0,"perimeter":0.0,"confidence":0.0,"status":"INPUT_REQUIRED","evidence":[]}
    merged=unary_union(polys); candidates=list(merged.geoms) if merged.geom_type=="MultiPolygon" else [merged]
    poly=max(candidates,key=lambda p:p.area)
    ring=[list(p) for p in list(poly.exterior.coords)]; handles=sorted({h for w in walls for h in w["source_handles"]})
    return {"building_envelope_id":_sid("ENV",[frame_id,ring]),"frame_id":frame_id,"outer_ring":ring,
            "interior_voids":[[list(p) for p in hole.coords] for hole in poly.interiors],
            "exterior_wall_ids":[w["wall_id"] for w in walls if LineString(w["centerline"]).distance(poly.boundary)<=max(tolerance*4,1e-7)],
            "source_handles":handles,"area":poly.area,"perimeter":poly.length,"confidence":.75,
            "status":"HIGH_CONFIDENCE","evidence":[{"class":"CANONICAL_WALL_CYCLE","polygon_count":len(polys)}]}


def host_portal_on_walls(portal_line, walls, *, tolerance, pixel_tolerance):
    """Host a portal on a wall span/gap; no source line need cross its centre."""
    # Search uncertainty derives from render mapping and the inferred local
    # wall strip, not from a consultant/project-specific radius.
    proven_thicknesses=[float(w["thickness"]) for w in walls if w.get("thickness")]
    local_strip=(max(proven_thicknesses)*.75 if proven_thicknesses else 0.0)
    search=max(float(tolerance)*5,float(pixel_tolerance),local_strip,portal_line.length*.5)
    axes=[LineString(w["centerline"]) for w in walls]
    tree=STRtree(axes) if axes else None; candidates=[]
    for raw in tree.query(portal_line.buffer(search)) if tree is not None else []:
        i=int(raw); wall=walls[i]; axis=axes[i]; (u,n,angle,_)=_axis(axis); (pu,pn,pa,_)=_axis(portal_line)
        direction_delta=min(abs(angle-pa),180-abs(angle-pa))
        # Providers may encode an opening either along the jamb-to-jamb span
        # or as a short cross-wall marker.  Oblique geometry is not a
        # defensible host signal, but both parallel and perpendicular forms
        # are legitimate and still require a proven wall interruption.
        if 20 < direction_delta < 70: continue
        distance=axis.distance(portal_line.centroid)
        origin=wall["wall_solid"]["axis_origin"]
        values=[(p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1] for p in portal_line.coords]
        interval=[min(values),max(values)]; gaps=[x["interval"] for x in wall.get("interruptions",[])]
        gap_match=next((g for g in gaps if min(interval[1],g[1])-max(interval[0],g[0])>=-search),None)
        candidates.append((0 if gap_match else 1,distance,wall,gap_match))
    if not candidates: return None,"NO_NEARBY_WALL",[]
    candidates.sort(key=lambda x:(x[0],x[1],x[2]["wall_id"])); _,distance,wall,gap=candidates[0]
    if gap is None: return None,"NO_WALL_GAP",[x[2]["wall_id"] for x in candidates]
    return wall,"WALL_OBJECT_GAP_SUPPORT",[x[2]["wall_id"] for x in candidates]


def virtual_opening_closures(walls):
    """Return non-material closure edges used only by the enclosure graph."""
    rows=[]
    for wall in walls:
        origin=wall["wall_solid"]["axis_origin"]; direction=wall["wall_solid"]["axis_direction"]
        for index,opening in enumerate(wall.get("interruptions") or []):
            low,high=opening["interval"]
            geometry=[[origin[0]+low*direction[0],origin[1]+low*direction[1]],
                      [origin[0]+high*direction[0],origin[1]+high*direction[1]]]
            rows.append({"closure_id":_sid("CLOSURE",[wall["wall_id"],index,geometry]),
                         "host_wall_id":wall["wall_id"],"geometry":geometry,
                         "reason":"CANONICAL_WALL_INTERRUPTION","opening_candidate_id":None,
                         "source_evidence":wall.get("source_fragments") or [],"material":False,
                         "graph_role":"ENCLOSURE_ONLY"})
    return rows
