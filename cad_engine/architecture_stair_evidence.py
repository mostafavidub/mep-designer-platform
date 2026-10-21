"""Conservative stair-flight and stair-assembly evidence from native CAD.

The output is inventory evidence, not code compliance, egress, safety, or
constructability approval. Physical stair identity remains reviewable when
several drawn flights cannot be joined unambiguously.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
import re

import numpy as np


SCHEMA = "planha-architectural-stair-evidence/1.0"
DETECTOR_REVISION = "corner-landing-and-short-arrow-flight-recovery/1.4.1"
PLAN_TYPES = {"ARCH_FLOOR_PLAN", "FURNITURE_PLAN", "PARKING_PLAN", "ROOF_PLAN",
              "LINTEL_PLAN", "SLOPE_PLAN", "PRIMARY_FLOOR", "ROOF", "SITE"}
EXCLUDED_CONTEXT = re.compile(
    r"dimension|\bdim\b|hatch|grid|axis|window|door|furniture|annotation|"
    r"اندازه|هاشور|محور|پنجره|درب|مبلمان", re.I)


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def _source_ref(row):
    own = str(row.get("handle") or _hash(row)[:16])
    insert = row.get("source_insert_handle")
    return f"{insert}/{own}" if insert else own


def _in_bounds(point, bounds, tolerance=1e-8):
    return bool(bounds and bounds[0]-tolerance <= point[0] <= bounds[2]+tolerance
                and bounds[1]-tolerance <= point[1] <= bounds[3]+tolerance)


def _frame_for(point, frames):
    matches = [row for row in frames if _in_bounds(point, row.get("bounds"))]
    if len(matches) != 1:
        return None, "AMBIGUOUS_FRAME" if matches else "OUTSIDE_CONFIRMED_FRAME"
    frame = matches[0]
    kind = frame.get("drawing_type") or frame.get("frame_type") or frame.get("view_type")
    if str(kind or "").upper() not in PLAN_TYPES and "plan" not in str(kind or "").lower():
        return frame, "NON_PLAN_VIEW"
    return frame, "PLAN_VIEW"


def _bounds(rows):
    points = []
    for row in rows:
        if row.get("entity_type") == "LINE":
            points.extend((row["start"], row["end"]))
        elif row.get("entity_type") == "ARC":
            c, r = row["center"], float(row["radius"])
            points.extend(([c[0]-r, c[1]-r], [c[0]+r, c[1]+r]))
    if not points:
        return None
    values = np.asarray(points, dtype=float)
    return [float(values[:, 0].min()), float(values[:, 1].min()),
            float(values[:, 0].max()), float(values[:, 1].max())]


def _recover_parallel_rows(candidate, lines, p, q, center, length, unit, frames):
    """Recover shorter/broken terminal rows on the seed flight's spacing grid.

    A recovered line remains geometry evidence only: an end row can be a tread,
    riser or landing boundary and is not assigned an engineering role here.
    """
    u = np.asarray(candidate["orientation"], dtype=float)
    v = np.asarray([-u[1], u[0]])
    seed_indexes = list(candidate["indexes"])
    spacing = float(candidate["spacing"])
    representative = float(candidate["tread_length"])
    seed_offsets = center[seed_indexes] @ v
    origin = float(seed_offsets.min())
    seed_keys = {int(round((value-origin)/spacing)) for value in seed_offsets}
    seed_lo, seed_hi = min(seed_keys), max(seed_keys)
    seed_intervals = np.sort(np.stack((p[seed_indexes]@u, q[seed_indexes]@u), axis=1), axis=1)
    envelope = [float(seed_intervals[:, 0].min()), float(seed_intervals[:, 1].max())]
    by_station = defaultdict(list)
    for index, row in enumerate(lines):
        frame, scope = _frame_for(center[index], frames)
        if scope != "PLAN_VIEW" or frame is not candidate["frame"]:
            continue
        if abs(float(unit[index]@u)) < .9998 or length[index] < .12*representative:
            continue
        offset = float(center[index]@v)
        station = int(round((offset-origin)/spacing))
        if station < seed_lo-4 or station > seed_hi+4:
            continue
        if abs(offset-(origin+station*spacing)) > max(.10*spacing, .008*representative):
            continue
        interval = sorted((float(p[index]@u), float(q[index]@u)))
        overlap = max(0., min(envelope[1], interval[1])-max(envelope[0], interval[0]))
        interval_gap = max(0., max(envelope[0], interval[0])-min(envelope[1], interval[1]))
        adjacent_fragment = interval_gap <= .03*representative and length[index] >= .35*representative
        if adjacent_fragment and overlap <= 0:
            boundary=(min(envelope[1],interval[1])+max(envelope[0],interval[0]))/2
            seed_v_min=float(seed_offsets.min()); seed_v_max=float(seed_offsets.max())
            for other in range(len(lines)):
                if abs(float(unit[other]@v)) < .9998:
                    continue
                other_u=float(center[other]@u)
                other_v=sorted((float(p[other]@v),float(q[other]@v)))
                vertical_overlap=max(0.,min(seed_v_max,other_v[1])-max(seed_v_min,other_v[0]))
                if abs(other_u-boundary) <= .03*representative and vertical_overlap >= .7*(seed_v_max-seed_v_min):
                    adjacent_fragment=False
                    break
        if overlap < min(.12*representative, .55*length[index]) and not adjacent_fragment:
            continue
        by_station[station].append(index)
    # Extend only through consecutive native stations adjacent to the seed.
    lo, hi = seed_lo, seed_hi
    while lo-1 in by_station and seed_lo-(lo-1) <= 4: lo -= 1
    while hi+1 in by_station and (hi+1)-seed_hi <= 4: hi += 1
    recovered=[]; stations=[]
    for station in range(lo, hi+1):
        indexes=sorted(set(by_station.get(station, [])))
        if not indexes:
            continue
        refs=sorted(_source_ref(lines[index]) for index in indexes)
        intervals=[sorted((float(p[index]@u),float(q[index]@u))) for index in indexes]
        role = "SEED_REGULAR_TREAD_ROW" if station in seed_keys else "TREAD_OR_BOUNDARY_UNRESOLVED"
        stations.append({"station":station,"offset":origin+station*spacing,"source_refs":refs,
                         "intervals":intervals,"role":role})
        recovered.extend(indexes)
    unique=tuple(sorted(set(recovered)))
    candidate["indexes"]=unique
    candidate["rows"]=[lines[index] for index in unique]
    candidate["bounds"]=_bounds(candidate["rows"])
    candidate["source_refs"]=sorted(_source_ref(row) for row in candidate["rows"])
    candidate["center"]=[(candidate["bounds"][0]+candidate["bounds"][2])/2,
                         (candidate["bounds"][1]+candidate["bounds"][3])/2]
    candidate["row_stations"]=stations
    candidate["seed_source_refs"]=sorted(_source_ref(lines[index]) for index in seed_indexes)
    candidate["recovered_source_refs"]=sorted(set(candidate["source_refs"])-set(candidate["seed_source_refs"]))
    return candidate


def _linear_flights(primitives, frames):
    lines = [row for row in primitives
             if row.get("entity_type") == "LINE" and row.get("start") and row.get("end")
             and row.get("handle") and not EXCLUDED_CONTEXT.search(" ".join(
                 str(row.get(key) or "") for key in ("layer", "source_block", "name")))]
    if not lines:
        return []
    p = np.asarray([row["start"] for row in lines], dtype=float)
    q = np.asarray([row["end"] for row in lines], dtype=float)
    delta = q-p
    length = np.linalg.norm(delta, axis=1)
    valid = length > 1e-9
    unit = np.zeros_like(delta)
    unit[valid] = delta[valid]/length[valid, None]
    center = (p+q)/2
    candidates = {}
    # Sub-0.8-unit repeated linework in this corpus is dominated by window
    # panes, threshold marks and compact roof/equipment arrows.  Real reviewed
    # tread rows remain at least 0.9 units long.  Keeping this gate here also
    # prevents a short four-pane window from seeding a larger candidate set.
    for i in np.where(valid & (length >= .8) & (length <= 3.5))[0]:
        frame, scope = _frame_for(center[i], frames)
        if scope != "PLAN_VIEW":
            continue
        u = unit[i].copy()
        if u[0] < -1e-9 or (abs(u[0]) < 1e-9 and u[1] < 0):
            u = -u
        v = np.array([-u[1], u[0]])
        own = np.sort([p[i]@u, q[i]@u])
        same_frame = np.asarray([_frame_for(value, frames)[0] is frame for value in center])
        parallel = np.abs(unit@u) >= .9998
        size = (length >= .65*length[i]) & (length <= 1.35*length[i])
        intervals = np.sort(np.stack((p@u, q@u), axis=1), axis=1)
        overlap = np.maximum(0, np.minimum(own[1], intervals[:, 1])-np.maximum(own[0], intervals[:, 0]))
        mask = same_frame & parallel & size & (overlap >= .72*np.minimum(length[i], length))
        indexes = np.where(mask)[0]
        offsets = center[indexes]@v
        order = np.argsort(offsets)
        indexes, offsets = indexes[order], offsets[order]
        for start in range(len(indexes)):
            for stop in range(start+4, len(indexes)+1):
                members = indexes[start:stop]
                gaps = np.diff(offsets[start:stop])
                spacing = float(np.median(gaps))
                representative = float(np.median(length[members]))
                ratio = spacing/max(representative, 1e-12)
                if not .08 <= ratio <= .45:
                    continue
                if np.max(np.abs(gaps-spacing)) > max(.35*spacing, .015*representative):
                    continue
                key = tuple(sorted(int(value) for value in members))
                candidates[key] = {
                    "indexes": key, "spacing": spacing, "tread_length": representative,
                    "frame": frame, "scope": scope, "orientation": u.tolist(),
                }
    maximal = []
    for key, value in candidates.items():
        if any(set(key) < set(other) for other in candidates):
            continue
        rows = [lines[index] for index in key]
        bounds = _bounds(rows)
        refs = sorted(_source_ref(row) for row in rows)
        value.update({"rows": rows, "bounds": bounds, "source_refs": refs,
                      "center": [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]})
        maximal.append(_recover_parallel_rows(value, lines, p, q, center, length, unit, frames))
    # Seeds created from adjacent fragments can recover the same native rows.
    # Collapse exact recovered sets so one physical arm is not reported twice.
    deduplicated={}
    for value in maximal:
        key=tuple(value["source_refs"])
        prior=deduplicated.get(key)
        if prior is None or len(value["seed_source_refs"]) > len(prior["seed_source_refs"]):
            deduplicated[key]=value
    values=list(deduplicated.values())
    return [value for value in values if not any(
        set(value["source_refs"]) < set(other["source_refs"]) for other in values)]


def _short_arrow_flights(primitives, frames, claimed_refs):
    """Recover two/three-station exterior flights only with a native arrow.

    Two or three parallel rows alone are far too common in doors, windows and
    furniture.  A candidate therefore also needs a perpendicular shaft that
    spans the row stations and two native arrow-head segments connected to one
    shaft end.  The result is deliberately short-flight evidence, not proof of
    a complete stair assembly or landing boundary.
    """
    lines = [row for row in primitives if row.get("entity_type") == "LINE"
             and row.get("start") and row.get("end") and row.get("handle")]
    if not lines:
        return []
    p=np.asarray([row["start"] for row in lines],dtype=float)
    q=np.asarray([row["end"] for row in lines],dtype=float)
    delta=q-p; length=np.linalg.norm(delta,axis=1)
    unit=np.zeros_like(delta); valid=length>1e-9; unit[valid]=delta[valid]/length[valid,None]
    center=(p+q)/2
    candidates={}
    for i in np.where(valid & (length >= .65) & (length <= 3.5))[0]:
        frame,scope=_frame_for(center[i],frames)
        if scope != "PLAN_VIEW": continue
        u=unit[i].copy()
        if u[0] < -1e-9 or (abs(u[0]) < 1e-9 and u[1] < 0): u=-u
        v=np.asarray([-u[1],u[0]])
        same=np.asarray([_frame_for(value,frames)[0] is frame for value in center])
        parallel=np.abs(unit@u)>=.9998
        sizes=(length>=.65*length[i]) & (length<=1.4*length[i])
        own=np.sort([p[i]@u,q[i]@u])
        intervals=np.sort(np.stack((p@u,q@u),axis=1),axis=1)
        overlap=np.maximum(0,np.minimum(own[1],intervals[:,1])-np.maximum(own[0],intervals[:,0]))
        indexes=np.where(same & parallel & sizes & (overlap>=.65*np.minimum(length[i],length)))[0]
        offsets=center[indexes]@v
        order=np.argsort(offsets); indexes=indexes[order]; offsets=offsets[order]
        # Collapse duplicate native lines at one station (the exterior sample
        # contains one coincident row represented on two source layers).
        stations=[]
        for index,offset in zip(indexes,offsets):
            if not stations or abs(offset-stations[-1][0]) > .025:
                stations.append([float(offset),[int(index)]])
            else:
                stations[-1][1].append(int(index))
        for start in range(len(stations)):
            for count in (3,):
                group=stations[start:start+count]
                if len(group)!=count: continue
                gaps=np.diff([row[0] for row in group]); spacing=float(np.median(gaps))
                representative=float(np.median([length[j] for row in group for j in row[1]]))
                if not .08 <= spacing/max(representative,1e-12) <= .5: continue
                if np.max(np.abs(gaps-spacing)) > max(.2*spacing,.02*representative): continue
                row_indexes=sorted({j for row in group for j in row[1]})
                row_refs={_source_ref(lines[j]) for j in row_indexes}
                if row_refs & claimed_refs: continue
                row_lo=max(min(p[j]@u,q[j]@u) for j in row_indexes)
                row_hi=min(max(p[j]@u,q[j]@u) for j in row_indexes)
                station_lo,station_hi=group[0][0],group[-1][0]
                shafts=[]
                for j in np.where(same & (np.abs(unit@v)>=.9998))[0]:
                    ju=float(center[j]@u); ja,jb=sorted((float(p[j]@v),float(q[j]@v)))
                    if (row_lo+.15*(row_hi-row_lo) <= ju <= row_hi-.15*(row_hi-row_lo)
                            and ja <= station_lo+.08*spacing and jb >= station_hi-.08*spacing
                            and .65*(station_hi-station_lo) <= length[j] <= 1.8*(station_hi-station_lo)):
                        shafts.append(int(j))
                for shaft in shafts:
                    endpoints=(p[shaft],q[shaft]); arrow_refs=[]
                    for endpoint in endpoints:
                        connected=[]
                        for j in np.where(same & valid & (length>=.04*representative)
                                          & (length<=.22*representative))[0]:
                            if j==shaft: continue
                            if min(np.linalg.norm(p[j]-endpoint),np.linalg.norm(q[j]-endpoint)) <= .025*representative:
                                connected.append(int(j))
                        if len(connected)>=2:
                            arrow_refs=connected; break
                    if not arrow_refs: continue
                    key=tuple(sorted(row_refs))
                    candidates[key]={"indexes":tuple(row_indexes),"rows":[lines[j] for j in row_indexes],
                        "bounds":_bounds([lines[j] for j in row_indexes]),"frame":frame,"scope":scope,
                        "spacing":spacing,"tread_length":representative,"orientation":u.tolist(),
                        "source_refs":sorted(row_refs),"seed_source_refs":sorted(row_refs),
                        "recovered_source_refs":[],"arrow_source_refs":sorted({_source_ref(lines[shaft])}
                            | {_source_ref(lines[j]) for j in arrow_refs})}
                    break
    return list(candidates.values())


def _spiral_flights(primitives, frames):
    groups = defaultdict(list)
    for row in primitives:
        handle = row.get("source_insert_handle")
        if handle and row.get("entity_type") in {"LINE", "ARC"}:
            groups[str(handle)].append(row)
    morphology = []
    for handle, rows in groups.items():
        lines = [row for row in rows if row.get("entity_type") == "LINE"]
        arcs = [row for row in rows if row.get("entity_type") == "ARC"]
        bounds = _bounds(rows)
        if len(lines) < 16 or len(arcs) < 2 or not bounds:
            continue
        width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
        span = max(width, height)
        if span <= 0 or min(width, height)/span < .75:
            continue
        center = np.mean(np.asarray([row["center"] for row in arcs], dtype=float), axis=0)
        near_concentric = sum(math.dist(row["center"], center) <= .04*span for row in arcs)
        almost_full = sum(abs(float(row.get("signed_sweep_degrees") or 0)) >= 300 for row in arcs)
        radial = 0
        for row in lines:
            line_length = math.dist(row["start"], row["end"])
            endpoint_distance = min(math.dist(row["start"], center), math.dist(row["end"], center))
            if .2*span <= line_length <= .7*span and endpoint_distance <= .12*span:
                radial += 1
        if near_concentric < 2 or almost_full < 2 or radial < 12:
            continue
        frame, scope = _frame_for(center, frames)
        if scope != "PLAN_VIEW":
            continue
        morphology.append({"handle": handle, "rows": rows, "bounds": bounds,
                           "center": center.tolist(), "frame": frame, "scope": scope,
                           "radial_count": radial, "arc_count": len(arcs),
                           "source_refs": sorted(_source_ref(row) for row in rows)})
    # A repeated architectural family is required so a lone radial tree or
    # decorative symbol cannot become a spiral stair by shape alone.
    if len(morphology) < 2:
        return []
    return morphology


def _corner_landing_evidence(members, primitives):
    """Recover two native corner landings around a perpendicular middle arm.

    In a three-sided stair the middle arm occupies the centre of the apparent
    full-width landing strip.  Treating that strip as one polygon is false, but
    rejecting it wholesale loses the two real corner landings.  This recovery
    requires native terminal/remote chains and all four side boundaries for
    each corner; no boundary is synthesized from flight extents.
    """
    flights=[row for row in members if row["kind"]=="linear_flight"]
    if len(flights)<3: return []
    lines=[]
    for row in primitives:
        if row.get("entity_type")!="LINE" or not row.get("start") or not row.get("end") or not row.get("handle"): continue
        a=np.asarray(row["start"],dtype=float); b=np.asarray(row["end"],dtype=float)
        size=float(np.linalg.norm(b-a))
        if size>1e-9: lines.append((_source_ref(row),row,a,b,(b-a)/size))
    results=[]
    for stem in flights:
        s=np.asarray(stem["evidence"]["orientation_unit_vector"],dtype=float)
        arms=[row for row in flights if abs(float(np.asarray(row["evidence"]["orientation_unit_vector"])@s))<.02]
        if len(arms)<2: continue
        u=np.asarray(arms[0]["evidence"]["orientation_unit_vector"],dtype=float)
        if u[0] < -1e-9 or (abs(u[0])<1e-9 and u[1]<0): u=-u
        v=np.asarray([-u[1],u[0]])
        spacing=float(np.median([row["evidence"]["regular_spacing"] for row in arms+[stem]]))
        line_by_ref={item[0]:item[1] for item in lines}
        def projected_bounds(flight, *, seed_only=False):
            seed_rows=[line_by_ref[ref] for ref in flight.get("evidence",{}).get("seed_source_refs",[])
                       if ref in line_by_ref] if seed_only else []
            b=_bounds(seed_rows) if seed_rows else flight["geometry"]["bounds"]
            pts=np.asarray([[b[0],b[1]],[b[0],b[3]],[b[2],b[1]],[b[2],b[3]]])
            return [float((pts@u).min()),float((pts@v).min()),
                    float((pts@u).max()),float((pts@v).max())]
        # Recovered collinear rows can be side boundaries belonging to the
        # adjacent arms.  The middle-arm footprint must come from its regular
        # seed rows, otherwise its v-extent incorrectly consumes the landing.
        sb=projected_bounds(stem,seed_only=True)
        arm_boxes=[projected_bounds(row) for row in arms]
        arm_u_lo=min(b[0] for b in arm_boxes); arm_u_hi=max(b[2] for b in arm_boxes)
        arm_u_span=arm_u_hi-arm_u_lo
        arm_v_lo=min(b[1] for b in arm_boxes); arm_v_hi=max(b[3] for b in arm_boxes)
        junction=min((sb[1],sb[3]),key=lambda value:min(abs(value-arm_v_lo),abs(value-arm_v_hi)))
        if min(abs(junction-arm_v_lo),abs(junction-arm_v_hi)) > .18*spacing: continue
        remote=sb[3] if abs(junction-sb[1])<abs(junction-sb[3]) else sb[1]
        outer_terminal_offset=remote
        if abs(remote-junction)<max(.7,2*spacing): continue
        horizontal=[]; vertical=[]
        for item in lines:
            ref,row,a,b,direction=item
            if abs(float(direction@u))>=.9998:
                offset=float(((a+b)/2)@v); interval=sorted((float(a@u),float(b@u)))
                horizontal.append((ref,row,offset,interval))
            elif abs(float(direction@v))>=.9998:
                pos=float(((a+b)/2)@u); interval=sorted((float(a@v),float(b@v)))
                vertical.append((ref,row,pos,interval))
        terminal=[x for x in horizontal if abs(x[2]-junction)<=.08*spacing
                  and min(x[3][1],arm_u_hi)-max(x[3][0],arm_u_lo)>=.7*arm_u_span]
        if not terminal: continue
        terminal=max(terminal,key=lambda x:x[3][1]-x[3][0])
        terminal_span=terminal[3][1]-terminal[3][0]
        # The architectural wall face can sit one wall-thickness before the
        # final stem tread. Prefer a similarly sized closed boundary over a
        # longer room wall or the unconnected final tread line.
        remotes=[x for x in horizontal if abs(x[2]-remote)<=.8*spacing
                 and .7*terminal_span <= x[3][1]-x[3][0] <= 1.15*terminal_span
                 and min(x[3][1],terminal[3][1])-max(x[3][0],terminal[3][0])>=.7*terminal_span]
        if not remotes: continue
        remote_line=max(remotes,key=lambda x:x[3][1]-x[3][0])
        remote=remote_line[2]
        lo=max(terminal[3][0],remote_line[3][0]); hi=min(terminal[3][1],remote_line[3][1])
        stem_lo=max(lo,sb[0]); stem_hi=min(hi,sb[2])
        if min(stem_lo-lo,hi-stem_hi)<max(.45,1.25*spacing): continue
        for left,right in ((lo,stem_lo),(stem_hi,hi)):
            sides=[]
            for target in (left,right):
                matches=[x for x in vertical if abs(x[2]-target)<=max(.03,.1*spacing)
                         and x[3][0]<=min(junction,remote)+.08*spacing
                         and x[3][1]>=max(junction,remote)-.08*spacing]
                if not matches: break
                sides.append(min(matches,key=lambda x:abs(x[2]-target)))
            if len(sides)!=2: continue
            actual_left=sides[0][2]; actual_right=sides[1][2]
            def point(a,b):
                value=u*a+v*b; return [float(value[0]),float(value[1])]
            polygon=[point(actual_left,junction),point(actual_right,junction),
                     point(actual_right,remote),point(actual_left,remote)]
            values=np.asarray(polygon)
            edges=[
                {"role":"TERMINAL_BOUNDARY","from":polygon[0],"to":polygon[1],"source_refs":[terminal[0]]},
                {"role":"SIDE_BOUNDARY_RIGHT","from":polygon[1],"to":polygon[2],"source_refs":[sides[1][0]]},
                {"role":"REMOTE_FLOOR_BOUNDARY","from":polygon[2],"to":polygon[3],"source_refs":[remote_line[0]]},
                {"role":"SIDE_BOUNDARY_LEFT","from":polygon[3],"to":polygon[0],"source_refs":[sides[0][0]]},
            ]
            native_by_ref={item[0]:item for item in lines}
            max_snap=0.0
            for edge in edges:
                item=native_by_ref[edge["source_refs"][0]]
                a,b=item[2],item[3]
                delta=b-a
                adjustments=[]
                for endpoint in (edge["from"],edge["to"]):
                    target=np.asarray(endpoint,dtype=float)
                    t=float((target-a)@delta/(delta@delta))
                    native=a+min(1.,max(0.,t))*delta
                    distance=float(np.linalg.norm(target-native))
                    max_snap=max(max_snap,distance)
                    adjustments.append({"polygon_endpoint":endpoint,"native_nearest_point":native.tolist(),
                                        "displacement_drawing_units":distance})
                edge["native_source_segments"]=[{"source_ref":item[0],"layer":item[1].get("layer"),
                    "start":a.tolist(),"end":b.tolist()}]
                edge["axis_projection_endpoint_adjustments"]=adjustments
            snapped=max_snap>1e-7
            refs=sorted({ref for edge in edges for ref in edge["source_refs"]})
            results.append({"status":"GEOMETRY_CLOSED_WITH_AXIS_SNAP" if snapped else "GEOMETRY_SUPPORTED_CLOSED",
                "boundary_scope":{"status":"CANDIDATE_INNER_FACE_REGION_REVIEW_REQUIRED",
                    "full_landing_outline_status":"UNRESOLVED",
                    "selected_face_layer":remote_line[1].get("layer"),
                    "candidate_inner_face_depth_drawing_units":abs(remote-junction),
                    "outer_architecture_reference_depth_drawing_units":abs(outer_terminal_offset-junction),
                    "outer_reference_basis":"MIDDLE_ARM_NATIVE_SEED_EXTENT_NOT_FULL_PERIMETER",
                    "layer_semantics_status":"UNCONFIRMED"},"geometry":{
                "bounds":[float(values[:,0].min()),float(values[:,1].min()),
                          float(values[:,0].max()),float(values[:,1].max())],
                "depth":abs(remote-junction),"ordered_polygon":polygon,"boundary_edges":edges,
                "closure_test":{"is_closed":True,"is_native_fully_covered":not snapped,
                    "exact_native_coincidence":not snapped,
                    "closure_basis":"AXIS_PROJECTED_SOURCE_SEGMENTS" if snapped else "NATIVE_SEGMENT_COINCIDENCE_WITH_NUMERIC_TOLERANCE",
                    "maximum_endpoint_displacement_drawing_units":max_snap,
                    "numeric_coincidence_tolerance_drawing_units":1e-7,
                    "side_position_match_tolerance_drawing_units":max(.03,.1*spacing),
                    "parallel_direction_abs_dot_threshold":.9998,
                    "snap_method":"SIDE_SEGMENT_MIDPOINT_AXIS_PROJECTION",
                    "minimum_native_edge_coverage_ratio":1.0,
                    "inferred_collinear_gap_drawing_units":0.0,
                    "collinear_merge_tolerance_drawing_units":max(.05,.04*(actual_right-actual_left)),
                    "effective_unit_status":"UNRESOLVED","missing_edge_roles":[]}},
                "shared_terminal_row_ref":terminal[0],"terminal_boundary_refs":[terminal[0]],
                "source_refs":refs,"side_boundary_count":2,"role":"CORNER_LANDING_POLYGON_CANDIDATE",
                "recovery_method":"THREE_SIDED_STAIR_NATIVE_CORNER_BOUNDARIES",
                "authority":{"safety":False,"code_compliance":False,"egress":False}})
    unique={}
    for row in results:
        key=tuple(round(value,5) for value in row["geometry"]["bounds"])
        unique[key]=row
    return list(unique.values())


def _landing_evidence(members, primitives):
    """Recover landings outside a flight end from traceable native boundaries.

    The previous implementation mixed station offsets from independently
    oriented flight coordinate systems.  That could reverse the outward side,
    accept another tread as a landing boundary, or extend a landing through an
    adjacent room.  This implementation projects every source row into one
    common local system per orientation family and requires the candidate strip
    to be outside the terminal row and free of detected tread rows.

    A polygon is emitted only when four native boundary chains close.  Partial
    evidence remains explicitly unresolved and is never padded into a box.
    """
    linear=[row for row in members if row["kind"] == "linear_flight"]
    if not linear:
        return []
    ref_rows={_source_ref(row):row for row in primitives
              if row.get("entity_type") == "LINE" and row.get("start") and row.get("end") and row.get("handle")}
    all_assembly_tread_refs={ref for flight in linear for ref in flight.get("source_refs",[])}
    def excluded_boundary(row):
        value=" ".join(str(row.get(key) or "") for key in ("layer","source_block","name"))
        return bool(re.search(r"(?:^|\W)(?:fon|f\s*n|furniture|dimension|dim|hatch)(?:$|\W)",value,re.I))

    def merged_intervals(items, tolerance):
        groups=[]
        for item in sorted(items,key=lambda x:x[7]):
            lo,hi=item[7]
            if not groups or lo-groups[-1][1] > tolerance:
                groups.append([lo,hi,[item]])
            else:
                groups[-1][1]=max(groups[-1][1],hi); groups[-1][2].append(item)
        return groups

    results=_corner_landing_evidence(members,primitives)
    remaining=list(linear)
    orientation_families=[]
    while remaining:
        first=remaining.pop(0)
        base=np.asarray(first["evidence"]["orientation_unit_vector"],dtype=float)
        family=[first]; keep=[]
        for flight in remaining:
            direction=np.asarray(flight["evidence"]["orientation_unit_vector"],dtype=float)
            (family if abs(float(direction@base)) >= .9998 else keep).append(flight)
        remaining=keep; orientation_families.append(family)

    for family in orientation_families:
        u=np.asarray(family[0]["evidence"]["orientation_unit_vector"],dtype=float)
        if u[0] < -1e-9 or (abs(u[0]) < 1e-9 and u[1] < 0): u=-u
        v=np.asarray([-u[1],u[0]])
        spacing=float(np.median([row["evidence"]["regular_spacing"] for row in family]))
        all_lines=[]
        for ref,row in ref_rows.items():
            a=np.asarray(row["start"],dtype=float); b=np.asarray(row["end"],dtype=float)
            delta=b-a; size=float(np.linalg.norm(delta))
            if size <= 1e-9: continue
            direction=delta/size
            all_lines.append((ref,row,a,b,size,direction,float(((a+b)/2)@v),
                              sorted((float(a@u),float(b@u)))))
        by_ref={item[0]:item for item in all_lines}
        seed_refs={ref for flight in family
                   for ref in (flight.get("evidence",{}).get("seed_source_refs") or [])}
        terminal_rows=[]
        for flight in family:
            stations=flight.get("evidence",{}).get("row_stations") or []
            if not stations: continue
            seed_items=[by_ref[ref] for ref in flight.get("evidence",{}).get("seed_source_refs",[])
                        if ref in by_ref and abs(float(by_ref[ref][5]@u)) >= .9998]
            if not seed_items: continue
            seed_mean=float(np.mean([item[6] for item in seed_items]))
            for terminal in (min(stations,key=lambda row:row["station"]),
                             max(stations,key=lambda row:row["station"])):
                items=[by_ref[ref] for ref in terminal.get("source_refs") or []
                       if ref in by_ref and abs(float(by_ref[ref][5]@u)) >= .9998]
                if not items: continue
                offset=float(np.mean([item[6] for item in items]))
                sign=1 if offset >= seed_mean else -1
                terminal_rows.append((offset,sign,items))

        # Combine fragments from adjacent arms at one terminal elevation.
        edge_groups=[]
        for offset,sign,items in sorted(terminal_rows,key=lambda x:(x[1],x[0])):
            match=next((row for row in edge_groups
                        if row["sign"]==sign and abs(row["offset"]-offset) <= .12*spacing),None)
            if match:
                match["items"].extend(items)
            else:
                edge_groups.append({"offset":offset,"sign":sign,"items":list(items)})

        for edge_group in edge_groups:
            edge_offset=edge_group["offset"]; sign=edge_group["sign"]
            edge_items=list({item[0]:item for item in edge_group["items"]}.values())
            edge_span=max(item[7][1] for item in edge_items)-min(item[7][0] for item in edge_items)
            if edge_span <= 1e-6: continue
            edge_chains=merged_intervals(edge_items,max(.03,.025*edge_span))
            remote_by_offset=defaultdict(list)
            for item in all_lines:
                ref,row,a,b,size,direction,offset,interval=item
                distance=sign*(offset-edge_offset)
                minimum_depth=max(.75,2*spacing)
                if (ref in seed_refs or excluded_boundary(row) or
                        abs(float(direction@u)) < .9998 or
                        distance < minimum_depth or
                        distance > max(2.2,1.25*edge_span)):
                    continue
                if any(min(interval[1],chain[1])-max(interval[0],chain[0]) > .05
                       for chain in edge_chains):
                    remote_by_offset[round(offset/max(.02*spacing,1e-6))].append(item)
            candidates=[]
            for remote_items in remote_by_offset.values():
                remote_offset=float(np.mean([item[6] for item in remote_items]))
                distance=abs(remote_offset-edge_offset)
                merge_tolerance=max(.05,.04*edge_span)
                remote_chains=merged_intervals(remote_items,merge_tolerance)
                if len(remote_chains)>1:
                    aggregate_lo=min(row[0] for row in remote_chains)
                    aggregate_hi=max(row[1] for row in remote_chains)
                    aggregate_items=[item for row in remote_chains for item in row[2]]
                    covered=sum(row[1]-row[0] for row in remote_chains)
                    # Preserve a materially supported but open remote boundary
                    # as unresolved evidence. Do not bridge its gaps into a
                    # closed polygon.
                    if covered/max(aggregate_hi-aggregate_lo,1e-12) >= .45:
                        remote_chains.append([aggregate_lo,aggregate_hi,aggregate_items])
                for remote_lo,remote_hi,remote_chain in remote_chains:
                    for edge_lo,edge_hi,edge_chain in edge_chains:
                        lo=max(remote_lo,edge_lo); hi=min(remote_hi,edge_hi)
                        clipped=sum(max(0.,min(edge_hi,item[7][1])-max(edge_lo,item[7][0]))
                                    for item in remote_chain)
                        partial_wall_boundary=(clipped/max(edge_hi-edge_lo,1e-12) >= .15 and
                            all("wall" in str(item[1].get("layer") or "").lower() or
                                "دیوار" in str(item[1].get("layer") or "") for item in remote_chain))
                        if hi-lo < max(.45,.25*edge_span):
                            if not partial_wall_boundary: continue
                            # Use the terminal extent only as an unresolved
                            # locator. Native coverage below records exactly how
                            # much of the remote edge is actually present.
                            lo,hi=edge_lo,edge_hi
                        # A landing strip may not cross any detected tread row.
                        blocked=False
                        for ref in all_assembly_tread_refs:
                            item=by_ref.get(ref)
                            if not item or ref in {x[0] for x in edge_items}: continue
                            # Check the complete native segment against the open
                            # landing strip in this family's coordinate system.
                            # This includes perpendicular flights in the same
                            # assembly, not only rows from the generating family.
                            pa=np.asarray([float(item[2]@u),float(item[2]@v)])
                            pb=np.asarray([float(item[3]@u),float(item[3]@v)])
                            lower=np.asarray([lo+.02*(hi-lo),min(edge_offset,remote_offset)+.08*spacing])
                            upper=np.asarray([hi-.02*(hi-lo),max(edge_offset,remote_offset)-.08*spacing])
                            delta=pb-pa; t0,t1=0.,1.
                            intersects=True
                            for axis in (0,1):
                                if abs(delta[axis]) <= 1e-12:
                                    if not lower[axis] < pa[axis] < upper[axis]: intersects=False; break
                                else:
                                    a=(lower[axis]-pa[axis])/delta[axis]; b=(upper[axis]-pa[axis])/delta[axis]
                                    t0=max(t0,min(a,b)); t1=min(t1,max(a,b))
                                    if t1-t0 <= 1e-9: intersects=False; break
                            if intersects:
                                blocked=True; break
                        if blocked: continue
                        side_items=[]
                        for item in all_lines:
                            if excluded_boundary(item[1]) or abs(float(item[5]@v)) < .9998: continue
                            va,vb=sorted((float(item[2]@v),float(item[3]@v)))
                            if va > min(edge_offset,remote_offset)+.06 or vb < max(edge_offset,remote_offset)-.06:
                                continue
                            pos=float(((item[2]+item[3])/2)@u)
                            if lo-.08*(hi-lo) <= pos <= hi+.08*(hi-lo):
                                side_items.append((pos,item))
                        positions=[]
                        for pos,item in sorted(side_items,key=lambda x:x[0]):
                            if not positions or abs(pos-positions[-1][0]) > max(.025,.02*(hi-lo)):
                                positions.append([pos,[item]])
                            else:
                                positions[-1][1].append(item)
                        endpoint_tolerance=max(.03,.015*(hi-lo))
                        left=next((x for x in positions if abs(x[0]-lo) <= endpoint_tolerance),None)
                        right=next((x for x in reversed(positions) if abs(x[0]-hi) <= endpoint_tolerance),None)
                        closed=bool(left and right and right[0]-left[0] >= .8*(hi-lo))
                        actual_lo=left[0] if left else lo; actual_hi=right[0] if right else hi
                        def native_coverage(items):
                            intervals=[]
                            for value in items:
                                a=max(actual_lo,value[7][0]); b=min(actual_hi,value[7][1])
                                if b>a: intervals.append((a,b))
                            covered=0.; cursor=None
                            for a,b in sorted(intervals):
                                if cursor is None: covered+=b-a; cursor=b
                                elif a<=cursor+1e-8: covered+=max(0.,b-cursor); cursor=max(cursor,b)
                                else: covered+=b-a; cursor=b
                            return min(covered/max(actual_hi-actual_lo,1e-12),1.)
                        terminal_coverage=native_coverage(edge_chain)
                        remote_coverage=native_coverage(remote_chain)
                        minimum_coverage=min(terminal_coverage,remote_coverage)
                        inferred_gap=(1-terminal_coverage+1-remote_coverage)*(actual_hi-actual_lo)
                        native_closed=bool(closed and inferred_gap <= 1e-7)
                        inferred_closed=bool(closed and inferred_gap <= merge_tolerance+1e-8)
                        terminal_refs=sorted({x[0] for x in edge_chain})
                        remote_refs=sorted({x[0] for x in remote_chain})
                        left_refs=sorted({x[0] for x in (left[1] if left else [])})
                        right_refs=sorted({x[0] for x in (right[1] if right else [])})
                        def point(a,b):
                            value=u*a+v*b
                            return [float(value[0]),float(value[1])]
                        polygon=[point(actual_lo,edge_offset),point(actual_hi,edge_offset),
                                 point(actual_hi,remote_offset),point(actual_lo,remote_offset)] if inferred_closed else None
                        points=polygon or [point(actual_lo,edge_offset),point(actual_hi,edge_offset),
                                           point(actual_hi,remote_offset),point(actual_lo,remote_offset)]
                        values=np.asarray(points,dtype=float)
                        edges=[
                            {"role":"TERMINAL_BOUNDARY","from":points[0],"to":points[1],"source_refs":terminal_refs},
                            {"role":"SIDE_BOUNDARY_RIGHT","from":points[1],"to":points[2],"source_refs":right_refs},
                            {"role":"REMOTE_FLOOR_BOUNDARY","from":points[2],"to":points[3],"source_refs":remote_refs},
                            {"role":"SIDE_BOUNDARY_LEFT","from":points[3],"to":points[0],"source_refs":left_refs},
                        ]
                        candidates.append({"distance":distance,"geometry":{
                            "bounds":[float(values[:,0].min()),float(values[:,1].min()),
                                      float(values[:,0].max()),float(values[:,1].max())],
                            "depth":distance,"ordered_polygon":polygon,
                            "boundary_edges":edges,
                            "closure_test":{"is_closed":inferred_closed,"is_native_fully_covered":native_closed,
                                "minimum_native_edge_coverage_ratio":minimum_coverage,
                                "inferred_collinear_gap_drawing_units":inferred_gap,
                                "collinear_merge_tolerance_drawing_units":max(.05,.04*edge_span),
                                "effective_unit_status":"UNRESOLVED",
                                "missing_edge_roles":[edge["role"] for edge in edges if not edge["source_refs"]]}},
                            "shared_terminal_row_ref":terminal_refs[0] if len(terminal_refs)==1 else None,
                            "terminal_boundary_refs":terminal_refs,
                            "source_refs":sorted(set(terminal_refs+remote_refs+left_refs+right_refs)),
                            "side_boundary_count":int(bool(left))+int(bool(right)),
                            "role":"LANDING_POLYGON_CANDIDATE",
                            "authority":{"safety":False,"code_compliance":False,"egress":False},
                            "native_closed":native_closed,"closed":inferred_closed})
            if candidates:
                # The closest valid floor boundary wins for each outward end.
                closest=min(row["distance"] for row in candidates)
                for row in candidates:
                    if row["distance"] > closest+max(.08,.15*spacing): continue
                    row.pop("distance",None)
                    closed=row.pop("closed")
                    native_closed=row.pop("native_closed")
                    row["status"]=("GEOMETRY_SUPPORTED_CLOSED" if native_closed else
                                   "GEOMETRY_CLOSED_WITH_INFERRED_COLLINEAR_GAP" if closed else
                                   "UNRESOLVED_OPEN_BOUNDARY")
                    results.append(row)
    unique={}
    for row in results:
        key=(tuple(round(value,5) for value in row["geometry"]["bounds"]),row["status"])
        prior=unique.get(key)
        if prior is None or len(row["source_refs"]) > len(prior["source_refs"]):
            unique[key]=row
    values=list(unique.values())
    def contained(a,b):
        aa=a["geometry"]["bounds"];bb=b["geometry"]["bounds"]
        return (bb[0]-1e-6 <= aa[0] and bb[1]-1e-6 <= aa[1] and
                bb[2]+1e-6 >= aa[2] and bb[3]+1e-6 >= aa[3] and aa != bb)
    return [row for row in values if not any(contained(row,other) for other in values)]


def detect_stair_evidence(primitives, *, source_sha256, frames=(), texts=()):
    """Return drawn flight samples and conservative stair-assembly groupings."""
    flights = []
    regular_candidates=_linear_flights(primitives, frames)
    for index, candidate in enumerate(regular_candidates):
        identity = [source_sha256, "regular-treads", candidate["source_refs"]]
        flights.append({
            "stair_flight_id": "STAIR-FLIGHT-"+_hash(identity)[:18].upper(),
            "kind": "linear_flight", "status": "CANDIDATE_GEOMETRY_SUPPORTED",
            "confidence": .82, "frame_id": (candidate["frame"] or {}).get("id") or
                (candidate["frame"] or {}).get("plan_id") or (candidate["frame"] or {}).get("frame_id"),
            "view_scope": candidate["scope"],
            "geometry": {"point": candidate["center"], "bounds": candidate["bounds"]},
            "source_refs": candidate["source_refs"],
            "evidence": {"method": "REGULAR_PARALLEL_TREAD_ARRAY",
                         "detected_row_fragment_count": len(candidate["source_refs"]),
                         "seed_source_refs": candidate.get("seed_source_refs") or candidate["source_refs"],
                         "recovered_source_refs": candidate.get("recovered_source_refs") or [],
                         "row_stations": candidate.get("row_stations") or [],
                         "regular_spacing": candidate["spacing"],
                         "representative_tread_length": candidate["tread_length"],
                         "spacing_to_tread_length_ratio": candidate["spacing"]/candidate["tread_length"],
                         "orientation_unit_vector": candidate["orientation"]},
            "direction": {"status": "UNCONFIRMED", "reason": "NO_NATIVE_UP_DOWN_EVIDENCE"},
            "authority": {"physical_stair_count": False, "safety": False,
                          "code_compliance": False, "egress": False},
        })
    claimed_refs={ref for candidate in regular_candidates for ref in candidate["source_refs"]}
    for candidate in _short_arrow_flights(primitives,frames,claimed_refs):
        identity=[source_sha256,"short-arrow-flight",candidate["source_refs"],candidate["arrow_source_refs"]]
        bounds=candidate["bounds"]
        flights.append({
            "stair_flight_id":"STAIR-FLIGHT-"+_hash(identity)[:18].upper(),
            "kind":"linear_flight","status":"SHORT_FLIGHT_EVIDENCE_REVIEW_REQUIRED",
            "confidence":.74,"frame_id":(candidate["frame"] or {}).get("id") or
                (candidate["frame"] or {}).get("plan_id") or (candidate["frame"] or {}).get("frame_id"),
            "view_scope":candidate["scope"],
            "geometry":{"point":[(bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2],"bounds":bounds},
            "source_refs":candidate["source_refs"],
            "evidence":{"method":"SHORT_REGULAR_ROWS_WITH_NATIVE_DIRECTION_MARKER",
                "detected_row_fragment_count":len(candidate["source_refs"]),
                "seed_source_refs":candidate["source_refs"],"recovered_source_refs":[],
                "row_stations":[],"regular_spacing":candidate["spacing"],
                "representative_tread_length":candidate["tread_length"],
                "spacing_to_tread_length_ratio":candidate["spacing"]/candidate["tread_length"],
                "orientation_unit_vector":candidate["orientation"],
                "native_direction_marker_refs":candidate["arrow_source_refs"],
                "assembly_boundary_status":"UNRESOLVED_NO_INDEPENDENT_PERIMETER_PROOF"},
            "direction":{"status":"NATIVE_MARKER_PRESENT_DIRECTION_SEMANTICS_UNCONFIRMED",
                         "reason":"ARROW_GEOMETRY_NOT_TEXT_SEMANTICALLY_VERIFIED"},
            "authority":{"physical_stair_count":False,"safety":False,
                         "code_compliance":False,"egress":False},
        })
    for candidate in _spiral_flights(primitives, frames):
        identity = [source_sha256, "spiral", candidate["handle"], candidate["source_refs"]]
        flights.append({
            "stair_flight_id": "STAIR-FLIGHT-"+_hash(identity)[:18].upper(),
            "kind": "spiral_stair", "status": "CANDIDATE_GEOMETRY_SUPPORTED",
            "confidence": .76, "frame_id": (candidate["frame"] or {}).get("id") or
                (candidate["frame"] or {}).get("plan_id") or (candidate["frame"] or {}).get("frame_id"),
            "view_scope": candidate["scope"],
            "geometry": {"point": candidate["center"], "bounds": candidate["bounds"]},
            "source_refs": candidate["source_refs"],
            "evidence": {"method": "REPEATED_CONCENTRIC_RADIAL_INSERT_FAMILY",
                         "radial_spoke_count": candidate["radial_count"],
                         "arc_count": candidate["arc_count"],
                         "source_insert_handle": candidate["handle"]},
            "direction": {"status": "UNCONFIRMED", "reason": "NO_NATIVE_UP_DOWN_EVIDENCE"},
            "authority": {"physical_stair_count": False, "safety": False,
                          "code_compliance": False, "egress": False},
        })

    # Group only obviously adjacent linear flights. Assembly count remains a
    # drawn-instance inventory and never claims cross-floor physical identity.
    parents = list(range(len(flights)))
    def find(value):
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value
    def gap(a, b):
        return math.hypot(max(0, max(a[0], b[0])-min(a[2], b[2])),
                          max(0, max(a[1], b[1])-min(a[3], b[3])))
    for i, first in enumerate(flights):
        for j in range(i+1, len(flights)):
            second = flights[j]
            if first["frame_id"] != second["frame_id"] or first["kind"] != second["kind"]:
                continue
            span = min(max(first["geometry"]["bounds"][2]-first["geometry"]["bounds"][0],
                           first["geometry"]["bounds"][3]-first["geometry"]["bounds"][1]),
                       max(second["geometry"]["bounds"][2]-second["geometry"]["bounds"][0],
                           second["geometry"]["bounds"][3]-second["geometry"]["bounds"][1]))
            shared_refs=bool(set(first.get("source_refs",())) & set(second.get("source_refs",())))
            # A broad fixed gap merged neighbouring independent stairs in the
            # Source-5 commercial plan.  Join by shared native terminal evidence
            # or by a genuinely narrow geometric separation instead.
            if shared_refs or gap(first["geometry"]["bounds"], second["geometry"]["bounds"]) <= min(.16, .08*span):
                a, b = find(i), find(j)
                if a != b:
                    parents[a] = b
    grouped = defaultdict(list)
    for index in range(len(flights)):
        grouped[find(index)].append(index)
    assemblies = []
    for indexes in grouped.values():
        members = [flights[index] for index in indexes]
        bounds = [min(row["geometry"]["bounds"][0] for row in members),
                  min(row["geometry"]["bounds"][1] for row in members),
                  max(row["geometry"]["bounds"][2] for row in members),
                  max(row["geometry"]["bounds"][3] for row in members)]
        refs = sorted(row["stair_flight_id"] for row in members)
        landing_candidates = _landing_evidence(members, primitives)
        assemblies.append({
            "stair_assembly_id": "STAIR-ASSEMBLY-"+_hash([source_sha256, refs])[:18].upper(),
            "status": "DRAWN_ASSEMBLY_CANDIDATE_REVIEW_REQUIRED",
            "frame_id": members[0]["frame_id"], "drawn_flight_count": len(members),
            "geometry": {"point": [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2],
                         "bounds": bounds},
            "flight_ids": refs,
            "physical_identity": "UNCONFIRMED_ACROSS_FLOORS",
            "landing": {"status": "GEOMETRY_EVIDENCE_AVAILABLE", "candidates": landing_candidates}
                if landing_candidates else
                {"status": "UNCONFIRMED", "reason": "NO_INDEPENDENT_LANDING_BOUNDARY_PROOF"},
            "direction": {"status": "UNCONFIRMED", "reason": "NO_NATIVE_UP_DOWN_EVIDENCE"},
            "authority": {"physical_stair_count": False, "safety": False,
                          "code_compliance": False, "egress": False},
        })
    flights.sort(key=lambda row: row["stair_flight_id"])
    assemblies.sort(key=lambda row: row["stair_assembly_id"])
    return {
        "schema": SCHEMA, "detector_revision": DETECTOR_REVISION,
        "source_sha256": source_sha256,
        "items": assemblies, "flight_samples": flights,
        "metrics": {"drawn_flight_sample_count": len(flights),
                    "drawn_assembly_candidate_count": len(assemblies),
                    "physical_stair_count": None,
                    "direction_confirmed_count": 0,
                    "landing_geometry_candidate_count": sum(
                        len(row.get("landing", {}).get("candidates") or []) for row in assemblies)},
        "limitations": [
            "DRAWN_SAMPLES_ARE_NOT_CROSS_FLOOR_PHYSICAL_STAIR_COUNTS",
            "NO_SAFETY_CODE_OR_EGRESS_APPROVAL",
            "DIRECTION_AND_LANDING_REQUIRE_NATIVE_EVIDENCE_OR_HUMAN_REVIEW",
        ],
    }

