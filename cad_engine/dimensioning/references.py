"""Semantic Architectural Reference Model v2."""
from __future__ import annotations
import math
from .model import REFERENCE_CLASSES

def _pt(value):
    if value is None or len(value) < 2:
        return None
    return (float(value[0]), float(value[1]))

def _edges(item):
    if not isinstance(item, dict):
        return []
    a=_pt(item.get("start")); b=_pt(item.get("end"))
    if a and b and a != b:
        return [(a,b)]
    pts=[_pt(x) for x in (item.get("polygon") or item.get("points") or [])]
    pts=[x for x in pts if x is not None]
    if len(pts)>=2:
        out=list(zip(pts,pts[1:]))
        if len(pts)>=3 and pts[0] != pts[-1]:
            out.append((pts[-1],pts[0]))
        return out
    bounds=item.get("bounds")
    if isinstance(bounds,(list,tuple)) and len(bounds)==4:
        x1,y1,x2,y2=map(float,bounds)
        if x2>x1 and y2>y1:
            return [((x1,y1),(x2,y1)),((x2,y1),(x2,y2)),((x2,y2),(x1,y2)),((x1,y2),(x1,y1))]
    return []

def _ref(element_id, kind, subfeature, a, b, *, side=None, zone_id=None, source="semantic_geometry", confidence=1.0, metadata=None):
    return {
        "id": f"{element_id}:{subfeature}" + (f":{side}" if side else ""),
        "element_id": str(element_id), "kind": kind, "subfeature": subfeature,
        "reference_class": REFERENCE_CLASSES.get(subfeature, kind),
        "a": (float(a[0]),float(a[1])), "b": (float(b[0]),float(b[1])),
        "side": side, "zone_id": zone_id, "source": source,
        "confidence": float(confidence), "metadata": dict(metadata or {}),
    }

def _poly_orientation(poly):
    area=0.0
    for a,b in zip(poly,poly[1:]+poly[:1]):
        area += a[0]*b[1]-b[0]*a[1]
    return 1 if area >= 0 else -1

def build_semantic_references(architecture: dict, *, zone_id=None) -> dict:
    """Create stable element/subfeature references; ambiguous face basis fails closed."""
    architecture=architecture or {}
    refs=[]; errors=[]; checkpoints=[]
    collections={
        "walls": ("WALL",None),
        "structural_walls": ("STRUCTURAL_WALL","CORE_FACE"),
        "columns": ("COLUMN","COLUMN_CENTER"),
        "grids": ("GRID","GRID_AXIS"),
        "shafts": ("SHAFT","SHAFT_FACE"),
        "lightwells": ("LIGHTWELL","SHAFT_FACE"),
        "stairs": ("STAIR","STAIR_EDGE"),
        "landings": ("LANDING","LANDING_EDGE"),
        "property_boundaries": ("PROPERTY","PROPERTY_EDGE"),
        "site_boundaries": ("SITE","PROPERTY_EDGE"),
    }
    for collection,(kind,default_subfeature) in collections.items():
        for idx,item in enumerate(architecture.get(collection) or []):
            if not isinstance(item,dict):
                continue
            if zone_id and item.get("zone_id") not in (None,zone_id):
                continue
            eid=str(item.get("id") or f"{kind}-{idx:04d}")
            edges=_edges(item)
            if not edges and kind=="COLUMN" and item.get("point"):
                p=_pt(item["point"])
                if p:
                    refs.append(_ref(eid,kind,"COLUMN_CENTER",p,p,zone_id=zone_id,confidence=item.get("confidence",1.0)))
                continue
            explicit_subfeature=str(item.get("subfeature") or "").upper()
            face_basis=str(item.get("face_basis") or "").upper()
            if kind=="WALL":
                basis_map={"FINISH":"FINISH_FACE","CORE":"CORE_FACE","CENTERLINE":"CENTERLINE"}
                subfeature=explicit_subfeature or basis_map.get(face_basis)
                if not subfeature:
                    checkpoints.append({"element_id":eid,"reason":"WALL_FACE_BASIS_AMBIGUOUS"})
                else:
                    for edge_i,(a,b) in enumerate(edges):
                        side=str(item.get("side") or edge_i)
                        refs.append(_ref(eid,kind,subfeature,a,b,side=side,zone_id=zone_id,confidence=item.get("confidence",1.0),
                                         metadata={"edge_index":edge_i,"exterior":bool(item.get("exterior") or item.get("is_exterior"))}))
            else:
                subfeature=explicit_subfeature or default_subfeature
                for edge_i,(a,b) in enumerate(edges):
                    side=str(item.get("side") or edge_i)
                    refs.append(_ref(eid,kind,subfeature,a,b,side=side,zone_id=zone_id,confidence=item.get("confidence",1.0),
                                     metadata={"edge_index":edge_i,"exterior":bool(item.get("exterior") or item.get("is_exterior"))}))
            # A distinct wall centreline is added only from explicit semantic evidence.
            centerline=item.get("centerline")
            if kind in {"WALL","STRUCTURAL_WALL"} and centerline and (kind!="WALL" or (explicit_subfeature or face_basis)!="CENTERLINE"):
                cedges=_edges({"points":centerline} if isinstance(centerline,list) else centerline)
                for edge_i,(a,b) in enumerate(cedges):
                    refs.append(_ref(eid,kind,"CENTERLINE",a,b,side=edge_i,zone_id=zone_id))
    for collection in ("doors","windows","openings"):
        for idx,item in enumerate(architecture.get(collection) or []):
            if not isinstance(item,dict):
                continue
            if zone_id and item.get("zone_id") not in (None,zone_id):
                continue
            kind=collection[:-1].upper() if collection.endswith("s") else collection.upper()
            eid=str(item.get("id") or f"{kind}-{idx:04d}")
            left=_pt(item.get("jamb_left")); right=_pt(item.get("jamb_right"))
            host=str(item.get("host_wall_id") or "")
            if not host:
                checkpoints.append({"element_id":eid,"reason":"OPENING_HOST_UNCERTAIN"})
            if left and right:
                refs.append(_ref(eid,kind,"OPENING_JAMB_LEFT",left,left,zone_id=zone_id,metadata={"host_wall_id":host}))
                refs.append(_ref(eid,kind,"OPENING_JAMB_RIGHT",right,right,zone_id=zone_id,metadata={"host_wall_id":host}))
                center=((left[0]+right[0])/2,(left[1]+right[1])/2)
                refs.append(_ref(eid,kind,"OPENING_CENTER",center,center,zone_id=zone_id,metadata={"host_wall_id":host}))
            else:
                edges=_edges(item)
                if len(edges):
                    endpoints=[]
                    for a,b in edges:
                        endpoints.extend([a,b])
                    unique=[]
                    for p in endpoints:
                        if not any(math.dist(p,q)<=1e-9 for q in unique):
                            unique.append(p)
                    if len(unique)>=2:
                        refs.append(_ref(eid,kind,"OPENING_JAMB_LEFT",unique[0],unique[0],zone_id=zone_id,metadata={"host_wall_id":host}))
                        refs.append(_ref(eid,kind,"OPENING_JAMB_RIGHT",unique[1],unique[1],zone_id=zone_id,metadata={"host_wall_id":host}))
                else:
                    errors.append({"element_id":eid,"reason":"OPENING_GEOMETRY_REQUIRED"})
    ids=[r["id"] for r in refs]
    dup=sorted({x for x in ids if ids.count(x)>1})
    if dup:
        errors.extend({"reference_id":x,"reason":"DUPLICATE_REFERENCE_ID"} for x in dup)
    return {"references":refs,"errors":errors,"human_checkpoints":checkpoints,
            "status":"FAIL" if errors else ("HUMAN_REVIEW" if checkpoints else "PASS")}
