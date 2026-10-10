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


def _canonical_points(points, precision=9):
    clean=[(round(float(x),precision),round(float(y),precision)) for x,y,*_ in points]
    reverse=list(reversed(clean))
    return clean if clean<=reverse else reverse


def _canonical_ring(points, precision=9):
    """Canonicalize a closed ring across start vertex and direction."""
    clean=[(round(float(x),precision),round(float(y),precision)) for x,y,*_ in points]
    if clean and clean[0]==clean[-1]: clean=clean[:-1]
    if not clean: return []
    variants=[]
    for sequence in (clean,list(reversed(clean))):
        for index in range(len(sequence)):
            rotated=sequence[index:]+sequence[:index]
            variants.append(rotated)
    best=min(variants)
    return best+[best[0]]


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
    # A canonical wall axis may span source fragmentation or a locally paired
    # face extent.  It is topology identity, not material.  Polygonization may
    # therefore consume occupied source-backed intervals only.
    material_by_wall=[_material_interval_lines(wall) for wall in walls]
    axes=[line for lines in material_by_wall for line in lines]
    eligible_closures=[row for row in enclosure_closures
                       if row.get("continuity_status") in {"PROVEN_WALL_CONTINUITY", "SUPPORTED_WALL_CONTINUITY"}
                       and "ENVELOPE_SUPPORT" in (row.get("roles") or [])]
    closure_lines=[LineString(row["geometry"]) for row in eligible_closures]
    polygons=[poly for poly in polygonize(unary_union(axes+closure_lines)) if poly.is_valid and poly.area>tol*tol*4]
    old_selected=max(polygons,key=lambda poly:poly.area) if polygons else None
    rows=[]
    for poly in sorted(polygons,key=lambda item:(-item.area,item.bounds)):
        boundary_ids=[]; internal_ids=[]; source_handles=set(); double=known=0
        internal_material_length=0.0
        for wall,material_lines in zip(walls,material_by_wall):
            if any(line.distance(poly.boundary)<=tol*4 for line in material_lines):
                boundary_ids.append(wall["wall_id"]); source_handles.update(wall.get("source_handles") or [])
                double+=wall.get("representation")=="DOUBLE_FACE"; known+=wall.get("thickness") is not None
            elif any(poly.buffer(tol).covers(line.representative_point()) for line in material_lines):
                internal_ids.append(wall["wall_id"])
                internal_material_length+=sum(line.intersection(poly).length for line in material_lines)
        hosted=[row for row in semantic_labels if row.get("point") and poly.covers(Point(row["point"]))]
        categories=[row.get("semantic_candidate") or row.get("category") for row in hosted]
        obj_count=sum(bool(row.get("point")) and poly.covers(Point(row["point"])) for row in objects)
        jcount=sum(bool(row.get("point")) and poly.buffer(tol).covers(Point(row["point"])) for row in junctions)
        terminating=sum(1 for line in axes for point in (Point(line.coords[0]),Point(line.coords[-1])) if poly.boundary.distance(point)<=tol*4 and poly.buffer(tol).covers(line.representative_point()))
        cid=_sid("ENVCAND",[frame_id,_canonical_ring(poly.exterior.coords)])
        closure_ids=[row["closure_id"] for row,line in zip(eligible_closures,closure_lines)
                     if line.distance(poly.boundary)<=tol*4]
        rows.append({"candidate_id":cid,"frame_id":frame_id,"polygon":[list(p) for p in poly.exterior.coords],"interior_rings":[[list(p) for p in ring.coords] for ring in poly.interiors],"area":poly.area,"perimeter":poly.length,"wall_ids":sorted(boundary_ids),"closure_ids":sorted(closure_ids),"source_handles":sorted(source_handles),"architectural_label_count":len(categories),"habitable_label_count":sum(c in _INTERIOR_SEMANTICS-_WET_SERVICE_SEMANTICS for c in categories),"wet_service_label_count":sum(c in _WET_SERVICE_SEMANTICS for c in categories),"stair_shaft_evidence_count":sum(c in {"stair","stair_landing","elevator","shaft","duct","pipe_shaft"} for c in categories),"exterior_site_label_count":sum(c in _SITE_EXTERIOR_SEMANTICS for c in categories),"yard_terrace_balcony_parking_label_count":sum(c in _SITE_EXTERIOR_SEMANTICS|_SEMI_EXTERIOR_SEMANTICS for c in categories),"semantic_categories":sorted(set(c for c in categories if c)),"internal_wall_length":internal_material_length,"internal_partition_count":len(internal_ids),"junction_density":jcount/max(poly.area,1e-12),"fixture_density":obj_count/max(poly.area,1e-12),"boundary_double_face_ratio":double/max(len(boundary_ids),1),"boundary_known_thickness_ratio":known/max(len(boundary_ids),1),"interior_walls_terminating_at_boundary":terminating,"boundary_opening_candidate_count":sum(len(w.get("interruptions") or []) for w in walls if w["wall_id"] in boundary_ids),"cross_level_relation":"NOT_EVALUATED","previously_selected":bool(old_selected and poly.equals(old_selected)),"selection_status":"UNASSESSED"})
    relationships=[]
    candidate_polygons=[Polygon(row["polygon"],row.get("interior_rings") or []) for row in rows]
    for index,left in enumerate(candidate_polygons):
        for other_index in range(index+1,len(candidate_polygons)):
            right=candidate_polygons[other_index]
            relation=("CONTAINS" if left.contains(right) else "WITHIN" if left.within(right) else
                      "OVERLAPS" if left.overlaps(right) else "TOUCHES" if left.touches(right) else "DISJOINT")
            relationships.append({"candidate_a_id":rows[index]["candidate_id"],
                                  "candidate_b_id":rows[other_index]["candidate_id"],"relation":relation})
    return {"frame_id":frame_id,"candidates":rows,"candidate_relationships":relationships,
            "runtime_seconds":round(time.perf_counter()-started,6)}


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
        regions.append({"region_id":_sid("REGION",candidate["candidate_id"]),"candidate_id":candidate["candidate_id"],"frame_id":candidate["frame_id"],"geometry":candidate["polygon"],"interior_rings":candidate.get("interior_rings") or [],"area":candidate["area"],"role":role,"status":status,"reason":reason,"semantic_evidence":sorted(categories),"wall_ids":candidate["wall_ids"],"adjacent_region_ids":[],"exterior_exposure":"UNKNOWN"})
    geoms=[Polygon(row["geometry"],row.get("interior_rings") or []) for row in regions]
    for i,left in enumerate(geoms):
        for j in range(i+1,len(geoms)):
            if left.boundary.intersection(geoms[j].boundary).length>0:
                regions[i]["adjacent_region_ids"].append(regions[j]["region_id"]); regions[j]["adjacent_region_ids"].append(regions[i]["region_id"])
    return regions


def _material_interval_records(wall):
    """Return identified occupied, source-backed wall material intervals."""
    if not (wall.get("source_handles") or wall.get("source_fragments")):
        return []
    solid=wall.get("wall_solid") or {}; origin=solid.get("axis_origin"); direction=solid.get("axis_direction")
    if not origin or not direction:
        return []
    rows=[]
    for index,(low,high) in enumerate(solid.get("occupied_intervals") or []):
        if not (math.isfinite(float(low)) and math.isfinite(float(high))) or high<=low:
            continue
        a=(origin[0]+low*direction[0],origin[1]+low*direction[1])
        b=(origin[0]+high*direction[0],origin[1]+high*direction[1])
        line=LineString((a,b))
        if line.length>0:
            rows.append({"material_interval_id":_sid("MATINT",[wall["wall_id"],index,low,high]),
                         "interval":[low,high],"line":line})
    return rows


def _material_interval_lines(wall):
    """Return only occupied, source-backed wall intervals as material evidence."""
    return [row["line"] for row in _material_interval_records(wall)]


def _direction_classes(lines, angular_tolerance=2.0):
    """Deterministically group supporting directions without using evidence ratios."""
    angles=[]
    for line in lines:
        angle=_axis(line)[2]
        if not any(min(abs(angle-other),180-abs(angle-other))<=angular_tolerance for other in angles):
            angles.append(angle)
    return sorted(round(value,6) for value in angles)


def _shell_boundary_proof(candidate, walls, tolerance, enclosure_closures=()):
    """Prove the complete exterior from source-backed material wall intervals.

    Buffers are used only as a governed tolerance predicate.  They never alter
    or repair the candidate geometry returned to downstream consumers.
    """
    tol=max(float(tolerance or .001),1e-8)
    shell=Polygon(candidate["polygon"],candidate.get("interior_rings") or [])
    wall_by_id={row["wall_id"]:row for row in walls}
    boundary_walls=[wall_by_id[wall_id] for wall_id in candidate.get("wall_ids") or [] if wall_id in wall_by_id]
    material=[]; strong=[]; known=[]
    for wall in boundary_walls:
        lines=_material_interval_lines(wall)
        material.extend(lines)
        if wall.get("representation")=="DOUBLE_FACE": strong.extend(lines)
        if wall.get("thickness") is not None and float(wall["thickness"])>0: known.extend(lines)
    governed_closures={row.get("closure_id"):row for row in enclosure_closures
                       if row.get("continuity_status") in {"PROVEN_WALL_CONTINUITY","SUPPORTED_WALL_CONTINUITY"}
                       and "ENVELOPE_SUPPORT" in (row.get("roles") or [])
                       and row.get("material") is False
                       and row.get("wall_authority")=="NONE"}
    unresolved_closure_ids=sorted(set(candidate.get("closure_ids") or [])-set(governed_closures))
    closure_lines=[LineString(governed_closures[closure_id]["geometry"])
                   for closure_id in candidate.get("closure_ids") or [] if closure_id in governed_closures]
    # Keep material and governed non-material continuity distinct in evidence;
    # their union is used only to test complete boundary support.
    support=unary_union(material+closure_lines) if material or closure_lines else None
    unsupported=shell.exterior if support is None else shell.exterior.difference(support.buffer(tol))
    unsupported_parts=[]
    if not unsupported.is_empty:
        geoms=list(getattr(unsupported,"geoms",[unsupported]))
        unsupported_parts=sorted(
            ([list(point) for point in geom.coords] for geom in geoms if hasattr(geom,"coords") and geom.length>tol),
            key=lambda points:(points[0],points[-1],len(points)))
    strong_directions=_direction_classes(strong)
    known_directions=_direction_classes(known)
    internal_partition_evidence=[]
    boundary_ids=set(candidate.get("wall_ids") or [])
    for wall in walls:
        if wall.get("wall_id") in boundary_ids:
            continue
        for material in _material_interval_records(wall):
            applicable=material["line"].intersection(shell)
            if applicable.is_empty or applicable.length<=tol:
                continue
            internal_partition_evidence.append({
                "wall_id":wall["wall_id"],
                "material_interval_id":material["material_interval_id"],
                "source_handles":sorted(wall.get("source_handles") or []),
                "source_lineage":wall.get("source_lineage") or [],
                "material_geometry":[list(point) for point in material["line"].coords],
                "applicable_material_length":applicable.length,
                "relationship_to_candidate_shell":"INTERSECTS_SHELL_INTERIOR",
            })
    internal_source_walls=sorted({row["wall_id"] for row in internal_partition_evidence})
    reasons=[]
    if not shell.is_valid or shell.area<=0: reasons.append("INVALID_SHELL_GEOMETRY")
    if unresolved_closure_ids: reasons.append("UNGOVERNED_EXTERIOR_CLOSURE")
    if unsupported_parts: reasons.append("UNSUPPORTED_EXTERIOR_INTERVAL")
    if len(strong_directions)<2: reasons.append("DOUBLE_FACE_SUPPORT_NOT_DISTRIBUTED")
    if len(known_directions)<2: reasons.append("KNOWN_THICKNESS_SUPPORT_NOT_DISTRIBUTED")
    if not internal_source_walls: reasons.append("SOURCE_BACKED_INTERNAL_PARTITION_REQUIRED")
    boundary_evidence=[]
    for wall in sorted(boundary_walls,key=lambda row:row["wall_id"]):
        intervals=[]
        for index,(low,high) in enumerate((wall.get("wall_solid") or {}).get("occupied_intervals") or []):
            intervals.append({"material_interval_id":_sid("MATINT",[wall["wall_id"],index,low,high]),
                              "interval":[low,high]})
        boundary_evidence.append({"wall_id":wall["wall_id"],"representation":wall.get("representation"),
                                  "source_handles":sorted(wall.get("source_handles") or []),
                                  "source_fragments":sorted(wall.get("source_fragments") or []),
                                  "source_lineage":wall.get("source_lineage") or [],
                                  "known_thickness":wall.get("thickness"),
                                  "material_intervals":intervals})
    return {
        "status":"SUPPORTED" if not reasons else "INPUT_REQUIRED",
        "reasons":reasons,
        "boundary_wall_count":len(boundary_walls),
        "source_backed_boundary_wall_count":sum(bool(_material_interval_lines(wall)) for wall in boundary_walls),
        "double_face_boundary_wall_count":sum(wall.get("representation")=="DOUBLE_FACE" for wall in boundary_walls),
        "known_thickness_boundary_wall_count":sum(wall.get("thickness") is not None and float(wall["thickness"])>0 for wall in boundary_walls),
        "unsupported_interval_count":len(unsupported_parts),
        "unsupported_intervals":unsupported_parts,
        "governed_nonmaterial_closure_count":len(closure_lines),
        "unresolved_closure_ids":unresolved_closure_ids,
        "double_face_direction_classes":strong_directions,
        "known_thickness_direction_classes":known_directions,
        "source_backed_internal_wall_ids":sorted(internal_source_walls),
        "internal_partition_evidence":sorted(internal_partition_evidence,
                                             key=lambda row:(row["wall_id"],row["material_interval_id"])),
        "closure_ids":sorted(candidate.get("closure_ids") or []),
        "boundary_evidence":boundary_evidence,
    }


def _source_supported_geometric_shell(candidate_diagnostic, regions, walls, tolerance, enclosure_closures=()):
    """Return one independently source-supported dominant building shell.

    Semantics may classify contained regions but cannot veto a geometrically
    proven shell merely because an interior void label is also inside it.  The
    proof deliberately requires source lineage, repeated double-face wall
    support and internal partition topology; a closed site outline or sheet
    border therefore cannot qualify by area alone.
    """
    region_by_candidate={row["candidate_id"]:row for row in regions}
    eligible=[]
    for row in candidate_diagnostic.get("candidates") or []:
        semantics=set(row.get("semantic_categories") or [])
        if semantics & (_SITE_EXTERIOR_SEMANTICS | _SEMI_EXTERIOR_SEMANTICS):
            continue
        proof=_shell_boundary_proof(row,walls,tolerance,enclosure_closures)
        row["source_boundary_proof"]=proof
        if proof["status"]!="SUPPORTED":
            continue
        poly=Polygon(row["polygon"],row.get("interior_rings") or [])
        if not poly.is_valid or poly.area<=0:
            continue
        eligible.append((poly.area,row,region_by_candidate.get(row["candidate_id"])))
    eligible.sort(key=lambda item:(-item[0],item[1]["candidate_id"]))
    if not eligible:
        return None
    # More than one independently supported shell is a real selection
    # ambiguity. Do not rank it away by area or a percentage threshold.
    if len(eligible)>1:
        return None
    return eligible[0][1]


def _compose_shell_holes(shell, classified_voids):
    """Compose source rings and classified source geometry without repair."""
    outer=Polygon(shell.exterior)
    if not outer.is_valid or outer.is_empty or outer.area<=0:
        return {"status":"CONFLICT","reason":"INVALID_OUTER_SHELL","holes":[],"provenance":[]}
    entries=[]
    for index,ring in enumerate(shell.interiors):
        hole=Polygon(ring)
        entries.append((hole,{"authority":"SOURCE_INTERIOR_RING","source_ring_index":index,"classified_void_ids":[]}))
    for row in sorted(classified_voids,key=lambda item:(item.get("candidate_id") or item.get("region_id") or "")):
        hole=Polygon(row["geometry"],row.get("interior_rings") or [])
        if hole.interiors:
            return {"status":"CONFLICT","reason":"INVALID_HOLE_GEOMETRY","holes":[],"provenance":[]}
        duplicate=next((index for index,(existing,_) in enumerate(entries) if existing.equals(hole)),None)
        if duplicate is not None:
            entries[duplicate][1]["classified_void_ids"].append(row.get("candidate_id") or row.get("region_id"))
        else:
            entries.append((hole,{"authority":"CLASSIFIED_SOURCE_CANDIDATE","source_ring_index":None,
                                  "classified_void_ids":[row.get("candidate_id") or row.get("region_id")]}))
    for hole,_ in entries:
        if hole.is_empty or not hole.is_valid or hole.area<=0:
            return {"status":"CONFLICT","reason":"INVALID_HOLE_GEOMETRY","holes":[],"provenance":[]}
        if not outer.contains(hole) or outer.boundary.intersects(hole):
            return {"status":"CONFLICT","reason":"HOLE_NOT_STRICTLY_CONTAINED","holes":[],"provenance":[]}
    for index,(left,_) in enumerate(entries):
        for right,_ in entries[index+1:]:
            if left.intersects(right):
                return {"status":"CONFLICT","reason":"HOLES_OVERLAP_OR_TOUCH","holes":[],"provenance":[]}
    entries.sort(key=lambda item:(item[0].bounds,item[0].area,item[0].wkb_hex))
    holes=[[list(point) for point in hole.exterior.coords] for hole,_ in entries]
    effective=Polygon(shell.exterior.coords,holes)
    if effective.is_empty or not effective.is_valid or effective.area<=0:
        return {"status":"CONFLICT","reason":"INVALID_COMBINED_SHELL","holes":[],"provenance":[]}
    return {"status":"SUPPORTED","reason":"SOURCE_HOLES_COMPOSED","holes":holes,
            "provenance":[provenance for _,provenance in entries],"geometry":effective}


def evidence_based_building_envelope(walls, *, frame_id, tolerance, semantic_labels=(), objects=(), junctions=(), enclosure_closures=()):
    diagnostic=enumerate_envelope_candidates(walls,frame_id=frame_id,tolerance=tolerance,semantic_labels=semantic_labels,objects=objects,junctions=junctions,enclosure_closures=enclosure_closures)
    regions=classify_plan_regions(diagnostic); conflicts=[row for row in regions if row["status"]=="CONFLICT"]
    geometric_shell=_source_supported_geometric_shell(diagnostic,regions,walls,tolerance,enclosure_closures)
    if geometric_shell is not None:
        shell=Polygon(geometric_shell["polygon"],geometric_shell.get("interior_rings") or [])
        classified_voids=[]
        for region in regions:
            if region["role"] not in {"LIGHTWELL","VOID"} or region["status"] not in {"HIGH_CONFIDENCE","VERIFIED"}:
                continue
            candidate=Polygon(region["geometry"],region.get("interior_rings") or [])
            if candidate.is_valid and candidate.area>0 and (candidate.within(Polygon(shell.exterior)) or any(candidate.equals(Polygon(ring)) for ring in shell.interiors)):
                classified_voids.append(region)
        composition=_compose_shell_holes(shell,classified_voids)
        if composition["status"]!="SUPPORTED":
            return ({"building_envelope_id":_sid("ENV",[frame_id,"UNKNOWN",composition["reason"]]),
                     "frame_id":frame_id,"outer_ring":[],"interior_voids":[],"components":[],
                     "exterior_wall_ids":[],"source_handles":[],"area":0.0,"perimeter":0.0,
                     "confidence":0.0,"status":"INPUT_REQUIRED","reason":composition["reason"],
                     "evidence":[{"class":"SOURCE_HOLE_COMPOSITION","status":"CONFLICT"}],
                     "schema":"canonical-building-envelope/2.0"},diagnostic,regions)
        holes=composition["holes"]; effective=composition["geometry"]
        boundary_ids=geometric_shell.get("wall_ids") or []
        envelope={"building_envelope_id":_sid("ENV",[frame_id,[list(p) for p in shell.exterior.coords],holes]),
                  "frame_id":frame_id,"outer_ring":[list(p) for p in shell.exterior.coords],
                  "interior_voids":[[list(p) for p in ring] for ring in holes],
                  "components":[{"outer_ring":[list(p) for p in shell.exterior.coords],
                                 "interior_voids":[[list(p) for p in ring] for ring in holes]}],
                  "exterior_wall_ids":sorted(boundary_ids),
                  "source_handles":sorted(geometric_shell.get("source_handles") or []),
                  "area":effective.area,"perimeter":effective.length,"confidence":.9,
                  "status":"HIGH_CONFIDENCE","reason":"SOURCE_SUPPORTED_DOMINANT_GEOMETRIC_SHELL",
                  "evidence":[{"class":"SOURCE_SUPPORTED_GEOMETRIC_SHELL",
                               "candidate_id":geometric_shell["candidate_id"],
                               "internal_partition_count":geometric_shell["internal_partition_count"],
                               "boundary_proof":geometric_shell["source_boundary_proof"],
                               "source_ring_count":len(shell.interiors),
                               "classified_source_void_count":len(classified_voids),
                               "effective_hole_count":len(holes),
                               "hole_provenance":composition["provenance"],
                               "semantic_authority":False}],
                  "schema":"canonical-building-envelope/2.0"}
        return envelope,diagnostic,regions
    interior=[Polygon(row["geometry"],row.get("interior_rings") or []) for row in regions if row["role"]=="BUILDING_INTERIOR"]
    interior_semantics={semantic for row in regions if row["role"]=="BUILDING_INTERIOR" for semantic in row["semantic_evidence"]}
    insufficient=len(interior_semantics)<2
    if conflicts or not interior or insufficient:
        reason=("CONFLICTING_INTERIOR_EXTERIOR_EVIDENCE" if conflicts else
                "INSUFFICIENT_INDEPENDENT_INTERIOR_EVIDENCE" if insufficient else
                "NO_DEFENSIBLE_BUILDING_INTERIOR_REGION")
        return ({"building_envelope_id":_sid("ENV",[frame_id,"UNKNOWN",reason]),"frame_id":frame_id,"outer_ring":[],"interior_voids":[],"components":[],"exterior_wall_ids":[],"source_handles":[],"area":0.0,"perimeter":0.0,"confidence":0.0,"status":"INPUT_REQUIRED","reason":reason,"evidence":[{"class":"EVIDENCE_BASED_REGION_CLASSIFICATION","conflict_count":len(conflicts),"interior_region_count":len(interior)}],"schema":"canonical-building-envelope/2.0"},diagnostic,regions)
    merged=unary_union(interior); components=list(merged.geoms) if merged.geom_type=="MultiPolygon" else [merged]; primary=max(components,key=lambda poly:poly.area)
    status="HIGH_CONFIDENCE" if len(components)==1 else "INPUT_REQUIRED"
    boundary_ids=[wall["wall_id"] for wall in walls
                  if any(line.distance(merged.boundary)<=max(tolerance*4,1e-7)
                         for line in _material_interval_lines(wall))]
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


def _internal_material_interruption(interruption, occupied, tol):
    """Return true only when paired material exists on both gap boundaries."""
    low,high=interruption["interval"]
    before=any(abs(float(end)-float(low))<=tol for _,end in occupied)
    after=any(abs(float(start)-float(high))<=tol for start,_ in occupied)
    return before and after


def _interruption_source_line(wall, interruption):
    """Map an interruption interval onto the source face that contains it."""
    solid=wall["wall_solid"]; origin=solid["axis_origin"]; u=solid["axis_direction"]
    n=(-u[1],u[0]); face_key=("face_a" if interruption.get("face_a_gap") else
                             "face_b" if interruption.get("face_b_gap") else None)
    face=LineString(wall[face_key]) if face_key and wall.get(face_key) else None
    offset=0.0
    if face is not None:
        point=face.interpolate(.5,normalized=True)
        offset=(point.x-origin[0])*n[0]+(point.y-origin[1])*n[1]
    low,high=interruption["interval"]
    return LineString(((origin[0]+low*u[0]+offset*n[0],origin[1]+low*u[1]+offset*n[1]),
                       (origin[0]+high*u[0]+offset*n[0],origin[1]+high*u[1]+offset*n[1])))


def _govern_source_backed_junction_interruptions(walls, tol, source_segments=(),
                                                  thickness_clusters=()):
    """Classify exact wall-junction trimming without inventing continuity."""
    for wall in walls:
        _,_,angle,_=_axis(LineString(wall["centerline"]))
        for interruption in wall.get("interruptions") or []:
            if interruption.get("kind")!="UNKNOWN_FRAGMENTATION":
                continue
            gap_line=_interruption_source_line(wall,interruption)
            gap_points=[Point(point) for point in gap_line.coords]
            candidates=[]
            for other in walls:
                if other["wall_id"]==wall["wall_id"] or other.get("representation")!="DOUBLE_FACE":
                    continue
                if not (other.get("source_handles") and other.get("source_lineage")
                        and other.get("face_a") and other.get("face_b") and other.get("thickness")):
                    continue
                _,_,other_angle,_=_axis(LineString(other["centerline"]))
                delta=min(abs(angle-other_angle),180-abs(angle-other_angle))
                if abs(delta-90)>2:
                    continue
                thickness=float(other["thickness"]); width=gap_line.length
                if abs(width-thickness)>tol*4:
                    continue
                faces=[LineString(other["face_a"]),LineString(other["face_b"])]
                direct=max(gap_points[0].distance(faces[0]),gap_points[1].distance(faces[1]))
                reverse=max(gap_points[0].distance(faces[1]),gap_points[1].distance(faces[0]))
                binding=min(direct,reverse)
                if binding>tol*2:
                    continue
                # Canonical face extent is topology geometry, not material
                # authority.  Require an occupied, source-backed interval of
                # the perpendicular wall at the actual connection point.
                junction_point=gap_line.interpolate(.5,normalized=True)
                material_records=_material_interval_records(other)
                local_material=[
                    record for record in material_records
                    if junction_point.distance(record["line"])<=tol*2
                ]
                if not local_material:
                    continue
                proof=dict(other)
                proof["junction_material_interval_ids"]=sorted(
                    record["material_interval_id"] for record in local_material)
                proof["junction_material_intervals"]=[
                    record["interval"] for record in sorted(
                        local_material,key=lambda record:record["material_interval_id"])]
                proof["junction_material_binding_distance"]=min(
                    junction_point.distance(record["line"])
                    for record in local_material)
                candidates.append((binding,other["wall_id"],proof))
            # A face may have been consumed by another canonical pair.  Retain
            # the accepted source faces as the earlier authority layer and
            # recover only an exact two-face junction binding.
            source_faces=[]
            for row in (() if candidates else (source_segments or [])):
                if (row.get("status")!="ACCEPTED"
                        or row.get("wall_evidence_state")!="CONFIRMED_WALL"
                        or not row.get("source_handle")):
                    continue
                line=LineString(row["geometry"])
                if line.distance(gap_line)>max(gap_line.length,tol*4):
                    continue
                _,_,source_angle,_=_axis(line)
                delta=min(abs(angle-source_angle),180-abs(angle-source_angle))
                if abs(delta-90)<=2:
                    source_faces.append((row,line,source_angle))
            cluster_values=sorted(float(row["median_thickness"])
                                  for row in (thickness_clusters or [])
                                  if float(row.get("median_thickness") or 0)>0)
            canonical_pairs={
                frozenset(str(handle) for handle in other.get("source_handles") or [])
                for other in walls if other.get("representation")=="DOUBLE_FACE"
            }
            canonical_pair_conflict=False
            for index,(left,left_line,left_angle) in enumerate(source_faces):
                for right,right_line,right_angle in source_faces[index+1:]:
                    delta=min(abs(left_angle-right_angle),180-abs(left_angle-right_angle))
                    if delta>2:
                        continue
                    distance=left_line.distance(right_line)
                    # Establish the raw face pair independently of this host
                    # interruption.  Host-gap width is deliberately absent
                    # from this proof: parallel faces must overlap like a
                    # normal face-pair and match an already-observed local
                    # thickness family.
                    origin=list(left_line.coords)[0]
                    left_axis,_,_,left_length=_axis(left_line)
                    left_interval=_project_interval(left_line,origin,left_axis)
                    right_interval=_project_interval(right_line,origin,left_axis)
                    overlap=max(0,min(left_interval[1],right_interval[1])-
                                  max(left_interval[0],right_interval[0]))
                    right_length=right_line.length
                    if overlap/max(min(left_length,right_length),1e-9)<.55:
                        continue
                    if not cluster_values:
                        continue
                    cluster=min(cluster_values,key=lambda value:abs(value-distance))
                    if abs(distance-cluster)>max(cluster*.3,tol*4):
                        continue
                    handles=frozenset((str(left["source_handle"]),
                                       str(right["source_handle"])))
                    # Reusing either source face from an incompatible
                    # canonical DOUBLE_FACE wall would assert two mutually
                    # exclusive physical pairings.  Such a case is ambiguous,
                    # not a downstream recovery opportunity.
                    if any(handles & pair and not handles.issubset(pair)
                           for pair in canonical_pairs):
                        canonical_pair_conflict=True
                        continue
                    width=gap_line.length
                    if abs(distance-width)>tol*4:
                        continue
                    direct=max(gap_points[0].distance(left_line),gap_points[1].distance(right_line))
                    reverse=max(gap_points[0].distance(right_line),gap_points[1].distance(left_line))
                    binding=min(direct,reverse)
                    if binding>tol*2:
                        continue
                    sorted_handles=sorted(handles)
                    candidates.append((binding,"SOURCE-FACES:"+":".join(sorted_handles),{
                        "wall_id":None,"source_handles":sorted_handles,
                        "source_lineage":[{
                            "segment_id":row.get("segment_id"),
                            "source_handle":row.get("source_handle"),
                            "source_insert_handle":row.get("source_insert_handle"),
                            "source_block_path":row.get("source_block_path") or [],
                            "source_transform":row.get("source_transform"),
                        } for row in (left,right)],
                        "proof_class":"INDEPENDENT_THICKNESS_CLUSTER_SOURCE_FACE_PAIR",
                        "face_pair_thickness_cluster":cluster,
                        "face_pair_projection_overlap":overlap,
                    }))
            if not candidates:
                if canonical_pair_conflict:
                    interruption.update({
                        "kind":"AMBIGUOUS_FACE_PAIRING",
                        "classification":"MULTIPLE_VALID_FACE_PAIRINGS",
                        "confidence":0.0,"status":"INPUT_REQUIRED",
                        "junction_proof_status":"CONFLICT",
                        "proof_class":"CANONICAL_VS_RAW_FACE_PAIR_CONFLICT",
                    })
                continue
            candidates.sort(key=lambda row:(row[0],row[1]))
            best=candidates[0]
            if len(candidates)>1 and abs(candidates[1][0]-best[0])<=tol:
                interruption.update({
                    "kind":"AMBIGUOUS_FACE_PAIRING",
                    "classification":"MULTIPLE_VALID_FACE_PAIRINGS",
                    "confidence":0.0,"status":"INPUT_REQUIRED",
                    "junction_proof_status":"CONFLICT",
                    "proof_class":"EQUAL_FACE_PAIR_BINDINGS",
                })
                continue
            other=best[2]
            interruption.update({
                "kind":"GOVERNED_DRAFTING_FRAGMENTATION",
                "classification":"SOURCE_BACKED_WALL_JUNCTION",
                "confidence":.95,"status":"PROVEN",
                "junction_proof_status":"PROVEN",
                "junction_wall_id":other["wall_id"],
                "junction_source_handles":sorted(other.get("source_handles") or []),
                "junction_source_lineage":other.get("source_lineage") or [],
                "junction_face_binding_distance":best[0],
                "junction_material_interval_ids":other.get("junction_material_interval_ids") or [],
                "junction_material_intervals":other.get("junction_material_intervals") or [],
                "junction_material_binding_distance":other.get("junction_material_binding_distance"),
                "proof_class":other.get("proof_class") or "EXACT_ORTHOGONAL_DOUBLE_FACE_BOUNDARY",
            })
            if other.get("face_pair_thickness_cluster") is not None:
                interruption["face_pair_thickness_cluster"]=other["face_pair_thickness_cluster"]
                interruption["face_pair_projection_overlap"]=other["face_pair_projection_overlap"]
    return walls


def _pair_wall_faces(walls, clusters, tol):
    """Greedily form local double-face walls without a global thickness default."""
    if not walls or not clusters:
        for wall in walls: wall.pop("_identity_sort_key",None)
        return walls
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
        a,b=walls[i],walls[j]; la,lb=axes[i],axes[j]
        longer=la if la.length>=lb.length else lb; u,n,angle,_=_axis(longer); base=list(longer.coords)[0]
        ia=_project_interval(la,base,u); ib=_project_interval(lb,base,u); lo=min(ia[0],ib[0]); hi=max(ia[1],ib[1])
        # Center the axis between the two proven faces.
        # Both offsets must use the chosen base.  A displacement from face A
        # to face B has the opposite sign when B supplies the longer base;
        # applying it there would place the axis outside the material faces.
        midpoints=[face.interpolate(.5,normalized=True) for face in (la,lb)]
        shift=sum((point.x-base[0])*n[0]+(point.y-base[1])*n[1]
                  for point in midpoints)/2
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
                # Paired material exists only where both faces exist.  The
                # material interruption is therefore the union of the two
                # overlapping face gaps, not merely their overlap.
                interval=[min(left[0],right[0]),max(left[1],right[1])]
                interruptions.append({"interval":interval,"kind":"SUPPORTED_OPENING","face_a_gap":left,"face_b_gap":right,
                                      "classification":"UNKNOWN_OPENING","confidence":.8,"status":"HIGH_CONFIDENCE"})
            else:
                interruptions.append({"interval":left,"kind":"UNKNOWN_FRAGMENTATION","face_a_gap":left,"face_b_gap":None,
                                      "classification":"FRAGMENTATION_GAP","confidence":.35,"status":"AMBIGUOUS"})
        for right in gb:
            if not any(min(right[1],left[1])-max(right[0],left[0])>tol*2 for left in ga):
                interruptions.append({"interval":right,"kind":"UNKNOWN_FRAGMENTATION","face_a_gap":None,"face_b_gap":right,
                                      "classification":"FRAGMENTATION_GAP","confidence":.35,"status":"AMBIGUOUS"})
        def projected_material(wall):
            solid=wall["wall_solid"]; old_origin=solid["axis_origin"]; old_u=solid["axis_direction"]
            projected=[]
            for start,end in solid.get("occupied_intervals") or []:
                points=[(old_origin[0]+value*old_u[0],old_origin[1]+value*old_u[1])
                        for value in (start,end)]
                values=[(point[0]-origin[0])*u[0]+(point[1]-origin[1])*u[1] for point in points]
                projected.append([min(values),max(values)])
            return projected
        # A paired material strip is justified only where BOTH source faces
        # contain material.  The union-length centerline remains a topology
        # candidate, but a short return cannot manufacture a full-length solid.
        occupied=[]
        for left in projected_material(a):
            for right in projected_material(b):
                start,end=max(left[0],right[0]),min(left[1],right[1])
                if end-start>tol:
                    occupied.append([start,end])
        occupied.sort()
        if not occupied:
            # No resolvable common material: preserve both original walls and
            # their source traces rather than granting an empty paired solid.
            continue
        discarded_interruptions=[]; retained_interruptions=[]
        for interruption in interruptions:
            if _internal_material_interruption(interruption,occupied,tol):
                retained_interruptions.append(interruption)
            else:
                discarded_interruptions.append(
                    dict(interruption,discard_reason="OUTSIDE_PAIRED_MATERIAL_INTERVAL"))
        interruptions=retained_interruptions
        used.update((i,j))
        handles=sorted(set(a.get("source_handles",[])+b.get("source_handles",[])))
        center_points=_canonical_points(center.coords)
        legacy_sort_id=_sid("WALL",[a["frame_id"],"DOUBLE_FACE",a.get("_identity_sort_key",a["wall_id"]),
                                     b.get("_identity_sort_key",b["wall_id"])])
        wid=_sid("WALL",[a["frame_id"],"DOUBLE_FACE",sorted([a["wall_id"],b["wall_id"]]),center_points])
        paired.append({"wall_id":wid,"frame_id":a["frame_id"],"level_id":None,"wall_type":"UNKNOWN",
                       "representation":"DOUBLE_FACE","centerline":[list(p) for p in center.coords],
                       "face_a":a["centerline"],"face_b":b["centerline"],
                       "wall_solid":{"occupied_intervals":occupied,"axis_origin":origin,"axis_direction":[u[0],u[1]]},
                       "thickness":distance,"thickness_status":"INFERRED_LOCAL_CLUSTER","orientation":angle,
                       "length":center.length,"source_fragments":sorted(set(a["source_fragments"]+b["source_fragments"])),
                       "source_handles":handles,"junction_start":None,"junction_end":None,"junctions":[],
                       "source_lineage":sorted(a.get("source_lineage",[])+b.get("source_lineage",[]),
                                               key=lambda row:json.dumps(row,sort_keys=True)),
                       "interruptions":interruptions,
                       "discarded_interruptions":discarded_interruptions,
                       "candidate_openings":[],"confidence":.9,"status":"HIGH_CONFIDENCE",
                       "evidence":[{"class":"PAIRED_WALL_FACES","face_wall_ids":[a["wall_id"],b["wall_id"]],
                                    "measured_thickness":distance,"local_cluster":cluster}],
                       "derived_geometry_provenance":{"method":"LOCAL_FACE_PAIRING","tolerance":tol},
                       "_identity_sort_key":legacy_sort_id})
    paired.extend(wall for index,wall in enumerate(walls) if index not in used)
    paired.sort(key=lambda wall:wall.get("_identity_sort_key",wall["wall_id"]))
    for wall in paired: wall.pop("_identity_sort_key",None)
    return paired


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
            center_points=_canonical_points(center.coords)
            legacy_wid=_sid("WALL",[frame_id,round(angle,3),
                                     [(round(a,6),round(b,6)) for a,b,_ in merged],handles])
            wid=_sid("WALL",[frame_id,"WORLD_AXIS",center_points,handles])
            walls.append({"wall_id":wid,"frame_id":frame_id,"level_id":None,"wall_type":"UNKNOWN",
                          "representation":"COMPOSITE" if len(group)>1 else "SINGLE_LINE",
                          "centerline":[list(p) for p in center.coords],"face_a":None,"face_b":None,
                          "wall_solid":{"occupied_intervals":[[a,b] for a,b,_ in merged],"axis_origin":list(origin),"axis_direction":[u[0],u[1]]},
                          "thickness":None,"thickness_status":"UNKNOWN",
                          "orientation":angle,"length":center.length,"source_fragments":[rows[i]["segment_id"] for i in group],
                          "source_handles":handles,"junction_start":None,"junction_end":None,"junctions":[],
                          "source_lineage":[{"segment_id":rows[i]["segment_id"],
                                             "source_handle":rows[i].get("source_handle"),
                                             "source_insert_handle":rows[i].get("source_insert_handle"),
                                             "source_block_path":rows[i].get("source_block_path") or [],
                                             "source_transform":rows[i].get("source_transform"),
                                             "primitive_geometry_fingerprint":_sid("PRIM",_canonical_points(rows[i]["geometry"]))}
                                            for i in sorted(group)],
                          "interruptions":[{"interval":g,"kind":"UNKNOWN_FRAGMENTATION","classification":"FRAGMENTATION_GAP",
                                            "confidence":.25,"status":"AMBIGUOUS"} for g in gaps],"candidate_openings":[],
                          "confidence":.8 if len(group)>1 else (.72 if recovered else .65),
                          "status":"HIGH_CONFIDENCE" if len(group)>1 else ("SUPPORTED_PARTITION" if recovered else "AMBIGUOUS"),
                          "evidence":[{"class":"COLLINEAR_FRAGMENT_STITCHING","source_interval_count":len(merged),"gap_count":len(gaps)},
                                      {"class":"SOURCE_WALL_ADMISSION","states":evidence_states,
                                       "iteratively_recovered":recovered}],
                          "derived_geometry_provenance":{"method":"ORIENTATION_OFFSET_BUCKET_AND_PROJECTED_INTERVALS","tolerance":tol},
                          "_identity_sort_key":legacy_wid})
    walls=_pair_wall_faces(walls,clusters,tol)
    _govern_source_backed_junction_interruptions(walls,tol,rows,clusters)
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


def canonical_enclosure_continuity(walls, *, frame_id=None, tolerance=.001):
    """Classify wall interruptions before envelope inference.

    A closure expresses continuity of enclosure topology, never wall material
    and never portal semantics.  Only independently proven double-face gaps are
    promoted automatically; supported/insufficient rows remain diagnostic.
    """
    rows=[]
    tol=max(float(tolerance or .001),1e-9)
    for wall in walls:
        origin=wall["wall_solid"]["axis_origin"]; direction=wall["wall_solid"]["axis_direction"]
        materials=_material_interval_records(wall)
        for index,opening in enumerate(wall.get("interruptions") or []):
            low,high=opening["interval"]
            geometry=[[origin[0]+low*direction[0],origin[1]+low*direction[1]],
                      [origin[0]+high*direction[0],origin[1]+high*direction[1]]]
            both_faces=bool(opening.get("face_a_gap") and opening.get("face_b_gap"))
            double=wall.get("representation")=="DOUBLE_FACE"
            kind=opening.get("kind")
            host_materials=sorted(
                row["material_interval_id"] for row in materials
                if abs(row["interval"][1]-low)<=tol or abs(row["interval"][0]-high)<=tol)
            material_on_both_sides=(
                any(abs(row["interval"][1]-low)<=tol for row in materials)
                and any(abs(row["interval"][0]-high)<=tol for row in materials))
            if (kind == "GOVERNED_DRAFTING_FRAGMENTATION"
                    and opening.get("junction_proof_status")=="PROVEN"
                    and material_on_both_sides):
                continuity,status,confidence,reason=("PROVEN_WALL_CONTINUITY","PROVEN",.95,
                                                     "GOVERNED_DRAFTING_FRAGMENTATION")
                roles=["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]
            elif (double and both_faces and material_on_both_sides
                    and kind == "PROVEN_OPENING"):
                continuity,status,confidence,reason=("PROVEN_WALL_CONTINUITY","PROVEN",.95,
                                                     "PAIRED_FACES_CONTINUE_ACROSS_MATCHED_GAP")
                roles=["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]
            elif kind == "SUPPORTED_OPENING":
                continuity,status,confidence,reason=("SUPPORTED_WALL_CONTINUITY","SUPPORTED",.65,
                                                     "COLLINEAR_WALL_INTERRUPTION_REQUIRES_CORROBORATION")
                roles=[]
            elif kind == "LIKELY_OPENING":
                continuity,status,confidence,reason=("INSUFFICIENT_CONTINUITY","INPUT_REQUIRED",.4,
                                                     "LIKELY_OPENING_REQUIRES_CORROBORATION")
                roles=[]
            elif kind == "AMBIGUOUS_FACE_PAIRING":
                continuity,status,confidence,reason=("INSUFFICIENT_CONTINUITY","INPUT_REQUIRED",0.0,
                                                     "MULTIPLE_VALID_FACE_PAIRINGS")
                roles=[]
            else:
                continuity,status,confidence,reason=("INSUFFICIENT_CONTINUITY","INPUT_REQUIRED",.25,
                                                     "UNMATCHED_OR_DRAFTING_FRAGMENTATION")
                roles=[]
            rows.append({"closure_id":_sid("CLOSURE",[wall["wall_id"],index,geometry]),
                         "frame_id":frame_id or wall.get("frame_id"),"host_wall_id":wall["wall_id"],
                         "host_material_interval_ids":host_materials,
                         "axis_interval":[low,high],"geometry":geometry,
                         "continuity_status":continuity,"status":status,
                         "wall_representation":wall.get("representation"),
                         "face_a_support":bool(opening.get("face_a_gap")),
                         "face_b_support":bool(opening.get("face_b_gap")),
                         "collinear_support":kind in {"PROVEN_OPENING","SUPPORTED_OPENING","LIKELY_OPENING"},
                         "junction_support":False,"source_handles":wall.get("source_handles") or [],
                         "source_evidence":wall.get("source_fragments") or [],
                         "source_lineage":wall.get("source_lineage") or [],"gap_width":high-low,
                         "junction_wall_id":opening.get("junction_wall_id"),
                         "junction_source_handles":opening.get("junction_source_handles") or [],
                         "junction_source_lineage":opening.get("junction_source_lineage") or [],
                         "junction_material_interval_ids":opening.get("junction_material_interval_ids") or [],
                         "junction_material_intervals":opening.get("junction_material_intervals") or [],
                         "junction_material_binding_distance":opening.get("junction_material_binding_distance"),
                         "junction_face_binding_distance":opening.get("junction_face_binding_distance"),
                         "proof_class":opening.get("proof_class"),
                         "material":False,"roles":roles,"possible_opening_type":"UNKNOWN",
                         "material_geometry":"NONE","wall_authority":"NONE",
                         "routing_authority":"NONE","portal_authority":"NONE","access_authority":"NONE",
                         "confidence":confidence,"evidence":[{"class":"WALL_INTERRUPTION_CONTINUITY","kind":kind,
                                                               "paired_face_gap":both_faces,
                                                               "material_on_both_sides":material_on_both_sides,
                                                               "host_material_interval_ids":host_materials}],"reason":reason})
    return rows


def source_supported_endpoint_closures(walls, *, frame_id=None, tolerance=0.001):
    """Enumerate endpoint relations and select only independently proven closures.

    The maximum join distance is derived from local double-face thicknesses.
    Proximity and orthogonality define candidate-search scope only.  Every
    plausible relation is retained; endpoint exclusivity applies only to the
    independently proven closure layer.
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
    materials=[]
    for wall in candidates:
        for material in _material_interval_records(wall):
            materials.append({"wall":wall,**material})
    endpoints=[]
    for index,material in enumerate(materials):
        line=material["line"]
        endpoints.extend([(index,Point(line.coords[0])),(index,Point(line.coords[-1]))])
    tree=STRtree([point for _,point in endpoints]); proposals={}
    for endpoint_index,(material_index,point) in enumerate(endpoints):
        left_material=materials[material_index]; left=left_material["wall"]
        (left_u,left_n,left_angle,_)=_axis(left_material["line"])
        for raw in tree.query(point.buffer(opening_limit)):
            other_endpoint_index=int(raw)
            if other_endpoint_index<=endpoint_index:continue
            other_material_index,other_point=endpoints[other_endpoint_index]
            right_material=materials[other_material_index]; right=right_material["wall"]
            if right["wall_id"]==left["wall_id"]:continue
            if left_material["line"].intersection(right_material["line"]).length>tol:continue
            (_,_,right_angle,_)=_axis(right_material["line"])
            delta=min(abs(left_angle-right_angle),180-abs(left_angle-right_angle))
            distance=point.distance(other_point)
            if distance<=tol:continue
            relation=None; limit=corner_limit; proven_continuity=False; proof_class=None
            shared_source=bool(
                set(left.get("source_fragments") or []).intersection(right.get("source_fragments") or [])
                or set(left.get("source_handles") or []).intersection(right.get("source_handles") or []))
            shared_junction_ids=sorted(set(left.get("junctions") or [])
                                       & set(right.get("junctions") or []))
            if delta<=3.0:
                # Collinear proximity is not an aperture or continuity proof.
                # Exact shared lineage may prove bounded drafting fragmentation;
                # otherwise independent opening evidence is required later.
                perpendicular_offset=abs((other_point.x-point.x)*left_n[0]+(other_point.y-point.y)*left_n[1])
                if perpendicular_offset>max(tol*4,typical*.35):continue
                if shared_source:
                    relation="GOVERNED_DRAFTING_FRAGMENTATION"; proven_continuity=True
                    proof_class="SHARED_SOURCE_LINEAGE"
                    limit=corner_limit
                else:
                    relation="COLLINEAR_GAP_REQUIRES_OPENING_OR_LINEAGE"
                    limit=opening_limit if left in proven and right in proven else corner_limit
            elif abs(delta-90)<=3.0:
                face_intersections=[]
                for left_face in (left.get("face_a"),left.get("face_b")):
                    if not left_face or len(left_face)<2: continue
                    for right_face in (right.get("face_a"),right.get("face_b")):
                        if not right_face or len(right_face)<2: continue
                        intersection=LineString(left_face).intersection(LineString(right_face))
                        candidates_for_intersection=[]
                        if intersection.geom_type=="Point": candidates_for_intersection=[intersection]
                        elif intersection.geom_type=="MultiPoint": candidates_for_intersection=list(intersection.geoms)
                        elif intersection.geom_type in {"LineString","MultiLineString"} and not intersection.is_empty:
                            lines=[intersection] if intersection.geom_type=="LineString" else list(intersection.geoms)
                            candidates_for_intersection=[Point(value) for line in lines
                                                         for value in (line.coords[0],line.coords[-1])]
                        for witness in candidates_for_intersection:
                            if witness.distance(point)<=corner_limit and witness.distance(other_point)<=corner_limit:
                                face_intersections.append([witness.x,witness.y])
                if shared_source:
                    relation="PROVEN_CORNER_CONTINUITY"; proven_continuity=True
                    proof_class="SHARED_SOURCE_LINEAGE"
                elif face_intersections:
                    relation="PROVEN_CORNER_CONTINUITY"; proven_continuity=True
                    proof_class="SOURCE_FACE_GEOMETRIC_INTERSECTION"
                else:
                    relation="UNRESOLVED_ENDPOINT_RELATION"
            else:continue
            if distance>limit:continue
            geometry=sorted([[point.x,point.y],[other_point.x,other_point.y]])
            host_wall_ids=sorted([left["wall_id"],right["wall_id"]])
            host_material_interval_ids=sorted([left_material["material_interval_id"],
                                               right_material["material_interval_id"]])
            candidate_id=_sid("ENDREL",[host_wall_ids,host_material_interval_ids,geometry])
            proposals[candidate_id]={"candidate_relation_id":candidate_id,"closure_id":None,
                "frame_id":frame_id or left.get("frame_id"),
                "host_wall_ids":host_wall_ids,"host_material_interval_ids":host_material_interval_ids,
                "geometry":geometry,
                "continuity_status":"CANDIDATE_RELATION","status":"CANDIDATE",
                "material":False,"material_geometry":"NONE","wall_authority":"NONE",
                "routing_authority":"NONE","portal_authority":"NONE","access_authority":"NONE",
                "roles":[],"reason":relation,"proof_class":proof_class,
                "proof_sufficient":proven_continuity,"selected_as_governed_closure":False,
                "gap_width":distance,"derived_join_limit":limit,
                "_endpoint_indexes":[endpoint_index,other_endpoint_index],
                "source_handles":sorted(set((left.get("source_handles") or [])+(right.get("source_handles") or []))),
                "source_evidence":sorted(set((left.get("source_fragments") or [])+(right.get("source_fragments") or []))),
                "source_lineage":sorted((left.get("source_lineage") or [])+(right.get("source_lineage") or []),
                                        key=lambda row:json.dumps(row,sort_keys=True)),
                "host_material_geometry":{
                    left_material["material_interval_id"]:[list(value) for value in left_material["line"].coords],
                    right_material["material_interval_id"]:[list(value) for value in right_material["line"].coords]},
                "evidence":[{"class":relation,"proof_class":proof_class,
                             "source_face_intersections":face_intersections if abs(delta-90)<=3.0 else [],
                             "canonical_junction_ids":shared_junction_ids,
                             "wall_angle_delta":delta,"local_wall_thickness":typical,
                             "host_material_interval_ids":host_material_interval_ids}]}
    used_endpoints=set()
    for row in sorted(proposals.values(),key=lambda item:(not item["proof_sufficient"],item["gap_width"],
                                                          item["candidate_relation_id"])):
        indexes=set(row.pop("_endpoint_indexes"))
        if not row["proof_sufficient"]: continue
        if indexes & used_endpoints:
            row["selection_status"]="PROVEN_NOT_SELECTED_ENDPOINT_CONFLICT"
            continue
        used_endpoints.update(indexes)
        row["selected_as_governed_closure"]=True
        row["selection_status"]="SELECTED_PROVEN_CLOSURE"
        row["closure_id"]=_sid("ENDCLOSE",[row["candidate_relation_id"]])
        row["continuity_status"]="PROVEN_WALL_CONTINUITY"; row["status"]="PROVEN"
        row["roles"]=["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]
    for row in proposals.values():
        if not row.get("selection_status"):
            row["selection_status"]="DIAGNOSTIC_ONLY"
            row["continuity_status"]="INSUFFICIENT_CONTINUITY"
            row["status"]="INPUT_REQUIRED"
    return sorted(proposals.values(),key=lambda row:row["candidate_relation_id"])


def material_continuity_graph(walls, closures=(), *, frame_id=None, tolerance=.001):
    """Describe a properly noded source-material network without adding authority."""
    tol=max(float(tolerance or .001),1e-9)
    material_edges=[]; material_by_id={}
    for wall in sorted(walls,key=lambda row:row["wall_id"]):
        for material in _material_interval_records(wall):
            edge={"edge_id":material["material_interval_id"],"edge_type":"SOURCE_MATERIAL",
                  "wall_id":wall["wall_id"],"source_handles":sorted(wall.get("source_handles") or []),
                  "source_lineage":wall.get("source_lineage") or [],"line":material["line"]}
            material_edges.append(edge); material_by_id[edge["edge_id"]]=edge
    # Node every actual material intersection and endpoint-on-material event.
    split_distances={edge["edge_id"]:{0.0,edge["line"].length} for edge in material_edges}
    material_tree=STRtree([edge["line"] for edge in material_edges]) if material_edges else None
    for index,left in enumerate(material_edges):
        for raw in material_tree.query(left["line"].buffer(tol)) if material_tree is not None else []:
            other_index=int(raw)
            if other_index<=index: continue
            right=material_edges[other_index]
            intersection=left["line"].intersection(right["line"])
            witnesses=[]
            if intersection.geom_type=="Point": witnesses=[intersection]
            elif intersection.geom_type=="MultiPoint": witnesses=list(intersection.geoms)
            elif intersection.geom_type in {"LineString","MultiLineString"} and not intersection.is_empty:
                lines=[intersection] if intersection.geom_type=="LineString" else list(intersection.geoms)
                witnesses=[Point(value) for line in lines for value in (line.coords[0],line.coords[-1])]
            for endpoint in (Point(left["line"].coords[0]),Point(left["line"].coords[-1])):
                if endpoint.distance(right["line"])<=tol: witnesses.append(endpoint)
            for endpoint in (Point(right["line"].coords[0]),Point(right["line"].coords[-1])):
                if endpoint.distance(left["line"])<=tol: witnesses.append(endpoint)
            for witness in witnesses:
                if witness.distance(left["line"])<=tol:
                    split_distances[left["edge_id"]].add(left["line"].project(witness))
                if witness.distance(right["line"])<=tol:
                    split_distances[right["edge_id"]].add(right["line"].project(witness))
    graph_material_edges=[]
    for edge in material_edges:
        distances=sorted(split_distances[edge["edge_id"]])
        for low,high in zip(distances,distances[1:]):
            if high-low<=1e-12: continue
            a=edge["line"].interpolate(low); b=edge["line"].interpolate(high)
            segment_id=_sid("MATSEG",[edge["edge_id"],round(low,9),round(high,9),
                                       [a.x,a.y],[b.x,b.y]])
            graph_material_edges.append({**edge,"edge_id":segment_id,
                                         "material_interval_id":edge["edge_id"],
                                         "edge_type":"SOURCE_MATERIAL","line":LineString((a,b))})
    closure_edges=[]
    for closure in sorted(closures,key=lambda row:row.get("closure_id") or ""):
        host_ids=closure.get("host_material_interval_ids") or []
        if not (closure.get("continuity_status") in {"PROVEN_WALL_CONTINUITY","SUPPORTED_WALL_CONTINUITY"}
                and "ENVELOPE_SUPPORT" in (closure.get("roles") or [])
                and closure.get("material") is False
                and closure.get("wall_authority")=="NONE"
                and closure.get("portal_authority")=="NONE"
                and closure.get("routing_authority")=="NONE"
                and host_ids and all(mid in material_by_id for mid in host_ids)):
            continue
        line=LineString(closure["geometry"])
        host_endpoints=[Point(point) for mid in host_ids for point in material_by_id[mid]["line"].coords]
        if any(min((Point(point).distance(host) for host in host_endpoints),default=float("inf"))>tol
               for point in line.coords):
            continue
        closure_edges.append({"edge_id":closure["closure_id"],"edge_type":"GOVERNED_NONMATERIAL_CONTINUITY",
                              "wall_id":None,"source_handles":sorted(closure.get("source_handles") or []),
                              "source_lineage":closure.get("source_lineage") or [],"line":line,
                              "host_material_interval_ids":sorted(host_ids)})
    edges=graph_material_edges+closure_edges
    points=[tuple(point) for edge in edges for point in (edge["line"].coords[0],edge["line"].coords[-1])]
    parent=list(range(len(points)))
    def find(index):
        while parent[index]!=index:
            parent[index]=parent[parent[index]]; index=parent[index]
        return index
    def union(left,right):
        left,right=find(left),find(right)
        if left!=right: parent[max(left,right)]=min(left,right)
    for index,point in enumerate(points):
        for other in range(index):
            if math.dist(point,points[other])<=tol: union(index,other)
    edge_parent=list(range(len(edges)))
    def edge_find(index):
        while edge_parent[index]!=index:
            edge_parent[index]=edge_parent[edge_parent[index]]; index=edge_parent[index]
        return index
    def edge_union(left,right):
        left,right=edge_find(left),edge_find(right)
        if left!=right: edge_parent[max(left,right)]=min(left,right)
    node_edges={}
    for index in range(len(edges)):
        node_edges.setdefault(find(index*2),[]).append(index)
        node_edges.setdefault(find(index*2+1),[]).append(index)
    for indexes in node_edges.values():
        for index in indexes[1:]: edge_union(indexes[0],index)
    component_edges={}
    for index,edge in enumerate(edges): component_edges.setdefault(edge_find(index),[]).append((index,edge))
    components=[]; open_endpoints=[]
    for _,members in sorted(component_edges.items(),key=lambda item:min(row[1]["edge_id"] for row in item[1])):
        point_indexes=sorted({index*2+offset for index,_ in members for offset in (0,1)})
        node_groups={}
        for point_index in point_indexes: node_groups.setdefault(find(point_index),[]).append(point_index)
        degrees={node:0 for node in node_groups}; material_degrees={node:0 for node in node_groups}
        incident={node:[] for node in node_groups}
        for index,edge in members:
            for node in (find(index*2),find(index*2+1)):
                degrees[node]+=1; incident[node].append(edge["edge_id"])
                if edge["edge_type"]=="SOURCE_MATERIAL": material_degrees[node]+=1
        material_ids=sorted({edge["material_interval_id"] for _,edge in members
                             if edge["edge_type"]=="SOURCE_MATERIAL"})
        closure_ids=sorted(edge["edge_id"] for _,edge in members if edge["edge_type"]!="SOURCE_MATERIAL")
        component_id=_sid("MATCOMP",[frame_id,material_ids,closure_ids])
        coordinates=[points[index] for index in point_indexes]
        wall_ids=sorted({edge["wall_id"] for _,edge in members if edge.get("wall_id")})
        handles=sorted({handle for _,edge in members for handle in edge.get("source_handles") or []})
        open_nodes=[]
        for node,indexes in sorted(node_groups.items(),key=lambda item:min(points[index] for index in item[1])):
            if degrees[node]!=1: continue
            coordinate=min(points[index] for index in indexes)
            incident_edges=[edge for _,edge in members if edge["edge_id"] in incident[node]]
            source_edges=[edge for edge in incident_edges if edge["edge_type"]=="SOURCE_MATERIAL"]
            source_edge=source_edges[0] if source_edges else None
            orientation=round(_axis(source_edge["line"])[2],6) if source_edge else None
            endpoint={"endpoint_id":_sid("MATEND",[frame_id,component_id,coordinate]),
                      "component_id":component_id,"coordinates":list(coordinate),
                      "incident_edge_ids":sorted(incident[node]),
                      "wall_id":source_edge.get("wall_id") if source_edge else None,
                      "material_interval_id":source_edge.get("material_interval_id") if source_edge else None,
                      "source_handles":source_edge.get("source_handles",[]) if source_edge else [],
                      "source_lineage":source_edge.get("source_lineage",[]) if source_edge else [],
                      "orientation_degrees":orientation}
            open_nodes.append(endpoint); open_endpoints.append(endpoint)
        edge_count=len(members); node_count=len(node_groups); cycle_rank=max(0,edge_count-node_count+1)
        material_junction_count=sum(degree>=3 for degree in material_degrees.values())
        components.append({"component_id":component_id,"frame_id":frame_id,
                           "material_interval_ids":material_ids,"matint_count":len(material_ids),
                           "graph_segment_count":sum(edge["edge_type"]=="SOURCE_MATERIAL" for _,edge in members),
                           "material_junction_count":material_junction_count,
                           "wall_ids":wall_ids,"source_handles":handles,
                           "total_material_length":sum(edge["line"].length for _,edge in members
                                                       if edge["edge_type"]=="SOURCE_MATERIAL"),
                           "bounds":[min(x for x,_ in coordinates),min(y for _,y in coordinates),
                                     max(x for x,_ in coordinates),max(y for _,y in coordinates)],
                           "endpoint_count":node_count,"open_endpoint_count":len(open_nodes),
                           "closure_count":len(closure_ids),"closure_ids":closure_ids,
                           "cycle_rank":cycle_rank,"closed_cycle":cycle_rank>0 and not open_nodes})
    # Nearest endpoints are diagnostic only.  They are deliberately computed
    # after connectivity and never feed an edge-selection rule.
    for endpoint in open_endpoints:
        nearest=[]
        for other in open_endpoints:
            if other["endpoint_id"]==endpoint["endpoint_id"]: continue
            angle_delta=None
            if endpoint["orientation_degrees"] is not None and other["orientation_degrees"] is not None:
                raw=abs(endpoint["orientation_degrees"]-other["orientation_degrees"])
                angle_delta=min(raw,180-raw)
            nearest.append({"endpoint_id":other["endpoint_id"],
                            "component_id":other["component_id"],
                            "distance":math.dist(endpoint["coordinates"],other["coordinates"]),
                            "angle_relationship_degrees":angle_delta,
                            "same_source":bool(set(endpoint["source_handles"])
                                               & set(other["source_handles"]))})
        endpoint["nearest_material_endpoints"]=sorted(
            nearest,key=lambda row:(row["distance"],row["endpoint_id"]))[:5]
    serialized_edges=[]
    for edge in edges:
        serialized_edges.append({key:value for key,value in edge.items() if key not in {"line"}} | {
            "geometry":[list(point) for point in edge["line"].coords]})
    return {"schema":"material-continuity-graph/1.0","frame_id":frame_id,
            "components":components,"open_endpoints":sorted(open_endpoints,key=lambda row:row["endpoint_id"]),
            "edges":serialized_edges,
            "graph_segment_count":len(graph_material_edges),
            "material_junction_count":sum(row["material_junction_count"] for row in components)}


def _same_interval(left, right, tolerance):
    return (isinstance(left,(list,tuple)) and isinstance(right,(list,tuple))
            and len(left)==2 and len(right)==2
            and abs(float(left[0])-float(right[0]))<=tolerance
            and abs(float(left[1])-float(right[1]))<=tolerance)


def _proven_material_aperture_match(closure, opening, *, tolerance):
    """Bind a supporting motif to an independently proven material gap.

    A symbol never proves the gap.  The gap must already be a canonical
    interruption of one exact host Wall, bounded by two source-material
    intervals with paired-face and lineage evidence.  Endpoint relations are
    deliberately ineligible: proximity between separate Walls is not an
    aperture contract.
    """
    host_wall_id=closure.get("host_wall_id")
    axis_interval=closure.get("axis_interval")
    evidence=next((row for row in closure.get("evidence") or []
                   if row.get("class")=="WALL_INTERRUPTION_CONTINUITY"),{})
    material_ids=closure.get("host_material_interval_ids") or []
    source_backed=bool(closure.get("source_handles")) and bool(
        closure.get("source_lineage") or closure.get("source_evidence"))
    gap_proven=(host_wall_id and axis_interval and len(material_ids)>=2
                and evidence.get("paired_face_gap") is True
                and evidence.get("material_on_both_sides") is True
                and source_backed)
    if not gap_proven:
        return False,"MATERIAL_GAP_UNPROVEN"
    if not any(opening.get("source_handles") or []):
        return False,"OPENING_SOURCE_PROVENANCE_MISSING"
    candidate_hosts=set(opening.get("candidate_host_wall_ids") or [])
    if host_wall_id not in candidate_hosts:
        return False,"EXACT_HOST_WALL_MISMATCH"
    host_evaluation=next((row for row in opening.get("host_evaluations") or []
                          if row.get("wall_id")==host_wall_id),None)
    if not host_evaluation:
        return False,"EXACT_HOST_EVALUATION_MISSING"
    if host_evaluation.get("orientation_agreement") != "PARALLEL_OR_PERPENDICULAR":
        return False,"OPENING_ORIENTATION_CONFLICT"
    if not (host_evaluation.get("wall_material_before") is True
            and host_evaluation.get("wall_material_after") is True):
        return False,"HOST_MATERIAL_SIDES_UNPROVEN"
    exact_gap=any(_same_interval(row.get("interval"),axis_interval,tolerance)
                  for row in host_evaluation.get("nearby_interruptions") or [])
    if not exact_gap:
        return False,"EXACT_INTERRUPTION_MISMATCH"
    if opening.get("material_gap_status") not in {None,"UNPROVEN","SOURCE_BACKED_PROVEN"}:
        return False,"MATERIAL_GAP_STATUS_CONFLICT"
    return True,"SOURCE_BACKED_MATERIAL_APERTURE"


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
            material_match,material_reason=_proven_material_aperture_match(
                closure,opening,tolerance=max(float(tolerance or .001),1e-9))
            if material_match:
                matching.append(opening)
            opening_matches.append({"opening_evidence_id":opening["opening_evidence_id"],
                                    "distance_to_gap":distance,
                                    "derived_locality_limit":locality_limit,
                                    "material_aperture_match":material_match,
                                    "material_aperture_reason":material_reason})
        portal_types=sorted({str(row.get("candidate_type") or "").upper() for row in matching})
        reason=closure.get("reason")
        if "DOOR" in portal_types:
            classification,status="PROVEN_DOOR_APERTURE","SUPPORTED"
        elif "WINDOW" in portal_types:
            classification,status="PROVEN_WINDOW_APERTURE","SUPPORTED"
        elif (reason=="PROVEN_CORNER_CONTINUITY"
              and closure.get("selected_as_governed_closure",True)):
            classification,status="PROVEN_CORNER_CONTINUITY","PROVEN"
        elif (reason=="GOVERNED_DRAFTING_FRAGMENTATION"
              and closure.get("selected_as_governed_closure",True)):
            classification,status="GOVERNED_DRAFTING_FRAGMENTATION","PROVEN"
        elif (reason=="UNRESOLVED_ENDPOINT_RELATION"
              and any(wall_by_id[wall_id].get("status")=="SUPPORTED_PARTITION"
                      and wall_by_id[wall_id].get("representation")=="SINGLE_LINE"
                      for wall_id in host_ids if wall_id in wall_by_id)):
            # The source material exists, but the architectural role of a
            # recovered single line is not independently authoritative.  This
            # is a bounded source-role question, never continuity authority.
            classification,status="SOURCE_ROLE_CLASSIFICATION_REQUIRED","INPUT_REQUIRED"
        else:
            classification,status="UNRESOLVED","INPUT_REQUIRED"
        if (classification in {"PROVEN_DOOR_APERTURE","PROVEN_WINDOW_APERTURE"}
                and closure.get("host_material_interval_ids")):
            closure.update({"continuity_status":"PROVEN_WALL_CONTINUITY","status":"SUPPORTED",
                            "roles":["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]})
        if classification=="SOURCE_ROLE_CLASSIFICATION_REQUIRED":
            ownership="SOURCE_ROLE_REVIEWABLE"
        elif classification!="UNRESOLVED":
            ownership=None
        elif reason=="COLLINEAR_GAP_REQUIRES_OPENING_OR_LINEAGE":
            ownership="OPENING_EVIDENCE_REQUIRED"
        elif reason=="UNMATCHED_OR_DRAFTING_FRAGMENTATION":
            ownership="ENGINE_DETECTOR_LIMITATION"
        elif reason in {"PAIRED_FACES_CONTINUE_ACROSS_MATCHED_GAP",
                        "MULTIPLE_VALID_FACE_PAIRINGS"}:
            ownership="GENUINE_AMBIGUITY"
        elif reason in {"PROVEN_CORNER_CONTINUITY","GOVERNED_DRAFTING_FRAGMENTATION"}:
            ownership="GENUINE_AMBIGUITY"
        elif reason=="UNRESOLVED_ENDPOINT_RELATION":
            ownership="GENUINE_AMBIGUITY"
        else:
            ownership="OTHER"
        gap_id=_sid("GAP",[frame_id,sorted(host_ids),closure.get("geometry")])
        closure.update({"gap_id":gap_id,"gap_classification":classification,
                        "gap_status":status,"unresolved_ownership":ownership,
                        "material_gap_status":("SOURCE_BACKED_PROVEN"
                                               if classification in {"PROVEN_DOOR_APERTURE",
                                                                     "PROVEN_WINDOW_APERTURE"}
                                               else "UNPROVEN"),
                        "portal_evidence_ids":sorted(
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
                     "candidate_relation_id":closure.get("candidate_relation_id"),
                     "unresolved_ownership":ownership,
                     "material_gap_status":closure["material_gap_status"],
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
