#!/usr/bin/env python3
"""Build source-only review material; never import reconstruction output."""
from __future__ import annotations
import argparse, html, json
from hashlib import sha256
from pathlib import Path
import ezdxf
from ezdxf.disassemble import recursive_decompose


def _points(entity):
    kind=entity.dxftype()
    try:
        if kind=="LINE": return [(float(entity.dxf.start.x),float(entity.dxf.start.y)),(float(entity.dxf.end.x),float(entity.dxf.end.y))]
        if kind=="LWPOLYLINE": return [(float(x),float(y)) for x,y,*_ in entity.get_points()]
        if kind=="POLYLINE": return [(float(v.dxf.location.x),float(v.dxf.location.y)) for v in entity.vertices]
        if kind in {"ARC","CIRCLE","ELLIPSE","SPLINE"}: return [(float(p.x),float(p.y)) for p in entity.flattening(.01)]
    except Exception: return []
    return []


def _text(entity):
    try:
        value=str(entity.dxf.text if entity.dxftype() in {"TEXT","ATTRIB","ATTDEF"} else entity.plain_text()).strip()
        point=entity.dxf.insert
        return value,(float(point.x),float(point.y)),float(getattr(entity.dxf,"height",.18) or .18)
    except Exception: return None


def _source_svg(doc,bounds,case_id):
    minx,miny,maxx,maxy=bounds; graphics=[]; texts=[]; counts={}
    for entity in recursive_decompose(doc.modelspace()):
        kind=entity.dxftype(); counts[kind]=counts.get(kind,0)+1; points=_points(entity)
        visible=points and max(x for x,_ in points)>=minx and min(x for x,_ in points)<=maxx and max(y for _,y in points)>=miny and min(y for _,y in points)<=maxy
        if visible:
            if bool(getattr(entity,"closed",False)) and points[0]!=points[-1]: points.append(points[0])
            encoded=" ".join(f"{x:.6f},{-y:.6f}" for x,y in points)
            graphics.append(f'<polyline points="{encoded}" fill="none" stroke="#263442" stroke-width="0.010" vector-effect="non-scaling-stroke"/>')
        label=_text(entity)
        if label:
            value,(x,y),height=label
            if minx<=x<=maxx and miny<=y<=maxy:
                texts.append(f'<text x="{x:.6f}" y="{-y:.6f}" font-size="{max(height,.08):.6f}" fill="#111827">{html.escape(value)}</text>')
    width=maxx-minx; height=maxy-miny
    svg=(f'<svg id="source-plan" xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}" '
         f'data-case="{html.escape(case_id)}"><rect x="{minx}" y="{-maxy}" width="{width}" height="{height}" fill="white"/>'
         +"".join(graphics)+"".join(texts)+"</svg>")
    return svg,counts


def _viewer(svg,case_id,level,bounds):
    initial=" ".join(str(v) for v in (bounds[0],-bounds[3],bounds[2]-bounds[0],bounds[3]-bounds[1]))
    return f'''<!doctype html><html><meta charset="utf-8"><title>{html.escape(case_id)}</title><style>
html,body{{margin:0;height:100%;background:#111827;font:14px system-ui;color:#fff}}header{{padding:8px 14px;display:flex;gap:18px}}
#canvas{{height:calc(100% - 42px);background:#fff;overflow:hidden}}svg{{width:100%;height:100%;touch-action:none;cursor:crosshair}}</style>
<header><b>{html.escape(case_id)}</b><span>{html.escape(level)}</span><span>RAW DXF ONLY</span><span id="xy">x —, y —</span><span>Wheel: zoom · Drag: pan</span></header><div id="canvas">{svg}</div><script>
const s=document.querySelector('svg'),o=document.querySelector('#xy');let b=[{initial}],d=null;const a=()=>s.setAttribute('viewBox',b.join(' '));a();
s.onwheel=e=>{{e.preventDefault();let p=s.createSVGPoint();p.x=e.clientX;p.y=e.clientY;p=p.matrixTransform(s.getScreenCTM().inverse());let f=e.deltaY>0?1.12:.88;b=[p.x+(b[0]-p.x)*f,p.y+(b[1]-p.y)*f,b[2]*f,b[3]*f];a()}};
s.onpointerdown=e=>{{d=[e.clientX,e.clientY,...b];s.setPointerCapture(e.pointerId)}};s.onpointermove=e=>{{let p=s.createSVGPoint();p.x=e.clientX;p.y=e.clientY;p=p.matrixTransform(s.getScreenCTM().inverse());o.textContent=`x ${{p.x.toFixed(4)}}, y ${{(-p.y).toFixed(4)}}`;if(d){{b[0]=d[2]-(e.clientX-d[0])*b[2]/s.clientWidth;b[1]=d[3]-(e.clientY-d[1])*b[3]/s.clientHeight;a()}}}};s.onpointerup=()=>d=null;
</script></html>'''


def _instructions(case_id,level,source_hash,frame_id,bounds):
    return f"""# Independent Golden review — {case_id}

Level: `{level}`

Source SHA-256: `{source_hash}`

Frame identity: `{frame_id}`

Frame bounds: `{bounds}`

Open `review.html`; it contains raw DXF primitives only. Do not open Planha
reconstruction output during annotation. Wheel zooms, drag pans, and the header
shows source DXF coordinates.

1. Trace building outer ring and real courtyard/lightwell voids.
2. Trace every physical space. Furniture, cabinets, dimensions, annotations and
   stair-tread graphics are not physical spaces.
3. Use stable IDs (`SPACE-001`, ...); use `UNKNOWN` instead of guessing.
4. Add functional zones only when independently clear; do not invent boundaries.
5. Add DOOR, WINDOW and OPEN_PASSAGE independently with connected spaces or
   EXTERIOR. Unclear portals remain UNKNOWN.
6. Record geometric adjacency separately from portal access connectivity.
7. Annotator records name/date and changes DRAFT to REVIEWED.
8. A different reviewer validates the source, records review/approval dates and
   changes REVIEWED to APPROVED. Scoring is disabled before APPROVED.

Run the structural validator before review and approval. It never edits data.
"""


def build(source,case_id,level,bounds,runtime_frame_id):
    source=Path(source); data=source.read_bytes(); source_hash=sha256(data).hexdigest(); doc=ezdxf.readfile(source)
    svg,counts=_source_svg(doc,bounds,case_id)
    golden={"schema":"architectural-topology-golden/1.0","case_id":case_id,"source_sha256":source_hash,"review_status":"DRAFT",
            "review":{"method":"INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW","annotator":None,"annotation_date":None,"reviewer":None,
                      "reviewed_at":None,"approved_at":None,"runtime_output_visible_during_annotation":False},
            "frame":{"runtime_frame_id":runtime_frame_id,"level":level,"bounds":bounds},"space_match_iou":.5,
            "building_envelope":{"status":"UNKNOWN","outer_ring":[],"interior_voids":[]},"spaces":[],"functional_zones":[],
            "portals":[],"geometric_adjacency":[],"access_connectivity":[],
            "annotation_notes":["Review source-only material without runtime output.","UNKNOWN is preferred to guessing."]}
    manifest={"case_id":case_id,"source_sha256":source_hash,"frame_identity":runtime_frame_id,"level":level,"bounds":bounds,
              "coordinate_system":"SOURCE_DXF_XY; SVG display uses -Y","render_source":"RAW_DXF_RECURSIVE_PRIMITIVES_ONLY",
              "rendered_primitive_counts":counts,"excluded_runtime_material":True}
    return svg,golden,manifest,_viewer(svg,case_id,level,bounds),_instructions(case_id,level,source_hash,runtime_frame_id,bounds)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--source",required=True); p.add_argument("--case-id",required=True); p.add_argument("--level",required=True)
    p.add_argument("--bounds",required=True,nargs=4,type=float); p.add_argument("--runtime-frame-id",required=True); p.add_argument("--output-dir",required=True)
    a=p.parse_args(); target=Path(a.output_dir); target.mkdir(parents=True,exist_ok=True)
    svg,golden,manifest,viewer,instructions=build(a.source,a.case_id,a.level,a.bounds,a.runtime_frame_id)
    for name,value in (("raw-source.svg",svg),("review.html",viewer),("REVIEWER-INSTRUCTIONS.md",instructions)): (target/name).write_text(value,encoding="utf-8")
    for name,value in (("golden.json",golden),("manifest.json",manifest)): (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"DRAFT_WAITING_FOR_INDEPENDENT_REVIEW","case_id":a.case_id,"package":str(target),"source_sha256":manifest["source_sha256"]},indent=2))


if __name__=="__main__": main()
