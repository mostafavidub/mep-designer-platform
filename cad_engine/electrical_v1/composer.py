from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ezdxf

from .documentation import SYMBOL_LIBRARY
from .models import ArchitecturalModel, SheetManifestItem


LAYER_STYLES = {
    "ENGITOOLS-E-DOC": (7, 25),
    "ENGITOOLS-E-ARCH-UNDERLAY": (8, 9),
    "ENGITOOLS-E-LIGHTING": (2, 25),
    "ENGITOOLS-E-LIGHTING-CONTROL": (2, 18),
    "ENGITOOLS-E-POWER": (1, 30),
    "ENGITOOLS-E-DEDICATED": (6, 35),
    "ENGITOOLS-E-WIRE": (7, 18),
    "ENGITOOLS-E-FIRE-ALARM": (1, 25),
    "ENGITOOLS-E-LOW-CURRENT": (4, 20),
    "ENGITOOLS-E-GROUNDING": (3, 35),
    "ENGITOOLS-E-BONDING": (3, 35),
    "ENGITOOLS-E-ANNOTATION": (7, 18),
    "ENGITOOLS-E-PANEL_SCHEDULE": (7, 18),
    "ENGITOOLS-E-SINGLE_LINE": (5, 30),
    "ENGITOOLS-E-RISER": (5, 30),
    "ENGITOOLS-E-CALCULATIONS": (7, 18),
    "ENGITOOLS-E-DETAIL": (7, 25),
}


def _ensure_layers(doc):
    for name,(color,lw) in LAYER_STYLES.items():
        if name not in doc.layers: doc.layers.add(name=name)
        layer=doc.layers.get(name); layer.dxf.color=color; layer.dxf.lineweight=lw


def _add_symbol_blocks(doc):
    for equipment_type,spec in SYMBOL_LIBRARY.items():
        name="ET_"+spec["symbol_id"].replace("-","_")
        if name in doc.blocks: continue
        b=doc.blocks.new(name=name)
        for primitive in spec["geometry"]:
            kind=primitive[0]
            if kind=="circle": b.add_circle((primitive[1],primitive[2]),primitive[3])
            elif kind=="line": b.add_line((primitive[1],primitive[2]),(primitive[3],primitive[4]))
            elif kind=="square":
                _,x,y,size=primitive; h=size/2; b.add_lwpolyline([(x-h,y-h),(x+h,y-h),(x+h,y+h),(x-h,y+h),(x-h,y-h)])
            elif kind=="rect":
                _,x1,y1,x2,y2=primitive; b.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2),(x1,y1)])
            elif kind=="triangle":
                _,x,y,size=primitive; h=size/2; b.add_lwpolyline([(x,y+h),(x+h,y-h),(x-h,y-h),(x,y+h)])
            elif kind=="text":
                _,txt,x,y=primitive; b.add_text(str(txt),dxfattribs={"height":.08}).set_placement((x-.03,y-.03))
            elif kind=="semicircle":
                _,x,y,r=primitive; b.add_arc((x,y),r,0,180)


def _frame(architecture: ArchitecturalModel, frame_id: str):
    return next((f for f in architecture.frames if f.id==frame_id),None)


def _fit_transform(bounds, paper, margins):
    pw,ph=paper; left,bottom,right,top=margins; x1,y1,x2,y2=bounds
    aw=max(pw-left-right,1e-6); ah=max(ph-bottom-top,1e-6); w=max(x2-x1,1e-9); h=max(y2-y1,1e-9)
    scale=min(aw/w,ah/h); ox=left+(aw-w*scale)/2-x1*scale; oy=bottom+(ah-h*scale)/2-y1*scale
    return lambda p:(p[0]*scale+ox,p[1]*scale+oy),scale


def _draw_title(layout: Any, sheet: SheetManifestItem, paper, status: str, project_name: str):
    w,h=paper; layer="ENGITOOLS-E-DOC"
    layout.add_lwpolyline([(5,5),(w-5,5),(w-5,h-5),(5,h-5),(5,5)],dxfattribs={"layer":layer})
    y=12
    layout.add_line((5,y),(w-5,y),dxfattribs={"layer":layer})
    layout.add_text(sheet.sheet_id,dxfattribs={"layer":layer,"height":3.0}).set_placement((8,7))
    layout.add_text(sheet.purpose[:90],dxfattribs={"layer":layer,"height":2.2}).set_placement((35,7))
    layout.add_text(project_name[:45],dxfattribs={"layer":layer,"height":2.0}).set_placement((w-125,7))
    layout.add_text(status,dxfattribs={"layer":layer,"height":2.0}).set_placement((w-40,7))


def _draw_architecture(layout, architecture, frame_id, transform):
    count=0
    for entity in architecture.entities:
        if entity.frame_id!=frame_id: continue
        if entity.kind=="line_candidate":
            a=transform(tuple(entity.geometry["a"])); b=transform(tuple(entity.geometry["b"])); layout.add_line(a,b,dxfattribs={"layer":"ENGITOOLS-E-ARCH-UNDERLAY"}); count+=1
    for room in architecture.rooms:
        if room.frame_id!=frame_id or not room.polygon: continue
        pts=[transform(tuple(p)) for p in room.polygon]; pts.append(pts[0]); layout.add_lwpolyline(pts,dxfattribs={"layer":"ENGITOOLS-E-ARCH-UNDERLAY"}); count+=1
        if room.label_point:
            p=transform(room.label_point); layout.add_text(str(room.label or room.room_type.value),dxfattribs={"layer":"ENGITOOLS-E-ARCH-UNDERLAY","height":1.4}).set_placement(p)
    return count


def _family_accepts(sheet_family, equipment_type, system):
    if sheet_family=="LIGHTING": return system in {"LIGHTING","EMERGENCY_LIGHTING"} or equipment_type=="LIGHT_SWITCH"
    if sheet_family=="POWER": return system in {"GENERAL_RECEPTACLES","DEDICATED_POWER","KITCHEN_POWER","HVAC_POWER","ELEVATOR_POWER","PUMP_POWER"}
    if sheet_family=="FIRE_ALARM": return system=="FIRE_ALARM"
    if sheet_family=="LOW_CURRENT": return system in {"TELECOM","DATA","TV","INTERCOM","CCTV","ACCESS_CONTROL"}
    if sheet_family=="GROUNDING": return system in {"GROUNDING","BONDING","LIGHTNING_PROTECTION"}
    return False


def _equipment_layer(eq_type, system):
    if system in {"LIGHTING","EMERGENCY_LIGHTING"}: return "ENGITOOLS-E-LIGHTING"
    if system in {"GENERAL_RECEPTACLES"}: return "ENGITOOLS-E-POWER"
    if system in {"DEDICATED_POWER","KITCHEN_POWER","HVAC_POWER","ELEVATOR_POWER","PUMP_POWER"}: return "ENGITOOLS-E-DEDICATED"
    if system=="FIRE_ALARM": return "ENGITOOLS-E-FIRE-ALARM"
    if system in {"TELECOM","DATA","TV","INTERCOM","CCTV","ACCESS_CONTROL"}: return "ENGITOOLS-E-LOW-CURRENT"
    return "ENGITOOLS-E-ANNOTATION"


def compose_drawing_set(path: str|Path, architecture: ArchitecturalModel, manifest: List[SheetManifestItem],
                        requirements, placements, routing, schedules, single_line, riser,
                        legend, notes, details, links, calculations,
                        project_name: str="EngiTools Electrical Project",
                        paper: Tuple[float,float]=(420.0,297.0),
                        drawing_status: str="PRELIMINARY") -> Dict[str,Any]:
    """Compose each sheet as independent Paper Space geometry, not viewports onto one shared design model."""
    doc=ezdxf.new("R2013"); doc.header["$INSUNITS"]=4; _ensure_layers(doc); _add_symbol_blocks(doc)
    # Modelspace is intentionally not the shared drawing canvas. It only holds file-manifest metadata.
    msp=doc.modelspace(); msp.add_text("ENGITOOLS ELECTRICAL DRAWING SET - PAPER SPACE OWNED GEOMETRY",dxfattribs={"layer":"ENGITOOLS-E-DOC","height":2.5}).set_placement((0,0))
    req_by_id={r.id:r for r in requirements}; placement_by_eq={p.equipment_id:p for p in placements}
    load_by_id={l.id:l for l in (calculations.get("topology",{}).get("loads") or [])} if isinstance(calculations,dict) else {}
    route_map={r["circuit_id"]:r for r in routing.get("routes") or []}
    signatures={}
    default=doc.layouts.get("Layout1"); doc.layouts.delete(default.name)
    for sheet in manifest:
        layout=doc.layouts.new(sheet.sheet_id); layout.page_setup(size=paper,margins=(0,0,0,0),units="mm")
        _draw_title(layout,sheet,paper,drawing_status,project_name); sig={"title_block":1,"architectural_underlay":0}
        transform=lambda p:p; scale=1.0
        frame_id=sheet.source_frame_ids[0] if sheet.source_frame_ids else None
        if frame_id:
            f=_frame(architecture,frame_id)
            if f:
                transform,scale=_fit_transform(f.bounds,paper,(12,18,12,12)); sig["architectural_underlay"]=_draw_architecture(layout,architecture,frame_id,transform)
        if sheet.family in {"LIGHTING","POWER","FIRE_ALARM","LOW_CURRENT","GROUNDING"}:
            for p in placements:
                req=req_by_id.get(p.requirement_id)
                if not req or p.frame_id not in sheet.source_frame_ids or not _family_accepts(sheet.family,req.equipment_type,req.system) or not p.point: continue
                spec=SYMBOL_LIBRARY.get(req.equipment_type)
                if spec:
                    name="ET_"+spec["symbol_id"].replace("-","_"); q=transform(p.point); layout.add_blockref(name,q,dxfattribs={"layer":_equipment_layer(req.equipment_type,req.system),"rotation":p.rotation_deg or 0})
                    layout.add_text(p.equipment_id,dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION","height":1.2}).set_placement((q[0]+1.5,q[1]+1.0))
                    if sheet.family=="LIGHTING": sig["lighting_fixtures" if req.equipment_type=="LIGHT_FIXTURE" else "switches"]=sig.get("lighting_fixtures" if req.equipment_type=="LIGHT_FIXTURE" else "switches",0)+1
                    elif sheet.family=="POWER": sig["power_loads"]=sig.get("power_loads",0)+1
                    elif sheet.family=="FIRE_ALARM": sig["fire_devices"]=sig.get("fire_devices",0)+1
                    elif sheet.family=="LOW_CURRENT": sig["low_current_devices"]=sig.get("low_current_devices",0)+1
            for route in routing.get("routes") or []:
                if route.get("frame_id") not in sheet.source_frame_ids: continue
                circuit=next((c for c in calculations.get("topology",{}).get("circuits",[]) if c.id==route["circuit_id"]),None) if isinstance(calculations,dict) else None
                if circuit and not _family_accepts(sheet.family,"",circuit.system): continue
                for part in route["parts"]:
                    pts=[transform(tuple(x)) for x in part["points"]]; layout.add_lwpolyline(pts,dxfattribs={"layer":"ENGITOOLS-E-WIRE"})
                    if circuit:
                        mid=pts[len(pts)//2]; label=f"{circuit.id} / {circuit.panel_id}"
                        if circuit.cable.value: label+=f" / {circuit.cable.value}"
                        layout.add_text(label,dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION","height":1.1}).set_placement((mid[0]+1,mid[1]+1))
                        key="lighting_circuits" if sheet.family=="LIGHTING" else "power_circuits"; sig[key]=sig.get(key,0)+1
            if legend:
                y=paper[1]-18; layout.add_text("LEGEND",dxfattribs={"layer":"ENGITOOLS-E-DOC","height":1.8}).set_placement((paper[0]-65,y)); y-=4
                for row in legend[:14]: layout.add_text(f"{row['legend_id']}  {row['equipment_type']}",dxfattribs={"layer":"ENGITOOLS-E-DOC","height":1.0}).set_placement((paper[0]-65,y)); y-=3
                sig["legend_entries"]=len(legend)
        elif sheet.family=="PANEL_SCHEDULE":
            y=paper[1]-20; count=0
            for panel_id,rows in schedules.items():
                layout.add_text(f"PANEL {panel_id}",dxfattribs={"layer":"ENGITOOLS-E-PANEL_SCHEDULE","height":2}).set_placement((15,y)); y-=4
                for row in rows:
                    text=f"{row['circuit_no']} | {row['description']} | {row['phase']} | {row['load_w']} W | {row['breaker']} | {row['cable']}"
                    layout.add_text(text,dxfattribs={"layer":"ENGITOOLS-E-PANEL_SCHEDULE","height":1.1}).set_placement((15,y)); y-=3; count+=1
            sig["panel_schedules"]=1 if schedules else 0; sig["schedule_rows"]=count
        elif sheet.family=="SINGLE_LINE":
            nodes=single_line.get("nodes") or []; edges=single_line.get("edges") or []; positions={}
            for i,node in enumerate(nodes):
                p=(25+(i%6)*60,paper[1]-35-(i//6)*45); positions[node["id"]]=p; layout.add_circle(p,5,dxfattribs={"layer":"ENGITOOLS-E-SINGLE_LINE"}); layout.add_text(node["id"],dxfattribs={"layer":"ENGITOOLS-E-SINGLE_LINE","height":1.2}).set_placement((p[0]-4,p[1]-1))
            for e in edges:
                if e["from"] in positions and e["to"] in positions: layout.add_line(positions[e["from"]],positions[e["to"]],dxfattribs={"layer":"ENGITOOLS-E-SINGLE_LINE"})
            sig["single_line_nodes"]=len(nodes); sig["single_line_edges"]=len(edges)
        elif sheet.family=="RISER":
            x=paper[0]/2; transitions=riser.get("transitions") or []
            for i,t in enumerate(transitions):
                y1=35+i*35; y2=y1+25; layout.add_line((x,y1),(x,y2),dxfattribs={"layer":"ENGITOOLS-E-RISER"}); layout.add_text(f"{t['from_level']} -> {t['to_level']}",dxfattribs={"layer":"ENGITOOLS-E-RISER","height":1.4}).set_placement((x+5,y1+10))
            sig["riser_transitions"]=len(transitions)
        elif sheet.family=="CALCULATIONS":
            y=paper[1]-20; layout.add_text("ELECTRICAL CALCULATIONS / QA",dxfattribs={"layer":"ENGITOOLS-E-CALCULATIONS","height":2}).set_placement((15,y)); y-=5
            for key,value in calculations.items():
                if key=="topology": continue
                layout.add_text(f"{key}: {str(value)[:180]}",dxfattribs={"layer":"ENGITOOLS-E-CALCULATIONS","height":1.0}).set_placement((15,y)); y-=3
            sig["calculation_tables"]=1
        signatures[sheet.sheet_id]={"family":sheet.family,"signature":sig,"scale_factor_to_paper":scale}
    doc.saveas(str(path))
    return {"path":str(path),"sheet_count":len(manifest),"signatures":signatures,"paper_mm":paper,"geometry_ownership":"PAPER_SPACE_PER_SHEET"}
