from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .architecture import reconstruct_architecture
from .composer import compose_drawing_set
from .design import (
    REFERENCE_TAXONOMY, build_design_basis, build_project_model, plan_sheets,
    resolve_equipment_requirements, resolve_system_requirements,
)
from .documentation import (
    build_general_notes, build_optional_system_models, build_project_legend,
    detail_link_qa, link_plan_details, resolve_details, used_symbol_types,
)
from .models import EngineeringStatus, EvidenceValue, serialize
from .placement_lighting import place_equipment, placement_qa, resolve_quantities
from .power import (
    build_circuit_topology, build_loads, build_riser, build_single_line,
    calculate_currents_and_phase_balance, calculate_voltage_drop,
    panel_schedules, schedule_sync_qa, size_circuits,
)
from .qa import (
    content_signature_qa, family_purity_qa, final_reopen_qa,
    reference_similarity_qa, semantic_duplicate_qa, visual_qa,
)
from .routing import route_circuits, routing_qa


PHASES = {
    0:"STUDY_EXISTING_ARCHITECTURE", 1:"ARCHITECTURAL_UNDERSTANDING", 2:"ELECTRICAL_PROJECT_MODEL",
    3:"ELECTRICAL_DESIGN_BASIS", 4:"SYSTEM_REQUIREMENT_ENGINE", 5:"REFERENCE_ELECTRICAL_ANALYSIS",
    6:"ADAPTIVE_SHEET_PLANNER", 7:"EQUIPMENT_REQUIREMENTS", 8:"CAD_BLOCK_LIBRARY",
    9:"ARCHITECTURE_AWARE_PLACEMENT", 10:"LIGHTING_DESIGN", 11:"POWER_RECEPTACLE_DESIGN",
    12:"CIRCUIT_TOPOLOGY", 13:"ELECTRICAL_ROUTING", 14:"LOAD_CALCULATION",
    15:"CABLE_WIRE_BREAKER_SIZING", 16:"VOLTAGE_DROP_PHASE_BALANCE", 17:"PANELBOARD_ENGINE",
    18:"PANEL_SCHEDULE", 19:"SINGLE_LINE", 20:"RISER", 21:"GROUNDING_BONDING",
    22:"FIRE_ALARM_LOW_CURRENT", 23:"EQUIPMENT_REPRESENTATION", 24:"ANNOTATION_LAYOUT",
    25:"DETAIL_REQUIREMENT_RESOLVER", 26:"PARAMETRIC_DETAIL_LIBRARY", 27:"PLAN_DETAIL_LINKING",
    28:"PROJECT_SPECIFIC_LEGEND", 29:"GENERAL_NOTES", 30:"INDEPENDENT_DRAWING_COMPOSER",
    31:"PAPER_SPACE_ENGINE", 32:"SHEET_CONTENT_SIGNATURE", 33:"FAMILY_PURITY",
    34:"SEMANTIC_DUPLICATE_DETECTION", 35:"REFERENCE_SIMILARITY", 36:"VISUAL_QA", 37:"FINAL_FILE_REOPEN",
}

ACCEPTANCE_GATES = [
    "ARCHITECTURE_MODEL","PROJECT_MODEL","DESIGN_BASIS","SYSTEM_REQUIREMENTS","REFERENCE_TAXONOMY","SHEET_MANIFEST",
    "EQUIPMENT_REQUIREMENTS","EQUIPMENT_PLACEMENT","LIGHTING_DESIGN","POWER_DESIGN","CIRCUIT_TOPOLOGY","LOAD_CALCULATION",
    "CABLE_SIZING","BREAKER_SIZING","VOLTAGE_DROP","PHASE_BALANCE","PANEL_DESIGN","PANEL_SCHEDULE","SINGLE_LINE","RISER",
    "GROUNDING","DETAIL_COVERAGE","PLAN_DETAIL_LINKS","LEGEND","GENERAL_NOTES","SHEET_CONTENT_SIGNATURE","FAMILY_PURITY",
    "NO_SEMANTIC_DUPLICATES","PAPER_SPACE","REFERENCE_SIMILARITY","VISUAL_QA","FINAL_FILE_REOPEN",
]


def _gate(status="PASS", errors=None, warnings=None, **metrics):
    return {"status":status,"errors":errors or [],"warnings":warnings or [],"metrics":metrics}


def _required_requirements_resolved(requirements):
    unresolved=[k for k,v in requirements.items() if v.status in {EngineeringStatus.UNKNOWN,EngineeringStatus.INPUT_REQUIRED}]
    return _gate("PASS" if not unresolved else "PRELIMINARY",warnings=[f"system_scope_unresolved:{x}" for x in unresolved],unresolved=len(unresolved))


def _equipment_gate(requirements):
    unresolved=[r.id for r in requirements if r.quantity.status in {EngineeringStatus.UNKNOWN,EngineeringStatus.INPUT_REQUIRED}]
    preliminary=[r.id for r in requirements if r.quantity.status==EngineeringStatus.PRELIMINARY]
    status="PASS" if not unresolved and not preliminary else "PRELIMINARY"
    return _gate(status,warnings=[f"quantity_unresolved:{x}" for x in unresolved]+[f"quantity_preliminary:{x}" for x in preliminary],count=len(requirements))


def _design_family_gate(requirements, family_systems):
    rows=[r for r in requirements if r.system in family_systems]
    unresolved=[r.id for r in rows if r.quantity.status!=EngineeringStatus.FINAL]
    return _gate("PASS" if rows and not unresolved else "PRELIMINARY",warnings=[f"unresolved:{x}" for x in unresolved],requirements=len(rows))


def _load_gate(topology):
    unresolved=[c.id for c in topology.get("circuits",[]) if c.connected_load_w.status!=EngineeringStatus.FINAL or c.demand_load_w.status!=EngineeringStatus.FINAL]
    return _gate("PASS" if not unresolved else "PRELIMINARY",warnings=[f"load_unresolved:{x}" for x in unresolved],circuits=len(topology.get("circuits",[])))


def _sizing_gate(topology, attr):
    unresolved=[c.id for c in topology.get("circuits",[]) if getattr(c,attr).status!=EngineeringStatus.FINAL]
    return _gate("PASS" if not unresolved else "PRELIMINARY",warnings=[f"{attr}_unresolved:{x}" for x in unresolved])


def _grounding(requirements, inputs):
    req=requirements.get("GROUNDING")
    if req and req.required is False: return {"status":"NOT_REQUIRED","elements":[]}
    cfg=(inputs or {}).get("grounding") or {}
    required=("earth_electrode","main_earth_bar","protective_conductors","panel_grounding")
    missing=[x for x in required if x not in cfg]
    elements=[{"kind":x,"value":cfg.get(x),"status":"FINAL" if x in cfg else "INPUT_REQUIRED"} for x in required]
    return {"status":"PASS" if not missing else "PRELIMINARY","missing":missing,"elements":elements}


def _paper_space_gate(composition, manifest):
    return _gate("PASS" if composition.get("geometry_ownership")=="PAPER_SPACE_PER_SHEET" and composition.get("sheet_count")==len(manifest) else "FAIL",
                 errors=[] if composition.get("sheet_count")==len(manifest) else ["paper_space_manifest_count_mismatch"],sheet_count=composition.get("sheet_count"))


class ElectricalPipeline:
    def __init__(self, config: Optional[Dict[str,Any]]=None):
        self.config=config or {}

    def run(self, source: str|Path, output: str|Path) -> Dict[str,Any]:
        cfg=self.config; output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
        report={"version":"electrical-project-driven-v1.0","source":str(source),"output":str(output),"phases":PHASES,"gates":{},"production_safe":True}

        architecture=reconstruct_architecture(source); arch_gate=architecture.validate(); report["gates"]["ARCHITECTURE_MODEL"]=_gate(arch_gate["status"],arch_gate["errors"],architecture.issues,rooms=len(architecture.rooms),levels=len(architecture.levels),frames=len(architecture.frames))
        if arch_gate["status"]=="FAIL": return self._finish(report,{"architecture":architecture})

        project=build_project_model(architecture,cfg.get("project_inputs")); pg=project.validate(); report["gates"]["PROJECT_MODEL"]=_gate(pg["status"],pg["errors"],rooms=len(project.rooms),levels=len(project.levels))
        if pg["status"]=="FAIL": return self._finish(report,{"architecture":architecture,"project":project})

        basis=build_design_basis(cfg.get("design_basis"),cfg.get("applicable_rules",{}).get("design_basis"),cfg.get("manufacturer_data",{}).get("design_basis")); bg=basis.validate(); report["gates"]["DESIGN_BASIS"]=_gate(bg["status"],bg["errors"],[f"input_required:{x}" for x in bg["missing"]],missing=len(bg["missing"]))

        requirements=resolve_system_requirements(project,basis); report["gates"]["SYSTEM_REQUIREMENTS"]=_required_requirements_resolved(requirements)
        report["gates"]["REFERENCE_TAXONOMY"]=_gate("PASS",families=len(REFERENCE_TAXONOMY["observed"]["families"]),source=REFERENCE_TAXONOMY["source"])

        density=cfg.get("content_density") or {}; manifest=plan_sheets(project,requirements,density); report["gates"]["SHEET_MANIFEST"]=_gate("PASS" if manifest else "FAIL",errors=[] if manifest else ["empty_manifest"],sheet_count=len(manifest))

        equipment=resolve_equipment_requirements(project,requirements); equipment=resolve_quantities(equipment,project,basis,cfg.get("manufacturer_data")); report["gates"]["EQUIPMENT_REQUIREMENTS"]=_equipment_gate(equipment)
        report["gates"]["LIGHTING_DESIGN"]=_design_family_gate(equipment,{"LIGHTING","EMERGENCY_LIGHTING"})
        report["gates"]["POWER_DESIGN"]=_design_family_gate(equipment,{"GENERAL_RECEPTACLES","DEDICATED_POWER","KITCHEN_POWER","HVAC_POWER","ELEVATOR_POWER","PUMP_POWER"})

        placements=place_equipment(equipment,project,architecture,cfg.get("placement_rules")); pq=placement_qa(placements); report["gates"]["EQUIPMENT_PLACEMENT"]=_gate(pq["status"],pq["errors"],pq["warnings"],placements=pq["count"])

        loads=build_loads(equipment,placements); topology=build_circuit_topology(loads,project,basis,cfg.get("circuit_rules")); report["gates"]["CIRCUIT_TOPOLOGY"]=_gate(topology["status"],topology["errors"],circuits=len(topology["circuits"]),loads=len(loads))
        report["gates"]["LOAD_CALCULATION"]=_load_gate(topology)

        routing=route_circuits(topology,placements,architecture,(cfg.get("circuit_rules") or {}).get("panel_locations")); rq=routing_qa(routing)
        # Routing is part of topology acceptance even though it does not have a separate named final gate in the user list.
        report["routing_qa"]=_gate(rq["status"],rq["errors"],rq["warnings"],routes=rq["route_count"])

        balance=calculate_currents_and_phase_balance(topology,basis,cfg.get("calculation_rules")); report["gates"]["PHASE_BALANCE"]=_gate(balance["status"],balance["errors"],balance["warnings"],values=balance.get("phase_balance_pct"))
        sizing=size_circuits(topology,basis,cfg.get("sizing_tables")); report["gates"]["CABLE_SIZING"]=_sizing_gate(topology,"cable"); report["gates"]["BREAKER_SIZING"]=_sizing_gate(topology,"breaker")
        vd=calculate_voltage_drop(topology,basis,cfg.get("voltage_drop_rules")); report["gates"]["VOLTAGE_DROP"]=_gate(vd["status"],vd["errors"],vd["warnings"])

        panel_unresolved=[p.id for p in topology["panels"] if p.location.status!=EngineeringStatus.FINAL or p.demand_load_w.status!=EngineeringStatus.FINAL]
        report["gates"]["PANEL_DESIGN"]=_gate("PASS" if topology["panels"] and not panel_unresolved else "PRELIMINARY",warnings=[f"panel_unresolved:{x}" for x in panel_unresolved],panels=len(topology["panels"]))
        schedules=panel_schedules(topology); sq=schedule_sync_qa(topology,schedules); report["gates"]["PANEL_SCHEDULE"]=_gate(sq["status"],sq["errors"],rows=sum(len(x) for x in schedules.values()))
        sld=build_single_line(topology); report["gates"]["SINGLE_LINE"]=_gate("PASS" if len(sld["nodes"])>=2 else "FAIL",nodes=len(sld["nodes"]),edges=len(sld["edges"]))
        riser=build_riser(topology,project); report["gates"]["RISER"]=_gate("PASS" if riser["status"] in {"PASS","NOT_REQUIRED"} else riser["status"],transitions=len(riser.get("transitions") or []))
        grounding=_grounding(requirements,cfg.get("optional_system_inputs")); report["gates"]["GROUNDING"]=_gate("PASS" if grounding["status"] in {"PASS","NOT_REQUIRED"} else grounding["status"],warnings=[f"grounding_input_required:{x}" for x in grounding.get("missing",[])])
        optional=build_optional_system_models(requirements,cfg.get("optional_system_inputs"))

        legend=build_project_legend(equipment,placements,[]); report["gates"]["LEGEND"]=_gate("PASS" if legend or not placements else "FAIL",entries=len(legend))
        details=resolve_details(requirements,used_symbol_types(equipment,placements),cfg.get("detail_parameters")); detail_missing=[d["detail_id"] for d in details if d["status"]!="FINAL"]
        report["gates"]["DETAIL_COVERAGE"]=_gate("PASS" if not detail_missing else "PRELIMINARY",warnings=[f"detail_parameters_missing:{x}" for x in detail_missing],details=len(details))
        links=link_plan_details(manifest,details); dlq=detail_link_qa(details,links); report["gates"]["PLAN_DETAIL_LINKS"]=_gate(dlq["status"],dlq["errors"],[f"unreferenced_detail:{x}" for x in dlq.get("unreferenced_details",[])],links=len(links))
        notes=build_general_notes(basis,requirements); report["gates"]["GENERAL_NOTES"]=_gate("PASS" if notes else "FAIL",notes=len(notes))

        calculations={"topology":topology,"phase_balance":balance,"sizing":sizing,"voltage_drop":vd,"grounding":grounding,"optional_systems":optional}
        composition=compose_drawing_set(output,architecture,manifest,equipment,placements,routing,schedules,sld,riser,legend,notes,details,links,calculations,
                                        project_name=str(project.project.get("project_name",EvidenceValue()).value or "EngiTools Electrical Project"),
                                        paper=tuple(cfg.get("paper_mm") or (420.0,297.0)),drawing_status="PRELIMINARY")
        report["gates"]["PAPER_SPACE"]=_paper_space_gate(composition,manifest)
        cs=content_signature_qa(manifest,composition["signatures"]); report["gates"]["SHEET_CONTENT_SIGNATURE"]=_gate(cs["status"],cs["errors"],sheets=len(cs["sheets"]))
        fp=family_purity_qa(output,manifest); report["gates"]["FAMILY_PURITY"]=_gate(fp["status"],fp["errors"])
        du=semantic_duplicate_qa(output,manifest); report["gates"]["NO_SEMANTIC_DUPLICATES"]=_gate(du["status"],du["errors"])
        rs=reference_similarity_qa(manifest,composition["signatures"],float(cfg.get("reference_similarity_threshold",.6))); report["gates"]["REFERENCE_SIMILARITY"]=_gate(rs["status"],rs["errors"],family_scores=rs["family_scores"])
        vq=visual_qa(output,manifest,tuple(cfg.get("paper_mm") or (420.0,297.0))); report["gates"]["VISUAL_QA"]=_gate(vq["status"],vq["errors"],vq["warnings"],sheets=len(vq["sheets"]))
        reopen=final_reopen_qa(output,manifest,composition["signatures"],output.parent/(output.stem+"_renders"),tuple(cfg.get("paper_mm") or (420.0,297.0))); report["gates"]["FINAL_FILE_REOPEN"]=_gate(reopen["status"],reopen["errors"],file_size_bytes=reopen.get("file_size_bytes"),renders=len(reopen.get("renders") or []))
        return self._finish(report,{"architecture":architecture,"project":project,"basis":basis,"requirements":requirements,"manifest":manifest,"equipment":equipment,"placements":placements,"routing":routing,"topology":topology,"schedules":schedules,"single_line":sld,"riser":riser,"grounding":grounding,"legend":legend,"details":details,"links":links,"notes":notes,"composition":composition})

    def _finish(self, report, data):
        # Any FAIL blocks; any PRELIMINARY/INPUT_REQUIRED gate blocks final acceptance too.
        for name in ACCEPTANCE_GATES:
            report["gates"].setdefault(name,_gate("PRELIMINARY",warnings=["gate_not_reached"]))
        hard_fail=[k for k,v in report["gates"].items() if v.get("status")=="FAIL"]
        incomplete=[k for k,v in report["gates"].items() if v.get("status") not in {"PASS","NOT_REQUIRED"}]
        report["acceptance"]={"status":"PASS" if not hard_fail and not incomplete else "NOT_ACCEPTED","hard_fail_gates":hard_fail,"incomplete_gates":incomplete,
                              "production_release_allowed":False if hard_fail or incomplete else bool(self.config.get("explicit_release_authorization",False))}
        report["data"]=serialize(data)
        return report


def run_electrical_pipeline(source, output, config=None):
    return ElectricalPipeline(config).run(source,output)
