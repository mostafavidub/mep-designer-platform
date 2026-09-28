#!/usr/bin/env python3
"""Private, single-parse fixture recognition audit and SVG QA overlays."""
import argparse, json
from collections import Counter
from pathlib import Path

from cad_engine.architectural_space_engine import NoVisionAdapter, reconstruct_architecture
from cad_engine.fixture_recognition import recognize_fixtures_equipment
from cad_engine.fixture_recognition_v14 import recognize_fixtures_equipment as recognize_legacy


class DeterministicOnly(NoVisionAdapter):
    provider="NONE"; model="NONE"; last_call_metadata={"network_call":False}

    def analyze(self, *, image_path, frame_id, regions, context=None):
        return {"frame_id":frame_id,"physical_spaces":[]}


def svg(rows, bounds, title):
    minx,miny,maxx,maxy=bounds; width=max(maxx-minx,1); height=max(maxy-miny,1)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}">',
         '<style>.p{stroke:#d1d5db;stroke-width:.001;vector-effect:non-scaling-stroke}.c{fill:none;stroke:#ef4444;stroke-width:.003;vector-effect:non-scaling-stroke}.t{font:12px sans-serif;paint-order:stroke;stroke:white;stroke-width:3px}</style>',
         f'<text class="t" x="{minx}" y="{-maxy+20}">{title}</text>']
    for row in rows:
        bbox=row.get("world_bbox"); point=row.get("world_anchor")
        if bbox:
            out.append(f'<rect class="c" x="{bbox[0]}" y="{-bbox[3]}" width="{bbox[2]-bbox[0]}" height="{bbox[3]-bbox[1]}"/>')
        if point:
            label=f'{row["candidate_id"][-6:]} {row.get("type_candidate") or "?"} {row["recognition_status"]}'
            out.append(f'<circle class="c" cx="{point[0]}" cy="{-point[1]}" r="3"/><text class="t" x="{point[0]+3}" y="{-point[1]}">{label}</text>')
    out.append('</svg>'); return ''.join(out)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("source"); parser.add_argument("output"); parser.add_argument("--frame-id")
    args=parser.parse_args(); output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    model=reconstruct_architecture(args.source,vision_adapter=DeterministicOnly())
    if args.frame_id:
        frame=next(f for f in model["frames"] if f["frame_id"]==args.frame_id)
        b=frame["bounds"]
        inside=lambda p: bool(p and b[0]<=p[0]<=b[2] and b[1]<=p[1]<=b[3])
        def primitive_inside(row):
            points=([row["point"]] if row.get("point") else [row["start"],row["end"]]
                    if row.get("start") and row.get("end") else row.get("points") or row.get("geometry") or [])
            return any(inside(p) for p in points)
        model={**model,"frames":[frame],"rooms":[r for r in model["rooms"] if r.get("plan_id")==args.frame_id or inside(r.get("centroid"))],
               "all_inserts":[r for r in model["all_inserts"] if inside(r.get("point"))],
               "recognition_primitives":[r for r in model.get("recognition_primitives") or [] if primitive_inside(r)]}
    legacy=recognize_legacy(model); result=recognize_fixtures_equipment(model)
    candidates=result["object_candidates"]
    frame_bounds=model["frames"][0].get("bounds") if len(model["frames"])==1 else None
    def in_frame_primitive(row):
        points=[]
        if row.get("point"): points=[row["point"]]
        elif row.get("start") and row.get("end"): points=[row["start"],row["end"]]
        else: points=row.get("points") or row.get("geometry") or []
        return bool(not frame_bounds or any(frame_bounds[0]<=p[0]<=frame_bounds[2] and frame_bounds[1]<=p[1]<=frame_bounds[3] for p in points))
    local_primitives=[r for r in model.get("recognition_primitives") or [] if in_frame_primitive(r)]
    audit={"schema":"fixture-source-audit/2.0","source_sha256":model["source"]["source_sha256"],
           "dxf_parse_count":model["diagnostics"]["dxf_parse_count"],"frames":model["frames"],
           "legacy_counts":{"candidates":len(legacy.get("candidates") or []),
                            "confirmed":len(legacy.get("detections") or [])},
           "entity_counts":model["diagnostics"]["entity_counts"],"top_level_insert_count":sum(r.get("nested_depth",0)==0 for r in model["all_inserts"]),
           "nested_insert_count":sum(r.get("nested_depth",0)>0 for r in model["all_inserts"]),
           "anonymous_insert_count":sum(str(r.get("name") or "").upper().startswith("*U") for r in model["all_inserts"]),
           "insert_inventory":[{"handle":r.get("handle"),"name":r.get("name"),"layer":r.get("layer"),
                                "point":r.get("point"),"nested_path":r.get("nested_path"),
                                "rotation":r.get("rotation"),"scale":r.get("scale")} for r in model["all_inserts"]],
           "frame_primitive_type_counts":dict(Counter(r.get("entity_type") for r in local_primitives)),
           "frame_primitive_layer_counts":dict(Counter(r.get("layer") for r in local_primitives).most_common()),
           "source_representation_counts":dict(Counter(r["source_representation"] for r in candidates)),
           "recognition_status_counts":dict(Counter(r["recognition_status"] for r in candidates)),
           "hosting_status_counts":dict(Counter(r["hosting_status"] for r in candidates)),
           "evidence_family_counts":dict(Counter(e for r in candidates for e in r["evidence_families"])),
           "candidates":candidates,"quality":result["quality"]}
    (output/"source-audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    (output/"blind-detector.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    bounds=(model["frames"][0].get("bounds") if len(model["frames"])==1 else model.get("bounds")) or [0,0,1,1]
    groups=[("02-all-object-candidates",candidates),("03-deterministically-confirmed",result["confirmed_objects"]),
            ("04-ambiguous",result["ambiguous_objects"]),("05-rejected-negative-evidence",result["rejected_objects"]),
            ("06-hosting-status",candidates)]
    for name,rows in groups:(output/f"{name}.svg").write_text(svg(rows,bounds,name))
    print(json.dumps({"output":str(output),"audit":{k:v for k,v in audit.items() if k!="candidates"}},indent=2))


if __name__=="__main__":main()
