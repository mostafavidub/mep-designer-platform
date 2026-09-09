"""Ordered fail-closed orchestration for the the canonical Mechanical phases."""
from .mechanical_coordination import build_coordination_model, route_25d
from .mechanical_manufacturer_selector import select_equipment
from .manufacturer_database import build_manufacturer_database
from .calculation_book import build_calculation_book
from .annotation_solver import solve_annotations
from .mechanical_documentation import (generate_detail, generate_final_parametric_detail, generate_riser_from_network, documentation_gate,
                                           required_detail_families, generate_annotation_support)
from .mechanical_submission_qa import evaluate_submission_readiness, submission_gate, validate_target_design_packages
from .engineering_feedback import process_engineer_redlines
from .quality_acceptance import evaluate_quality_targets
from .mechanical_target_design import build_target_design_packages


def _pmm_v3_traceability_required(payload: dict) -> bool:
    pmm = payload.get("project_mechanical_model") or {}
    return pmm.get("schema") == "project-mechanical-model/v3" and (
        (pmm.get("traceability_contract") or {}).get("policy") == "NO_ORPHAN_ENGINEERING_OUTPUT"
    )


def run_pipeline(payload: dict) -> dict:
    phases={}
    target_packages=payload.get("target_design_packages")
    if payload.get("target_design_inputs") is not None:
        built=build_target_design_packages(payload.get("target_design_inputs") or {})
        phases["target_design_build"]=built
        if built["status"] != "PASS":return _blocked(phases,"target_design_build")
        target_packages=built["packages"]
    required_targets={"heating","gas","split_ac","exhaust","ventilation_exhaust","rainwater","roof_rainwater"}.intersection(
        key for key,value in (payload.get("active_systems") or {}).items() if value
    )
    if target_packages is not None or required_targets:
        phases["target_design_packages"]=validate_target_design_packages(target_packages)
        if phases["target_design_packages"]["status"] != "PASS":
            return _blocked(phases,"target_design_packages")
    if payload.get("manufacturer_database_records") is not None:
        database=build_manufacturer_database(payload.get("manufacturer_database_records") or [])
        phases["manufacturer_database"]=database
        if database["status"] != "PASS": return _blocked(phases,"manufacturer_database")
    model=build_coordination_model(payload)
    route=route_25d(payload.get("route_request") or {},model) if model["status"] == "PASS" else {"status":"INPUT_REQUIRED","selected":None,"missing_inputs":model["missing_inputs"]}
    phases["coordination"]={"status":"PASS" if model["status"] == route["status"] == "PASS" else route["status"],"model":model,"route":route}
    if phases["coordination"]["status"] != "PASS": return _blocked(phases,"coordination")
    selection=select_equipment(payload.get("equipment_requirements") or {},payload.get("manufacturer_catalogue") or [],route)
    phases["manufacturer"]=selection
    if selection["status"] != "PASS": return _blocked(phases,"manufacturer")
    if payload.get("equipment_selection_checks") is not None:
        book=build_calculation_book(payload.get("calculation_rows") or [],payload.get("equipment_selection_checks") or [],
                                    payload.get("declared_equipment_ids") or [])
        phases["calculation_book"]=book
        if book["status"] != "PASS": return _blocked(phases,"calculation_book")
    details=[generate_detail(x) for x in payload.get("detail_specs") or []]
    details.extend(generate_final_parametric_detail(x) for x in payload.get("final_parametric_detail_specs") or [])
    riser=generate_riser_from_network(payload.get("network_graph") or {})
    require_traceability=_pmm_v3_traceability_required(payload)
    calculation_rows=payload.get("calculation_rows")
    if require_traceability and calculation_rows is None:
        calculation_rows=[]
    active_systems=payload.get("active_systems") or {}
    mandatory_families=required_detail_families(active_systems)
    annotation_support=None
    if payload.get("annotation_solver") is not None:
        request=payload.get("annotation_solver") or {}
        layout=solve_annotations(request.get("plan") or {},request.get("requests") or [],request.get("config") or {})
        phases["annotation_solver"]=layout
        if layout["status"] != "PASS": return _blocked(phases,"annotation_solver")
        identity_annotations=[{**row,"network_edge_id":row.get("source_id")} for row in layout["annotations"]]
        annotation_support=generate_annotation_support(payload.get("network_graph") or {},identity_annotations,
                                                       layout.get("enlarged_plans") or [])
    elif "annotations" in payload or "enlarged_plans" in payload:
        annotation_support=generate_annotation_support(payload.get("network_graph") or {},
                                                       payload.get("annotations") or [],
                                                       payload.get("enlarged_plans") or [])
    doc_gate=documentation_gate(details,riser,calculation_rows if require_traceability or calculation_rows is not None else None,
                                mandatory_families,annotation_support)
    phases["documentation"]={**doc_gate,"details":details,"riser":riser,
                             "pmm_traceability_required":require_traceability}
    if phases["documentation"]["status"] != "PASS": return _blocked(phases,"documentation")
    phases["submission_quality"]=evaluate_submission_readiness(payload.get("submission_checks"))
    if phases["submission_quality"]["status"] != "PASS": return _blocked(phases,"submission_quality")
    phases["engineer_feedback"]=process_engineer_redlines(payload.get("engineer_review"))
    if phases["engineer_feedback"]["status"] != "PASS": return _blocked(phases,"engineer_feedback")
    quality_metrics=dict(payload.get("quality_metrics") or {})
    if "major_redlines" not in quality_metrics:
        quality_metrics["major_redlines"]=phases["engineer_feedback"].get("open_major_redlines")
    phases["quality_targets"]=evaluate_quality_targets(quality_metrics)
    if phases["quality_targets"]["status"] != "PASS": return _blocked(phases,"quality_targets")
    phases["golden"]=payload.get("golden_result") or {"status":"MISSING"}
    gate=submission_gate(phases)
    return {"status":gate["status"],"blocked_at":None if gate["release_allowed"] else "golden","phases":phases,"submission":gate}


def _blocked(phases: dict, name: str) -> dict:
    return {"status":"INPUT_REQUIRED" if phases[name]["status"] in {"INPUT_REQUIRED","PRE_SUBMISSION"} else "FAIL",
            "blocked_at":name,"phases":phases,"submission":{"status":"FAIL","release_allowed":False,"errors":[f"{name}:{phases[name]['status']}"]}}
