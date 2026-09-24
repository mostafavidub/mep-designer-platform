"""Canonical professional Dimension Engine shadow/canonical orchestration.

The generation-2 contract is shadow-first. It may compute complete intents and QA, but callers must
explicitly request materialization; current Mechanical visible output remains v1
until benchmark/acceptance promotion.
"""
from __future__ import annotations
from collections import Counter

from .dimension_reference_model import build_reference_model_v2
from .dimension_requirement_engine import (
    collect_profile_elements,generate_setout_candidates,generate_context_intents,
    generate_governed_requirement_intents,
)
from .dimension_determinacy_solver import minimum_constraint_set
from .dimension_source_reconciliation import reconcile_source_dimensions
from .dimension_redundancy_optimizer import optimize_dimensions
from .dimension_placement_solver import solve_dimension_placement
from .dimension_qa import construction_determinacy_gate
from .dimension_intent_model import validate_intents
from .semantic_dimension_engine import extract_source_dimension_registry,_display_number


def _legacy_reference_catalog(v2_model):
    kind_map={
      "GRID_AXIS":"GRID_AXIS","PROPERTY_BOUNDARY":"PROPERTY_BOUNDARY","SHAFT_FACE":"SHAFT_FACE",
      "STAIR_CORE_FACE":"STAIR_CORE_FACE","OPENING_JAMB":"OPENING_JAMB","STRUCTURAL_FACE":"STRUCTURAL_FACE",
      "WALL_CORE_FACE":"WALL_FACE","WALL_INNER_FINISH_FACE":"WALL_FACE","WALL_OUTER_FINISH_FACE":"WALL_FACE",
      "BUILDING_ENVELOPE_FACE":"WALL_FACE",
    }
    rows=[]
    for r in v2_model.get("references") or []:
        g=r.get("geometry") or {}
        if g.get("type")!="SEGMENT" or r.get("subfeature") not in kind_map:continue
        row={"id":r["id"],"kind":kind_map[r["subfeature"]],"a":tuple(g["a"]),"b":tuple(g["b"]),
             "priority":int(r.get("priority",50)),"source":"v2_reference_model"}
        if r.get("subfeature")=="BUILDING_ENVELOPE_FACE":
            row["envelope_candidate"]=True
        rows.append(row)
    return rows


def _apply_units_and_display(intents,source_registry):
    unit=(source_registry or {}).get("unit_evidence") or {};scale=unit.get("effective_scale_to_m")
    rows=[]
    for r in intents or []:
        x=dict(r)
        if x.get("engineering_value_m") is None and scale is not None:
            x["engineering_value_m"]=float(x.get("measured_value") or 0.0)*float(scale)
        if not x.get("display_value"):x["display_value"]=_display_number(x.get("measured_value"))
        x["effective_scale_to_m"]=scale;x["unit_evidence_source"]=unit.get("source")
        rows.append(x)
    return rows


def _stable_reference_ids(model):
    allowed={"GRID_AXIS","GRID_INTERSECTION","STRUCTURAL_CENTERLINE","STRUCTURAL_FACE",
             "WALL_CORE_FACE","WALL_INNER_FINISH_FACE","WALL_OUTER_FINISH_FACE",
             "BUILDING_ENVELOPE_FACE","PROPERTY_BOUNDARY","SHAFT_FACE","STAIR_CORE_FACE","OPENING_JAMB"}
    return [r["id"] for r in model.get("references") or [] if r.get("subfeature") in allowed and float(r.get("confidence",0))>=.85]


def shadow_compare(v1_report,v2_selected,v2_qa):
    v1=list((v1_report or {}).get("materialized") or [])
    p1=Counter(str(r.get("purpose") or "UNKNOWN") for r in v1)
    p2=Counter(str(r.get("purpose") or "UNKNOWN") for r in v2_selected or [])
    purposes=sorted(set(p1)|set(p2))
    return {
      "mode":"SHADOW","visible_output_changed":False,
      "v1_count":len(v1),"v2_count":len(v2_selected or []),
      "purpose_delta":{p:{"v1":p1[p],"v2":p2[p],"delta":p2[p]-p1[p]} for p in purposes},
      "v1_missing_determinacy":len((v1_report or {}).get("missing_determinacy") or []),
      "v2_missing_critical":len((v2_qa or {}).get("critical_missing") or []),
      "v2_status":(v2_qa or {}).get("status"),
    }


def run_dimension_engine_shadow(doc,plan,architecture,pipeline,profile,board,v1_report=None,
        wall_reference_basis=None,governed_requirements=None,level=None):
    plan_id=plan.get("plan_id");bounds=tuple(plan["bounds"])
    ref_model=build_reference_model_v2(doc,bounds,architecture=architecture,plan_id=plan_id,level=level,wall_reference_basis=wall_reference_basis)
    source_registry=extract_source_dimension_registry(doc,bounds,architecture=architecture,plan_id=plan_id,
                                                     reference_catalog=_legacy_reference_catalog(ref_model))
    elements_result=collect_profile_elements(profile,architecture=architecture,pipeline=pipeline,plan_id=plan_id)
    candidate_result=generate_setout_candidates(elements_result.get("elements") or [],ref_model,profile)
    context=generate_context_intents(ref_model,profile)
    governed=generate_governed_requirement_intents(governed_requirements or [],ref_model,profile,plan_id)
    candidates=_apply_units_and_display(context+candidate_result.get("intents",[])+governed.get("intents",[]),source_registry)
    intent_errors=validate_intents([{k:v for k,v in r.items() if k in {
        "id","purpose","role","reference_a","reference_b","measured_value","engineering_value_m","drawing_profile",
        "plan_id","level","priority_class","required","rule_id","source_kind","source_dimension_id","display_value",
        "orientation","datum_class","evidence"}} for r in candidates])
    stable=_stable_reference_ids(ref_model)
    minimum=minimum_constraint_set(candidates,elements_result.get("elements") or [],stable)
    redundancy=optimize_dimensions(minimum["selected"])
    selected=redundancy["selected"]
    reconciliation=reconcile_source_dimensions(source_registry,selected)
    placement=solve_dimension_placement(selected,bounds,board)
    qa=construction_determinacy_gate(ref_model,elements_result.get("elements") or [],minimum["determinacy"],
        reconciliation,redundancy,placement,selected,source_registry=source_registry,profile=profile)
    if governed.get("errors"):qa["errors"]=sorted(set(qa.get("errors",[])+["GOVERNED_DIMENSION_REQUIREMENT_INVALID"]));qa["status"]="FAIL"
    if intent_errors:qa["errors"]=sorted(set(qa.get("errors",[])+["DIMENSION_INTENT_SCHEMA_INVALID"]));qa["status"]="FAIL"
    if candidate_result.get("human_review"):
        qa["human_review"]=list(qa.get("human_review") or [])+candidate_result["human_review"]
        if qa["status"]=="PASS":qa["status"]="HUMAN_REVIEW_REQUIRED"
    return {
      "version":"planha-dimension-engine/2","mode":"SHADOW","profile":profile,"plan_id":plan_id,
      "reference_model":ref_model,"source_registry":source_registry,"elements":elements_result,
      "candidate_generation":candidate_result,"governed_requirements":governed,"intent_errors":intent_errors,
      "selected_intents":selected,"redundancy":redundancy,"determinacy":minimum["determinacy"],
      "reconciliation":reconciliation,"placement":placement,"qa":qa,
      "shadow_compare":shadow_compare(v1_report,selected,qa),
    }
