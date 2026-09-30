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

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize, snap, unary_union
from shapely.strtree import STRtree


def _sid(prefix, value):
    return f"{prefix}-" + sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16].upper()


REGION_ROLES = {"BUILDING_INTERIOR", "SEMI_EXTERIOR", "SITE_EXTERIOR", "COURTYARD", "LIGHTWELL", "VOID", "UNBOUNDED_EXTERIOR", "UNKNOWN"}
_INTERIOR_SEMANTICS = {"bedroom", "master_bedroom", "living", "reception", "dining", "kitchen", "kitchenette", "bathroom", "shower", "toilet", "entrance", "vestibule", "shoe_area", "corridor", "lobby", "closet", "storage", "laundry", "utility", "stair", "stair_landing", "elevator", "elevator_lobby", "shaft", "duct", "pipe_shaft", "mechanical_shaft", "electrical_shaft", "office", "shop", "commercial", "mechanical_room", "electrical_room", "boiler_room", "janitor", "common_room"}
_WET_SERVICE_SEMANTICS = {"bathroom", "shower", "toilet", "kitchen", "kitchenette", "laundry", "utility", "shaft", "duct", "pipe_shaft", "mechanical_shaft", "electrical_shaft"}
_SEMI_EXTERIOR_SEMANTICS = {"balcony", "terrace", "roof_terrace", "patio"}
_SITE_EXTERIOR_SEMANTICS = {"yard", "backyard", "parking", "parking_stall", "ramp", "driveway"}
_VOID_SEMANTICS = {"void", "lightwell"}


def _wall_line(wall):
    return LineString(wall["centerline"])


def enumerate_envelope_candidates(walls, *, frame_id, tolerance, semantic_labels=(), objects=(), junctions=(), enclosure_closures=()):
    """Enumerate closed cycles before any envelope selection is attempted."""
    started=time.perf_counter(); tol=max(float(tolerance or .001),1e-8)
    axes=[_wall_line(wall) for wall in walls]
    eligible_closures=[row for row in enclosure_closures
                       if row.get("continuity_status") in {"PROVEN_WALL_CONTINUITY", "SUPPORTED_WALL_CONTINUITY"}
                       and "ENVELOPE_SUPPORT" in (row.get("roles") or [])]
    closure_lines=[LineString(row["geometry"]) for row in eligible_closures]
    polygons=[poly for poly in polygonize(unary_union(axes+closure_lines)) if poly.is_valid and poly.area>tol*tol*4]
    old_selected=max(polygons,key=lambda poly:poly.area) if polygons else None
    rows=[]
    for poly in sorted(polygons,key=lambda item:(-item.area,item.bounds)):
        boundary_ids=[]; internal_ids=[]; source_handles=set(); double=known=0
        for wall,line in zip(walls,axes):
            if line.distance(poly.boundary)<=tol*4:
                boundary_ids.append(wall["wall_id"]); source_handles.update(wall.get("source_handles") or [])
                double+=wall.get("representation")=="DOUBLE_FACE"; known+=wall.get("thickness") is not None
            elif poly.buffer(tol).covers(line.representative_point()): internal_ids.append(wall["wall_id"])
        hosted=[row for row in semantic_labels if row.get("point") and poly.covers(Point(row["point"]))]
        categories=[row.get("semantic_candidate") or row.get("category") for row in hosted]
        obj_count=sum(bool(row.get("point")) and poly.covers(Point(row["point"])) for row in objects)
        jcount=sum(bool(row.get("point")) and poly.buffer(tol).covers(Point(row["point"])) for row in junctions)
        terminating=sum(1 for line in axes for point in (Point(line.coords[0]),Point(line.coords[-1])) if poly.boundary.distance(point)<=tol*4 and poly.buffer(tol).covers(line.representative_point()))
        cid=_sid("ENVCAND",[frame_id,[list(p) for p in poly.exterior.coords]])
        closure_ids=[row["closure_id"] for row,line in zip(eligible_closures,closure_lines)
                     if line.distance(poly.boundary)<=tol*4]
        rows.append({"candidate_id":cid,"frame_id":frame_id,"polygon":[list(p) for p in poly.exterior.coords],"area":poly.area,"perimeter":poly.length,"wall_ids":sorted(boundary_ids),"closure_ids":sorted(closure_ids),"source_handles":sorted(source_handles),"architectural_label_count":len(categories),"habitable_label_count":sum(c in _INTERIOR_SEMANTICS-_WET_SERVICE_SEMANTICS for c in categories),"wet_service_label_count":sum(c in _WET_SERVICE_SEMANTICS for c in categories),"stair_shaft_evidence_count":sum(c in {"stair","stair_landing","elevator","shaft","duct","pipe_shaft"} for c in categories),"exterior_site_label_count":sum(c in _SITE_EXTERIOR_SEMANTICS for c in categories),"yard_terrace_balcony_parking_label_count":sum(c in _SITE_EXTERIOR_SEMANTICS|_SEMI_EXTERIOR_SEMANTICS for c in categories),"semantic_categories":sorted(set(c for c in categories if c)),"internal_wall_length":sum(_wall_line(w).length for w in walls if w["wall_id"] in internal_ids),"internal_partition_count":len(internal_ids),"junction_density":jcount/max(poly.area,1e-12),"fixture_density":obj_count/max(poly.area,1e-12),"boundary_double_face_ratio":double/max(len(boundary_ids),1),"boundary_known_thickness_ratio":known/max(len(boundary_ids),1),"interior_walls_terminating_at_boundary":terminating,"boundary_opening_candidate_count":sum(len(w.get("interruptions") or []) for w in walls if w["wall_id"] in boundary_ids),"cross_level_relation":"NOT_EVALUATED","previously_selected":bool(old_selected and poly.equals(old_selected)),"selection_status":"UNASSESSED"})
    return {"frame_id":frame_id,"candidates":rows,"runtime_seconds":round(time.perf_counter()-started,6)}


def classify_plan_regions(candidate_diagnostic):
    regions=[]
    for candidate in candidate_diagnostic.get("candidates") or []:
        categories=set(candidate.get("semantic_categories") or []); interior=categories&_INTERIOR_SEMANTICS; semi=categories&_SEMI_EXTERIOR_SEMANTICS; site=categories&_SITE_EXTERIOR_SEMANTICS; voids=categories&_VOID_SEMANTICS
        conflict=sum(bool(group) for group in (interior,semi,site,voids))>1
        if conflict: role,status,reason="UNKNOWN","CONFLICT","CONFLICTING_REGION_SEMANTICS"
        elif voids: role,status,reason=("LIGHTWELL" if "lightwell" in voids else "VOID"),"HIGH_CONFIDENCE","ONTOLOGY_VOID_LABEL"
        elif site: role,status,reason="SITE_EXTERIOR","HIGH_CONFIDENCE","ONTOLOGY_SITE_LABEL"
        elif semi: role,status,reason="SEMI_EXTERIOR","HIGH_CONFIDENCE","ONTOLOGY_SEMI_EXTERIOR_LABEL"
        elif interior: role,status,reason="BUILDING_INTERIOR","HIGH_CONFIDENCE","ONTOLOGY_INTERIOR_LABEL"
        else: role,status,reason="UNKNOWN","INPUT_REQUIRED","INSUFFICIENT_INDEPENDENT_EVIDENCE"
        regions.append({"region_id":_sid("REGION",candidate["candidate_id"]),"candidate_id":candidate["candidate_id"],"frame_id":candidate["frame_id"],"geometry":candidate["polygon"],"area":candidate["area"],"role":role,"status":status,"reason":reason,"semantic_evidence":sorted(categories),"wall_ids":candidate["wall_ids"],"adjacent_region_ids":[],"exterior_exposure":"UNKNOWN"})
    geoms=[Polygon(row["geometry"]) for row in regions]
    for i,left in enumerate(geoms):
        for j in range(i+1,len(geoms)):
            if left.boundary.intersection(geoms[j].boundary).length>0:
                regions[i]["adjacent_region_ids"].append(regions[j]["region_id"]); regions[j]["adjacent_region_ids"].append(regions[i]["region_id"])
    return regions


def evidence_based_building_envelope(walls, *, frame_id, tolerance, semantic_labels=(), objects=(), junctions=(), enclosure_closures=()):
    diagnostic=enumerate_envelope_candidates(walls,frame_id=frame_id,tolerance=tolerance,semantic_labels=semantic_labels,objects=objects,junctions=junctions,enclosure_closures=enclosure_closures)
    regions=classify_plan_regions(diagnostic); conflicts=[row for row in regions if row["status"]=="CONFLICT"]
    interior=[Polygon(row["geometry"]) for row in regions if row["role"]=="BUILDING_INTERIOR"]
    interior_semantics={semantic for row in regions if row["role"]=="BUILDING_INTERIOR" for semantic in row["semantic_evidence"]}
    insufficient=len(interior_semantics)<2
    if conflicts or not interior or insufficient:
        reason=("CONFLICTING_INTERIOR_EXTERIOR_EVIDENCE" if conflicts else
                "INSUFFICIENT_INDEPENDENT_INTERIOR_EVIDENCE" if insufficient else
                "NO_DEFENSIBLE_BUILDING_INTERIOR_REGION")
        return ({"building_envelope_id":_sid("ENV",[frame_id,"UNKNOWN",reason]),"frame_id":frame_id,"outer_ring":[],"interior_voids":[],"components":[],"exterior_wall_ids":[],"source_handles":[],"area":0.0,"perimeter":0.0,"confidence":0.0,"status":"INPUT_REQUIRED","reason":reason,"evidence":[{"class":"EVIDENCE_BASED_REGION_CLASSIFICATION","conflict_count":len(conflicts),"interior_region_count":len(interior)}],"schema":"canonical-building-envelope/2.0"},diagnostic,regions)
    merged=unary_union(interior); components=list(merged.geoms) if merged.geom_type=="MultiPolygon" else [merged]; primary=max(components,key=lambda poly:poly.area)
    status="HIGH_CONFIDENCE" if len(components)==1 else "INPUT_REQUIRED"
    boundary_ids=[wall["wall_id"] for wall in walls if _wall_line(wall).distance(merged.boundary)<=max(tolerance*4,1e-7)]
    handles=sorted({handle for wall in walls if wall["wall_id"] in boundary_ids for handle in wall.get("source_handles") or []})
    envelope={"building_envelope_id":_sid("ENV",[frame_id,[list(p) for p in primary.exterior.coords]]),"frame_id":frame_id,"outer_ring":[list(p) for p in primary.exterior.coords],"interior_voids":[[list(p) for p in ring.coords] for ring in primary.interiors],"components":[{"outer_ring":[list(p) for p in poly.exterior.coords],"interior_voids":[[list(p) for p in ring.coords] for ring in poly.interiors]} for poly in components],"exterior_wall_ids":boundary_ids,"source_handles":handles,"area":merged.area,"perimeter":merged.length,"confidence":.85 if status=="HIGH_CONFIDENCE" else .4,"status":status,"reason":"EVIDENCE_SUPPORTED_INTERIOR_UNION" if status=="HIGH_CONFIDENCE" else "DISCONNECTED_INTERIOR_COMPONENTS","evidence":[{"class":"EVIDENCE_BASED_REGION_CLASSIFICATION","interior_region_count":len(interior),"site_region_count":sum(r["role"]=="SITE_EXTERIOR" for r in regions),"semi_exterior_region_count":sum(r["role"]=="SEMI_EXTERIOR" for r in regions)}],"schema":"canonical-building-envelope/2.0"}
    return envelope,diagnostic,regions


def _axis(line):
    a, b = list(line.coords)[0], list(line.coords)[-1]
    dx, dy = b[0]-a[0], b[1]-a[1]; length=max(math.hypot(dx,dy), 1e-12)
    ux, uy = dx/length, dy/length
    if ux < 0 or (abs(ux) < 1e-9 and uy < 0): ux, uy = -ux, -uy
    angle=(math.degrees(math.atan2(uy,ux))+180)%180
    return (ux,uy),(-uy,ux),angle,length


def _project_interval(line, origin, direction):
    values=[(p[0]-origin[0])*direction[0]+(p[1]-origin[1])*direction[1] for p in line.coords]
    return min(values),max(values)


def _pair_wall_faces(walls, clusters, tol):
    """Greedily form local double-face walls without a global thickness default."""
    if not walls or not clusters: return walls
    medians=[float(c["median_thickness"]) for c in clusters]
    axes=[LineString(w["centerline"]) for w in walls]; tree=STRtree(axes)
    candidates=[]
    for i,line in enumerate(axes):
        u,n,angle,length=_axis(line)
        for raw in tree.query(line.buffer(max(medians)*1.6+tol)):
            j=int(raw)
            if j<=i: continue
            other=axes[j]; ou,on,oa,ol=_axis(other)
            if min(abs(angle-oa),180-abs(angle-oa))>2: continue
            distance=line.distance(other); cluster=min(medians,key=lambda value:abs(value-distance))
            if abs(distance-cluster)>max(cluster*.3,tol*4): continue
            origin=list(line.coords)[0]; left=_project_interval(line,origin,u); right=_project_interval(other,origin,u)
            overlap=max(0,min(left[1],right[1])-max(left[0],right[0]))
            if overlap/max(min(length,ol),1e-9)<.55: continue
            candidates.append((abs(distance-cluster),-overlap,i,j,distance,cluster))
    used=set(); paired=[]
    for _,_,i,j,distance,cluster in sorted(candidates):
        if i in used or j in used: continue
        used.update((i,j)); a,b=walls[i],walls[j]; la,lb=axes[i],axes[j]
        longer=la if la.length>=lb.length else lb; u,n,angle,_=_axis(longer); base=list(longer.coords)[0]
        ia=_project_interval(la,base,u); ib=_project_interval(lb,base,u); lo=min(ia[0],ib[0]); hi=max(ia[1],ib[1])
        # Center the axis between the two proven faces.
        midpoint=la.interpolate(.5,normalized=True); signed=(lb.interpolate(.5,normalized=True).x-midpoint.x)*n[0]+(lb.interpolate(.5,normalized=True).y-midpoint.y)*n[1]
        shift=signed/2
        origin=[base[0]+shift*n[0],base[1]+shift*n[1]]
        center=LineString([(origin[0]+lo*u[0],origin[1]+lo*u[1]),(origin[0]+hi*u[0],origin[1]+hi*u[1])])
        def projected_gaps(wall):
            old_origin=wall["wall_solid"]["axis_origin"]; old_u=wall["wall_solid"]["axis_direction"]
            result=[]
            for opening in wall.get("interruptions") or []:
                x,y=opening["interval"]
                points=[(old_origin[0]+x*old_u[0],old_origin[1]+x*old_u[1]),(old_origin[0]+y*old_u[0],old_origin[1]+y*old_u[1])]
                values=[(p[0]-origin[0])*u[0]+(p[1]-origin[1])*u[1] for p in points]
                result.append([min(values),max(values)])
            return result
        ga,gb=projected_gaps(a),projected_gaps(b); interruptions=[]
        for left in ga:
            matches=[right for right in gb if min(left[1],right[1])-max(left[0],right[0])>tol*2]
            if matches:
                right=max(matches,key=lambda row:min(left[1],row[1])-max(left[0],row[0]))
                interval=[max(left[0],right[0]),min(left[1],right[1])]
                interruptions.append({"interval":interval,"kind":"SUPPORTED_OPENING","face_a_gap":left,"face_b_gap":right,
                                      "classification":"UNKNOWN_OPENING","confidence":.8,"status":"HIGH_CONFIDENCE"})
            else:
                interruptions.append({"interval":left,"kind":"UNKNOWN_FRAGMENTATION","face_a_gap":left,"face_b_gap":None,
                                      "classification":"FRAGMENTATION_GAP","confidence":.35,"status":"AMBIGUOUS"})
        for right in gb:
            if not any(min(right[1],left[1])-max(right[0],left[0])>tol*2 for left in ga):
                interruptions.append({"interval":right,"kind":"UNKNOWN_FRAGMENTATION","face_a_gap":None,"face_b_gap":right,
                                      "classification":"FRAGMENTATION_GAP","confidence":.35,"status":"AMBIGUOUS"})
        cuts=sorted(interruptions,key=lambda row:row["interval"]); occupied=[]; cursor=lo
        for opening in cuts:
            start,end=opening["interval"]
            if start>cursor+tol: occupied.append([cursor,start])
            cursor=max(cursor,end)
        if cursor<hi-tol: occupied.append([cursor,hi])
        handles=sorted(set(a.get("source_handles",[])+b.get("source_handles",[])))
        wid=_sid("WALL",[a["frame_id"],"DOUBLE_FACE",a["wall_id"],b["wall_id"]])
        paired.append({"wall_id":wid,"frame_id":a["frame_id"],"level_id":None,"wall_type":"UNKNOWN",
                       "representation":"DOUBLE_FACE","centerline":[list(p) for p in center.coords],
                       "face_a":a["centerline"],"face_b":b["centerline"],
                       "wall_solid":{"occupied_intervals":occupied,"axis_origin":origin,"axis_direction":[u[0],u[1]]},
                       "thickness":distance,"thickness_status":"INFERRED_LOCAL_CLUSTER","orientation":angle,
                       "length":center.length,"source_fragments":sorted(set(a["source_fragments"]+b["source_fragments"])),
                       "source_handles":handles,"junction_start":None,"junction_end":None,"junctions":[],
                       "interruptions":interruptions,"candidate_openings":[],"confidence":.9,"status":"HIGH_CONFIDENCE",
                       "evidence":[{"class":"PAIRED_WALL_FACES","face_wall_ids":[a["wall_id"],b["wall_id"]],
                                    "measured_thickness":distance,"local_cluster":cluster}],
                       "derived_geometry_provenance":{"method":"LOCAL_FACE_PAIRING","tolerance":tol}})
    paired.extend(wall for index,wall in enumerate(walls) if index not in used)
    return sorted(paired,key=lambda wall:wall["wall_id"])


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
            evidence_states=sorted({rows[i].get("wall_evidence_state") for i in group
                                    if rows[i].get("wall_evidence_state")})
            recovered=any(rows[i].get("admission_trace") for i in group)
            wid=_sid("WALL",[frame_id,round(angle,3),[(round(a,6),round(b,6)) for a,b,_ in merged],handles])
            walls.append({"wall_id":wid,"frame_id":frame_id,"level_id":None,"wall_type":"UNKNOWN",
                          "representation":"COMPOSITE" if len(group)>1 else "SINGLE_LINE",
                          "centerline":[list(p) for p in center.coords],"face_a":None,"face_b":None,
                          "wall_solid":{"occupied_intervals":[[a,b] for a,b,_ in merged],"axis_origin":list(origin),"axis_direction":[u[0],u[1]]},
                          "thickness":None,"thickness_status":"UNKNOWN",
                          "orientation":angle,"length":center.length,"source_fragments":[rows[i]["segment_id"] for i in group],
                          "source_handles":handles,"junction_start":None,"junction_end":None,"junctions":[],
                          "interruptions":[{"interval":g,"kind":"UNKNOWN_FRAGMENTATION","classification":"FRAGMENTATION_GAP",
                                            "confidence":.25,"status":"AMBIGUOUS"} for g in gaps],"candidate_openings":[],
                          "confidence":.8 if len(group)>1 else (.72 if recovered else .65),
                          "status":"HIGH_CONFIDENCE" if len(group)>1 else ("SUPPORTED_PARTITION" if recovered else "AMBIGUOUS"),
                          "evidence":[{"class":"COLLINEAR_FRAGMENT_STITCHING","source_interval_count":len(merged),"gap_count":len(gaps)},
                                      {"class":"SOURCE_WALL_ADMISSION","states":evidence_states,
                                       "iteratively_recovered":recovered}],
                          "derived_geometry_provenance":{"method":"ORIENTATION_OFFSET_BUCKET_AND_PROJECTED_INTERVALS","tolerance":tol}})
    walls=_pair_wall_faces(walls,clusters,tol)
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
    if len(polys)!=1:
        return {"building_envelope_id":_sid("ENV",[frame_id,"AMBIGUOUS_CYCLES"]),"frame_id":frame_id,"outer_ring":[],"interior_voids":[],"components":[],"exterior_wall_ids":[],"source_handles":[],"area":0.0,"perimeter":0.0,"confidence":0.0,"status":"INPUT_REQUIRED","reason":"MULTIPLE_UNCLASSIFIED_WALL_CYCLES","schema":"canonical-building-envelope/2.0","evidence":[{"class":"CANONICAL_WALL_CYCLE_ENUMERATION","polygon_count":len(polys)}]}
    poly=polys[0]
    ring=[list(p) for p in list(poly.exterior.coords)]; handles=sorted({h for w in walls for h in w["source_handles"]})
    return {"building_envelope_id":_sid("ENV",[frame_id,ring]),"frame_id":frame_id,"outer_ring":ring,
            "interior_voids":[[list(p) for p in hole.coords] for hole in poly.interiors],
            "exterior_wall_ids":[w["wall_id"] for w in walls if LineString(w["centerline"]).distance(poly.boundary)<=max(tolerance*4,1e-7)],
            "source_handles":handles,"area":poly.area,"perimeter":poly.length,"confidence":.75,
            "components":[{"outer_ring":ring,"interior_voids":[[list(p) for p in hole.coords] for hole in poly.interiors]}],"schema":"canonical-building-envelope/2.0","status":"HIGH_CONFIDENCE","evidence":[{"class":"SINGLE_UNAMBIGUOUS_CANONICAL_WALL_CYCLE","polygon_count":len(polys)}]}


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
        interval=[min(values),max(values)]; gaps=[x["interval"] for x in wall.get("interruptions",[])
                                                if x.get("kind") in {"PROVEN_OPENING","SUPPORTED_OPENING","LIKELY_OPENING"}]
        gap_match=next((g for g in gaps if min(interval[1],g[1])-max(interval[0],g[0])>=-search),None)
        candidates.append((0 if gap_match else 1,distance,wall,gap_match))
    if not candidates: return None,"NO_NEARBY_WALL",[]
    candidates.sort(key=lambda x:(x[0],x[1],x[2]["wall_id"])); _,distance,wall,gap=candidates[0]
    if gap is None: return None,"NO_WALL_GAP",[x[2]["wall_id"] for x in candidates]
    return wall,"WALL_OBJECT_GAP_SUPPORT",[x[2]["wall_id"] for x in candidates]


def canonical_enclosure_continuity(walls, *, frame_id=None):
    """Classify wall interruptions before envelope inference.

    A closure expresses continuity of enclosure topology, never wall material
    and never portal semantics.  Only independently proven double-face gaps are
    promoted automatically; supported/insufficient rows remain diagnostic.
    """
    rows=[]
    for wall in walls:
        origin=wall["wall_solid"]["axis_origin"]; direction=wall["wall_solid"]["axis_direction"]
        for index,opening in enumerate(wall.get("interruptions") or []):
            low,high=opening["interval"]
            geometry=[[origin[0]+low*direction[0],origin[1]+low*direction[1]],
                      [origin[0]+high*direction[0],origin[1]+high*direction[1]]]
            both_faces=bool(opening.get("face_a_gap") and opening.get("face_b_gap"))
            double=wall.get("representation")=="DOUBLE_FACE"
            kind=opening.get("kind")
            if double and both_faces and kind in {"PROVEN_OPENING","SUPPORTED_OPENING","LIKELY_OPENING"}:
                continuity,status,confidence,reason=("PROVEN_WALL_CONTINUITY","PROVEN",.95,
                                                     "PAIRED_FACES_CONTINUE_ACROSS_MATCHED_GAP")
                roles=["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]
            elif kind in {"PROVEN_OPENING","SUPPORTED_OPENING","LIKELY_OPENING"}:
                continuity,status,confidence,reason=("SUPPORTED_WALL_CONTINUITY","SUPPORTED",.65,
                                                     "COLLINEAR_WALL_INTERRUPTION_REQUIRES_CORROBORATION")
                roles=[]
            else:
                continuity,status,confidence,reason=("INSUFFICIENT_CONTINUITY","INPUT_REQUIRED",.25,
                                                     "UNMATCHED_OR_DRAFTING_FRAGMENTATION")
                roles=[]
            rows.append({"closure_id":_sid("CLOSURE",[wall["wall_id"],index,geometry]),
                         "frame_id":frame_id or wall.get("frame_id"),"host_wall_id":wall["wall_id"],
                         "axis_interval":[low,high],"geometry":geometry,
                         "continuity_status":continuity,"status":status,
                         "wall_representation":wall.get("representation"),
                         "face_a_support":bool(opening.get("face_a_gap")),
                         "face_b_support":bool(opening.get("face_b_gap")),
                         "collinear_support":kind in {"PROVEN_OPENING","SUPPORTED_OPENING","LIKELY_OPENING"},
                         "junction_support":False,"source_handles":wall.get("source_handles") or [],
                         "source_evidence":wall.get("source_fragments") or [],"gap_width":high-low,
                         "material":False,"roles":roles,"possible_opening_type":"UNKNOWN",
                         "confidence":confidence,"evidence":[{"class":"WALL_INTERRUPTION_CONTINUITY","kind":kind,
                                                               "paired_face_gap":both_faces}],"reason":reason})
    return rows


def source_supported_endpoint_closures(walls, *, frame_id=None, tolerance=0.001):
    """Close bounded drafting gaps between independently proven wall axes.

    The maximum join distance is derived from local double-face thicknesses.
    These records are enclosure topology only: they never claim material,
    routing, portal or access authority.
    """
    tol=max(float(tolerance or .001),1e-9)
    proven=[wall for wall in walls if wall.get("status")=="HIGH_CONFIDENCE"
            and wall.get("representation")=="DOUBLE_FACE" and wall.get("thickness")]
    if len(proven)<2:return []
    thicknesses=sorted(float(wall["thickness"]) for wall in proven)
    typical=thicknesses[len(thicknesses)//2]
    corner_limit=max(tol*8,typical*3.0)
    opening_limit=max(corner_limit,typical*12.0)
    supported=[wall for wall in walls if wall.get("status")=="SUPPORTED_PARTITION"
               and any(e.get("class")=="SOURCE_WALL_ADMISSION" and e.get("iteratively_recovered")
                       for e in wall.get("evidence") or [])]
    candidates=proven+supported
    axes=[_wall_line(wall) for wall in candidates]; endpoints=[]
    for index,line in enumerate(axes):
        endpoints.extend([(index,Point(line.coords[0])),(index,Point(line.coords[-1]))])
    tree=STRtree([point for _,point in endpoints]); proposals={}
    for endpoint_index,(wall_index,point) in enumerate(endpoints):
        left=candidates[wall_index]; (left_u,left_n,left_angle,_)=_axis(axes[wall_index])
        for raw in tree.query(point.buffer(opening_limit)):
            other_endpoint_index=int(raw)
            if other_endpoint_index<=endpoint_index:continue
            other_wall_index,other_point=endpoints[other_endpoint_index]
            if other_wall_index==wall_index:continue
            right=candidates[other_wall_index]; (_,_,right_angle,_)=_axis(axes[other_wall_index])
            delta=min(abs(left_angle-right_angle),180-abs(left_angle-right_angle))
            distance=point.distance(other_point)
            if distance<=tol:continue
            relation=None; limit=corner_limit
            if delta<=3.0:
                # Collinear separated wall spans support a bounded opening gap.
                perpendicular_offset=abs((other_point.x-point.x)*left_n[0]+(other_point.y-point.y)*left_n[1])
                if perpendicular_offset>max(tol*4,typical*.35):continue
                both_material=left in proven and right in proven
                relation="COLLINEAR_WALL_GAP" if both_material else "SUPPORTED_PARTITION_ENDPOINT_JOIN"
                limit=opening_limit if both_material else corner_limit
            elif abs(delta-90)<=3.0:
                relation=("EXTERIOR_CORNER_JOIN" if left in proven and right in proven
                          else "SUPPORTED_PARTITION_ENDPOINT_JOIN")
            else:continue
            if distance>limit:continue
            geometry=sorted([[point.x,point.y],[other_point.x,other_point.y]])
            host_wall_ids=sorted([left["wall_id"],right["wall_id"]])
            closure_id=_sid("ENDCLOSE",[host_wall_ids,geometry])
            proposals[closure_id]={"closure_id":closure_id,"frame_id":frame_id or left.get("frame_id"),
                "host_wall_ids":host_wall_ids,"geometry":geometry,
                "continuity_status":"PROVEN_WALL_CONTINUITY","status":"PROVEN",
                "material":False,"material_geometry":"NONE","wall_authority":"NONE",
                "routing_authority":"NONE","portal_authority":"NONE","access_authority":"NONE",
                "roles":["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"],"reason":relation,
                "gap_width":distance,"derived_join_limit":limit,
                "_endpoint_indexes":[endpoint_index,other_endpoint_index],
                "source_handles":sorted(set((left.get("source_handles") or [])+(right.get("source_handles") or []))),
                "source_evidence":sorted(set((left.get("source_fragments") or [])+(right.get("source_fragments") or []))),
                "evidence":[{"class":relation,"wall_angle_delta":delta,"local_wall_thickness":typical}]}
    selected=[]; used_endpoints=set()
    for row in sorted(proposals.values(),key=lambda item:(item["gap_width"],item["closure_id"])):
        indexes=set(row.pop("_endpoint_indexes"))
        if indexes & used_endpoints: continue
        used_endpoints.update(indexes); selected.append(row)
    return sorted(selected,key=lambda row:row["closure_id"])


def classify_internal_wall_gaps(walls, closures, opening_evidence, *, frame_id=None, tolerance=.001):
    """Classify discontinuities before they may enter subdivision topology.

    Opening evidence remains supporting-only.  It may identify the likely gap
    type, but does not itself verify a Portal or create material geometry.
    """
    wall_by_id={wall["wall_id"]:wall for wall in walls}
    opening_rows=[row for row in opening_evidence or []
                  if row.get("status")=="OPENING_EVIDENCE_PRESENT"]
    rows=[]
    for closure in closures:
        host_ids=set(closure.get("host_wall_ids") or [])
        if closure.get("host_wall_id"): host_ids.add(closure["host_wall_id"])
        gap_width=float(closure.get("gap_width") or LineString(closure["geometry"]).length)
        thicknesses=[float(wall_by_id[wid]["thickness"]) for wid in host_ids
                     if wid in wall_by_id and wall_by_id[wid].get("thickness")]
        local_thickness=sorted(thicknesses)[len(thicknesses)//2] if thicknesses else None
        gap_line=LineString(closure["geometry"])
        matching=[]; opening_matches=[]
        for opening in opening_rows:
            if not host_ids.intersection(opening.get("candidate_host_wall_ids") or []): continue
            geometry=opening.get("geometry") or {}
            points=geometry.get("points") or []
            if len(points)>=2:
                opening_geometry=LineString(points)
                opening_width=opening_geometry.length
            elif geometry.get("point"):
                opening_geometry=Point(geometry["point"]); opening_width=0.0
            elif geometry.get("bounds") and len(geometry["bounds"])==4:
                opening_geometry=box(*geometry["bounds"]); opening_width=min(
                    geometry["bounds"][2]-geometry["bounds"][0],
                    geometry["bounds"][3]-geometry["bounds"][1])
            else: continue
            distance=gap_line.distance(opening_geometry)
            locality_limit=max(float(tolerance or .001)*5,
                               (local_thickness or 0.0)*1.5,
                               min(gap_width,opening_width)*.5)
            if distance>locality_limit: continue
            matching.append(opening)
            opening_matches.append({"opening_evidence_id":opening["opening_evidence_id"],
                                    "distance_to_gap":distance,
                                    "derived_locality_limit":locality_limit})
        portal_types=sorted({str(row.get("candidate_type") or "").upper() for row in matching})
        reason=closure.get("reason")
        if "DOOR" in portal_types:
            classification,status="DOOR_GAP","SUPPORTED"
        elif "WINDOW" in portal_types:
            classification,status="WINDOW_GAP","SUPPORTED"
        elif reason=="EXTERIOR_CORNER_JOIN":
            classification,status="DRAFTING_BREAK","PROVEN"
        elif (reason=="COLLINEAR_WALL_GAP" and local_thickness
              and gap_width<=local_thickness*1.5):
            classification,status="MISSING_WALL_GEOMETRY","SUPPORTED"
        elif (reason=="SUPPORTED_PARTITION_ENDPOINT_JOIN" and local_thickness
              and gap_width<=local_thickness):
            classification,status="DRAFTING_BREAK","SUPPORTED"
        else:
            classification,status="AMBIGUOUS_GAP","INPUT_REQUIRED"
        gap_id=_sid("GAP",[frame_id,sorted(host_ids),closure.get("geometry")])
        closure.update({"gap_id":gap_id,"gap_classification":classification,
                        "gap_status":status,"portal_evidence_ids":sorted(
                            row["opening_evidence_id"] for row in matching),
                        "opening_locality_matches":sorted(opening_matches,key=lambda row:row["opening_evidence_id"]),
                        "portal_ref":None,"local_wall_thickness":local_thickness})
        rows.append({"gap_id":gap_id,"frame_id":frame_id,"host_wall_ids":sorted(host_ids),
                     "geometry":closure.get("geometry"),"gap_width":gap_width,
                     "local_wall_thickness":local_thickness,"classification":classification,
                     "status":status,"source_handles":closure.get("source_handles") or [],
                     "portal_evidence_ids":closure["portal_evidence_ids"],
                     "opening_locality_matches":closure["opening_locality_matches"],
                     "closure_id":closure.get("closure_id"),
                     "material_geometry":"NONE","wall_authority":"NONE",
                     "routing_authority":"NONE","portal_authority":"NONE"})
    return sorted(rows,key=lambda row:row["gap_id"])


def virtual_opening_closures(walls):
    """Backward-compatible view containing only promoted enclosure closures."""
    return [row for row in canonical_enclosure_continuity(walls)
            if "ENCLOSURE_BARRIER" in row.get("roles",[])]


def canonical_space_subdivision(walls, envelope, *, frame_id, tolerance, void_boundaries=None, enclosure_closures=None):
    """Build physical-space cells from the canonical enclosure topology.

    Unlike the legacy path this function does not treat an arbitrary collection
    of stitched axes as space truth.  Material wall intervals, explicit virtual
    closures, the selected building envelope, and supported void boundaries are
    assembled into one noded barrier graph first.  Openings therefore remain
    non-material while still closing the *enclosure* graph.
    """
    started=time.perf_counter(); tol=max(float(tolerance or .001),1e-8)
    outer=(envelope or {}).get("outer_ring") or []
    if len(outer)<4 or (envelope or {}).get("status") not in {"VERIFIED","HIGH_CONFIDENCE"}:
        return {"status":"INPUT_REQUIRED","authority":"LEGACY_FALLBACK",
                "reason":"CANONICAL_BUILDING_ENVELOPE_UNPROVEN","cells":[],"barriers":[],
                "closures":[],"edges":[],"runtime_seconds":round(time.perf_counter()-started,6)}
    shell=Polygon(outer,(envelope or {}).get("interior_voids") or [])
    if not shell.is_valid or shell.area<=0:
        return {"status":"CONFLICT","authority":"LEGACY_FALLBACK","reason":"INVALID_BUILDING_ENVELOPE",
                "cells":[],"barriers":[],"closures":[],"edges":[],
                "runtime_seconds":round(time.perf_counter()-started,6)}

    barriers=[]; void_polygons=[]
    # The envelope is an active barrier and an active spatial constraint.
    for a,b in zip(list(shell.exterior.coords),list(shell.exterior.coords)[1:]):
        barriers.append({"barrier_id":_sid("BAR",[frame_id,"ENVELOPE",a,b]),"kind":"ENVELOPE",
                         "geometry":[list(a),list(b)],"wall_id":None,"closure_id":None})
    for ring in shell.interiors:
        coords=list(ring.coords)
        for a,b in zip(coords,coords[1:]):
            barriers.append({"barrier_id":_sid("BAR",[frame_id,"VOID",a,b]),"kind":"VOID",
                             "geometry":[list(a),list(b)],"wall_id":None,"closure_id":None})
    for boundary in void_boundaries or []:
        coords=list(boundary.coords) if hasattr(boundary,"coords") else boundary
        candidate=Polygon(coords)
        if candidate.is_valid and candidate.area>tol*tol*4: void_polygons.append(candidate)
        for a,b in zip(coords,coords[1:]):
            barriers.append({"barrier_id":_sid("BAR",[frame_id,"VOID",a,b]),"kind":"VOID",
                             "geometry":[list(a),list(b)],"wall_id":None,"closure_id":None})

    for wall in walls:
        origin=wall["wall_solid"]["axis_origin"]; u=wall["wall_solid"]["axis_direction"]
        for index,(low,high) in enumerate(wall["wall_solid"].get("occupied_intervals") or []):
            a=[origin[0]+low*u[0],origin[1]+low*u[1]]; b=[origin[0]+high*u[0],origin[1]+high*u[1]]
            barriers.append({"barrier_id":_sid("BAR",[wall["wall_id"],"MATERIAL",index,a,b]),
                             "kind":"WALL_MATERIAL","geometry":[a,b],"wall_id":wall["wall_id"],"closure_id":None})
    closures=(list(enclosure_closures) if enclosure_closures is not None else virtual_opening_closures(walls))
    for closure in closures:
        if "ENCLOSURE_BARRIER" not in closure.get("roles",["ENCLOSURE_BARRIER"]):
            continue
        barriers.append({"barrier_id":_sid("BAR",[closure["closure_id"],"ENCLOSURE"]),
                         "kind":"VIRTUAL_CLOSURE","geometry":closure["geometry"],
                         "wall_id":closure.get("host_wall_id"),
                         "host_wall_ids":closure.get("host_wall_ids") or
                                           ([closure["host_wall_id"]] if closure.get("host_wall_id") else []),
                         "closure_id":closure["closure_id"]})

    source_lines=[LineString(row["geometry"]) for row in barriers]
    # Snap before unary_union; unary_union then explicitly nodes every crossing.
    network=unary_union(source_lines)
    network=snap(network,network,max(tol*2,1e-9))
    noded=unary_union(network)
    raw=list(polygonize(noded))
    cells=[]
    for poly in raw:
        representative=poly.representative_point()
        if not shell.covers(representative):
            continue
        clipped=poly.intersection(shell)
        if clipped.geom_type == "Polygon":
            candidates=[clipped]
        elif clipped.geom_type in {"MultiPolygon","GeometryCollection"}:
            candidates=[part for part in clipped.geoms if part.geom_type=="Polygon"]
        else:
            candidates=[]
        for candidate in candidates:
            if candidate.is_empty or candidate.area<=tol*tol*4: continue
            # The bounded face inside a verified void is topology, not an
            # occupied Physical Space.  The surrounding polygon retains the
            # ring as a hole through polygonization.
            if any(void.covers(candidate.representative_point()) for void in void_polygons): continue
            quality="FACE_RESOLVED" if all(w.get("face_a") and w.get("face_b") for w in walls) else "CENTERLINE_APPROXIMATION"
            cells.append({"cell_id":_sid("CELL",[frame_id,list(candidate.exterior.coords)]),
                          "frame_id":frame_id,"topology_polygon":[list(p) for p in candidate.exterior.coords],
                          "physical_polygon":[list(p) for p in candidate.exterior.coords],
                          "interior_rings":[[list(p) for p in ring.coords] for ring in candidate.interiors],
                          "boundary_quality":quality,"region_class":"INTERIOR","area":candidate.area})
    cells.sort(key=lambda row:row["cell_id"])
    edges=[]
    polygons=[Polygon(c["topology_polygon"],c["interior_rings"]) for c in cells]
    for i,left in enumerate(polygons):
        for j in range(i+1,len(polygons)):
            shared=left.boundary.intersection(polygons[j].boundary)
            if shared.length<=tol: continue
            supported=[row for row,line in zip(barriers,source_lines) if line.intersection(shared.buffer(tol)).length>tol]
            wall_ids=sorted({row["wall_id"] for row in supported if row.get("wall_id")})
            closure_ids=sorted({row["closure_id"] for row in supported if row.get("closure_id")})
            edges.append({"space_a":cells[i]["cell_id"],"space_b":cells[j]["cell_id"],
                          "relationship":"TOPOLOGICAL_NEIGHBOR","boundary_wall_ids":wall_ids,
                          "closure_ids":closure_ids,"shared_length":shared.length})
    return {"status":"PASS" if cells else "INPUT_REQUIRED","authority":"CANONICAL" if cells else "LEGACY_FALLBACK",
            "reason":None if cells else "NO_CANONICAL_CELLS","cells":cells,"barriers":barriers,
            "closures":closures,"edges":edges,"noded":True,"envelope_id":envelope.get("building_envelope_id"),
            "runtime_seconds":round(time.perf_counter()-started,6)}
