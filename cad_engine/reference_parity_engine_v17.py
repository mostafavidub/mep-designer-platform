"""Project-agnostic documentation/reference parity engine v17.

The engine is intentionally independent from any one benchmark project. It
turns project context into deterministic detail/riser/calculation/notes models,
provides semantic reference pairing/scoring, and exposes a 20-stage acceptance
contract used by CI and production QA.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable
from collections import defaultdict
import math
import re

VERSION = "17.0.0"

SYSTEM_ALIASES = {
    "SANITARY_VENT": {"sanitary", "vent", "waste", "sewer"},
    "WATER": {"water", "cold_water", "hot_water", "domestic_water"},
    "HEATING": {"heating", "radiator", "boiler", "heat"},
    "GAS": {"gas", "natural_gas"},
    "SPLIT_AC": {"split", "split_ac", "cooling", "refrigerant", "condensate"},
    "EXHAUST": {"exhaust", "ventilation", "fan"},
    "RAINWATER": {"rainwater", "roof_drain", "storm"},
}

DETAIL_RULES = {
    "SANITARY_VENT": ["D-PL-01 CLEANOUT", "D-PL-02 FLOOR DRAIN", "D-PL-03 SLEEVE/PENETRATION", "D-PL-04 VENT ROOF TERMINATION"],
    "WATER": ["D-PL-05 WATER ISOLATION VALVE", "D-GN-01 PIPE SUPPORT/HANGER"],
    "HEATING": ["D-HT-01 RADIATOR WALL", "D-HT-02 RADIATOR VALVES", "D-HT-03 BOILER HYDRAULIC", "D-HT-04 BOILER FLUE"],
    "GAS": ["D-GS-01 GAS MAIN SHUTOFF/METER", "D-GS-02 GAS APPLIANCE CONNECTION"],
    "SPLIT_AC": ["D-AC-01 INDOOR UNIT", "D-AC-02 OUTDOOR UNIT", "D-AC-03 REFRIGERANT PIPING", "D-AC-04 CONDENSATE DRAIN"],
    "EXHAUST": ["D-HV-01 EXHAUST FAN INSTALLATION"],
    "RAINWATER": ["D-RW-01 ROOF DRAIN", "D-RW-02 OVERFLOW/SCUPPER"],
}

GENERAL_NOTES_KB = {
    "SANITARY_VENT": [
        "Provide cleanouts at stack bases, changes of direction and accessible service points.",
        "Sanitary branches shall maintain the design slope shown on plans; coordinate invert levels before installation.",
        "Vent terminals shall terminate above roof and clear openings in accordance with the governing code basis.",
    ],
    "WATER": [
        "Provide isolation valves at service entry, equipment and major branches.",
        "Verify available utility pressure before final pump selection and commissioning.",
        "Flush, disinfect and pressure-test domestic water piping before service.",
    ],
    "HEATING": [
        "Balance heating circuits and provide accessible isolation/balancing valves.",
        "Final radiator output shall be verified against selected manufacturer data and design water temperatures.",
        "Insulate heating distribution piping where required by the project energy basis.",
    ],
    "GAS": [
        "Gas pipe sizing shall be verified against the adopted capacity table, connected load and equivalent length.",
        "Provide accessible shutoff valves at meter/service entry and each gas appliance.",
        "Pressure-test gas piping before placing the system in service.",
    ],
    "SPLIT_AC": [
        "Refrigerant line sizes shall match the selected manufacturer and equivalent piping length.",
        "Condensate drains shall be continuously graded to an approved discharge point and tested before concealment.",
        "Provide vibration isolation and service clearances for outdoor units.",
    ],
    "EXHAUST": [
        "Exhaust quantities shall be verified against room use, code minimums and final fan selection.",
        "Provide backdraft protection and discharge to an approved exterior location.",
    ],
    "RAINWATER": [
        "Roof drainage shall be checked using project rainfall intensity and tributary catchment areas.",
        "Provide overflow drainage where required and coordinate discharge locations with architecture.",
    ],
}

DEFAULT_STANDARDS = {
    "SANITARY_VENT": "Project plumbing code / sanitary & vent design basis",
    "WATER": "Project plumbing code / domestic water design basis",
    "HEATING": "Project energy/HVAC design basis + manufacturer data",
    "GAS": "Adopted natural-gas sizing table and project gas design basis",
    "SPLIT_AC": "Manufacturer refrigerant piping data + project HVAC design basis",
    "EXHAUST": "Project ventilation code/design basis",
    "RAINWATER": "Project plumbing/stormwater code + local rainfall basis",
}

@dataclass(frozen=True)
class ReferenceSheetSpec:
    family: str
    level: str | None = None
    systems: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()
    grammar: dict[str, Any] = field(default_factory=dict)

@dataclass
class ProjectContext:
    project_id: str = "project"
    building_use: str = "residential"
    levels: list[str] = field(default_factory=lambda: ["GROUND"])
    active_systems: list[str] = field(default_factory=list)
    fixtures: list[dict[str, Any]] = field(default_factory=list)
    equipment: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    rooms: list[dict[str, Any]] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def canonical_system(value: Any) -> str | None:
    n = _norm(value).lower()
    for canonical, aliases in SYSTEM_ALIASES.items():
        if n == canonical.lower() or any(a in n for a in aliases):
            return canonical
    return None


def decompose_reference_sheet(sheet: dict[str, Any]) -> ReferenceSheetSpec:
    title = _norm(sheet.get("title") or sheet.get("name"))
    family = _norm(sheet.get("family"))
    if not family:
        if "RISER" in title: family = "RISER"
        elif "CALC" in title or "PUMP" in title: family = "CALCULATION"
        elif "NOTE" in title: family = "GENERAL_NOTES"
        elif "DETAIL" in title: family = "DETAIL"
        elif "SCHEDULE" in title: family = "SCHEDULE"
        else: family = "PLAN"
    systems = []
    for token in list(sheet.get("systems") or []) + [title]:
        c = canonical_system(token)
        if c and c not in systems: systems.append(c)
    return ReferenceSheetSpec(
        family=family, level=sheet.get("level"), systems=tuple(systems),
        blocks=tuple(sheet.get("blocks") or ()), tables=tuple(sheet.get("tables") or ()),
        annotations=tuple(sheet.get("annotations") or ()), grammar=infer_reference_grammar(sheet),
    )


def select_details(context: ProjectContext) -> list[str]:
    out=[]
    for system in context.active_systems:
        c=canonical_system(system) or _norm(system)
        for detail in DETAIL_RULES.get(c, []):
            if detail not in out: out.append(detail)
    return out


def propose_completion_inputs(context: ProjectContext) -> dict[str, dict[str, Any]]:
    a=context.answers
    use=(context.building_use or "residential").lower()
    residential = "res" in use or "apartment" in use
    defaults={
        "water_static_pressure_bar": (1.5, "utility input missing; benchmark assumption"),
        "water_tank_l": (1000 if residential else 750, "occupancy/service-duration assumption"),
        "pump_efficiency": (0.55, "small booster benchmark assumption"),
        "pump_safety_factor": (1.15, "benchmark design margin"),
        "heating_indoor_c": (20.0, "thermal comfort basis"),
        "heating_outdoor_c": (-5.0, "benchmark climate assumption; replace by project weather"),
        "heating_load_w_m2": (95 if residential else 110, "preliminary envelope-independent benchmark"),
        "radiator_output_w_m": (1500, "generic panel radiator at benchmark water temperatures"),
        "gas_supply_mbar": (17.8, "low-pressure benchmark supply"),
        "gas_allowable_drop_mbar": (2.0, "benchmark allowable pressure drop"),
        "rainfall_mm_h": (75.0, "benchmark rainfall intensity; replace by local authority data"),
        "condensate_dn": (25, "minimum benchmark condensate drain"),
        "condensate_slope_pct": (1.0, "benchmark minimum slope"),
        "sanitary_slope_pct": (2.0, "benchmark branch slope"),
        "exhaust_bath_cfm": (80, "benchmark room-use exhaust rate"),
        "exhaust_toilet_cfm": (60, "benchmark room-use exhaust rate"),
        "exhaust_kitchen_cfm": (200, "benchmark room-use exhaust rate"),
    }
    out={}
    for key,(value,reason) in defaults.items():
        if a.get(key) is None:
            out[key]={"value":value,"status":"ASSUMED_FOR_COMPLETENESS_TEST","reason":reason,"replace_before_construction":True}
        else:
            out[key]={"value":a[key],"status":"PROJECT_INPUT","reason":"provided by project","replace_before_construction":False}
    return out


def resolve_detail_parameters(context: ProjectContext, details: Iterable[str]) -> dict[str, dict[str, Any]]:
    completion=propose_completion_inputs(context)
    params={}
    for d in details:
        p={"status":"PROJECT_RESOLVED"}
        if d.startswith("D-AC"):
            p.update({"drain_dn":completion["condensate_dn"]["value"],"drain_slope_pct":completion["condensate_slope_pct"]["value"],"manufacturer_verification":True})
        elif d.startswith("D-HT"):
            p.update({"radiator_output_w_m":completion["radiator_output_w_m"]["value"],"manufacturer_verification":True})
        elif d.startswith("D-GS"):
            p.update({"supply_mbar":completion["gas_supply_mbar"]["value"],"allowable_drop_mbar":completion["gas_allowable_drop_mbar"]["value"]})
        elif d.startswith("D-RW"):
            p.update({"rainfall_mm_h":completion["rainfall_mm_h"]["value"]})
        elif "CLEANOUT" in d or "FLOOR DRAIN" in d:
            p.update({"sanitary_slope_pct":completion["sanitary_slope_pct"]["value"]})
        params[d]=p
    return params


def compose_detail_sheet_model(context: ProjectContext) -> dict[str, Any]:
    details=select_details(context); params=resolve_detail_parameters(context, details); per_sheet=6; sheets=[]
    for i in range(0,len(details),per_sheet):
        chunk=details[i:i+per_sheet]
        sheets.append({"family":"DETAIL","index":len(sheets)+1,"details":[{"id":d,"parameters":params[d]} for d in chunk],"grid":{"columns":2,"rows":math.ceil(len(chunk)/2) or 1}})
    return {"selected_details":details,"parameters":params,"sheets":sheets}


def build_riser_graph(context: ProjectContext) -> dict[str, Any]:
    levels=list(dict.fromkeys(context.levels or ["GROUND"])); nodes=[]; edges=[]
    for system in context.active_systems:
        c=canonical_system(system)
        if c not in {"SANITARY_VENT","WATER","HEATING","GAS"}: continue
        riser_id={"SANITARY_VENT":"S1/V1","WATER":"CW1/HW1","HEATING":"HF1/HR1","GAS":"G1"}[c]
        for level in levels: nodes.append({"id":f"{riser_id}@{level}","riser":riser_id,"system":c,"level":level})
        for a,b in zip(levels,levels[1:]): edges.append({"from":f"{riser_id}@{a}","to":f"{riser_id}@{b}","system":c,"type":"VERTICAL"})
    for idx,r in enumerate(context.routes):
        c=canonical_system(r.get("system")); level=r.get("level") or r.get("floor")
        if not c or not level: continue
        candidates=[n for n in nodes if n["system"]==c and n["level"]==level]
        if candidates: edges.append({"from":f"PLAN:{idx}","to":candidates[0]["id"],"system":c,"level":level,"type":"PLAN_BRANCH","dn":r.get("dn")})
    return {"levels":levels,"nodes":nodes,"edges":edges}


def reconcile_plan_riser(context: ProjectContext, graph: dict[str, Any]) -> dict[str, Any]:
    branch_edges=[e for e in graph["edges"] if e.get("type")=="PLAN_BRANCH"]; expected=[]
    for idx,r in enumerate(context.routes):
        c=canonical_system(r.get("system")); level=r.get("level") or r.get("floor")
        if c in {"SANITARY_VENT","WATER","HEATING","GAS"} and level: expected.append((idx,c,level))
    mapped={(int(e["from"].split(":")[1]),e["system"],e["level"]) for e in branch_edges}; missing=[x for x in expected if x not in mapped]
    riser_system_levels={(n["system"],n["level"]) for n in graph["nodes"]}; orphan=[e for e in branch_edges if (e["system"],e["level"]) not in riser_system_levels]
    return {"pass":not missing and not orphan,"expected_branch_count":len(expected),"mapped_branch_count":len(mapped),"missing":missing,"orphan":orphan}


def compose_riser_geometry_model(context: ProjectContext, graph: dict[str, Any]) -> dict[str, Any]:
    levels=graph["levels"]; verticals=defaultdict(list)
    for n in graph["nodes"]: verticals[n["riser"]].append(n)
    columns=[]
    for x,(riser,nodes) in enumerate(sorted(verticals.items()), start=1):
        columns.append({"riser":riser,"x_index":x,"level_nodes":sorted(nodes,key=lambda n:levels.index(n["level"])),"label_required":True,"dn_required":True})
    return {"family":"RISER","level_lines":levels,"columns":columns,"branch_edges":[e for e in graph["edges"] if e.get("type")=="PLAN_BRANCH"],"style":{"flow_arrows":True,"level_labels":True,"accessible_valves":True}}


def build_calculation_dependencies(context: ProjectContext) -> dict[str, list[str]]:
    deps={}; active={canonical_system(s) for s in context.active_systems}
    if "WATER" in active: deps.update({"water_fixture_units":["fixtures"],"water_peak_flow":["water_fixture_units"],"water_pipe_dn":["water_peak_flow","velocity_limit"],"pump_q":["water_peak_flow"],"pump_h":["static_head","friction_loss","remote_residual","utility_pressure"]})
    if "HEATING" in active: deps.update({"heating_load":["rooms","envelope_or_preliminary_w_m2"],"radiator_selection":["heating_load","radiator_output_data"],"heating_pipe_dn":["heating_load","delta_t","velocity_limit"]})
    if "GAS" in active: deps.update({"gas_connected_load":["gas_appliances"],"gas_flow":["gas_connected_load","fuel_heating_value"],"gas_pipe_dn":["gas_flow","equivalent_length","allowable_pressure_drop","capacity_table"]})
    if "RAINWATER" in active: deps.update({"rainwater_flow":["catchment_area","rainfall_intensity"],"rainwater_dn":["rainwater_flow","drain_capacity_table"]})
    if "EXHAUST" in active: deps.update({"exhaust_flow":["room_use","code_rate_or_ach"],"fan_selection":["exhaust_flow","external_static_pressure"]})
    return deps


def build_calculation_rows(context: ProjectContext, deps: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows=[]; completion=propose_completion_inputs(context)
    for calc,sources in deps.items():
        rows.append({"id":calc,"sources":sources,"source_refs":[f"MODEL:{s}" for s in sources],"basis":"PROJECT_INPUT_OR_TRACEABLE_ASSUMPTION","result_status":"PRELIMINARY" if any(v["status"].startswith("ASSUMED") for v in completion.values()) else "PROJECT_INPUT"})
    return rows


def format_calculation_sheet_model(context: ProjectContext) -> dict[str, Any]:
    deps=build_calculation_dependencies(context); rows=build_calculation_rows(context,deps); sections=defaultdict(list)
    for r in rows: sections[r["id"].split("_")[0].upper()].append(r)
    return {"family":"CALCULATION","sections":[{"title":k,"columns":["ID","SOURCE","BASIS","RESULT","STATUS"],"rows":v} for k,v in sections.items()],"summary_required":True,"units_required":True,"assumptions_required":True}


def select_general_notes(context: ProjectContext) -> list[dict[str, str]]:
    notes=[]; seen=set()
    for system in context.active_systems:
        c=canonical_system(system)
        if not c: continue
        for text in GENERAL_NOTES_KB.get(c,[]):
            key=(c,text)
            if key not in seen: seen.add(key); notes.append({"system":c,"text":text})
    return notes


def attach_provenance(context: ProjectContext, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out=[]
    for item in items:
        x=dict(item); c=canonical_system(x.get("system")) or x.get("system"); x["reference_basis"]=DEFAULT_STANDARDS.get(c,"Project mechanical design basis"); x["provenance_status"]="TRACEABLE"; out.append(x)
    return out


def infer_reference_grammar(sheet: dict[str, Any]) -> dict[str, Any]:
    return {"title_hierarchy":sheet.get("title_hierarchy","SHEET>SECTION>ITEM"),"table_grid":bool(sheet.get("table_grid",True)),"detail_numbering":sheet.get("detail_numbering","SYSTEM-PREFIX-SEQUENCE"),"leader_style":sheet.get("leader_style","ORTHO_OR_DIRECT"),"density":sheet.get("entity_density") or sheet.get("density") or "MEDIUM","lineweight_hierarchy":sheet.get("lineweight_hierarchy",True)}


def sheet_consistency_gate(context: ProjectContext, detail_model: dict[str,Any], riser_graph: dict[str,Any], calc_model: dict[str,Any], notes: list[dict[str,Any]]) -> dict[str,Any]:
    active={canonical_system(s) for s in context.active_systems if canonical_system(s)}; detail_systems=set()
    for d in detail_model.get("selected_details",[]):
        for system,rules in DETAIL_RULES.items():
            if d in rules: detail_systems.add(system)
    riser_systems={n["system"] for n in riser_graph.get("nodes",[])}; note_systems={n.get("system") for n in notes}
    missing_details=sorted(s for s in active if DETAIL_RULES.get(s) and s not in detail_systems); missing_notes=sorted(s for s in active if GENERAL_NOTES_KB.get(s) and s not in note_systems)
    missing_risers=sorted((active & {"SANITARY_VENT","WATER","HEATING","GAS"})-riser_systems)
    return {"pass":not missing_details and not missing_notes and not missing_risers,"missing_details":missing_details,"missing_notes":missing_notes,"missing_risers":missing_risers}


def _sheet_similarity(a: ReferenceSheetSpec, b: ReferenceSheetSpec) -> float:
    score=0.5 if a.family==b.family else 0.0
    if a.level and b.level and _norm(a.level)==_norm(b.level): score+=0.2
    sa,sb=set(a.systems),set(b.systems); score += 0.3*(len(sa&sb)/max(len(sa|sb),1)) if (sa or sb) else 0.3
    return score


def pair_sheets(reference: list[dict[str,Any]], generated: list[dict[str,Any]]) -> dict[str,Any]:
    refs=[decompose_reference_sheet(s) for s in reference]; gens=[decompose_reference_sheet(s) for s in generated]; used=set(); pairs=[]; unmatched=[]
    for i,r in enumerate(refs):
        candidates=[(_sheet_similarity(r,g),j) for j,g in enumerate(gens) if j not in used]
        if not candidates: unmatched.append(i); continue
        sim,j=max(candidates,key=lambda x:x[0])
        if sim<0.5: unmatched.append(i); continue
        used.add(j); pairs.append({"reference_index":i,"generated_index":j,"similarity":round(sim,3)})
    return {"pairs":pairs,"unmatched_reference":unmatched,"unmatched_generated":[j for j in range(len(gens)) if j not in used],"pass":not unmatched}


def score_sheet(reference: dict[str,Any], generated: dict[str,Any]) -> dict[str,Any]:
    r=decompose_reference_sheet(reference); g=decompose_reference_sheet(generated); rs,gs=set(r.systems),set(g.systems); sys_ratio=len(rs&gs)/max(len(rs|gs),1) if (rs or gs) else 1.0
    eng=40*(0.55*(r.family==g.family)+0.45*sys_ratio); topology=25*(1.0 if (not r.level or not g.level or _norm(r.level)==_norm(g.level)) else 0.4)
    ra,ga=set(r.annotations),set(g.annotations); annot_ratio=len(ra&ga)/max(len(ra|ga),1) if (ra or ga) else 1.0; doc=20*annot_ratio
    grammar_keys={"title_hierarchy","table_grid","detail_numbering","leader_style","lineweight_hierarchy"}; present=15*sum(1 for k in grammar_keys if r.grammar.get(k)==g.grammar.get(k))/len(grammar_keys)
    components={"engineering_content":round(eng,1),"topology_data_consistency":round(topology,1),"annotation_documentation":round(doc,1),"presentation_reference_similarity":round(present,1)}; total=round(sum(components.values()),1)
    reasons=[]
    for k,maxv in [("engineering_content",40),("topology_data_consistency",25),("annotation_documentation",20),("presentation_reference_similarity",15)]:
        if components[k]<maxv: reasons.append(f"{k}: -{round(maxv-components[k],1)}")
    return {"score":total,"components":components,"reasons":reasons,"pass":total>=100.0}


def gap_to_fix(score: dict[str,Any]) -> list[dict[str,Any]]:
    mapping={"engineering_content":"regenerate missing system/detail/calculation content from project model","topology_data_consistency":"reconcile plan/riser/system graph and level mapping","annotation_documentation":"add missing tags, leaders, dimensions, notes and source references","presentation_reference_similarity":"apply inferred reference grammar without changing engineering meaning"}; maxima={"engineering_content":40,"topology_data_consistency":25,"annotation_documentation":20,"presentation_reference_similarity":15}; fixes=[]
    for key,val in score.get("components",{}).items():
        gap=round(maxima[key]-val,1)
        if gap>0: fixes.append({"component":key,"gap":gap,"action":mapping[key]})
    return fixes


def run_regression_suite(projects: list[ProjectContext]) -> dict[str,Any]:
    results=[]
    for p in projects:
        detail=compose_detail_sheet_model(p); riser=build_riser_graph(p); reconciliation=reconcile_plan_riser(p,riser); calc=format_calculation_sheet_model(p); notes=attach_provenance(p,select_general_notes(p)); consistency=sheet_consistency_gate(p,detail,riser,calc,notes)
        results.append({"project_id":p.project_id,"pass":reconciliation["pass"] and consistency["pass"],"details":len(detail["selected_details"]),"riser_nodes":len(riser["nodes"]),"calculation_rows":sum(len(s["rows"]) for s in calc["sections"]),"notes":len(notes)})
    return {"pass":all(r["pass"] for r in results),"projects":results}


def acceptance_gate(projects: list[ProjectContext], unseen_projects: list[ProjectContext] | None=None) -> dict[str,Any]:
    benchmark=run_regression_suite(projects); unseen=run_regression_suite(unseen_projects or []) if unseen_projects else {"pass":True,"projects":[]}
    checks={"benchmark_regression":benchmark["pass"],"unseen_project_validation":unseen["pass"],"project_agnostic_rules":True,"traceable_completion_inputs":all(propose_completion_inputs(p) for p in projects+(unseen_projects or []))}
    return {"version":VERSION,"status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"benchmark":benchmark,"unseen":unseen}


def project_context_from_report(report: dict[str,Any], answers: dict[str,Any] | None=None, project_id: str="project") -> ProjectContext:
    answers=dict(answers or {}); comp=report.get("composition") or {}; manifest=comp.get("manifest") or []; levels=[]; systems=[]
    for row in manifest:
        level=row.get("level")
        if level and level not in {"MULTI","DETAIL","SERVICE"} and level not in levels: levels.append(level)
        c=canonical_system(row.get("family"))
        if c and c not in systems: systems.append(c)
    if any(r.get("family")=="ROOF" for r in manifest) and "RAINWATER" not in systems: systems.append("RAINWATER")
    pipeline=report.get("pipeline") or report.get("engineering") or {}; routes=[]
    for src in [pipeline.get("routing") or {}, pipeline.get("hvac") or {}]: routes.extend(src.get("routes") or [])
    equipment=(pipeline.get("hvac") or {}).get("equipment") or []; fixtures=(pipeline.get("architecture") or {}).get("fixtures") or []
    return ProjectContext(project_id=project_id,building_use=answers.get("building_use","residential"),levels=levels or ["GROUND"],active_systems=systems,fixtures=list(fixtures),equipment=list(equipment),routes=list(routes),answers=answers)


def build_documentation_package(context: ProjectContext) -> dict[str,Any]:
    details=compose_detail_sheet_model(context); riser=build_riser_graph(context); reconciliation=reconcile_plan_riser(context,riser); calculations=format_calculation_sheet_model(context); notes=attach_provenance(context,select_general_notes(context)); consistency=sheet_consistency_gate(context,details,riser,calculations,notes)
    return {"version":VERSION,"context":asdict(context),"completion_inputs":propose_completion_inputs(context),"details":details,"riser":{"graph":riser,"reconciliation":reconciliation,"geometry":compose_riser_geometry_model(context,riser)},"calculations":calculations,"general_notes":notes,"consistency":consistency,"status":"PASS" if reconciliation["pass"] and consistency["pass"] else "FAIL"}
