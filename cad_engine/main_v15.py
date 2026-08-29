"""Production CAD Designer entrypoint v15.

Electrical keeps the existing rule-driven flow.
Mechanical is routed through the authority-style engineering pipeline v15.
"""
from __future__ import annotations

import base64
import shutil
import tempfile
from pathlib import Path

import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

from .main import (
    SYSTEMS, DesignRequest, OUTPUT_ROOT, source_files,
    design_dxf, render_pdf, merge_pdfs, zip_outputs,
)
from .mechanical_authority_site_v15 import design_mechanical_authority_site
from app.dxf_input import normalize_input_copy

app = FastAPI(title="EngiTools CAD Designer", version="15.1.0")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "cad-designer",
        "version": "15.1.0",
        "mechanical_mode": "authority-project-driven",
        "electrical_mode": "rule-driven-preliminary",
    }


def _in_bounds(entity, bounds):
    try:
        ex = bbox.extents([entity], fast=True)
        if not ex.has_data:
            return False
        cx=(ex.extmin.x+ex.extmax.x)/2
        cy=(ex.extmin.y+ex.extmax.y)/2
        return bounds[0]-.2 <= cx <= bounds[2]+.2 and bounds[1]-.2 <= cy <= bounds[3]+.2
    except Exception:
        return False


def render_mechanical_pages(dxf_path: Path, report: dict, out_dir: Path) -> list[Path]:
    """Render each generated authority board as one PDF page."""
    doc=ezdxf.readfile(dxf_path)
    msp=doc.modelspace()
    boards=(report.get("composition") or {}).get("boards") or {}
    manifest=(report.get("composition") or {}).get("manifest") or []
    by_old={r.get("old_sheet"):r for r in manifest}
    pages=[]
    for i,(old_sheet,b) in enumerate(boards.items(),1):
        bounds=tuple(b["bounds"])
        fig=plt.figure(figsize=(8.27,11.69))
        ax=fig.add_axes([0.02,0.02,0.96,0.96])
        ax.set_aspect("equal",adjustable="box")
        ax.axis("off")
        try:
            ctx=RenderContext(doc)
            out=MatplotlibBackend(ax)
            Frontend(ctx,out).draw_layout(
                msp,finalize=True,
                filter_func=lambda e,bounds=bounds:_in_bounds(e,bounds),
            )
            ax.set_xlim(bounds[0],bounds[2])
            ax.set_ylim(bounds[1],bounds[3])
        except Exception:
            ax.text(.5,.5,"Mechanical sheet preview unavailable",ha="center",va="center",transform=ax.transAxes)
        code=(by_old.get(old_sheet) or {}).get("code") or old_sheet
        page=out_dir/f"{i:02d}_{code}.pdf"
        fig.savefig(page,format="pdf",bbox_inches="tight",pad_inches=.02)
        plt.close(fig)
        pages.append(page)
    return pages


def _validate_scope(req: DesignRequest):
    discipline=req.discipline.strip().lower()
    if discipline not in SYSTEMS:
        raise HTTPException(400,"discipline must be mechanical or electrical")
    scope=req.output_scope or {}
    if scope.get("discipline") != discipline:
        raise HTTPException(400,"output_scope discipline mismatch")
    if scope.get("only_this_discipline") is not True or scope.get("include_other_disciplines") is not False:
        raise HTTPException(400,"discipline isolation flags are required")
    requested=scope.get("systems") or []
    allowed=SYSTEMS[discipline]
    if any(s not in allowed for s in requested):
        raise HTTPException(400,"output_scope contains unsupported or cross-discipline systems")
    return discipline, requested or allowed


@app.post("/design")
def design(req: DesignRequest):
    discipline,systems=_validate_scope(req)
    project_out=OUTPUT_ROOT/str(req.project_id)/f"R{req.revision:03d}"/discipline
    shutil.rmtree(project_out,ignore_errors=True)
    project_out.mkdir(parents=True,exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="engitools-cad-") as td:
        temp_input=Path(td)/"input"
        temp_input.mkdir()
        try:
            sources=source_files(req,temp_input)
        except Exception as exc:
            raise HTTPException(400,str(exc))

        generated=[]
        page_pdfs=[]
        reports=[]

        for idx,src in enumerate(sources,start=1):
            input_recovery=normalize_input_copy(src)
            safe_stem="".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)[:80] or f"plan_{idx}"
            dxf_out=project_out/f"{idx:02d}_{safe_stem}_{discipline}.dxf"

            if discipline=="mechanical":
                report=design_mechanical_authority_site(
                    src,dxf_out,
                    answers=req.answers,
                    plan_analysis=req.plan_analysis,
                )
                if report.get("status")!="PASS":
                    detail={
                        "message":"Mechanical authority pipeline failed",
                        "pipeline_qa":report.get("pipeline_qa"),
                        "engineering_acceptance":report.get("engineering_acceptance"),
                        "authority_qa":((report.get("authority") or {}).get("authority_qa")),
                        "dxf_qa":report.get("dxf_qa"),
                        "semantic_qa":report.get("semantic_qa"),
                        "stage":report.get("stage"),
                        "architecture_preservation_qa":report.get("architecture_preservation_qa"),
                        "architecture_preservation_qa_after_v17":report.get("architecture_preservation_qa_after_v17"),
                        "reference_parity_documentation":report.get("reference_parity_documentation"),
                        "documentation_enhancement_qa":report.get("documentation_enhancement_qa"),
                    }
                    raise HTTPException(422,detail)
                pages=render_mechanical_pages(dxf_out,report,project_out)
                page_pdfs.extend(pages)
            else:
                report=design_dxf(src,dxf_out,discipline,systems,req.revision)
                page=project_out/f"{idx:02d}_{discipline}.pdf"
                render_pdf(dxf_out,page,discipline)
                page_pdfs.append(page)

            reports.append({"source":src.name,**report})
            generated.append(dxf_out)

        merged=project_out/f"EngiTools_{req.project_id}_{discipline}_R{req.revision}.pdf"
        merge_pdfs(page_pdfs,merged)
        package=project_out/f"EngiTools_{req.project_id}_{discipline}_R{req.revision}_DXF.zip"
        zip_outputs(generated,package)

        return {
            "ok":True,
            "project_id":req.project_id,
            "discipline":discipline,
            "engine_version":"15.1.0",
            "mode":"authority-project-driven" if discipline=="mechanical" else "rule-driven-preliminary",
            "preliminary":True,
            "requires_professional_review":True,
            "systems":systems,
            "design_reports":reports,
            "generated_files":[p.name for p in generated],
            "pdf_path":str(merged),
            "zip_path":str(package),
            "pdf_base64":base64.b64encode(merged.read_bytes()).decode("ascii"),
            "zip_base64":base64.b64encode(package.read_bytes()).decode("ascii"),
        }
