"""Render the raw-to-canonical wall admission funnel for visual QA."""
from __future__ import annotations
import json,sys
from pathlib import Path
from shapely.geometry import LineString,box

COLORS={"ACCEPTED":"#16a34a","PROVISIONAL":"#d97706","REJECTED":"#dc2626","EXCLUDED_NOISE":"#6b7280"}
def pts(points): return " ".join(f"{x},{-y}" for x,y in points)
def line(points,color,width=1,dash=""):
    return f'<polyline points="{pts(points)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}" vector-effect="non-scaling-stroke"/>'
def svg(bounds,body):
    x0,y0,x1,y1=bounds
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {-y1} {x1-x0} {y1-y0}"><style>text{{font:.18px sans-serif;paint-order:stroke;stroke:white;stroke-width:2px}}</style>{body}</svg>'
def main(source,output):
    model=json.loads(Path(source).read_text()); root=Path(output); root.mkdir(parents=True,exist_ok=True)
    for frame in model["frames"]:
        if frame.get("frame_type")!="PRIMARY_FLOOR" or not frame.get("bounds"): continue
        fid=frame["frame_id"]; clip=box(*frame["bounds"])
        segments=[row for row in model["architectural_segments"] if row.get("frame_id")==fid]
        excluded=[row for row in model.get("boundary_extraction_rejections") or [] if len(row.get("geometry") or [])>=2 and LineString(row["geometry"]).intersects(clip)]
        raw=''.join(line(row["geometry"],"#9ca3af") for row in segments+excluded)
        extraction=raw+''.join(line(row["geometry"],"#dc2626",2,"4 3") for row in excluded)
        accepted=raw+''.join(line(row["geometry"],COLORS["ACCEPTED"],2) for row in segments if row["status"]=="ACCEPTED" and not row.get("admission_trace"))
        rejected=raw+''.join(line(row["geometry"],COLORS.get(row["status"],"#dc2626"),2,"3 2") for row in segments if row["status"]!="ACCEPTED")
        recovered=raw+''.join(line(row["geometry"],"#7c3aed",3) for row in segments if row.get("admission_trace"))
        admitted=raw+''.join(line(row["geometry"],"#16a34a",2) for row in segments if row["status"]=="ACCEPTED")
        walls=''.join(line(row["centerline"],"#2563eb",2) for row in model["canonical_walls"] if row["frame_id"]==fid)
        barriers=''.join(line(row["geometry"],{"ENVELOPE":"#16a34a","WALL_MATERIAL":"#2563eb","VIRTUAL_CLOSURE":"#d97706"}.get(row["kind"],"#6b7280"),2) for row in model.get("enclosure_barrier_graph",{}).get("barriers",[]) if LineString(row["geometry"]).intersects(clip))
        env=next((row for row in model.get("building_envelopes") or [] if row["frame_id"]==fid),None)
        env_body=raw+(f'<polygon points="{pts(env["outer_ring"])}" fill="#16a34a22" stroke="#16a34a" stroke-width="3"/>' if env and env.get("outer_ring") else '')
        regions=raw+''.join(f'<polygon points="{pts(row["geometry"])}" fill="{("#16a34a" if row["role"]=="BUILDING_INTERIOR" else "#2563eb" if row["role"]=="SITE_EXTERIOR" else "#d97706" if row["role"]=="SEMI_EXTERIOR" else "#dc2626")}22" stroke="{("#16a34a" if row["role"]=="BUILDING_INTERIOR" else "#2563eb" if row["role"]=="SITE_EXTERIOR" else "#d97706" if row["role"]=="SEMI_EXTERIOR" else "#dc2626")}"/>' for row in model.get("plan_regions",{}).get("regions",[]) if row["frame_id"]==fid)
        spaces=raw+''.join(f'<polygon points="{pts(row["polygon"])}" fill="#7c3aed22" stroke="#7c3aed"/>' for row in model["physical_spaces"] if row["frame_id"]==fid)
        views=[("01-raw-source",raw),("02-boundary-admission-funnel",extraction+accepted),("03-rejected-real-wall-candidates",rejected),("04-recovered-partitions",recovered),("05-final-wall-objects",walls),("06-interior-partitions",admitted),("07-envelope-candidates",regions),("08-final-envelope",env_body),("09-plan-regions",regions),("10-final-physical-spaces",spaces)]
        for name,body in views: (root/f'{fid}-{name}.svg').write_text(svg(frame["bounds"],body))
    (root/'wall-admission-funnel.json').write_text(json.dumps(model.get("wall_admission_funnel"),ensure_ascii=False,indent=2))
    residual=[]
    for frame in model.get("wall_admission_funnel") or []:
        fid=frame["frame_id"]
        frame_bounds=next(item["bounds"] for item in model["frames"] if item["frame_id"]==fid); frame_clip=box(*frame_bounds)
        extraction=[row for row in model.get("boundary_extraction_rejections") or [] if row.get("reason") and len(row.get("geometry") or [])>=2 and LineString(row["geometry"]).intersects(frame_clip)]
        segments=[row for row in model.get("architectural_segments") or [] if row.get("frame_id")==fid]
        for category,count,rows,hypothesis in [
            ("MISSING_AT_EXTRACTION",frame["boundary_admission_rejected"],extraction,"Audit excluded nested/source geometry with positive architectural block evidence."),
            ("MISSING_FACE_PAIR",sum(row.get("wall_evidence_state")=="WEAK_WALL_CANDIDATE" for row in segments),[row for row in segments if row.get("wall_evidence_state")=="WEAK_WALL_CANDIDATE"],"Recover fragmented or curved face families without globally lowering pair thresholds."),
            ("MISSING_PARTITION_ADMISSION",sum(row.get("status") in {"PROVISIONAL","REJECTED"} for row in segments),[row for row in segments if row.get("status") in {"PROVISIONAL","REJECTED"}],"Inspect remaining candidates against junction and enclosure-gain evidence."),
            ("ENVELOPE_FAILURE",1,[],"Internal barrier graph still fuses interior and site semantics; do not tune envelope."),
        ]:
            residual.append({"frame_id":fid,"category":category,"count":count,
                             "representative_source_handles":[row.get("handle") or row.get("source_handle") for row in rows[:10]],
                             "affected_plan_regions":"AUTHORITATIVE_FRAME","next_hypothesis":hypothesis})
    (root/'residual-failure-matrix.json').write_text(json.dumps(residual,ensure_ascii=False,indent=2))
    print(root)
if __name__=='__main__': main(sys.argv[1],sys.argv[2])
