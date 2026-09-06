from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .architecture import reconstruct_architecture
from .composer import compose_drawing_set
from .design import (
    REFERENCE_TAXONOMY, build_design_basis, build_project_model, plan_sheets,
    resolve_equipment_requirements, resolve_system_requirements,
)
from .distribution import (
    build_electrical_riser, finalize_panels, grounding_model,
    normalize_requirement_scope, panel_design_qa, resolve_switch_quantities,
)
from .documentation import (
    build_general_notes, build_optional_system_models, build_project_legend,
    detail_link_qa, link_plan_details, resolve_details, used_symbol_types,
)
from .geometry_acceptance import finalize_placements
from .models import EngineeringStatus, EvidenceValue, serialize
from .placement_lighting import place_equipment, resolve_quantities
from .postcompose import append_detail_sheet, apply_postcomposition
from .power import (
    build_circuit_topology, build_loads, calculate_currents_and_phase_balance,
    calculate_voltage_drop, panel_schedules, schedule_sync_qa, size_circuits,
)
from .qa import (
    content_signature_qa, family_purity_qa, final_reopen_qa,
    reference_similarity_qa, semantic_duplicate_qa, visual_qa,
)
from .routing import route_circuits, routing_qa
from .service import build_service_feeders, full_traceability_qa, service_single_line


ALL_GATES = (
    "ARCHITECTURE_MODEL", "PROJECT_MODEL", "DESIGN_BASIS", "SYSTEM_REQUIREMENTS",
    "REFERENCE_TAXONOMY", "SHEET_MANIFEST", "EQUIPMENT_REQUIREMENTS",
    "EQUIPMENT_PLACEMENT", "LIGHTING_DESIGN", "POWER_DESIGN", "CIRCUIT_TOPOLOGY",
    "ROUTING", "LOAD_CALCULATION", "CABLE_SIZING", "BREAKER_SIZING",
    "VOLTAGE_DROP", "PHASE_BALANCE", "PANEL_DESIGN", "PANEL_SCHEDULE",
    "SINGLE_LINE", "RISER", "GROUNDING", "FIRE_ALARM_LOW_CURRENT",
    "DETAIL_COVERAGE", "PLAN_DETAIL_LINKS", "LEGEND", "GENERAL_NOTES",
    "SHEET_CONTENT_SIGNATURE", "FAMILY_PURITY", "NO_SEMANTIC_DUPLICATES",
    "PAPER_SPACE", "REFERENCE_SIMILARITY", "VISUAL_QA", "FINAL_FILE_REOPEN",
)


def gate(status: str, errors=None, warnings=None, **metrics):
    return {"status": status, "errors": errors or [], "warnings": warnings or [], "metrics": metrics}


def _is_final(value):
    return isinstance(value, EvidenceValue) and value.status == EngineeringStatus.FINAL and value.value is not None


def _status_from_unresolved(unresolved, *, require_nonempty=False, count=0):
    if require_nonempty and count <= 0:
        return "FAIL"
    return "PASS" if not unresolved else "PRELIMINARY"


def _require_system_scope(requirements):
    unresolved = [name for name, req in requirements.items() if req.required is None]
    return gate("PASS" if not unresolved else "PRELIMINARY",
                warnings=[f"scope_input_required:{x}" for x in unresolved], unresolved=len(unresolved))


def _equipment_gate(items):
    unresolved = [x.id for x in items if x.quantity.status != EngineeringStatus.FINAL]
    return gate(_status_from_unresolved(unresolved, require_nonempty=True, count=len(items)),
                errors=["no_equipment_requirements"] if not items else [],
                warnings=[f"quantity_not_final:{x}" for x in unresolved], count=len(items))


def _family_design_gate(items, systems, required_systems):
    applicable = bool(set(systems) & required_systems)
    if not applicable:
        return gate("NOT_REQUIRED")
    rows = [x for x in items if x.system in systems]
    unresolved = [x.id for x in rows if x.quantity.status != EngineeringStatus.FINAL]
    return gate("PASS" if rows and not unresolved else "PRELIMINARY",
                warnings=[f"design_not_final:{x}" for x in unresolved] + ([] if rows else ["no_design_rows"]), count=len(rows))


def _load_gate(topology):
    unresolved=[]
    for circuit in topology.get("circuits") or []:
        if not _is_final(circuit.connected_load_w): unresolved.append(f"{circuit.id}.connected")
        if not _is_final(circuit.demand_load_w): unresolved.append(f"{circuit.id}.demand")
    return gate("PASS" if topology.get("circuits") and not unresolved else "PRELIMINARY",
                warnings=[f"load_unresolved:{x}" for x in unresolved], circuits=len(topology.get("circuits") or []))


def _attr_gate(topology, attr):
    circuits = topology.get("circuits") or []
    unresolved=[x.id for x in circuits if not _is_final(getattr(x, attr))]
    return gate("PASS" if circuits and not unresolved else "PRELIMINARY",
                warnings=[f"{attr}_unresolved:{x}" for x in unresolved], circuits=len(circuits))


def _optional_system_gate(requirements, models):
    unresolved=[]
    for name, req in requirements.items():
        if name not in {"FIRE_ALARM","TELECOM","DATA","TV","INTERCOM","CCTV","ACCESS_CONTROL"}:
            continue
        if req.required is True:
            model=models.get(name) or {}
            if model.get("status") not in {"PASS","FINAL"}:
                unresolved.append(name)
    return gate("PASS" if not unresolved else "PRELIMINARY",
                warnings=[f"optional_system_design_input_required:{x}" for x in unresolved])


def _detail_gate(details):
    unresolved=[x["detail_id"] for x in details if x.get("status") != "FINAL"]
    return gate("PASS" if details and not unresolved else ("NOT_REQUIRED" if not details else "PRELIMINARY"),
                warnings=[f"detail_not_final:{x}" for x in unresolved], details=len(details))


def _link_gate(details, links):
    q=detail_link_qa(details, links)
    unreferenced=q.get("unreferenced_details") or []
    errors=list(q.get("errors") or [])
    if unreferenced:
        errors.append(f"orphan_details:{sorted(unreferenced)}")
    return gate("PASS" if not errors else "FAIL", errors=errors, links=len(links))


def _complete_links(manifest, details, links):
    """Attach each generated project detail to an owning plan family when possible."""
    referenced={x["detail_id"] for x in links}
    by_family={}
    for sheet in manifest:
        by_family.setdefault(sheet.family, []).append(sheet.sheet_id)
    for detail in details:
        did=detail["detail_id"]
        if did in referenced: continue
        preferred=[]
        if "EARTH" in did: preferred=by_family.get("GROUNDING",[])
        elif "LIGHT" in did or "FIRE" in did or "EMERGENCY" in did: preferred=by_family.get("LIGHTING",[]) + by_family.get("FIRE_ALARM",[])
        else: preferred=by_family.get("POWER",[])
        if preferred:
            links.append({"sheet_id":preferred[0],"detail_id":did})
            referenced.add(did)
    return links


def _paper_gate(composition, manifest):
    ok = composition.get("geometry_ownership") == "PAPER_SPACE_PER_SHEET" and composition.get("sheet_count") == len(manifest)
    return gate("PASS" if ok else "FAIL",
                errors=[] if ok else ["independent_paper_space_or_manifest_mismatch"], sheets=composition.get("sheet_count"))


def run_strict_electrical_pipeline(source: str|Path, output: str|Path, config: Optional[Dict[str,Any]]=None):
    cfg=config or {}; output=Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    report={"version":"electrical-project-driven-v1.1-strict","source":str(source),"output":str(output),"gates":{},"production_changed":False}

    architecture=reconstruct_architecture(source)
    q=architecture.validate(); report["gates"]["ARCHITECTURE_MODEL"]=gate(q["status"],q["errors"],architecture.issues,levels=len(architecture.levels),rooms=len(architecture.rooms),frames=len(architecture.frames))
    if q["status"]=="FAIL": return _finish(report,{"architecture":architecture})

    project=build_project_model(architecture,cfg.get("project_inputs"))
    q=project.validate(); report["gates"]["PROJECT_MODEL"]=gate(q["status"],q["errors"],levels=len(project.levels),rooms=len(project.rooms))
    if q["status"]=="FAIL": return _finish(report,{"architecture":architecture,"project":project})

    basis=build_design_basis(cfg.get("design_basis"),(cfg.get("applicable_rules") or {}).get("design_basis"),(cfg.get("manufacturer_data") or {}).get("design_basis"))
    q=basis.validate(); report["gates"]["DESIGN_BASIS"]=gate(q["status"],q["errors"],[f"INPUT_REQUIRED:{x}" for x in q["missing"]],missing=len(q["missing"]))

    requirements=normalize_requirement_scope(resolve_system_requirements(project,basis),basis)
    report["gates"]["SYSTEM_REQUIREMENTS"]=_require_system_scope(requirements)
    report["gates"]["REFERENCE_TAXONOMY"]=gate("PASS",families=len(REFERENCE_TAXONOMY["observed"]["families"]),source=REFERENCE_TAXONOMY["source"])

    manifest=plan_sheets(project,requirements,cfg.get("content_density"))
    report["gates"]["SHEET_MANIFEST"]=gate("PASS" if manifest else "FAIL",errors=[] if manifest else ["empty_manifest"],sheet_count=len(manifest))

    equipment=resolve_equipment_requirements(project,requirements)
    equipment=resolve_quantities(equipment,project,basis,cfg.get("manufacturer_data"))
    equipment=resolve_switch_quantities(equipment,project,basis)
    report["gates"]["EQUIPMENT_REQUIREMENTS"]=_equipment_gate(equipment)
    required_systems={x for x,r in requirements.items() if r.required is True}
    report["gates"]["LIGHTING_DESIGN"]=_family_design_gate(equipment,{"LIGHTING","EMERGENCY_LIGHTING"},required_systems)
    report["gates"]["POWER_DESIGN"]=_family_design_gate(equipment,{"GENERAL_RECEPTACLES","DEDICATED_POWER","KITCHEN_POWER","HVAC_POWER","ELEVATOR_POWER","PUMP_POWER"},required_systems)

    placements=place_equipment(equipment,project,architecture,cfg.get("placement_rules"))
    pq=finalize_placements(placements,equipment,project,architecture,cfg.get("placement_rules"))
    report["gates"]["EQUIPMENT_PLACEMENT"]=gate(pq["status"],pq["errors"],pq["warnings"],final=pq["final"],total=pq["total"])

    loads=build_loads(equipment,placements)
    topology=build_circuit_topology(loads,project,basis,cfg.get("circuit_rules"))
    report["gates"]["CIRCUIT_TOPOLOGY"]=gate(topology["status"],topology["errors"],loads=len(loads),circuits=len(topology["circuits"]))
    report["gates"]["LOAD_CALCULATION"]=_load_gate(topology)

    balance=calculate_currents_and_phase_balance(topology,basis,cfg.get("calculation_rules"))
    report["gates"]["PHASE_BALANCE"]=gate(balance["status"],balance["errors"],balance["warnings"],values=balance.get("phase_balance_pct"))

    sizing=size_circuits(topology,basis,cfg.get("sizing_tables"))
    report["gates"]["CABLE_SIZING"]=_attr_gate(topology,"cable")
    report["gates"]["BREAKER_SIZING"]=_attr_gate(topology,"breaker")

    routing=route_circuits(topology,placements,architecture,(cfg.get("circuit_rules") or {}).get("panel_locations"))
    rq=routing_qa(routing); report["gates"]["ROUTING"]=gate(rq["status"],rq["errors"],rq["warnings"],routes=rq["route_count"])

    vd=calculate_voltage_drop(topology,basis,cfg.get("voltage_drop_rules"))
    report["gates"]["VOLTAGE_DROP"]=gate(vd["status"],vd["errors"],vd["warnings"])

    panel_finalize=finalize_panels(topology,basis,cfg.get("panel_rules")); panel_q=panel_design_qa(topology)
    report["gates"]["PANEL_DESIGN"]=gate(panel_q["status"],panel_q["errors"],panel_q["warnings"]+panel_finalize["warnings"],panels=len(topology["panels"]))

    service=build_service_feeders(topology,cfg.get("service_inputs")); trace=full_traceability_qa(topology)
    if trace["status"]=="FAIL":
        report["gates"]["CIRCUIT_TOPOLOGY"]=gate("FAIL",trace["errors"],chain=trace["chain"])

    schedules=panel_schedules(topology); sq=schedule_sync_qa(topology,schedules)
    report["gates"]["PANEL_SCHEDULE"]=gate(sq["status"],sq["errors"],rows=sum(len(x) for x in schedules.values()))

    sld=service_single_line(topology)
    report["gates"]["SINGLE_LINE"]=gate(sld["status"],warnings=[f"service_or_feeder_input_required:{x}" for x in service.get("missing",[])],nodes=len(sld["nodes"]),edges=len(sld["edges"]))

    riser=build_electrical_riser(topology,project,(cfg.get("service_inputs") or {}).get("riser_feeders"))
    report["gates"]["RISER"]=gate("PASS" if riser["status"] in {"PASS","NOT_REQUIRED"} else "PRELIMINARY",warnings=[f"riser_input_required:{x}" for x in riser.get("missing",[])],transitions=len(riser.get("transitions") or []))

    grounding=grounding_model(requirements,cfg.get("optional_system_inputs"))
    report["gates"]["GROUNDING"]=gate("PASS" if grounding["status"] in {"PASS","NOT_REQUIRED"} else "PRELIMINARY",warnings=[f"grounding_input_required:{x}" for x in grounding.get("missing",[])])

    optional_models=build_optional_system_models(requirements,cfg.get("optional_system_inputs"))
    report["gates"]["FIRE_ALARM_LOW_CURRENT"]=_optional_system_gate(requirements,optional_models)

    legend=build_project_legend(equipment,placements,[])
    report["gates"]["LEGEND"]=gate("PASS" if legend or not placements else "FAIL",entries=len(legend))
    notes=build_general_notes(basis,requirements)
    report["gates"]["GENERAL_NOTES"]=gate("PASS" if notes else "FAIL",notes=len(notes))

    details=resolve_details(requirements,used_symbol_types(equipment,placements),cfg.get("detail_parameters"))
    report["gates"]["DETAIL_COVERAGE"]=_detail_gate(details)
    links=_complete_links(manifest,details,link_plan_details(manifest,details))
    report["gates"]["PLAN_DETAIL_LINKS"]=_link_gate(details,links)
    append_detail_sheet(manifest,details)

    calculations={"topology":topology,"phase_balance":balance,"sizing":sizing,"voltage_drop":vd,"service":service,"grounding":grounding,"optional_systems":optional_models}
    project_name=str(project.project.get("project_name",EvidenceValue()).value or "EngiTools Electrical Project")
    paper=tuple(cfg.get("paper_mm") or (420.0,297.0))
    composition=compose_drawing_set(output,architecture,manifest,equipment,placements,routing,schedules,sld,riser,legend,notes,details,links,calculations,project_name=project_name,paper=paper,drawing_status="PRELIMINARY")
    apply_postcomposition(output,manifest,details,grounding,composition["signatures"],paper)
    report["gates"]["PAPER_SPACE"]=_paper_gate(composition,manifest)

    cs=content_signature_qa(manifest,composition["signatures"])
    report["gates"]["SHEET_CONTENT_SIGNATURE"]=gate(cs["status"],cs["errors"],sheets=len(cs["sheets"]))
    fp=family_purity_qa(output,manifest); report["gates"]["FAMILY_PURITY"]=gate(fp["status"],fp["errors"])
    du=semantic_duplicate_qa(output,manifest); report["gates"]["NO_SEMANTIC_DUPLICATES"]=gate(du["status"],du["errors"])
    rs=reference_similarity_qa(manifest,composition["signatures"],float(cfg.get("reference_similarity_threshold",.6)))
    report["gates"]["REFERENCE_SIMILARITY"]=gate(rs["status"],rs["errors"],family_scores=rs["family_scores"])
    vq=visual_qa(output,manifest,paper); report["gates"]["VISUAL_QA"]=gate(vq["status"],vq["errors"],vq["warnings"],sheets=len(vq["sheets"]))
    reopen=final_reopen_qa(output,manifest,composition["signatures"],output.parent/(output.stem+"_renders"),paper)
    report["gates"]["FINAL_FILE_REOPEN"]=gate(reopen["status"],reopen["errors"],file_size_bytes=reopen.get("file_size_bytes"),renders=len(reopen.get("renders") or []))

    return _finish(report,{"architecture":architecture,"project":project,"basis":basis,"requirements":requirements,"manifest":manifest,
                          "equipment":equipment,"placements":placements,"topology":topology,"routing":routing,"service":service,"schedules":schedules,
                          "single_line":sld,"riser":riser,"grounding":grounding,"optional_systems":optional_models,"legend":legend,"notes":notes,
                          "details":details,"detail_links":links,"composition":composition})


def _finish(report, data):
    for name in ALL_GATES:
        report["gates"].setdefault(name, gate("PRELIMINARY",warnings=["gate_not_reached"]))
    hard=[name for name,value in report["gates"].items() if value.get("status")=="FAIL"]
    incomplete=[name for name,value in report["gates"].items() if value.get("status") not in {"PASS","NOT_REQUIRED"}]
    accepted=not hard and not incomplete
    report["acceptance"]={"status":"PASS" if accepted else "NOT_ACCEPTED","hard_fail_gates":hard,"incomplete_gates":incomplete,
                          "real_project_acceptance":accepted,"reference_similarity":report["gates"]["REFERENCE_SIMILARITY"]["status"],
                          "final_file_reopen":report["gates"]["FINAL_FILE_REOPEN"]["status"],"production_release_allowed":False}
    report["data"]=serialize(data)
    return report
