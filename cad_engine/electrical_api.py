"""Active production HTTP adapter for Electrical."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException

from .runtime_core import DesignRequest, OUTPUT_ROOT, source_files, zip_outputs
from .electrical_v1.production import design_electrical_authority_site, PIPELINE_AUTHORITY
from .electrical_v1.release_contract import release_contract_status
from .build_identity import build_identity


def _missing_inputs(report):
    missing = []
    data = report.get("data") or {}
    basis = (data.get("basis") or {}).get("values") or {}
    for key, value in basis.items():
        if isinstance(value, dict) and value.get("status") in {"INPUT_REQUIRED", "UNKNOWN"}:
            missing.append(key)
    for gate_name, gate in (report.get("gates") or {}).items():
        for warning in gate.get("warnings") or []:
            text = str(warning)
            if ":" in text and any(token in text for token in ("input_required", "unresolved", "not_final")):
                tail = text.rsplit(":", 1)[-1].strip()
                if tail and len(tail) < 80:
                    missing.append(tail.split(".", 1)[0])
    return list(dict.fromkeys(missing))


def register_electrical(app):
    @app.get("/electrical/status")
    def electrical_status():
        return {
            **release_contract_status(),
            "production_entrypoint": "cad_engine.main:app",
            "pipeline_authority": PIPELINE_AUTHORITY,
            "build": build_identity(),
        }

    @app.post("/design-electrical")
    def design_electrical(req: DesignRequest):
        if str(req.discipline or "").lower() != "electrical":
            raise HTTPException(400, "Electrical endpoint accepts electrical discipline only")
        scope = req.output_scope or {}
        if scope.get("discipline") != "electrical" or scope.get("only_this_discipline") is not True or scope.get("include_other_disciplines") is not False:
            raise HTTPException(400, "discipline isolation flags are required")
        project_out = OUTPUT_ROOT / str(req.project_id) / f"R{req.revision:03d}" / "electrical"
        shutil.rmtree(project_out, ignore_errors=True)
        project_out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="engitools-electrical-") as td:
            input_dir = Path(td) / "input"; input_dir.mkdir()
            try:
                sources = source_files(req, input_dir)
            except Exception as exc:
                shutil.rmtree(project_out, ignore_errors=True)
                raise HTTPException(400, str(exc))
            generated = []; reports = []
            for index, src in enumerate(sources, 1):
                safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)[:80] or f"plan_{index}"
                dst = project_out / f"{index:02d}_{safe_stem}_electrical.dxf"
                report = design_electrical_authority_site(src, dst, answers=req.answers, plan_analysis=req.plan_analysis)
                if report.get("status") != "PASS":
                    missing = _missing_inputs(report)
                    shutil.rmtree(project_out, ignore_errors=True)
                    raise HTTPException(422, {
                        "message": "Electrical authority pipeline requires additional evidence",
                        "code": "ELECTRICAL_INPUT_REQUIRED" if missing else "ELECTRICAL_QA_FAILED",
                        "status": "INPUT_REQUIRED" if missing else "FAIL",
                        "missing_inputs": missing,
                        "acceptance": report.get("acceptance"),
                        "execution_readiness": report.get("execution_readiness"),
                        "gates": {k:v for k,v in (report.get("gates") or {}).items() if v.get("status") not in {"PASS","NOT_REQUIRED"}},
                        "pipeline_authority": PIPELINE_AUTHORITY,
                    })
                reports.append({"source": src.name, **report})
                generated.append(dst)
            package = project_out / f"EngiTools_{req.project_id}_electrical_R{req.revision}_DXF.zip"
            if len(generated) > 1:
                zip_outputs(generated, package)
                for path in generated:
                    path.unlink(missing_ok=True)
            return {
                "ok": True, "project_id": req.project_id, "discipline": "electrical",
                "engine_identity": build_identity(),
                "mode": "electrical-authoritative",
                "pipeline_authority": PIPELINE_AUTHORITY,
                "preliminary": False,
                "requires_professional_review": True,
                "submission_state": "EXECUTION_REVIEW_READY",
                "systems": scope.get("systems") or [],
                "design_reports": reports,
                "generated_files": [p.name for p in generated],
                "pdf_path": "",
                "zip_path": str(package),
                "pdf_base64": "", "zip_base64": "",
            }
