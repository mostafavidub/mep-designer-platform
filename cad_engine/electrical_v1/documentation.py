from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .models import ElectricalDesignBasis, EngineeringStatus, EquipmentPlacement, EquipmentRequirement, SystemRequirement


SYMBOL_LIBRARY = {
    "LIGHT_FIXTURE": {"symbol_id":"EL-LIGHT-01","legend_id":"LGT","host":"ceiling","ports":["power"],"geometry":[("circle",0,0,.12),("line",-.18,0,.18,0),("line",0,-.18,0,.18)]},
    "DOWNLIGHT": {"symbol_id":"EL-LIGHT-02","legend_id":"DL","host":"ceiling","ports":["power"],"geometry":[("circle",0,0,.12)]},
    "WALL_LIGHT": {"symbol_id":"EL-LIGHT-03","legend_id":"WL","host":"wall","ports":["power"],"geometry":[("semicircle",0,0,.12)]},
    "LIGHT_SWITCH": {"symbol_id":"EL-SW-01","legend_id":"S1","host":"wall","ports":["control"],"geometry":[("circle",0,0,.07),("line",.07,0,.22,.1)]},
    "SWITCH_2WAY": {"symbol_id":"EL-SW-02","legend_id":"S2","host":"wall","ports":["control"],"geometry":[("circle",0,0,.07),("line",.07,0,.22,.1),("line",.07,0,.22,-.1)]},
    "GENERAL_SOCKET": {"symbol_id":"EL-PWR-01","legend_id":"SO","host":"wall","ports":["power"],"geometry":[("circle",0,0,.09),("line",-.055,-.03,.055,-.03),("line",-.055,.03,.055,.03)]},
    "DEDICATED_APPLIANCE_OUTLET": {"symbol_id":"EL-PWR-02","legend_id":"DO","host":"wall","ports":["power"],"geometry":[("square",0,0,.18),("text","D",0,0)]},
    "AC_ISOLATOR": {"symbol_id":"EL-PWR-03","legend_id":"ISO","host":"wall","ports":["power_in","power_out"],"geometry":[("square",0,0,.18),("text","I",0,0)]},
    "PANELBOARD": {"symbol_id":"EL-PNL-01","legend_id":"DB","host":"wall","ports":["feeder","branches"],"geometry":[("rect",-.2,-.3,.2,.3),("line",-.15,.1,.15,.1),("line",-.15,0,.15,0),("line",-.15,-.1,.15,-.1)]},
    "METER": {"symbol_id":"EL-MTR-01","legend_id":"M","host":"wall","ports":["service","feeder"],"geometry":[("circle",0,0,.14),("text","M",0,0)]},
    "SMOKE_DETECTOR": {"symbol_id":"EL-FA-01","legend_id":"SD","host":"ceiling","ports":["fire_loop"],"geometry":[("circle",0,0,.11),("text","SD",0,0)]},
    "HEAT_DETECTOR": {"symbol_id":"EL-FA-02","legend_id":"HD","host":"ceiling","ports":["fire_loop"],"geometry":[("circle",0,0,.11),("text","HD",0,0)]},
    "MCP": {"symbol_id":"EL-FA-03","legend_id":"MCP","host":"wall","ports":["fire_loop"],"geometry":[("square",0,0,.17),("text","M",0,0)]},
    "SOUNDER": {"symbol_id":"EL-FA-04","legend_id":"SND","host":"wall","ports":["fire_loop"],"geometry":[("triangle",0,0,.18)]},
    "EMERGENCY_LIGHT": {"symbol_id":"EL-EM-01","legend_id":"EM","host":"ceiling_or_wall","ports":["emergency_power"],"geometry":[("rect",-.18,-.08,.18,.08),("text","EM",0,0)]},
    "DATA_SOCKET": {"symbol_id":"EL-LC-01","legend_id":"DATA","host":"wall","ports":["data"],"geometry":[("square",0,0,.16),("text","D",0,0)]},
    "TV_SOCKET": {"symbol_id":"EL-LC-02","legend_id":"TV","host":"wall","ports":["tv"],"geometry":[("square",0,0,.16),("text","TV",0,0)]},
    "EARTH_ELECTRODE": {"symbol_id":"EL-GND-01","legend_id":"EARTH","host":"ground","ports":["earth"],"geometry":[("line",0,.15,0,-.04),("line",-.15,-.04,.15,-.04),("line",-.1,-.09,.1,-.09),("line",-.05,-.14,.05,-.14)]},
    "JUNCTION_BOX": {"symbol_id":"EL-JB-01","legend_id":"JB","host":"wall_or_ceiling","ports":["in","out"],"geometry":[("square",0,0,.14),("text","JB",0,0)]},
}


DETAIL_LIBRARY = {
    "D-EL-PANEL-MOUNT": {"trigger":{"equipment":["PANELBOARD"]},"parameters":["mounting_height","wall_type","clearance"],"geometry":[("wall_section",), ("panel_box",), ("dimension","mounting_height"), ("clearance_zone",)]},
    "D-EL-METER": {"trigger":{"equipment":["METER"]},"parameters":["mounting_height","service_type"],"geometry":[("wall_section",),("meter_box",),("dimension","mounting_height")]},
    "D-EL-CONDUIT-SUPPORT": {"trigger":{"systems":["FEEDERS","PANEL_DISTRIBUTION"]},"parameters":["support_spacing","conduit_type"],"geometry":[("support",),("conduit",),("dimension","support_spacing")]},
    "D-EL-WALL-PEN": {"trigger":{"systems":["FEEDERS"]},"parameters":["wall_type","fire_rating","sleeve"],"geometry":[("wall_section",),("sleeve",),("firestop",)]},
    "D-EL-EARTHING": {"trigger":{"systems":["GROUNDING"]},"parameters":["electrode_type","conductor","inspection_point"],"geometry":[("earth",),("electrode",),("connection",)]},
    "D-EL-LIGHT-MOUNT": {"trigger":{"equipment":["LIGHT_FIXTURE"]},"parameters":["ceiling_type","fixture_type"],"geometry":[("ceiling_section",),("luminaire",),("support",)]},
    "D-EL-SWITCH-OUTLET": {"trigger":{"equipment":["LIGHT_SWITCH","GENERAL_SOCKET","DEDICATED_APPLIANCE_OUTLET"]},"parameters":["mounting_height","wall_type"],"geometry":[("wall_section",),("device_box",),("dimension","mounting_height")]},
    "D-EL-FIRE-DETECTOR": {"trigger":{"equipment":["SMOKE_DETECTOR","HEAT_DETECTOR"]},"parameters":["ceiling_type","clearance_basis"],"geometry":[("ceiling_section",),("detector",),("clearance",)]},
    "D-EL-EMERGENCY": {"trigger":{"equipment":["EMERGENCY_LIGHT"]},"parameters":["mounting","supply"],"geometry":[("mounting_surface",),("emergency_light",)]},
    "D-EL-JB": {"trigger":{"equipment":["JUNCTION_BOX"]},"parameters":["box_size","access"],"geometry":[("junction_box",),("access_zone",)]},
    "D-EL-TERMINATION": {"trigger":{"systems":["FEEDERS","MAIN_SERVICE"]},"parameters":["cable","lug","protection"],"geometry":[("cable",),("lug",),("terminal",)]},
    "D-EL-ISOLATOR": {"trigger":{"equipment":["AC_ISOLATOR"]},"parameters":["rating","mounting","clearance"],"geometry":[("equipment",),("isolator",),("connection",)]},
}


def used_symbol_types(requirements: List[EquipmentRequirement], placements: List[EquipmentPlacement], optional_equipment: Optional[List[Dict[str,Any]]]=None) -> Set[str]:
    req={r.id:r for r in requirements}; used={req[p.requirement_id].equipment_type for p in placements if p.requirement_id in req}
    used |= {str(x.get("equipment_type")) for x in (optional_equipment or []) if x.get("equipment_type")}
    return used


def build_project_legend(requirements, placements, optional_equipment=None):
    used=used_symbol_types(requirements,placements,optional_equipment)
    return [{"equipment_type":kind,**SYMBOL_LIBRARY[kind]} for kind in sorted(used) if kind in SYMBOL_LIBRARY]


def resolve_details(requirements: Dict[str,SystemRequirement], equipment_types: Set[str], detail_parameters: Optional[Dict[str,Any]]=None):
    detail_parameters=detail_parameters or {}; active={k for k,v in requirements.items() if v.required is True}; rows=[]
    for detail_id,spec in DETAIL_LIBRARY.items():
        trigger=spec["trigger"]; hit=bool(set(trigger.get("equipment",[]))&equipment_types or set(trigger.get("systems",[]))&active)
        if not hit: continue
        params={}; missing=[]
        supplied=detail_parameters.get(detail_id) or {}
        for name in spec["parameters"]:
            if name in supplied: params[name]={"value":supplied[name],"status":"FINAL","source":"explicit_user_input"}
            else: params[name]={"value":None,"status":"INPUT_REQUIRED"}; missing.append(name)
        rows.append({"detail_id":detail_id,"geometry":spec["geometry"],"parameters":params,"status":"PRELIMINARY" if missing else "FINAL","missing":missing})
    return rows


def link_plan_details(manifest, details):
    detail_ids={d["detail_id"] for d in details}; links=[]
    for sheet in manifest:
        if sheet.family in {"COVER","PANEL_SCHEDULE","SINGLE_LINE","RISER","CALCULATIONS"}: continue
        for detail_id in sorted(detail_ids):
            if sheet.family=="LIGHTING" and "LIGHT" in detail_id: links.append({"sheet_id":sheet.sheet_id,"detail_id":detail_id})
            elif sheet.family=="POWER" and any(x in detail_id for x in ("SWITCH","PANEL","ISOLATOR","JB")): links.append({"sheet_id":sheet.sheet_id,"detail_id":detail_id})
            elif sheet.family=="GROUNDING" and "EARTHING" in detail_id: links.append({"sheet_id":sheet.sheet_id,"detail_id":detail_id})
            elif sheet.family=="FIRE_ALARM" and "FIRE" in detail_id: links.append({"sheet_id":sheet.sheet_id,"detail_id":detail_id})
    return links


def detail_link_qa(details, links):
    ids={d["detail_id"] for d in details}; referenced={x["detail_id"] for x in links}; errors=[]
    orphan_details=ids-referenced
    bad_refs=referenced-ids
    # Some schedule/service details legitimately live on a dedicated details sheet; caller can add links before final acceptance.
    if bad_refs: errors.append(f"orphan_references:{sorted(bad_refs)}")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"unreferenced_details":sorted(orphan_details)}


def build_general_notes(basis: ElectricalDesignBasis, requirements: Dict[str,SystemRequirement]):
    notes=[]
    def add(title,key):
        v=basis.get(key)
        if v.status not in {EngineeringStatus.UNKNOWN,EngineeringStatus.INPUT_REQUIRED}:
            notes.append({"topic":title,"text":f"{title}: {v.value}","source":v.source,"status":v.status.value})
    add("Supply","supply_voltage_v"); add("Phase configuration","phase_configuration"); add("Earthing system","earthing_system")
    add("Installation method","installation_method"); add("Conductor material","conductor_material"); add("Voltage drop criteria","voltage_drop_limits")
    notes.extend([
        {"topic":"Coordination","text":"Coordinate electrical equipment and routes with the current architectural and mechanical project models; cross-discipline tag/location mismatch blocks release.","source":"project_qa_policy","status":"FINAL"},
        {"topic":"Identification","text":"Circuit, panel, feeder, equipment and detail identifiers must remain traceable across plans, schedules and diagrams.","source":"project_qa_policy","status":"FINAL"},
        {"topic":"Fire stopping","text":"Penetration fire-stopping requirements remain INPUT_REQUIRED until the project fire-rating basis is supplied.","source":"project_qa_policy","status":"INPUT_REQUIRED"},
        {"topic":"Testing","text":"Testing and commissioning requirements must be taken from the applicable project specification/rules before issue for construction.","source":"project_qa_policy","status":"INPUT_REQUIRED"},
    ])
    return notes


def build_optional_system_models(requirements: Dict[str,SystemRequirement], inputs: Optional[Dict[str,Any]]=None):
    inputs=inputs or {}; out={}
    fire=requirements.get("FIRE_ALARM")
    if fire and fire.required is True:
        cfg=inputs.get("fire_alarm")
        out["FIRE_ALARM"]=(cfg if isinstance(cfg,dict) else {"status":"INPUT_REQUIRED","devices":[],"panel":None,"loops_or_zones":None,"reason":"coverage/code/project fire basis required"})
    else: out["FIRE_ALARM"]={"status":"NOT_REQUIRED" if fire and fire.required is False else "INPUT_REQUIRED","devices":[]}
    for system in ("TELECOM","DATA","TV","INTERCOM","CCTV","ACCESS_CONTROL"):
        req=requirements.get(system)
        if req and req.required is True:
            cfg=(inputs.get("low_current") or {}).get(system)
            out[system]=cfg if isinstance(cfg,dict) else {"status":"INPUT_REQUIRED","devices":[],"reason":"system design basis required"}
        else: out[system]={"status":"NOT_REQUIRED" if req and req.required is False else "INPUT_REQUIRED","devices":[]}
    return out
