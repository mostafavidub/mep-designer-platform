"""Create a read-only, instance-aware nested-block admission gate and overlays."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path

import ezdxf
from shapely.geometry import LineString

from cad_engine.architectural_block_classifier_qa import definition_summary, inventory_instances

COLORS={"ARCHITECTURAL_WALL_ASSEMBLY":"#16a34a","ARCHITECTURAL_PARTITION_ASSEMBLY":"#22c55e",
        "DOOR_ASSEMBLY":"#2563eb","WINDOW_ASSEMBLY":"#06b6d4","OPENING_ASSEMBLY":"#0ea5e9",
        "STRUCTURAL_COLUMN_OR_CORE":"#64748b","SANITARY_FIXTURE":"#a855f7","KITCHEN_CASEWORK":"#f97316",
        "FURNITURE":"#d97706","ANNOTATION_SYMBOL":"#9333ea","DETAIL_GRAPHIC":"#7c3aed",
        "TEXT_GLYPH_GRAPHIC":"#db2777","MIXED_ARCHITECTURAL_BLOCK":"#e11d48","UNKNOWN":"#dc2626"}

def points(value): return " ".join(f"{x},{-y}" for x,y in value)
def polyline(value,color,width=1,dash=""):
    return f'<polyline points="{points(value)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}" vector-effect="non-scaling-stroke"/>'
def svg(bounds,body):
    x0,y0,x1,y1=bounds
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {-y1} {x1-x0} {y1-y0}"><rect x="{x0}" y="{-y1}" width="{x1-x0}" height="{y1-y0}" fill="white"/>{body}</svg>'

def main(source, model_path, output):
    started=time.perf_counter(); model=json.loads(Path(model_path).read_text())
    selected_ids={"FRAME-C7C5B4F856993D8A":"GROUND","FRAME-BB1323C2D20E9400":"LEVEL_01"}
    frames=[{"frame_id":row["frame_id"],"floor":selected_ids[row["frame_id"]],"bounds":row["bounds"]}
            for row in model["frames"] if row.get("frame_id") in selected_ids]
    accepted={frame["frame_id"]:[] for frame in frames}
    for row in model.get("architectural_segments") or []:
        if row.get("frame_id") in accepted and row.get("status")=="ACCEPTED" and len(row.get("geometry") or [])>=2:
            accepted[row["frame_id"]].append(LineString(row["geometry"]))
    parse_started=time.perf_counter(); doc=ezdxf.readfile(source); parse_seconds=time.perf_counter()-parse_started
    instances=inventory_instances(doc,frames=frames,accepted_lines_by_frame=accepted,
                                  metres_per_unit=model["source"].get("metres_per_unit") or 1.0)
    definitions=definition_summary(instances)
    admitted=[row for row in instances if row["action"]=="ADMIT_WALL_CHILDREN"]
    excluded=[row for row in instances if row["action"]=="EXCLUDE_FROM_WALL_PIPELINE"]
    unresolved=[row for row in instances if row["action"]=="KEEP_EXCLUDED_UNRESOLVED"]
    gate="YES" if admitted else "NO"
    status="SELECTIVE_NESTED_WALL_RECOVERY_REQUIRED" if admitted else "NESTED_BLOCKS_NOT_DOMINANT_WALL_SOURCE"
    report={"source":{"sha256":model["source"]["source_sha256"],"parse_count":1},
            "scope":"FASIHI_GROUND_AND_LEVEL_01_ONLY","runtime_reconstruction_modified":False,
            "frames":frames,"definition_inventory":definitions,"instance_inventory":instances,
            "gate":{"are_nested_blocks_a_dominant_missing_wall_source":gate,"status":status,
                    "admitted_instances":len(admitted),"supported_non_wall_instances":len(excluded),
                    "unresolved_instances":len(unresolved),
                    "decision":"Do not change extraction; retain fail-closed nested exclusion." if gate=="NO" else "Admit only proven wall child primitives."},
            "performance":{"dxf_parse_seconds":parse_seconds,"total_seconds":time.perf_counter()-started}}
    root=Path(output); root.mkdir(parents=True,exist_ok=True)
    (root/"nested-block-inventory.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for frame in frames:
        rows=[row for row in instances if row["frame_id"]==frame["frame_id"]]
        base="".join(polyline(list(line.coords),"#e2e8f0") for line in accepted[frame["frame_id"]])
        raw=base+"".join(polyline(g,"#475569") for row in rows for g in row["world_geometries"])
        roles=base+"".join(polyline(g,COLORS[row["role"]],2) for row in rows for g in row["world_geometries"])
        decisions=base+"".join(polyline(g,"#16a34a" if row["action"]=="ADMIT_WALL_CHILDREN" else "#dc2626",2,"3 2" if row["action"]!="ADMIT_WALL_CHILDREN" else "") for row in rows for g in row["world_geometries"])
        connected=base+"".join(polyline(g,"#16a34a" if row["features"]["external_connections"]>=2 else "#dc2626",2) for row in rows for g in row["world_geometries"])
        thickness=base+"".join(polyline(g,"#16a34a" if row["features"]["parallel_face_pairs"] else "#d97706",2) for row in rows for g in row["world_geometries"])
        final=base+"".join(polyline(g,"#16a34a" if row["status"]=="PROVEN" else "#64748b" if row["status"]=="SUPPORTED_NON_WALL" else "#dc2626",2) for row in rows for g in row["world_geometries"])
        for name,body in [("01-raw-nested",raw),("02-role-classification",roles),("03-admit-reject",decisions),
                          ("04-external-connectivity",connected),("05-local-thickness",thickness),("06-final-decision",final)]:
            (root/f'{frame["floor"].lower()}-{name}.svg').write_text(svg(frame["bounds"],body))
    print(json.dumps({"output":str(root),"gate":report["gate"],"performance":report["performance"]},indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("source"); parser.add_argument("model"); parser.add_argument("output")
    args=parser.parse_args(); main(args.source,args.model,args.output)
