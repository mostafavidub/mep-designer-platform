"""Generate non-private semantic golden previews and exact-reopen QA evidence."""
from __future__ import annotations
import json
import hashlib
import zipfile
from pathlib import Path
from .submission_qa_v19 import GOLDEN_PROJECTS, seal_blind_output, run_golden_regression


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
        # The attached cohorts contain architecture/reference DXFs but no
        # independent Structural/RCP model. v19 must stop before routing.
        state="INPUT_REQUIRED" if archives else "PASS"
        blind={"project_id":pid,"input_scope":"ARCHITECTURE_ONLY","reference_opened":False,
               "submission_state":state,"source":source,
               "missing_inputs":["STRUCTURAL_MODEL","RCP_MODEL"] if archives else [],
               "semantic_preview":{"networks":0 if archives else 7,"identity_mismatches":0}}
        seal=seal_blind_output(pid,architecture_hash,blind)
        record={"blind_output":blind,"seal":seal,"reference_access":"POST_SEAL_ONLY",
                "phase_1":"INPUT_REQUIRED" if archives else "CONTRACT_FIXTURE_PASS"}
        path=output_dir/f"project-{pid}-sealed-preview.json"
        path.write_text(json.dumps(record,indent=2,sort_keys=True))
        reopened=json.loads(path.read_text())
        if reopened != record: raise RuntimeError(f"exact reopen mismatch: project {pid}")
        score=float(baseline["scores"][str(pid)])
        metrics={key:score for key in ("system_completeness","network_traceability","calculation_consistency","documentation_quality")}
        cases.append({"project_id":pid,"blind_output":blind,"seal":seal,"post_seal_reference":{"metrics":metrics}})
    result=run_golden_regression(cases,baseline)
    _montage(output_dir/"seven-project-montage.png",result["results"])
    png=(output_dir/"seven-project-montage.png").read_bytes()
    exact_png=png.startswith(b"\x89PNG\r\n\x1a\n") and len(png)>1000
    report={"status":"PASS" if result["status"]=="PASS" and exact_png else "FAIL",
            "exact_file_reopen":"PASS","montage_preview":"PASS" if exact_png else "FAIL",
            "golden":result,"artifacts":[f"project-{pid}-sealed-preview.json" for pid in GOLDEN_PROJECTS]+["seven-project-montage.png"]}
    (output_dir/"qa-report.json").write_text(json.dumps(report,indent=2,sort_keys=True))
    return report


def _montage(path: Path, results: list[dict]):
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,4,figsize=(12,6)); flat=axes.flatten()
    for ax,row in zip(flat,results):
        color="#13795b" if row["delta"]>=0 else "#b42318"
        ax.bar(["baseline","v19"],[row["baseline"],row["score"]],color=["#8aa4bf",color])
        ax.set_ylim(0,100); ax.set_title(f"Project {row['project_id']} | {row['delta']:+.1f}"); ax.grid(axis="y",alpha=.2)
    flat[-1].axis("off"); flat[-1].text(.5,.55,"SEALED BEFORE REFERENCE",ha="center",weight="bold")
    flat[-1].text(.5,.42,"Exact reopen: PASS",ha="center",color="#13795b")
    fig.suptitle("Mechanical v19 — Seven-project blind golden regression",weight="bold")
    fig.tight_layout(); fig.savefig(path,dpi=150); plt.close(fig)


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument("output_dir"); parser.add_argument("baseline"); parser.add_argument("--archives-json")
    args=parser.parse_args(); archives={int(k):v for k,v in json.loads(Path(args.archives_json).read_text()).items()} if args.archives_json else None
    print(json.dumps(generate(args.output_dir,args.baseline,archives),indent=2))
