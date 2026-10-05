"""Source-derived, pre-authority architectural candidate topology.

This module deliberately operates before canonical wall/envelope authority.
Its output is a bounded hypothesis space, never architectural truth.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize_full, unary_union
from shapely.strtree import STRtree

HARD = "HARD_ACCEPTED_ARCHITECTURAL"
SOFT = "SOFT_ARCHITECTURAL_CANDIDATE"
EXCLUDED = "HARD_EXCLUDED_NON_ARCHITECTURAL"


def _semantic_candidate(text):
    """Return only deterministic label semantics; never infer missing text."""
    value=" ".join(str(text or "").strip().lower().replace("ي","ی").replace("ك","ک").split())
    rules=(("حیاط","yard"),("yard","yard"),("شفت","shaft"),("shaft","shaft"),
           ("راه پله","stair"),("راه‌پله","stair"),("پله","stair"),("stair","stair"),
           ("آشپزخانه","kitchen"),("kitchen","kitchen"),("پذیرایی","reception"),
           ("نشیمن","living"),("هال","living"),("living","living"),("خواب","bedroom"),
           ("bedroom","bedroom"),("حمام","bathroom"),("bathroom","bathroom"),
           ("سرویس","toilet"),("توالت","toilet"),("toilet","toilet"),("لابی","lobby"),
           ("lobby","lobby"),("پارکینگ","parking"),("parking","parking"),
           ("انبار","storage"),("storage","storage"),("راهرو","corridor"),("corridor","corridor"))
    return next((semantic for token,semantic in rules if token in value),"UNKNOWN")


def _sid(prefix, value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str)
    return f"{prefix}-"+sha256(raw.encode()).hexdigest()[:10].upper()


def _tier(row):
    semantic=str(row.get("semantic_class") or ""); reason=str(row.get("reason") or "")
    state=str(row.get("wall_evidence_state") or ""); status=str(row.get("status") or "")
    exclusions={"PRINT_BORDER","DIMENSION","DIMENSION_CHAIN","LEADER","HATCH","GLYPH","ANNOTATION",
                "FURNITURE","FIXTURE_DETAIL","CABINET_DETAIL","STAIR_TREAD","SHEET_FRAME","GRID_AXIS",
                "COLUMN","STAIR_ASSEMBLY","WINDOW_ASSEMBLY","DOOR_ASSEMBLY","DOUBLE_DOOR_ASSEMBLY",
                "OPEN_PASSAGE","DINING_TABLE_ASSEMBLY","VEHICLE","PARKING_BAY","SECTION_CUT",
                "GENERIC_NON_ENCLOSURE_OBJECT","HARD_EXCLUDED_NON_ENCLOSURE_OBJECT"}
    if reason in {"GLYPH_FILTER","NON_BOUNDARY_LAYER","NESTED_SYMBOL_GEOMETRY"}:
        return EXCLUDED,[reason]
    if any(token in semantic or token in reason for token in exclusions):
        return EXCLUDED,[semantic or reason]
    if status=="ACCEPTED" or state=="CONFIRMED_WALL": return HARD,[state or status]
    return SOFT,[state or status or "ANONYMOUS_SOURCE_GEOMETRY"]


def source_segments(model, frame, tolerance):
    clip=box(*frame["bounds"]); frame_boundary=clip.boundary; rows=[]
    source=list(model.get("architectural_segments") or [])+list(model.get("boundary_extraction_rejections") or [])
    for raw in source:
        if raw.get("frame_id") not in {None,frame["frame_id"]}: continue
        geometry=raw.get("geometry") or []
        if len(geometry)<2: continue
        try: clipped=LineString(geometry).intersection(clip)
        except Exception: continue
        pieces=[clipped] if clipped.geom_type=="LineString" else list(getattr(clipped,"geoms",[]))
        for piece in pieces:
            if piece.is_empty or piece.length<=tolerance: continue
            # The authoritative print/view frame is calibration context, not
            # a possible building wall. Keep its removal explicit and local.
            if piece.distance(frame_boundary)<=tolerance*3 and piece.intersection(frame_boundary.buffer(tolerance*3)).length>=piece.length*.95:
                continue
            tier,evidence=_tier(raw); coords=[[float(x),float(y)] for x,y in piece.coords]
            rows.append({"segment_id":raw.get("segment_id") or _sid("SRC",[raw.get("handle"),coords]),
                "source_handle":raw.get("source_handle") or raw.get("handle"),
                "layer":(raw.get("source_context") or {}).get("layer") or raw.get("layer"),
                "entity_type":(raw.get("source_context") or {}).get("entity_type") or raw.get("entity_type"),
                "geometry":coords,"classification":raw.get("semantic_class") or "UNKNOWN_GEOMETRY",
                "classification_evidence":evidence,"authority_tier":tier})
    unique={}
    for row in rows:
        ends=sorted(tuple(round(v,7) for v in point) for point in (row["geometry"][0],row["geometry"][-1]))
        key=tuple(ends); current=unique.get(key)
        if current is None or (current["authority_tier"]==SOFT and row["authority_tier"]==HARD): unique[key]=row
    return sorted(unique.values(),key=lambda row:row["segment_id"])


def activity_region(segments,texts,objects,frame,tolerance):
    evidence=[LineString(row["geometry"]) for row in segments if row["authority_tier"]!=EXCLUDED]
    points=[Point(row["point"]) for row in texts+objects if row.get("point")]
    if not evidence and not points: return box(*frame["bounds"]),["FRAME_FALLBACK_NO_ACTIVITY_EVIDENCE"]
    merged=unary_union(evidence+points); bounds=merged.bounds
    span=max(bounds[2]-bounds[0],bounds[3]-bounds[1],tolerance)
    return merged.convex_hull.buffer(max(tolerance*5,span*.015),join_style=2).intersection(box(*frame["bounds"])),["SOURCE_GEOMETRY_AND_LABEL_EXTENT"]


def connected_components(segments,tolerance,texts,objects):
    eligible=[row for row in segments if row["authority_tier"]!=EXCLUDED]
    if not eligible:return []
    lines=[LineString(row["geometry"]) for row in eligible]; tree=STRtree(lines); parent=list(range(len(lines)))
    def find(i):
        while parent[i]!=i: parent[i]=parent[parent[i]]; i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    for i,line in enumerate(lines):
        for raw in tree.query(line.buffer(tolerance*2)):
            j=int(raw)
            if j>i and line.distance(lines[j])<=tolerance*2:union(i,j)
    groups=defaultdict(list)
    for i in range(len(lines)):groups[find(i)].append(i)
    result=[]
    for indexes in groups.values():
        geometry=unary_union([lines[i] for i in indexes]); extent=box(*geometry.bounds)
        result.append({"component_id":_sid("COMP",sorted(eligible[i]["segment_id"] for i in indexes)),
            "span_bounds":list(geometry.bounds),"span_area":extent.area,"segment_count":len(indexes),
            "hard_segment_count":sum(eligible[i]["authority_tier"]==HARD for i in indexes),
            "soft_segment_count":sum(eligible[i]["authority_tier"]==SOFT for i in indexes),
            "label_count_in_extent":sum(extent.covers(Point(t["point"])) for t in texts if t.get("point")),
            "object_count_in_extent":sum(extent.covers(Point(o["point"])) for o in objects if o.get("point")),
            "source_segment_ids":sorted(eligible[i]["segment_id"] for i in indexes)})
    return sorted(result,key=lambda row:(-row["label_count_in_extent"],-row["span_area"],row["component_id"]))


def bridge_candidates(segments,tolerance,max_candidates=24):
    eligible=[row for row in segments if row["authority_tier"]!=EXCLUDED]; endpoints=[]
    lengths=sorted(LineString(row["geometry"]).length for row in eligible)
    typical=lengths[len(lengths)//2] if lengths else tolerance*10
    max_gap=max(tolerance*20,min(typical*.18,tolerance*120))
    for row in eligible:
        pts=row["geometry"];endpoints.extend([(row,tuple(pts[0]),tuple(pts[-1])),(row,tuple(pts[-1]),tuple(pts[0]))])
    point_geometries=[Point(point) for _,point,_ in endpoints];tree=STRtree(point_geometries) if point_geometries else None; proposals={}
    for i,(left,a,other_a) in enumerate(endpoints):
        for raw in tree.query(Point(a).buffer(max_gap)) if tree is not None else []:
            j=int(raw)
            if j<=i:continue
            right,b,other_b=endpoints[j]
            if left["segment_id"]==right["segment_id"]:continue
            gap=math.dist(a,b)
            if gap<=tolerance or gap>max_gap:continue
            bridge=(b[0]-a[0],b[1]-a[1])
            def align(other,point):
                vector=(point[0]-other[0],point[1]-other[1])
                return abs((vector[0]*bridge[0]+vector[1]*bridge[1])/max(math.hypot(*vector)*gap,1e-12))
            alignment=max(align(other_a,a),align(other_b,b))
            if alignment<.96:continue
            bid=_sid("BRIDGE",[left["segment_id"],right["segment_id"],a,b])
            proposals[bid]={"bridge_id":bid,"endpoint_a":list(a),"endpoint_b":list(b),
                "source_segments":sorted([left["segment_id"],right["segment_id"]]),"gap_length":gap,
                "alignment":alignment,"local_wall_context":[left["authority_tier"],right["authority_tier"]],
                "candidate_reason":"NEAR_ALIGNED_SOURCE_ENDPOINTS","status":"AMBIGUOUS",
                "material_geometry":"NONE","authority":"CANDIDATE_ONLY"}
    return sorted(proposals.values(),key=lambda row:(row["gap_length"],row["bridge_id"]))[:max_candidates]


def atomic_faces(segments,tolerance,frame=None):
    eligible=[row for row in segments if row["authority_tier"]!=EXCLUDED]
    lines=[LineString(row["geometry"]) for row in eligible]
    if not lines:return [],{"dangling_edges":0,"cut_edges":0,"invalid_rings":0}
    polygons,dangles,cuts,invalid=polygonize_full(unary_union(lines));faces=[]
    for polygon in polygons.geoms:
        if not polygon.is_valid or polygon.area<=tolerance*tolerance*4:continue
        if frame is not None:
            frame_area=box(*frame["bounds"]).area
            if polygon.area>=frame_area*.90:
                continue
        supporting=[];hard=soft=0.0
        for row,line in zip(eligible,lines):
            overlap=polygon.boundary.intersection(line.buffer(tolerance)).length
            if overlap<=tolerance:continue
            supporting.append(row)
            if row["authority_tier"]==HARD:hard+=overlap
            else:soft+=overlap
        coords=[[float(x),float(y)] for x,y in polygon.exterior.coords]
        faces.append({"face_id":_sid("FACE",coords),"polygon":coords,"area":polygon.area,
            "centroid":[polygon.centroid.x,polygon.centroid.y],
            "boundary_segment_ids":sorted(row["segment_id"] for row in supporting),
            "hard_boundary_fraction":hard/max(hard+soft,1e-12),"soft_boundary_fraction":soft/max(hard+soft,1e-12),
            "source_handles":sorted({row["source_handle"] for row in supporting if row.get("source_handle")}),
            "contained_labels":[],"contained_objects":[],"status":"CANDIDATE_ONLY"})
    faces.sort(key=lambda row:(-row["area"],row["face_id"]))
    return faces,{"dangling_edges":len(dangles.geoms),"cut_edges":len(cuts.geoms),"invalid_rings":len(invalid.geoms)}


def host_evidence(faces,texts,objects,activity=None):
    polygons=[Polygon(row["polygon"]) for row in faces];label_diag=[];object_diag=[]
    for kind,records,diagnostics,field in (("LABEL",texts,label_diag,"contained_labels"),("OBJECT",objects,object_diag,"contained_objects")):
        for row in records:
            if not row.get("point"):continue
            hosts=[i for i,poly in enumerate(polygons) if poly.covers(Point(row["point"]))]
            identity=row.get("handle") or _sid(kind,row)
            if len(hosts)==1:
                evidence=({"source_handle":identity,"text":str(row.get("text") or ""),
                           "semantic_candidate":_semantic_candidate(row.get("text"))}
                          if kind=="LABEL" else {"source_handle":identity,"kind":row.get("kind") or "SOURCE_OBJECT"})
                faces[hosts[0]][field].append(evidence);diagnostics.append({f"{kind.lower()}_id":identity,"point":row["point"],"host_face_id":faces[hosts[0]]["face_id"],"status":"HOSTED"})
            else:
                reason=("LABEL_OUTSIDE_PLAN" if activity is not None and not activity.covers(Point(row["point"])) else
                        "NO_CLOSED_FACE" if not hosts else "MULTIPLE_CANDIDATE_FACES")
                diagnostics.append({f"{kind.lower()}_id":identity,"point":row["point"],"host_face_id":None,"status":"UNHOSTED","reason":reason})
    return label_diag,object_diag


def region_groups(faces,tolerance,max_regions=80):
    polygons=[Polygon(row["polygon"]) for row in faces];parent=list(range(len(faces)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    for i,left in enumerate(polygons):
        for j in range(i+1,len(polygons)):
            if left.boundary.intersection(polygons[j].boundary).length<=tolerance:continue
            if max(faces[i]["hard_boundary_fraction"],faces[j]["hard_boundary_fraction"])<.5:union(i,j)
    groups=defaultdict(list)
    for i in range(len(faces)):groups[find(i)].append(i)
    rows=[]
    for indexes in groups.values():
        merged=unary_union([polygons[i] for i in indexes]);parts=list(merged.geoms) if merged.geom_type=="MultiPolygon" else [merged]
        for part in parts:
            members=sorted(faces[i]["face_id"] for i in indexes if part.buffer(tolerance).intersects(polygons[i]))
            coords=[[float(x),float(y)] for x,y in part.exterior.coords]
            rows.append({"region_id":_sid("R2",members),"level":"FACE_GROUP" if len(members)>1 else "ATOMIC_FACE",
                "member_face_ids":members,"polygon":coords,"area":part.area,"centroid":[part.centroid.x,part.centroid.y],
                "boundary_ids":[],"merge_evidence":["SHARED_SOFT_BOUNDARY"] if len(members)>1 else ["ATOMIC_FACE"],
                "contained_labels":sorted({x["source_handle"]:x for i in indexes for x in faces[i]["contained_labels"]}.values(),key=lambda x:x["source_handle"]),
                "contained_objects":sorted({x["source_handle"]:x for i in indexes for x in faces[i]["contained_objects"]}.values(),key=lambda x:x["source_handle"]),
                "exact_text_evidence":[],"object_evidence":[],"authority":"CANDIDATE_ONLY"})
    return sorted(rows,key=lambda row:(-row["area"],row["region_id"]))[:max_regions]


def build_preauthority_graph(model,frame,*,tolerance,max_regions=80,max_bridges=24):
    texts=[row for row in model.get("all_texts") or [] if row.get("point") and box(*frame["bounds"]).covers(Point(row["point"]))]
    objects=[row for row in model.get("architectural_objects") or [] if row.get("point") and box(*frame["bounds"]).covers(Point(row["point"]))]
    segments=source_segments(model,frame,tolerance)
    components=connected_components(segments,tolerance,texts,objects)
    if components and (components[0]["label_count_in_extent"]>0 or components[0]["hard_segment_count"]>0):
        selected=components[0]; extent=box(*selected["span_bounds"]); span=max(extent.bounds[2]-extent.bounds[0],extent.bounds[3]-extent.bounds[1])
        activity=extent.buffer(max(tolerance*5,span*.04),join_style=2).intersection(box(*frame["bounds"]))
        evidence=["MOST_ARCHITECTURALLY_SUPPORTED_CONNECTED_COMPONENT",selected["component_id"]]
    else:
        activity,evidence=activity_region(segments,texts,objects,frame,tolerance)
    bridges=bridge_candidates(segments,tolerance,max_bridges)
    virtual=[]
    for bridge in bridges:
        if bridge["alignment"]<.98 or bridge["local_wall_context"]!=[HARD,HARD]:continue
        closure_id=_sid("VCLOSE",bridge["bridge_id"])
        virtual.append({"closure_id":closure_id,"opening_candidate_id":None,
            "geometry":[bridge["endpoint_a"],bridge["endpoint_b"]],
            "source_evidence":bridge["source_segments"]+["COLLINEAR_HARD_WALL_CONTINUATION"],
            "material_geometry":"NONE","authority":"CANDIDATE_ONLY","status":"AMBIGUOUS"})
    topology_segments=list(segments)+[{"segment_id":row["closure_id"],"source_handle":None,"layer":None,
        "entity_type":"VIRTUAL_CLOSURE","geometry":row["geometry"],"classification":"PHYSICAL_ENCLOSURE_CLOSURE",
        "classification_evidence":row["source_evidence"],"authority_tier":SOFT} for row in virtual]
    faces,polygonize_diagnostics=atomic_faces(topology_segments,tolerance,frame);label_diag,object_diag=host_evidence(faces,texts,objects,activity)
    regions=region_groups(faces,tolerance,max_regions)
    face_by_id={row["face_id"]:row for row in faces}
    for region in regions:
        region["exact_text_evidence"]=[dict(item) for item in region["contained_labels"]]
        region["object_evidence"]=[dict(item) for item in region["contained_objects"]]
    gap_diagnostics=[{"rank":rank,"bridge_id":row["bridge_id"],"dangling_endpoints":[row["endpoint_a"],row["endpoint_b"]],
        "nearby_aligned_endpoints":True,"candidate_missing_wall_pair":row["source_segments"],
        "possible_portal_gap":row["alignment"]>=.98,"possible_open_plan_boundary":True,
        "soft_candidate_geometry_near_gap":SOFT in row["local_wall_context"],
        "hard_excluded_geometry_near_gap":False,"impact_proxy":row["alignment"]/max(row["gap_length"],tolerance)}
        for rank,row in enumerate(sorted(bridges,key=lambda item:(-item["alignment"]/max(item["gap_length"],tolerance),item["bridge_id"])),1)]
    return {"schema":"pre-authority-candidate-graph/2.0","frame_id":frame["frame_id"],"activity_region":{"polygon":[list(p) for p in activity.exterior.coords] if not activity.is_empty and activity.geom_type=="Polygon" else [],"area":activity.area,"evidence":evidence},
        "source_segments":segments,"atomic_faces":faces,"region_candidates":regions,"bridge_candidates":bridges,
        "virtual_closure_candidates":virtual,"label_host_diagnostics":label_diag,"object_host_diagnostics":object_diag,
        "connected_components":components,"polygonize_diagnostics":polygonize_diagnostics,
        "source_edge_recovery_diagnostics":gap_diagnostics,
        "authority":"CANDIDATE_ONLY","face_index_count":len(face_by_id)}
