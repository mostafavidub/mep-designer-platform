#!/usr/bin/env python3
"""Blind, local-only Fasihi Ground semantic Mechanical shadow qualification."""
import argparse, hashlib, json, time
from pathlib import Path

from cad_engine.architectural_space_engine import reconstruct_architecture
from cad_engine.semantic_guided_mechanical_preanalysis import (
    build_search_plan, run_shadow_ab, scope_architecture_to_frame, search_space_metrics,
)

DEPENDENCY="f7c09e3305cbf0ef23595b273922d51143da28b9"

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def visual_html(image_path, plan, report):
    zones=[]
    colors={1:"#00a86b",2:"#ff9800",3:"#3b82f6"}
    for z in plan["search_zones"]:
        x1,y1,x2,y2=z["approx_bbox_norm"]
        zones.append(f'<div class="zone" style="left:{x1*100:.3f}%;top:{y1*100:.3f}%;width:{(x2-x1)*100:.3f}%;height:{(y2-y1)*100:.3f}%;border-color:{colors[z["priority"]]}"><b>{z["semantic_type"]}</b><small>P{z["priority"]} · SEARCH ONLY</small></div>')
    rows=''.join(f'<tr><td>{z["semantic_type"]}</td><td>{z["mep_group"]}</td><td>{", ".join(z["recommended_searches"])}</td><td>{report["comparison"]["zone_work"].get(z["search_zone_id"],0)}</td></tr>' for z in plan["search_zones"])
    return f'''<!doctype html><meta charset="utf-8"><title>Fasihi Ground — Mechanical Shadow A/B</title><style>body{{font:14px system-ui;background:#101827;color:#eaf1ff;margin:0}}header{{padding:16px 24px}}.wrap{{display:grid;grid-template-columns:minmax(520px,1fr) 520px;gap:18px;padding:0 24px 24px}}.plan{{position:relative;background:white}}.plan img{{width:100%;display:block}}.zone{{position:absolute;border:3px solid;background:#3b82f622;box-sizing:border-box;color:#111;padding:4px;text-shadow:0 1px white}}.zone small{{display:block}}table{{border-collapse:collapse;width:100%;background:#182338}}td,th{{border:1px solid #40506a;padding:7px;vertical-align:top}}.warning{{color:#ffd166}}</style><header><h1>Fasihi Ground — Semantic-guided Mechanical Shadow</h1><p class="warning">کادرها فقط اولویت جست‌وجو هستند؛ هندسه یا تصمیم مهندسی نیستند. Global fallback فعال است.</p></header><div class="wrap"><div class="plan"><img src="file://{image_path}">{''.join(zones)}</div><div><h2>A/B conclusion</h2><p><b>{report['qualification_status']}</b></p><p>Ground deterministic detections: {len(report['baseline']['result']['detections'])}; candidates: {len(report['baseline']['result']['candidates'])}</p><p>Baseline recall in B: {report['comparison']['baseline_detection_recall_in_b']*100:.1f}%</p><table><tr><th>Semantic zone</th><th>MEP group</th><th>Expected investigation</th><th>CAD objects in zone</th></tr>{rows}</table></div></div>'''

def main():
    p=argparse.ArgumentParser(); p.add_argument("source"); p.add_argument("artifact"); p.add_argument("render_manifest"); p.add_argument("output")
    args=p.parse_args(); output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    source_sha=digest(args.source); artifact=json.loads(Path(args.artifact).read_text()); manifest=json.loads(Path(args.render_manifest).read_text())
    t0=time.perf_counter(); architecture=reconstruct_architecture(args.source); parse_seconds=time.perf_counter()-t0
    frame_id=artifact["frame_id"]
    frame=next(row for row in architecture["frames"] if row["frame_id"]==frame_id)
    scoped=scope_architecture_to_frame(architecture,frame["bounds"],frame_id)
    t0=time.perf_counter(); plan=build_search_plan(artifact,manifest,source_sha256=source_sha,frame_id=frame_id,
      dependency_commit=DEPENDENCY,expected_dependency_commit=DEPENDENCY,render_sha256=artifact["render_sha256"]); load_plan_seconds=time.perf_counter()-t0
    # Freeze A before executing or inspecting B.
    empty_plan={**plan,"search_zones":[]}
    baseline=run_shadow_ab(scoped,empty_plan)["baseline"]
    baseline_frozen_hash=hashlib.sha256(json.dumps(baseline,sort_keys=True,default=str).encode()).hexdigest()
    comparison=run_shadow_ab(scoped,plan)
    metrics=search_space_metrics(scoped,plan)
    report={"schema":"fasihi-ground-semantic-mep-shadow-qualification/1.0","dependency_commit":DEPENDENCY,
      "source_sha256":source_sha,"frame_id":frame_id,"semantic_artifact_sha256":digest(args.artifact),
      "render_manifest_sha256":digest(args.render_manifest),"semantic_artifact_reused":True,"additional_deepseek_calls":0,
      "additional_provider_tokens":0,"dxf_parse_count":1,"parse_seconds":parse_seconds,"search_plan_seconds":load_plan_seconds,
      "baseline_frozen_hash":baseline_frozen_hash,"baseline":baseline,"comparison":comparison,"search_space_metrics":metrics,
      "frame_inventory":{"physical_spaces":len(scoped["physical_spaces"]),"rooms":len(scoped["rooms"]),
        "objects":len(scoped["all_inserts"]),"texts":len(scoped["all_texts"]),"shafts":len(scoped["shafts"])},
      "reference_mechanical_drawing_used":False,"hard_pruning_enabled":False,
      "engineering_conclusion":"SAFE_BUT_NO_MATERIAL_DETECTION_BENEFIT" if not baseline["result"]["detections"] and not baseline["result"]["candidates"] else "MEASURED",
      "qualification_status":"SEMANTIC_GUIDANCE_NO_MATERIAL_BENEFIT" if not baseline["result"]["detections"] and not baseline["result"]["candidates"] else "SEMANTIC_GUIDED_MEP_PREANALYSIS_PARTIAL"}
    (output/"search-plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    (output/"ab-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (output/"visual-qa.html").write_text(visual_html(manifest["image_path"],plan,report))
    print(json.dumps({"output":str(output),"status":report["qualification_status"],"metrics":metrics},indent=2))

if __name__=="__main__": main()
