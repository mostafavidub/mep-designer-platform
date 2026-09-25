"""Fail-closed Architectural Dimension QA 100 contract."""
from __future__ import annotations
from .chains import closure_check
from .determinacy import analyze_overdimensioning
from .profiles import mandatory_for
from .model import reference_class

CONTROL_IDS=[
"unit_basis_known","semantic_references_valid","reference_subfeatures_valid","drawing_profile_applied",
"mandatory_overall_complete","required_grid_complete","setout_determinacy_complete","partition_chains_complete",
"opening_dimensions_valid","stair_dimensions_valid","shaft_core_dimensions_valid","site_setback_dimensions_valid",
"code_dimensions_traceable","check_dimensions_valid","chain_closure_valid","no_critical_under_dimensioning",
"no_accidental_over_dimensioning","no_semantic_duplicates","no_source_value_corruption","source_evidence_preserved",
"no_unresolved_critical_override","no_zero_generated_dimension","collision_free_placement","extension_line_readability",
"correct_dimension_tiers","correct_local_coordinate_frame","exact_file_reopen_pass","dimension_intent_dxf_identity",
"generated_not_reingested_as_source","visual_qa_pass",
]

def _control(cid,status="PASS",errors=None):
    return {"id":cid,"status":status,"errors":list(errors or [])}

def evaluate_architectural_dimension_qa(*,profile,intents,references,reference_report=None,frames=None,
                                       determinacy=None,unit_evidence=None,source_preservation=None,
                                       exact_file=None,visual_qa=None,placement=None,stage="FINAL"):
    refs=list(references or []); intents=list(intents or [])
    controls=[]; mandatory=mandatory_for(profile)
    unit_ok=(unit_evidence or {}).get("effective_scale_to_m") is not None
    controls.append(_control("unit_basis_known","PASS" if unit_ok else "INPUT_REQUIRED",[] if unit_ok else ["DIMENSION_UNIT_BASIS_REQUIRED"]))
    ref_errors=(reference_report or {}).get("errors") or []
    controls.append(_control("semantic_references_valid","FAIL" if ref_errors else "PASS",ref_errors))
    bad_sub=[r.get("id") for r in refs if not r.get("subfeature") and r.get("kind") not in {"PLAN_EDGE"}]
    controls.append(_control("reference_subfeatures_valid","FAIL" if bad_sub else "PASS",bad_sub))
    controls.append(_control("drawing_profile_applied","PASS" if profile else "FAIL",[] if profile else ["DRAWING_PROFILE_REQUIRED"]))
    purposes={r.get("purpose") for r in intents}
    controls.append(_control("mandatory_overall_complete","PASS" if "BUILDING_OVERALL" not in mandatory or "BUILDING_OVERALL" in purposes else "FAIL",[] if "BUILDING_OVERALL" not in mandatory or "BUILDING_OVERALL" in purposes else ["BUILDING_OVERALL_REQUIRED"]))
    grid_refs=any(r.get("subfeature")=="GRID_AXIS" for r in refs)
    controls.append(_control("required_grid_complete","PASS" if not grid_refs or "GRID" in purposes else "FAIL",[] if not grid_refs or "GRID" in purposes else ["GRID_DIMENSIONS_REQUIRED"]))
    det=determinacy or {}
    controls.append(_control("setout_determinacy_complete","PASS" if det.get("status")=="PASS" else "FAIL",det.get("missing_reference_ids") or []))
    wall_chains=[r for r in intents if r.get("purpose")=="WALL_SETOUT"]
    walls=[r for r in refs if r.get("kind")=="WALL"]
    controls.append(_control("partition_chains_complete","PASS" if not walls or wall_chains else "FAIL",[] if not walls or wall_chains else ["PARTITION_CHAIN_REQUIRED"]))
    for cid,purpose in (("opening_dimensions_valid","OPENING"),("stair_dimensions_valid","STAIR_CORE"),("shaft_core_dimensions_valid","SHAFT")):
        applicable={"OPENING":("DOOR","WINDOW","OPENING"),"STAIR_CORE":("STAIR",),"SHAFT":("SHAFT","LIGHTWELL")}[purpose]
        has=any(r.get("kind") in applicable for r in refs)
        controls.append(_control(cid,"PASS" if not has or purpose in purposes else "FAIL",[] if not has or purpose in purposes else [purpose+"_DIMENSION_REQUIRED"]))
    site_profile=str(profile)=="SITE_PLAN"
    controls.append(_control("site_setback_dimensions_valid","PASS" if not site_profile or {"PROPERTY","SETBACK"}.issubset(purposes) else "FAIL",[] if not site_profile or {"PROPERTY","SETBACK"}.issubset(purposes) else ["PROPERTY_AND_SETBACK_REQUIRED"]))
    bad_code=[r.get("id") for r in intents if r.get("purpose")=="CODE_CLEARANCE" and not r.get("governance_rule_id")]
    controls.append(_control("code_dimensions_traceable","FAIL" if bad_code else "PASS",bad_code))
    bad_check=[r.get("id") for r in intents if r.get("purpose")=="CHECK" and not r.get("check_group_id")]
    controls.append(_control("check_dimensions_valid","FAIL" if bad_check else "PASS",bad_check))
    closure=closure_check(intents)
    controls.append(_control("chain_closure_valid",closure["status"],closure["errors"]))
    controls.append(_control("no_critical_under_dimensioning","PASS" if det.get("status")=="PASS" else "FAIL",det.get("missing_reference_ids") or []))
    over=analyze_overdimensioning(intents)
    controls.append(_control("no_accidental_over_dimensioning","PASS" if over["status"]=="PASS" else "FAIL",over["errors"]))
    keys=[];dups=[]
    for r in intents:
        key=(r.get("purpose"),tuple(sorted([str((r.get("reference_a") or {}).get("id") or ""),str((r.get("reference_b") or {}).get("id") or "")])))
        if key in keys and r.get("purpose")!="CHECK":dups.append(r.get("id"))
        keys.append(key)
    controls.append(_control("no_semantic_duplicates","FAIL" if dups else "PASS",dups))
    sp=source_preservation or {}
    sp_missing=not bool(source_preservation)
    corruption=sp.get("source_value_corruption") or []
    controls.append(_control("no_source_value_corruption",
                             "INPUT_REQUIRED" if sp_missing else ("FAIL" if corruption else "PASS"),
                             corruption if corruption else ([] if not sp_missing else ["SOURCE_PRESERVATION_EVIDENCE_REQUIRED"])))
    source_status=("INPUT_REQUIRED" if sp_missing else ("PASS" if sp.get("pass") else "FAIL"))
    controls.append(_control("source_evidence_preserved",source_status,
                             sp.get("missing_critical_source_dimensions") or ([] if not sp_missing else ["SOURCE_PRESERVATION_EVIDENCE_REQUIRED"])))
    conflicts=sp.get("critical_source_conflicts") or []
    controls.append(_control("no_unresolved_critical_override","FAIL" if conflicts else "PASS",conflicts))
    zeros=[r.get("id") for r in intents if r.get("source_kind")!="SOURCE_REGENERATED" and float(r.get("measured_value") or 0)<=1e-12]
    controls.append(_control("no_zero_generated_dimension","FAIL" if zeros else "PASS",zeros))
    placement=placement or {}
    collisions=placement.get("collision_intents") or []
    controls.append(_control("collision_free_placement","FAIL" if collisions else ("INPUT_REQUIRED" if stage=="FINAL" and not placement else "PASS"),collisions))
    ext=placement.get("extension_line_errors") or []
    controls.append(_control("extension_line_readability","FAIL" if ext else ("INPUT_REQUIRED" if stage=="FINAL" and not placement else "PASS"),ext))
    bad_tiers=[r.get("id") for r in intents if r.get("purpose") in {"BUILDING_OVERALL","GRID","PROPERTY","SETBACK"} and r.get("tier") is None]
    controls.append(_control("correct_dimension_tiers","FAIL" if bad_tiers else "PASS",bad_tiers))
    frame_bad=[f.get("id") for f in (frames or []) if f.get("status")!="PASS"]
    controls.append(_control("correct_local_coordinate_frame","FAIL" if frame_bad else "PASS",frame_bad))
    exact=exact_file or {}
    exact_status="PASS" if exact.get("status")=="PASS" and exact.get("exact_file_reopened") else ("INPUT_REQUIRED" if stage!="FINAL" or not exact else "FAIL")
    controls.append(_control("exact_file_reopen_pass",exact_status,exact.get("errors") or []))
    controls.append(_control("dimension_intent_dxf_identity",exact_status,exact.get("errors") or []))
    reingest=exact.get("generated_reingested_as_source") or []
    controls.append(_control("generated_not_reingested_as_source","FAIL" if reingest else ("INPUT_REQUIRED" if stage=="FINAL" and not exact else "PASS"),reingest))
    visual=visual_qa or {}
    visual_status="PASS" if visual.get("status")=="PASS" else ("INPUT_REQUIRED" if stage!="FINAL" or not visual else "FAIL")
    controls.append(_control("visual_qa_pass",visual_status,visual.get("errors") or visual.get("critical_defects") or []))
    assert [c["id"] for c in controls]==CONTROL_IDS
    status="FAIL" if any(c["status"]=="FAIL" for c in controls) else ("INPUT_REQUIRED" if any(c["status"]=="INPUT_REQUIRED" for c in controls) else "PASS")
    return {"contract":"architectural-dimension-qa/1","status":status,"controls":controls,
            "all_controls_pass":all(c["status"]=="PASS" for c in controls),
            "release_allowed":status=="PASS" and stage=="FINAL",
            "errors":[e for c in controls for e in c["errors"]]}
