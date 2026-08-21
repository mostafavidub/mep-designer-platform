import base64
import io
import math
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

app = FastAPI(title="EngiTools CAD Designer", version="0.2.0")

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
OUTPUT_ROOT = Path(os.getenv("CAD_OUTPUT_DIR", "/data/cad-engine"))
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

ROOM_RULES = {
    "kitchen": ["kitchen", "آشپزخانه", "اشپزخانه"],
    "bath": ["bath", "bathroom", "حمام"],
    "toilet": ["toilet", "wc", "w.c", "سرویس", "توالت"],
    "bedroom": ["bed", "bedroom", "خواب", "اتاق خواب"],
    "living": ["living", "lounge", "پذیرایی", "نشیمن", "هال"],
    "parking": ["parking", "پارکینگ"],
    "corridor": ["corridor", "hall", "راهرو", "لابی"],
    "shaft": ["shaft", "duct", "شفت", "داکت"],
    "roof": ["roof", "بام"],
    "stair": ["stair", "staircase", "پله", "راه پله"],
}

class DesignRequest(BaseModel):
    project_id: str
    discipline: str
    architecture_dir: str | None = None
    architecture_archive_b64: str | None = None
    answers: dict = Field(default_factory=dict)
    plan_analysis: dict = Field(default_factory=dict)
    output_scope: dict
    revision: int = 1
    revision_instructions: str = ""

@app.get("/health")
def health():
    return {"ok": True, "service": "cad-designer", "version": "0.2.0", "mode": "rule-driven-preliminary"}

def safe_extract_b64(payload: str, target: Path) -> list[Path]:
    raw = base64.b64decode(payload, validate=True)
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

def source_files(req: DesignRequest, temp_input: Path) -> list[Path]:
    if req.architecture_archive_b64:
        return safe_extract_b64(req.architecture_archive_b64, temp_input)
    if req.architecture_dir:
        root = Path(req.architecture_dir).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("architecture_dir does not exist")
        files = [p for p in sorted(root.rglob("*.dxf")) if p.is_file() and "__MACOSX" not in p.parts and not p.name.startswith(".") and not p.name.startswith("._")]
        if not files:
            raise ValueError("no DXF files found in architecture_dir")
        return files
    raise ValueError("architecture_dir or architecture_archive_b64 is required")

def ensure_layer(doc, name: str):
    if name not in doc.layers:
        doc.layers.add(name=name)

def text_value(entity):
    try:
        if entity.dxftype() == "TEXT":
            return entity.dxf.text or ""
        if entity.dxftype() == "MTEXT":
            return entity.plain_text() or ""
    except Exception:
        return ""
    return ""

def text_point(entity):
    try:
        if entity.dxftype() == "TEXT":
            p = entity.dxf.insert
        else:
            p = entity.dxf.insert
        return float(p.x), float(p.y)
    except Exception:
        return None

def classify_room(text: str):
    s = (text or "").strip().lower()
    for room, keys in ROOM_RULES.items():
        if any(k.lower() in s for k in keys):
            return room
    return None

def detect_room_labels(msp):
    labels = []
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        txt = text_value(e)
        room = classify_room(txt)
        pt = text_point(e)
        if room and pt:
            labels.append({"room": room, "text": txt[:120], "point": pt})
    # de-duplicate labels that are almost coincident
    dedup = []
    for item in labels:
        if not any(item["room"] == x["room"] and math.dist(item["point"], x["point"]) < 80 for x in dedup):
            dedup.append(item)
    return dedup

def extents(msp):
    try:
        ext = bbox.extents(msp, fast=True)
        if ext.has_data:
            minx, miny = ext.extmin.x, ext.extmin.y
            maxx, maxy = ext.extmax.x, ext.extmax.y
            return minx, miny, maxx, maxy
    except Exception:
        pass
    return 0.0, 0.0, 10000.0, 10000.0

def add_circle_symbol(msp, point, radius, layer, tag=None, text_h=120):
    x, y = point
    msp.add_circle((x, y), radius=radius, dxfattribs={"layer": layer})
    if tag:
        msp.add_text(tag, dxfattribs={"layer": layer, "height": text_h}).set_placement((x + radius * 1.2, y + radius * 0.2))

def add_cross_symbol(msp, point, size, layer, tag=None, text_h=120):
    x, y = point
    msp.add_line((x-size, y), (x+size, y), dxfattribs={"layer": layer})
    msp.add_line((x, y-size), (x, y+size), dxfattribs={"layer": layer})
    if tag:
        msp.add_text(tag, dxfattribs={"layer": layer, "height": text_h}).set_placement((x + size * 1.3, y + size * 0.3))

def add_box_symbol(msp, point, size, layer, tag=None, text_h=120):
    x, y = point
    pts = [(x-size,y-size),(x+size,y-size),(x+size,y+size),(x-size,y+size),(x-size,y-size)]
    msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
    if tag:
        msp.add_text(tag, dxfattribs={"layer": layer, "height": text_h}).set_placement((x + size * 1.3, y + size * 0.3))

def nearest_point(origin, candidates):
    if not candidates:
        return None
    return min(candidates, key=lambda p: math.dist(origin, p))

def electrical_design(msp, rooms, systems, scale):
    stats = {"lighting":0,"power":0,"dedicated_loads":0,"fire_alarm":0,"elv":0,"panels":0}
    r = max(scale * 0.004, 90.0)
    text_h = max(scale * 0.0045, 90.0)
    shaft_pts = [x["point"] for x in rooms if x["room"] == "shaft"]
    anchor = shaft_pts[0] if shaft_pts else None

    for item in rooms:
        room, (x,y) = item["room"], item["point"]
        if "lighting" in systems and room not in ("shaft",):
            add_cross_symbol(msp, (x,y), r, "ENGITOOLS-E-LIGHTING", "L", text_h)
            stats["lighting"] += 1
        if "power" in systems and room in ("bedroom","living","kitchen","parking","corridor"):
            offsets = [(-2.2*r,-1.7*r),(2.2*r,-1.7*r)] if room in ("bedroom","living","kitchen") else [(2.0*r,-1.5*r)]
            for dx,dy in offsets:
                add_circle_symbol(msp, (x+dx,y+dy), r*0.55, "ENGITOOLS-E-POWER", "P", text_h*0.85)
                stats["power"] += 1
        if "dedicated_loads" in systems and room == "kitchen":
            for i, tag in enumerate(("REF","WM","DW")):
                add_box_symbol(msp, (x+(i-1)*2.4*r,y+2.4*r), r*0.65, "ENGITOOLS-E-DEDICATED_LOADS", tag, text_h*0.75)
                stats["dedicated_loads"] += 1
        if "fire_alarm" in systems and room in ("bedroom","living","corridor","stair","parking"):
            add_circle_symbol(msp, (x,y+2.2*r), r*0.65, "ENGITOOLS-E-FIRE_ALARM", "SD", text_h*0.8)
            stats["fire_alarm"] += 1
        if "elv" in systems and room in ("living","bedroom"):
            add_box_symbol(msp, (x-2.3*r,y+2.0*r), r*0.55, "ENGITOOLS-E-ELV", "DATA", text_h*0.7)
            stats["elv"] += 1

    if rooms and "panels" in systems:
        candidate = anchor or rooms[0]["point"]
        add_box_symbol(msp, (candidate[0]+4*r,candidate[1]), r*0.9, "ENGITOOLS-E-PANELS", "DB", text_h)
        stats["panels"] += 1

    # preliminary home-runs from room lighting to nearest shaft/panel anchor; no cable sizing inferred
    if anchor and "lighting" in systems:
        for item in rooms:
            if item["room"] not in ("shaft",):
                p = item["point"]
                msp.add_line(p, anchor, dxfattribs={"layer":"ENGITOOLS-E-LIGHTING"})
    return stats

def mechanical_design(msp, rooms, systems, scale):
    stats = {"cold_water":0,"hot_water":0,"sanitary":0,"vent":0,"gas":0,"cooling":0,"condensate":0,"exhaust_ventilation":0}
    r = max(scale * 0.004, 90.0)
    text_h = max(scale * 0.0045, 90.0)
    shaft_pts = [x["point"] for x in rooms if x["room"] == "shaft"]

    service_points = []
    for item in rooms:
        room, (x,y) = item["room"], item["point"]
        if room in ("kitchen","bath","toilet"):
            service_points.append((x,y))
            if "cold_water" in systems:
                add_circle_symbol(msp,(x-1.7*r,y),r*0.5,"ENGITOOLS-M-COLD_WATER","CW",text_h*0.75); stats["cold_water"]+=1
            if "hot_water" in systems and room in ("kitchen","bath"):
                add_circle_symbol(msp,(x,y),r*0.5,"ENGITOOLS-M-HOT_WATER","HW",text_h*0.75); stats["hot_water"]+=1
            if "sanitary" in systems:
                add_circle_symbol(msp,(x+1.7*r,y),r*0.55,"ENGITOOLS-M-SANITARY","S",text_h*0.75); stats["sanitary"]+=1
            if "vent" in systems and room in ("bath","toilet"):
                add_cross_symbol(msp,(x+1.7*r,y+1.8*r),r*0.55,"ENGITOOLS-M-VENT","V",text_h*0.75); stats["vent"]+=1
            if "exhaust_ventilation" in systems and room in ("bath","toilet"):
                add_box_symbol(msp,(x-1.7*r,y+1.8*r),r*0.55,"ENGITOOLS-M-EXHAUST_VENTILATION","EF",text_h*0.75); stats["exhaust_ventilation"]+=1
        if room == "kitchen" and "gas" in systems:
            add_box_symbol(msp,(x,y+2.1*r),r*0.55,"ENGITOOLS-M-GAS","G",text_h*0.8); stats["gas"]+=1
        if room in ("bedroom","living") and "cooling" in systems:
            add_box_symbol(msp,(x,y+2.0*r),r*0.8,"ENGITOOLS-M-COOLING","AC",text_h*0.8); stats["cooling"]+=1
            if "condensate" in systems:
                add_circle_symbol(msp,(x+1.8*r,y+2.0*r),r*0.4,"ENGITOOLS-M-CONDENSATE","C",text_h*0.7); stats["condensate"]+=1

    # schematic preliminary service routing to nearest identified shaft only
    if shaft_pts:
        for p in service_points:
            shaft = nearest_point(p, shaft_pts)
            if shaft:
                if "sanitary" in systems:
                    msp.add_line(p, shaft, dxfattribs={"layer":"ENGITOOLS-M-SANITARY"})
                if "cold_water" in systems:
                    msp.add_line((p[0]-1.7*r,p[1]), shaft, dxfattribs={"layer":"ENGITOOLS-M-COLD_WATER"})
        if "mechanical_risers" in systems:
            for p in shaft_pts:
                add_box_symbol(msp,p,r*0.9,"ENGITOOLS-M-MECHANICAL_RISERS","R",text_h)
    return stats

def design_dxf(src: Path, dst: Path, discipline: str, systems: list[str], revision: int):
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()
    prefix = PREFIX[discipline]
    for system in systems:
        ensure_layer(doc, f"ENGITOOLS-{prefix}-{system.upper()}")
    note_layer = f"ENGITOOLS-{prefix}-NOTES"
    ensure_layer(doc, note_layer)

    minx,miny,maxx,maxy = extents(msp)
    width, height = max(maxx-minx,1000.0), max(maxy-miny,1000.0)
    scale = max(width,height)
    rooms = detect_room_labels(msp)
    stats = electrical_design(msp,rooms,systems,scale) if discipline == "electrical" else mechanical_design(msp,rooms,systems,scale)

    # Rulebook presentation separation: notes start outside plan region with conservative 5%+ gap.
    gap = max(width * 0.08, 500.0)
    x0, y0 = maxx + gap, maxy
    text_h = max(min(width,height)*0.018,60.0)
    lines = [
        f"ENGITOOLS {discipline.upper()} RULE-DRIVEN PRELIMINARY DESIGN - REV {revision}",
        "AUTOMATED PRELIMINARY DESIGN - PROFESSIONAL ENGINEERING REVIEW REQUIRED",
        f"DETECTED ROOM LABELS: {len(rooms)}",
        "NO FINAL SIZING / BREAKER / CABLE / PIPE DIAMETER / SLOPE / CAPACITY IS ASSERTED",
    ]
    yy = y0
    for line in lines:
        msp.add_text(line,dxfattribs={"layer":note_layer,"height":text_h*0.72}).set_placement((x0,yy)); yy -= text_h*1.2
    for key,val in stats.items():
        if val:
            msp.add_text(f"{key}: {val}",dxfattribs={"layer":note_layer,"height":text_h*0.62}).set_placement((x0,yy)); yy -= text_h
    if not rooms:
        msp.add_text("WARNING: NO RECOGNIZED ROOM LABELS; ONLY LAYERS/NOTES WERE GENERATED",dxfattribs={"layer":note_layer,"height":text_h*0.62}).set_placement((x0,yy))

    doc.saveas(dst)
    return {"room_labels":len(rooms),"placements":stats}

def render_pdf(dxf_path: Path, pdf_path: Path, discipline: str):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fig = plt.figure(figsize=(11.69,8.27))
    ax = fig.add_axes([0.03,0.06,0.94,0.88])
    ax.set_aspect("equal",adjustable="datalim"); ax.axis("off")
    try:
        ctx = RenderContext(doc); out = MatplotlibBackend(ax); Frontend(ctx,out).draw_layout(msp,finalize=True)
    except Exception:
        ax.text(0.5,0.5,"DXF preview rendering unavailable",ha="center",va="center",transform=ax.transAxes)
    fig.suptitle(f"EngiTools {discipline.title()} - RULE-DRIVEN PRELIMINARY DESIGN - ENGINEERING REVIEW REQUIRED",fontsize=10)
    fig.savefig(pdf_path,format="pdf",bbox_inches="tight"); plt.close(fig)

def merge_pdfs(paths: list[Path], out_path: Path):
    writer = PdfWriter()
    for p in paths:
        for page in PdfReader(str(p)).pages:
            writer.add_page(page)
    with out_path.open("wb") as f:
        writer.write(f)

def zip_outputs(paths: list[Path], out_path: Path):
    with zipfile.ZipFile(out_path,"w",zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p,arcname=p.name)

@app.post("/design")
def design(req: DesignRequest):
    discipline = req.discipline.strip().lower()
    if discipline not in SYSTEMS:
        raise HTTPException(400,"discipline must be mechanical or electrical")
    scope = req.output_scope or {}
    if scope.get("discipline") != discipline:
        raise HTTPException(400,"output_scope discipline mismatch")
    if scope.get("only_this_discipline") is not True or scope.get("include_other_disciplines") is not False:
        raise HTTPException(400,"discipline isolation flags are required")
    requested = scope.get("systems") or []
    allowed = SYSTEMS[discipline]
    if any(s not in allowed for s in requested):
        raise HTTPException(400,"output_scope contains unsupported or cross-discipline systems")
    systems = requested or allowed

    project_out = OUTPUT_ROOT / str(req.project_id) / f"R{req.revision:03d}" / discipline
    shutil.rmtree(project_out,ignore_errors=True); project_out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engitools-cad-") as td:
        temp_input = Path(td)/"input"; temp_input.mkdir()
        try:
            sources = source_files(req,temp_input)
        except Exception as exc:
            raise HTTPException(400,str(exc))
        generated,page_pdfs,reports = [],[],[]
        for idx,src in enumerate(sources,start=1):
            safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)[:80] or f"plan_{idx}"
            dxf_out = project_out/f"{idx:02d}_{safe_stem}_{discipline}.dxf"
            report = design_dxf(src,dxf_out,discipline,systems,req.revision)
            reports.append({"source":src.name,**report}); generated.append(dxf_out)
            page = project_out/f"{idx:02d}_{discipline}.pdf"; render_pdf(dxf_out,page,discipline); page_pdfs.append(page)
        merged = project_out/f"EngiTools_{req.project_id}_{discipline}_R{req.revision}.pdf"; merge_pdfs(page_pdfs,merged)
        package = project_out/f"EngiTools_{req.project_id}_{discipline}_R{req.revision}_DXF.zip"; zip_outputs(generated,package)
        return {
            "ok":True,"project_id":req.project_id,"discipline":discipline,"engine_version":"0.2.0",
            "mode":"rule-driven-preliminary","preliminary":True,"requires_professional_review":True,
            "systems":systems,"design_reports":reports,"generated_files":[p.name for p in generated],
            "pdf_path":str(merged),"zip_path":str(package),
            "pdf_base64":base64.b64encode(merged.read_bytes()).decode("ascii"),
            "zip_base64":base64.b64encode(package.read_bytes()).decode("ascii"),
        }
