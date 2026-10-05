"""Source-occurrence roles before enclosure, void and wall evidence generation."""
from collections import Counter
from hashlib import sha256
import json
import math
import re

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely.strtree import STRtree


def _context(record):
    return ' '.join(str(record.get(k) or '') for k in ('layer', 'source_block', 'name')).lower()


def _wall_context(record):
    return any(word in _context(record) for word in ('wall', 'partition', 'دیوار'))


def _points(record):
    return list(record.get('points') or ([record['start'], record['end']] if record.get('start') and record.get('end') else []))


def _identity(record):
    return (str(record.get('handle') or ''), tuple(record.get('source_block_path') or ()), str(record.get('source_insert_handle') or ''))


def annotate_source_roles(extracted, frames, metres_per_unit, tolerance):
    """Annotate original world occurrences; return auditable, non-authority evidence.

    Roles exclude source graphics, never positively grant enclosure authority.
    Geometry is kept intact for presentation and provenance.
    """
    scale = float(metres_per_unit or 1)
    tol = max(float(tolerance or .002), .002 / scale)
    records = extracted.get('primitives') or []
    lines = extracted.get('boundary_lines') or []
    metas = extracted.get('boundary_meta') or []
    diagnostics = []
    by_identity = {}
    for index, meta in enumerate(metas):
        by_identity.setdefault(_identity(meta), []).append(index)
    def mark(record, kind, evidence, role='NON_TOPOLOGICAL'):
        pts = _points(record)
        occurrence = 'SRC-' + sha256(json.dumps([_identity(record), pts], sort_keys=True).encode()).hexdigest()[:16].upper()
        fields = {'pre_topology_object_class': kind, 'pre_topology_role': role,
                  'pre_topology_evidence': list(evidence), 'source_occurrence_id': occurrence}
        record.update(fields)
        shape = LineString(pts + ([pts[0]] if record.get('closed') and pts[0] != pts[-1] else [])) if len(pts) > 1 else None
        for index in by_identity.get(_identity(record), []):
            # Block handles may repeat across world occurrences. Require geometry membership.
            if shape is not None and shape.buffer(tol).covers(lines[index]):
                metas[index].update(fields)
        diagnostics.append({'source_occurrence_id': occurrence, 'source_handle': record.get('handle'),
                            'object_class': kind, 'topology_role': role, 'evidence': list(evidence),
                            'geometry': pts, 'enclosure_authority': 'NONE'})

    # Repeated chamfered compact polylines are an object assembly grammar. Mere
    # shortness, closedness or diagonal orientation is deliberately insufficient.
    motifs = []
    for record in records:
        pts = _points(record)
        if record.get('entity_type') not in {'LWPOLYLINE', 'POLYLINE'} or len(pts) < 8 or _wall_context(record):
            continue
        edges = [(b[0]-a[0], b[1]-a[1]) for a,b in zip(pts,pts[1:])]
        lengths = [math.hypot(dx,dy)*scale for dx,dy in edges]
        width=(max(p[0] for p in pts)-min(p[0] for p in pts))*scale
        height=(max(p[1] for p in pts)-min(p[1] for p in pts))*scale
        if not (.06 <= min(width,height) <= .9 and .2 <= max(width,height) <= 2):
            continue
        axial=[i for i,(dx,dy) in enumerate(edges) if min(abs(dx),abs(dy)) <= tol]
        chamfers=[i for i,(dx,dy) in enumerate(edges) if min(abs(dx),abs(dy)) > tol and abs(abs(dx)-abs(dy)) <= tol*2]
        if len(axial) < 4 or len(chamfers) < 3 or len(axial)+len(chamfers) != len(edges):
            continue
        if max(lengths[i] for i in chamfers) > max(lengths)*.35:
            continue
        signature=tuple(sorted(round(length/.01) for length in lengths))
        motifs.append((record,signature))
    counts=Counter(signature for _,signature in motifs)
    for record, signature in motifs:
        if counts[signature] >= 2:
            mark(record,'GENERIC_NON_ENCLOSURE_OBJECT',['REPEATED_COMPACT_CHAMFERED_OBJECT_ASSEMBLY', 'NO_INDEPENDENT_WALL_CONTEXT'] + (['NATIVE_ROUNDED_CORNERS'] if sum(abs(abs(float(b))-.41421356237)<.001 for b in record.get('bulges',[]))>=3 else []))

    # Native compact column outlines, only with repetition, before void extraction.
    column_candidates=[]
    from shapely.geometry import Polygon
    for record in records:
        pts=_points(record)
        if not record.get('closed') or len(pts)<4 or _wall_context(record) or record.get('pre_topology_object_class'): continue
        # Independent void identity outweighs resemblance to repeated columns.
        if any(token in _context(record) for token in ('duct', 'shaft', 'void', 'داکت', 'شفت', 'نورگیر')): continue
        poly=Polygon(pts)
        if not poly.is_valid or poly.is_empty: continue
        x0,y0,x1,y1=poly.bounds; w=(x1-x0)*scale; h=(y1-y0)*scale
        if .12<=w<=.90 and .12<=h<=.90 and min(w,h)/max(w,h)>=.65 and poly.area/max((x1-x0)*(y1-y0),1e-12)>=.82:
            column_candidates.append((record,tuple(sorted((round(w/.025),round(h/.025))))))
    column_counts=Counter(signature for _,signature in column_candidates)
    for record,signature in column_candidates:
        if column_counts[signature]>=3:
            mark(record,'COLUMN',['REPEATED_COMPACT_CLOSED_FOOTPRINT'],'OBSTACLE_EVIDENCE_ONLY')

    # Construction section islands require aligned material-thickness callouts,
    # explicit drafting context, and a geometry component separated from the plan.
    for frame in frames:
        if not frame.get('bounds'): continue
        frame_box=box(*frame['bounds'])
        callouts=[]
        for text in extracted.get('texts') or []:
            value=str(text.get('text') or '').strip().lower()
            if text.get('point') and frame_box.covers(Point(text['point'])) and re.fullmatch(r'\d+(?:\.\d+)?\s*(?:cm|mm)',value):
                if any(token in _context(text) for token in ('construction','detail','section','جزئیات','دیتیل')):
                    callouts.append(text)
        clusters=[]
        for text in callouts:
            cluster=next((group for group in clusters if abs(group[0]['point'][0]-text['point'][0])<=.12/scale),None)
            if cluster is None: clusters.append([text])
            else: cluster.append(text)
        clusters=[group for group in clusters if len(group)>=3 and max(t['point'][1] for t in group)-min(t['point'][1] for t in group)<=5/scale]
        if not clusters: continue
        local=[i for i,line in enumerate(lines) if frame_box.covers(line)]
        local_lines=[lines[i] for i in local]
        tree_local=STRtree(local_lines); parents=list(range(len(local)))
        def find(i):
            while parents[i]!=i:
                parents[i]=parents[parents[i]];i=parents[i]
            return i
        reach=.8/scale
        for i,line in enumerate(local_lines):
            for raw in tree_local.query(line.buffer(reach)):
                j=int(raw)
                if j>i and line.distance(local_lines[j])<=reach:
                    a,b=find(i),find(j)
                    if a!=b:parents[a]=b
        groups={}
        for i in range(len(local)):groups.setdefault(find(i),[]).append(i)
        for members in groups.values():
            island=unary_union([local_lines[i] for i in members]);x0,y0,x1,y1=island.bounds
            fw=frame_box.bounds[2]-frame_box.bounds[0];fh=frame_box.bounds[3]-frame_box.bounds[1]
            if (x1-x0)>fw*.72 or (y1-y0)>fh*.8:continue
            matching=[group for group in clusters if sum(island.distance(Point(t['point']))<=reach for t in group)>=3]
            if not matching:continue
            # At least three parallel material-layer strokes adjacent to callouts.
            strokes=[local_lines[i] for i in members if len(local_lines[i].coords)==2 and abs(local_lines[i].coords[0][1]-local_lines[i].coords[1][1])<=tol and .2<=local_lines[i].length*scale<=2]
            if len(strokes)<3:continue
            scope=box(x0-tol,y0-tol,x1+tol,y1+tol)
            for record in records:
                pts=_points(record)
                if ((len(pts)>=2 and scope.covers(LineString(pts))) or
                        (record.get('point') and scope.covers(Point(record['point'])))):
                    mark(record,'SECTION_CUT',['ALIGNED_CONSTRUCTION_THICKNESS_CALLOUTS','SEPARATED_LAYERED_DETAIL_ISLAND'],'REFERENCE_ONLY')

    # A labelled compact cabinet/shaft symbol has rectangular perimeter support
    # independent of its interior chord. Keep all perimeter geometry.
    axis_lines=[]
    for line,meta in zip(lines,metas):
        coords=list(line.coords)
        if len(coords)==2 and not meta.get('pre_topology_object_class') and min(abs(coords[1][0]-coords[0][0]),abs(coords[1][1]-coords[0][1])) <= tol:
            axis_lines.append(line)
    tree=STRtree(axis_lines) if axis_lines else None
    labels=[]
    for record in extracted.get('texts') or []:
        text=str(record.get('text') or '').lower().replace('ي','ی').replace('ك','ک')
        if any(word in text for word in ('closet','elevator','lift','کمد','آسانسور','اسانسور')) and record.get('point'):
            labels.append(Point(record['point']))
    for record in records:
        if record.get('entity_type')!='LINE' or _wall_context(record) or record.get('pre_topology_object_class'):
            continue
        pts=_points(record)
        if len(pts)!=2: continue
        width=abs(pts[1][0]-pts[0][0])*scale; height=abs(pts[1][1]-pts[0][1])*scale
        if not (.25<=width<=4 and .25<=height<=4): continue
        bounds=LineString(pts).bounds; host=box(*bounds)
        if not any(host.buffer(.15/scale).covers(label) for label in labels): continue
        near=.16/scale
        indexes=tree.query(host.buffer(near)) if tree is not None else []
        support=unary_union([axis_lines[int(i)] for i in indexes])
        if support.is_empty: continue
        corners=list(host.exterior.coords)
        edges=[LineString([a,b]) for a,b in zip(corners,corners[1:])]
        if not all(edge.intersection(support.buffer(near)).length / edge.length >= .85 for edge in edges): continue
        # Independent near-parallel mate is physical-wall evidence, not a symbol.
        diagonal=LineString(pts); dx=pts[1][0]-pts[0][0];dy=pts[1][1]-pts[0][1];length=diagonal.length
        paired=False
        for other,meta in zip(lines,metas):
            if other.equals(diagonal) or meta.get('pre_topology_object_class'):continue
            oc=list(other.coords)
            if len(oc)!=2 or other.length<length*.65:continue
            ox=oc[-1][0]-oc[0][0];oy=oc[-1][1]-oc[0][1]
            if abs(dx*ox+dy*oy)/(length*other.length)>.999 and .035/scale<diagonal.distance(other)<.5/scale:
                projected=[((p[0]-pts[0][0])*dx+(p[1]-pts[0][1])*dy)/length for p in oc]
                overlap=max(0.,min(length,max(projected))-max(0.,min(projected)))
                in_host=other.intersection(host.buffer(near)).length
                if overlap>=length*.65 and in_host>=min(length,other.length)*.65:
                    paired=True;break
        if not paired:
            mark(record,'GENERIC_NON_ENCLOSURE_OBJECT',['LABELLED_COMPACT_RECTANGULAR_SYMBOL','INTERNAL_CORNER_CHORD','INDEPENDENT_PERIMETER_SUPPORT','NO_PARALLEL_WALL_FACE'])
    return {'schema':'architectural-source-roles/1.0','items':diagnostics,'authority':'EXCLUSION_EVIDENCE_ONLY'}
