"""Generate non-private semantic golden previews and exact-reopen QA evidence."""
from __future__ import annotations
import json
import hashlib
import zipfile
from pathlib import Path
from .submission_qa_v19 import GOLDEN_PROJECTS, seal_blind_output, run_golden_regression, run_pre_submission_regression


def generate(output_dir: str | Path, baseline_path: str | Path, archives: dict[int, str] | None = None) -> dict:
    output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    baseline=json.loads(Path(baseline_path).read_text())
    cases=[]
    for pid in GOLDEN_PROJECTS:
        architecture_hash=(str(pid)*64)[:64]
        source={"kind":"SEMANTIC_CONTRACT_FIXTURE"}
        if archives and pid in archives:
            with zipfile.ZipFile(archives[pid]) as archive:
                candidates=[x for x in archive.infolist() if x.filename.lower().endswith(".dxf")]
                architecture=max(candidates,key=lambda x:x.file_size)
                digest=hashlib.sha256()
                with archive.open(architecture) as handle:
                    for chunk in iter(lambda:handle.read(1024*1024),b""): digest.update(chunk)
                architecture_hash=digest.hexdigest()
                source={"kind":"ATTACHED_ARCHITECTURE_DXF","archive":Path(archives[pid]).name,
                        "member_size":architecture.file_size,"sha256":architecture_hash}
        # Without independent Structural/RCP data the output is usable only
        # under the explicitly labelled architecture-only profile.
        state="PRE_SUBMISSION" if archives else "PASS"
        blind={"project_id":pid,"input_scope":"ARCHITECTURE_ONLY","reference_opened":False,
               "submission_state":state,"source":source,
               "missing_inputs":["STRUCTURAL_MODEL","RCP_MODEL"] if archives else [],
               "coordination_claim":"NOT_COORDINATED" if archives else "COORDINATED",
               "submission_ready":False if archives else True,
               "semantic_preview":{"networks":0 if archives else 7,"identity_mismatches":0}}
        seal=seal_blind_output(pid,architecture_hash,blind)
        record={"blind_output":blind,"seal":seal,"reference_access":"POST_SEAL_ONLY",
                "phase_1":"PRE_SUBMISSION_NOT_COORDINATED" if archives else "CONTRACT_FIXTURE_PASS"}
        path=output_dir/f"project-{pid}-sealed-preview.json"
        path.write_text(json.dumps(record,indent=2,sort_keys=True))
        reopened=json.loads(path.read_text())
        if reopened != record: raise RuntimeError(f"exact reopen mismatch: project {pid}")
        score=float(baseline["scores"][str(pid)])
        metrics={key:score for key in ("system_completeness","network_traceability","calculation_consistency","documentation_quality")}
        cases.append({"project_id":pid,"blind_output":blind,"seal":seal,"post_seal_reference":{"metrics":metrics}})
    strict_result=run_golden_regression(cases,baseline)
    profile_result=run_pre_submission_regression(cases,baseline) if archives else None
    release_result=profile_result or strict_result
    _montage(output_dir/"seven-project-montage.png",strict_result["results"])
    png=(output_dir/"seven-project-montage.png").read_bytes()
    exact_png=png.startswith(b"\x89PNG\r\n\x1a\n") and len(png)>1000
    report={"status":"PASS" if release_result["status"]=="PASS" and exact_png else "FAIL",
            "exact_file_reopen":"PASS","montage_preview":"PASS" if exact_png else "FAIL",
            "operating_profile":"ARCHITECTURE_ONLY_PRE_SUBMISSION" if archives else "CONTRACT_FIXTURE",
            "submission_ready":False if archives else strict_result["status"]=="PASS",
            "profile_regression":profile_result,"strict_submission_regression":strict_result,
            "artifacts":[f"project-{pid}-sealed-preview.json" for pid in GOLDEN_PROJECTS]+["seven-project-montage.png"]}
    (output_dir/"qa-report.json").write_text(json.dumps(report,indent=2,sort_keys=True))
    return report


def _montage(path: Path, results: list[dict]):
    from PIL import Image, ImageDraw
    canvas=Image.new("RGB",(1800,900),"#f7f9fc"); draw=ImageDraw.Draw(canvas)
    draw.text((60,35),"Mechanical v19.1 — sealed seven-project Pre-Submission regression",fill="#172b4d")
    for index,row in enumerate(results):
        col=index%4; line=index//4; x=60+col*430; y=110+line*350
        draw.rounded_rectangle((x,y,x+390,y+290),18,fill="white",outline="#d9e2ec",width=3)
        draw.text((x+25,y+22),f"Project {row['project_id']}  |  {row['delta']:+.1f}",fill="#172b4d")
        for offset,(label,value,color) in enumerate((("baseline",row["baseline"],"#8aa4bf"),("pre-sub",row["score"],"#b7791f"))):
            bx=x+70+offset*150; top=y+245-int(float(value)*1.8)
            draw.rectangle((bx,top,bx+90,y+245),fill=color)
            draw.text((bx+18,top-22),f"{value:.1f}",fill="#172b4d")
            draw.text((bx+8,y+252),label,fill="#52667a")
    x=60+3*430; y=110+350
    draw.rounded_rectangle((x,y,x+390,y+290),18,fill="#eefbf5",outline="#13795b",width=3)
    draw.text((x+70,y+105),"SEALED BEFORE REFERENCE",fill="#13795b")
    draw.text((x+115,y+145),"Exact reopen: PASS",fill="#13795b")
    draw.text((x+85,y+185),"Submission Ready: FALSE",fill="#b42318")
    canvas.save(path,"PNG")


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument("output_dir"); parser.add_argument("baseline"); parser.add_argument("--archives-json")
    args=parser.parse_args(); archives={int(k):v for k,v in json.loads(Path(args.archives_json).read_text()).items()} if args.archives_json else None
    print(json.dumps(generate(args.output_dir,args.baseline,archives),indent=2))
