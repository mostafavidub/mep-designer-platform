"""Deterministic local visual context for ID-only candidate review.

The renderer never changes candidate geometry or authority.  It creates QA and
provider views from the already frozen Candidate Graph v2.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path

from shapely.geometry import Polygon


def _stable(prefix, value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str)
    return f"{prefix}-"+sha256(raw.encode()).hexdigest()[:10].upper()


def candidate_adjacency(graph: dict) -> dict[str,set[str]]:
    adjacency={row["region_id"]:set() for row in graph.get("regions") or []}
    for boundary in graph.get("boundaries") or []:
        ids=[i for i in boundary.get("adjacent_region_ids") or [] if i in adjacency]
        for left in ids:
            adjacency[left].update(right for right in ids if right!=left)
    return adjacency


def build_candidate_neighborhoods(graph: dict, target_ids: list[str], *, max_targets: int=6) -> list[dict]:
    """Partition targets by connected topology, deterministically and boundedly."""
    targets=set(target_ids); adjacency=candidate_adjacency(graph); seen=set(); result=[]
    for seed in sorted(targets):
        if seed in seen: continue
        queue=[seed]; component=[]
        while queue:
            current=queue.pop(0)
            if current in seen or current not in targets: continue
            seen.add(current); component.append(current)
            queue.extend(sorted(adjacency.get(current,set()) & targets - seen))
        for offset in range(0,len(component),max_targets):
            members=component[offset:offset+max_targets]
            context=sorted(set().union(*(adjacency.get(i,set()) for i in members))-set(members))
            result.append({"neighborhood_id":_stable("NB",[graph["frame_id"],members]),
                "target_region_ids":members,"context_region_ids":context})
    return result


def build_context_pack(graph: dict, target_ids: list[str], *, graph_hash: str) -> dict:
    regions={row["region_id"]:row for row in graph.get("regions") or []}
    missing=set(target_ids)-set(regions)
    if missing: raise ValueError(f"unknown target IDs: {sorted(missing)}")
    adjacency=candidate_adjacency(graph); adjacent=sorted(set().union(*(adjacency[i] for i in target_ids))-set(target_ids))
    included=target_ids+adjacent
    polygons=[Polygon(regions[i]["polygon"]) for i in included]
    minx=min(p.bounds[0] for p in polygons); miny=min(p.bounds[1] for p in polygons)
    maxx=max(p.bounds[2] for p in polygons); maxy=max(p.bounds[3] for p in polygons)
    span=max(maxx-minx,maxy-miny,1e-9); margin=span*.12
    bounds=[minx-margin,miny-margin,maxx+margin,maxy+margin]
    boundary_ids=[]
    for row in graph.get("boundaries") or []:
        if set(row.get("adjacent_region_ids") or []) & set(included): boundary_ids.append(row["boundary_id"])
    labels=[]; objects=[]
    for identity in included:
        labels.extend(x.get("source_handle") for x in regions[identity].get("exact_text_evidence") or [])
        objects.extend(x.get("source_handle") for x in regions[identity].get("object_evidence") or [])
    contract={"target_region_ids":sorted(target_ids),"crop_cad_bounds":bounds,
        "source_sha256":graph.get("source_sha256"),"graph_hash":graph_hash,
        "candidate_ids":sorted(included),"adjacent_ids":adjacent,
        "included_label_handles":sorted(x for x in labels if x),
        "included_object_handles":sorted(x for x in objects if x),
        "included_boundary_ids":sorted(boundary_ids)}
    contract["context_pack_id"]=_stable("CTX",contract)
    return contract


def cad_to_view(point, bounds, width, height, *, padding=24):
    minx,miny,maxx,maxy=bounds; sx=(width-2*padding)/max(maxx-minx,1e-12); sy=(height-2*padding)/max(maxy-miny,1e-12)
    scale=min(sx,sy); ox=padding+(width-2*padding-(maxx-minx)*scale)/2; oy=padding+(height-2*padding-(maxy-miny)*scale)/2
    return [ox+(point[0]-minx)*scale,height-(oy+(point[1]-miny)*scale)]


def view_to_cad(point, bounds, width, height, *, padding=24):
    minx,miny,maxx,maxy=bounds; sx=(width-2*padding)/max(maxx-minx,1e-12); sy=(height-2*padding)/max(maxy-miny,1e-12)
    scale=min(sx,sy); ox=padding+(width-2*padding-(maxx-minx)*scale)/2; oy=padding+(height-2*padding-(maxy-miny)*scale)/2
    return [(point[0]-ox)/scale+minx,((height-point[1])-oy)/scale+miny]


def _poly_points(points,bounds,width,height):
    return " ".join(f"{x:.2f},{y:.2f}" for x,y in (cad_to_view(p,bounds,width,height) for p in points))


def render_local_svg(graph: dict, pack: dict, path: str|Path, *, debug=False, width=1200, height=900) -> dict:
    """Render source geometry plus target/direct-neighbor overlays with short IDs."""
    bounds=pack["crop_cad_bounds"]; target=set(pack["target_region_ids"]); neighbors=set(pack["adjacent_ids"])
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#fffdf8"/>']
    source=(graph.get("preauthority") or {}).get("source_segments") or []
    for segment in source:
        geom=segment.get("geometry") or []
        if len(geom)<2: continue
        pts=_poly_points(geom,bounds,width,height)
        tier=segment.get("authority_tier"); color="#293241" if tier=="HARD_ACCEPTED_ARCHITECTURAL" else "#8793a1"
        lines.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.2" opacity=".82"/>')
    label_points={row.get("label_id"):row.get("point") for row in (graph.get("preauthority") or {}).get("label_host_diagnostics") or []}
    occupied=[]
    for region in graph.get("regions") or []:
        identity=region["region_id"]
        if identity not in target|neighbors: continue
        is_target=identity in target; color="#dc2626" if is_target else "#2563eb"; opacity=".16" if is_target else ".06"
        lines.append(f'<polygon points="{_poly_points(region["polygon"],bounds,width,height)}" fill="{color}" fill-opacity="{opacity}" stroke="{color}" stroke-width="{4 if is_target else 2}"/>')
        cx,cy=cad_to_view(region["centroid"],bounds,width,height); short=identity.split("-")[-1][:5]
        candidates=[(cx,cy),(cx+28,cy-28),(cx-28,cy+28),(cx+35,cy+35)]
        px,py=next(((x,y) for x,y in candidates if all(math.hypot(x-a,y-b)>45 for a,b in occupied)),candidates[-1]); occupied.append((px,py))
        lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="16" fill="{color}" stroke="white" stroke-width="2"/>')
        lines.append(f'<text x="{px:.1f}" y="{py+4:.1f}" text-anchor="middle" font-family="Arial" font-size="10" fill="white">{short}</text>')
        if (px,py)!=(cx,cy): lines.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" stroke="{color}"/>')
    for region in graph.get("regions") or []:
        if region["region_id"] not in target|neighbors: continue
        for label_index,evidence in enumerate(region.get("exact_text_evidence") or []):
            text=str(evidence.get("text") or "")
            if text:
                point=label_points.get(evidence.get("source_handle")) or region["centroid"]
                cx,cy=cad_to_view(point,bounds,width,height)
                lines.append(f'<text x="{cx:.1f}" y="{cy+label_index*16:.1f}" text-anchor="middle" font-family="Arial" font-size="15" font-weight="bold" fill="#111827" stroke="white" stroke-width="3" paint-order="stroke">{text}</text>')
    if debug:
        lines.append(f'<text x="20" y="28" font-family="Arial" font-size="15">{pack["context_pack_id"]} | CAD bounds {bounds}</text>')
    lines.append('</svg>'); data="".join(lines); Path(path).write_text(data,encoding="utf-8")
    return {"render_hash":sha256(data.encode()).hexdigest(),"width":width,"height":height,"cad_bounds":bounds}


def provider_target_graph(graph: dict, target_ids: list[str]) -> dict:
    allowed=set(target_ids); clone={**graph,"regions":[row for row in graph.get("regions") or [] if row["region_id"] in allowed],
        "boundaries":[],"bridges":[]}
    if {row["region_id"] for row in clone["regions"]}!=allowed: raise ValueError("Provider target is not supplied by CAD")
    return clone


def render_context_png(graph: dict, pack: dict, path: str|Path, *, composite=True) -> dict:
    """Create a clean provider PNG: global location at left, local detail at right."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as Patch
    target=set(pack["target_region_ids"]); neighbors=set(pack["adjacent_ids"])
    fig,axes=plt.subplots(1,2 if composite else 1,figsize=(14 if composite else 8,8),dpi=140)
    axes=list(axes) if composite else [axes]
    source=(graph.get("preauthority") or {}).get("source_segments") or []
    region_map={row["region_id"]:row for row in graph.get("regions") or []}
    label_points={row.get("label_id"):row.get("point") for row in (graph.get("preauthority") or {}).get("label_host_diagnostics") or []}
    for index,ax in enumerate(axes):
        bounds=graph["frame_bounds"] if composite and index==0 else pack["crop_cad_bounds"]
        for segment in source:
            geom=segment.get("geometry") or []
            if len(geom)>=2:
                xs=[p[0] for p in geom]; ys=[p[1] for p in geom]
                ax.plot(xs,ys,color="#273444" if segment.get("authority_tier")=="HARD_ACCEPTED_ARCHITECTURAL" else "#9aa4b2",lw=.55,alpha=.78)
        for identity in target|neighbors:
            row=region_map[identity]; is_target=identity in target
            ax.add_patch(Patch(row["polygon"],closed=True,facecolor="#ef4444" if is_target else "#60a5fa",
                edgecolor="#b91c1c" if is_target else "#2563eb",alpha=.22 if is_target else .08,lw=2.5 if is_target else 1))
            if index==len(axes)-1:
                short=identity.split("-")[-1][:5]; ax.annotate(short,row["centroid"],xytext=(8,8),textcoords="offset points",
                    fontsize=8,color="white",bbox={"boxstyle":"circle,pad=.35","fc":"#b91c1c" if is_target else "#2563eb","ec":"white"},
                    arrowprops={"arrowstyle":"-","color":"#64748b","lw":.7})
                for label_index,evidence in enumerate(row.get("exact_text_evidence") or []):
                    if evidence.get("text"):
                        point=label_points.get(evidence.get("source_handle")) or row["centroid"]
                        ax.annotate(str(evidence["text"]),point,xytext=(0,-10-label_index*2),textcoords="offset points",ha="center",fontsize=8,fontweight="bold",
                            bbox={"boxstyle":"round,pad=.12","fc":"white","ec":"none","alpha":.72})
        ax.set_xlim(bounds[0],bounds[2]); ax.set_ylim(bounds[1],bounds[3]); ax.set_aspect("equal"); ax.axis("off")
        ax.set_title("Whole floor location" if composite and index==0 else "Local architectural context",fontsize=11)
    fig.tight_layout(); path=Path(path); fig.savefig(path,bbox_inches="tight",facecolor="white"); plt.close(fig)
    return {"render_hash":sha256(path.read_bytes()).hexdigest(),"path":str(path)}
