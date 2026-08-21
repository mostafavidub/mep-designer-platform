import base64
import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

app = FastAPI(title="EngiTools CAD Designer", version="0.1.0")

SYSTEMS = {
    "electrical": [
        "lighting", "power", "dedicated_loads", "fire_alarm", "elv",
        "earthing_bonding", "panels", "single_line_diagram",
        "electrical_risers", "electrical_legend_notes",
    ],
    "mechanical": [
        "cold_water", "hot_water", "sanitary", "vent", "gas",
        "heating_supply", "heating_return", "cooling", "condensate",
        "exhaust_ventilation", "mechanical_risers",
        "mechanical_details_legend_notes",
    ],
}

PREFIX = {"electrical": "E", "mechanical": "M"}


class DesignRequest(BaseModel):
    project_id: str
    discipline: str
    architecture_archive_b64: str
    answers: dict = Field(default_factory=dict)
    plan_analysis: dict = Field(default_factory=dict)
    output_scope: dict
    revision: int = 1
    revision_instructions: str = ""


@app.get("/health")
def health():
    return {"ok": True, "service": "cad-designer", "version": "0.1.0"}


def safe_extract_b64(payload: str, target: Path) -> list[Path]:
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("architecture_archive_b64 is not valid base64") from exc
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        useful = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            p = Path(info.filename)
            if "__MACOSX" in p.parts or p.name.startswith(".") or p.name.startswith("._"):
                continue
            if p.suffix.lower() != ".dxf":
                raise ValueError(f"archive contains non-DXF file: {info.filename}")
            dest = (target / p.name).resolve()
            if not str(dest).startswith(str(target.resolve())):
                raise ValueError("unsafe ZIP member")
            with zf.open(info) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            useful.append(dest)
    if not useful:
        raise ValueError("no DXF files found in archive")
    return useful


def ensure_layer(doc, name: str):
    if name not in doc.layers:
        doc.layers.add(name=name)


def decorate_dxf(src: Path, dst: Path, discipline: str, systems: list[str], revision: int):
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()
    prefix = PREFIX[discipline]
    note_layer = f"ENGITOOLS-{prefix}-NOTES"
    ensure_layer(doc, note_layer)
    for system in systems:
        ensure_layer(doc, f"ENGITOOLS-{prefix}-{system.upper()}")

    try:
        ext = bbox.extents(msp, fast=True)
        if ext.has_data:
            minx, miny = ext.extmin.x, ext.extmin.y
            maxx, maxy = ext.extmax.x, ext.extmax.y
            width = max(maxx - minx, 1000.0)
            height = max(maxy - miny, 1000.0)
        else:
            minx = miny = 0.0
            maxx = maxy = 1000.0
            width = height = 1000.0
    except Exception:
        minx = miny = 0.0
        maxx = maxy = 1000.0
        width = height = 1000.0

    gap = max(width * 0.08, 500.0)
    x0 = maxx + gap
    y0 = maxy
    text_h = max(min(width, height) * 0.018, 60.0)
    title = f"ENGITOOLS {discipline.upper()} DRAFT - REV {revision}"
    warning = "PRELIMINARY AUTOMATED DRAFT - NOT FOR CONSTRUCTION"
    msp.add_text(title, dxfattribs={"layer": note_layer, "height": text_h}).set_placement((x0, y0))
    msp.add_text(warning, dxfattribs={"layer": note_layer, "height": text_h * 0.8}).set_placement((x0, y0 - text_h * 2.0))
    msp.add_text("SYSTEM LAYERS:", dxfattribs={"layer": note_layer, "height": text_h * 0.72}).set_placement((x0, y0 - text_h * 4.0))
    yy = y0 - text_h * 5.4
    for system in systems:
        msp.add_text(f"{prefix}-{system}", dxfattribs={"layer": note_layer, "height": text_h * 0.62}).set_placement((x0, yy))
        yy -= text_h * 1.1

    # Lightweight legend strokes placed outside the architectural plan; no fabricated routing.
    legend_x2 = x0 + max(width * 0.12, 900.0)
    yline = yy - text_h
    for system in systems[:8]:
        layer = f"ENGITOOLS-{prefix}-{system.upper()}"
        msp.add_line((x0, yline), (legend_x2, yline), dxfattribs={"layer": layer})
        yline -= text_h * 0.9

    doc.saveas(dst)


def render_pdf(dxf_path: Path, pdf_path: Path, discipline: str):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([0.03, 0.06, 0.94, 0.88])
    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")
    try:
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp, finalize=True)
    except Exception:
        ax.text(0.5, 0.5, "DXF preview rendering unavailable", ha="center", va="center", transform=ax.transAxes)
    fig.suptitle(f"EngiTools {discipline.title()} — PRELIMINARY AUTOMATED DRAFT — NOT FOR CONSTRUCTION", fontsize=10)
    fig.savefig(pdf_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def merge_pdfs(paths: list[Path], out_path: Path):
    writer = PdfWriter()
    for p in paths:
        reader = PdfReader(str(p))
        for page in reader.pages:
            writer.add_page(page)
    with out_path.open("wb") as f:
        writer.write(f)


def zip_outputs(paths: list[Path]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    return bio.getvalue()


@app.post("/design")
def design(req: DesignRequest):
    discipline = req.discipline.strip().lower()
    if discipline not in SYSTEMS:
        raise HTTPException(400, "discipline must be mechanical or electrical")
    scope = req.output_scope or {}
    if scope.get("discipline") != discipline:
        raise HTTPException(400, "output_scope discipline mismatch")
    if scope.get("only_this_discipline") is not True or scope.get("include_other_disciplines") is not False:
        raise HTTPException(400, "discipline isolation flags are required")

    requested = scope.get("systems") or []
    allowed = SYSTEMS[discipline]
    if any(s not in allowed for s in requested):
        raise HTTPException(400, "output_scope contains systems from another or unsupported discipline")
    systems = requested or allowed

    with tempfile.TemporaryDirectory(prefix="engitools-cad-") as td:
        root = Path(td)
        inp = root / "input"; inp.mkdir()
        out = root / "output"; out.mkdir()
        try:
            sources = safe_extract_b64(req.architecture_archive_b64, inp)
        except Exception as exc:
            raise HTTPException(400, str(exc))

        generated = []
        page_pdfs = []
        for idx, src in enumerate(sources, start=1):
            safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)[:80] or f"plan_{idx}"
            dxf_out = out / f"{idx:02d}_{safe_stem}_{discipline}.dxf"
            decorate_dxf(src, dxf_out, discipline, systems, req.revision)
            generated.append(dxf_out)
            page = out / f"{idx:02d}_{discipline}.pdf"
            render_pdf(dxf_out, page, discipline)
            page_pdfs.append(page)

        merged = out / f"EngiTools_{req.project_id}_{discipline}_R{req.revision}.pdf"
        merge_pdfs(page_pdfs, merged)
        package = zip_outputs(generated)
        return {
            "ok": True,
            "project_id": req.project_id,
            "discipline": discipline,
            "engine_version": "0.1.0",
            "preliminary": True,
            "not_for_construction": True,
            "systems": systems,
            "generated_files": [p.name for p in generated],
            "pdf_base64": base64.b64encode(merged.read_bytes()).decode("ascii"),
            "zip_base64": base64.b64encode(package).decode("ascii"),
        }
