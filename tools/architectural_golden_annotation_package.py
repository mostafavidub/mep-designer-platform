#!/usr/bin/env python3
"""Create a source-only annotation package for independent Golden review.

The renderer reads raw DXF primitives inside the selected authoritative frame.
It never imports or executes architectural reconstruction output.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import html
import json
from pathlib import Path

import ezdxf


def _points(entity):
    kind=entity.dxftype()
    try:
        if kind=="LINE": return [(float(entity.dxf.start.x),float(entity.dxf.start.y)),(float(entity.dxf.end.x),float(entity.dxf.end.y))]
        if kind=="LWPOLYLINE": return [(float(x),float(y)) for x,y,*_ in entity.get_points()]
        if kind=="POLYLINE": return [(float(v.dxf.location.x),float(v.dxf.location.y)) for v in entity.vertices]
        if kind in {"ARC","CIRCLE"}: return [(float(p.x),float(p.y)) for p in entity.flattening(.02)]
    except Exception: return []
    return []


def build(source,case_id,level,bounds,runtime_frame_id):
    source=Path(source); data=source.read_bytes(); doc=ezdxf.readfile(source); minx,miny,maxx,maxy=bounds
    paths=[]
    for entity in doc.modelspace():
        points=_points(entity)
        if not points: continue
        if max(x for x,_ in points)<minx or min(x for x,_ in points)>maxx or max(y for _,y in points)<miny or min(y for _,y in points)>maxy: continue
        if bool(getattr(entity,"closed",False)) and points[0]!=points[-1]: points.append(points[0])
        encoded=" ".join(f"{x:.6f},{-y:.6f}" for x,y in points)
        paths.append(f'<polyline points="{encoded}" fill="none" stroke="#27313f" stroke-width="0.012" vector-effect="non-scaling-stroke"/>')
    width=maxx-minx; height=maxy-miny
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}" '
         f'data-case="{html.escape(case_id)}"><rect x="{minx}" y="{-maxy}" width="{width}" height="{height}" fill="white"/>'
         +"".join(paths)+"</svg>")
    golden={"schema":"architectural-topology-golden/1.0","case_id":case_id,"source_sha256":sha256(data).hexdigest(),
            "review_status":"PENDING","review":{"method":"INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW","reviewer":None,
            "reviewed_at":None,"runtime_output_visible_during_annotation":False},
            "frame":{"runtime_frame_id":runtime_frame_id,"level":level,"bounds":bounds},"space_match_iou":.5,
            "building_envelope":{"status":"UNKNOWN","outer_ring":[],"interior_voids":[]},"spaces":[],"portals":[],"adjacency":[],
            "annotation_notes":["Review raw-source.svg without opening runtime reconstruction output.",
                                "Record UNKNOWN rather than infer an architectural fact without sufficient source evidence."]}
    return svg,golden


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--source",required=True); parser.add_argument("--case-id",required=True)
    parser.add_argument("--level",required=True); parser.add_argument("--bounds",required=True,nargs=4,type=float)
    parser.add_argument("--runtime-frame-id",required=True); parser.add_argument("--output-dir",required=True)
    args=parser.parse_args(); target=Path(args.output_dir); target.mkdir(parents=True,exist_ok=True)
    svg,golden=build(args.source,args.case_id,args.level,args.bounds,args.runtime_frame_id)
    (target/"raw-source.svg").write_text(svg,encoding="utf-8")
    (target/"golden.json").write_text(json.dumps(golden,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PENDING_INDEPENDENT_REVIEW","case_id":args.case_id,
                      "source_svg":str(target/"raw-source.svg"),"golden":str(target/"golden.json")},indent=2))


if __name__=="__main__": main()
