"""Construction Determinacy Gate for Dimension Engine v2."""
from __future__ import annotations
from collections import defaultdict


def _rid(ref):return str((ref or {}).get("id") or (ref or {}).get("element_id") or "")


def validate_chain_closure(intents,tolerance_m=1e-6):
    """Only close chains inside the same explicit datum class and chain_id."""
    groups=defaultdict(list);errors=[]
    for row in intents or []:
        cid=row.get("chain_id");datum=row.get("datum_class")
        if cid and datum:groups[(cid,datum)].append(row)
    for (cid,datum),rows in groups.items():
        parts=[r for r in rows if r.get("chain_role")=="PART"]
        totals=[r for r in rows if r.get("chain_role")=="TOTAL"]
        if not parts or not totals:continue
        p=sum(float(r.get("engineering_value_m") or 0.0) for r in parts)
        for total in totals:
            t=float(total.get("engineering_value_m") or 0.0)
            if abs(p-t)>tolerance_m:errors.append({"chain_id":cid,"datum_class":datum,"parts_m":p,"total_m":t,"reason":"CHAIN_CLOSURE_FAILURE"})
    return errors


def construction_determinacy_gate(reference_model,elements,determinacy,reconciliation,redundancy,placement,intents,source_registry=None,profile=None):
    errors=[];reviews=[]
    if reference_model.get("errors"):errors.append("REFERENCE_MODEL_INVALID")
    ref_reviews=list(reference_model.get("human_review") or [])
    used_subfeatures={str((r.get("reference_a") or {}).get("subfeature") or "") for r in intents or []}|{str((r.get("reference_b") or {}).get("subfeature") or "") for r in intents or []}
    wall_review="WALL_REFERENCE_BASIS_REQUIRED" in ref_reviews
    wall_used=bool(used_subfeatures & {"WALL_CORE_FACE","WALL_INNER_FINISH_FACE","WALL_OUTER_FINISH_FACE"})
    if wall_review and profile!="ARCHITECTURAL_FLOOR_PLAN" and not wall_used:
        ref_reviews=[r for r in ref_reviews if r!="WALL_REFERENCE_BASIS_REQUIRED"]
    reviews.extend(ref_reviews)
    critical_missing=determinacy.get("critical_missing") or []
    if critical_missing:errors.append("UNDER_DETERMINED_P0_P1_GEOMETRY")
    if redundancy.get("status")=="FAIL":errors.append("CONTRADICTORY_DIMENSION_DEFINITION")
    if int(redundancy.get("duplicate_count") or 0):reviews.append("SEMANTIC_DUPLICATES_REMOVED")
    if placement.get("status")!="PASS":errors.append("UNRESOLVED_DIMENSION_PLACEMENT")
    if reconciliation.get("status")!="PASS":reviews.append("SOURCE_RECONCILIATION_REVIEW_REQUIRED")
    chain_errors=validate_chain_closure(intents)
    if chain_errors:errors.append("CHAIN_CLOSURE_FAILURE")

    # Over-dimensioning is evaluated against explicit element DOFs, not raw count.
    over=[]
    by_element=defaultdict(set)
    for r in intents or []:
        if r.get("role")!="SETOUT" or not r.get("constraint_dof"):continue
        eid=str(((r.get("reference_a") or {}).get("element_id") or ""))
        if eid:by_element[eid].add(str(r.get("constraint_dof")))
    for e in elements or []:
        eid=str(e.get("id") or "");required=set(e.get("required_dofs") or [])
        extra=sorted(by_element.get(eid,set())-required)
        if extra:over.append({"element_id":eid,"extra_dofs":extra})
    if over:errors.append("OVER_DIMENSIONED_ELEMENT_CONSTRAINTS")

    envelope_valid=(reference_model.get("envelope") or {}).get("status")=="PASS" and bool((reference_model.get("envelope") or {}).get("envelopes"))
    overall_required=profile in {"ARCHITECTURAL_FLOOR_PLAN","MECHANICAL_PLAN","PARKING_PLAN","ROOF_PLAN"} and envelope_valid
    overall_present=any(r.get("purpose")=="BUILDING_OVERALL" and r.get("role")=="CHECK" for r in intents or [])
    if overall_required and not overall_present:errors.append("MISSING_BUILDING_OVERALL_CHECK")

    source_coverage_ok=True
    if source_registry:
        source_count=len(source_registry.get("records") or [])
        reconciled_count=len(reconciliation.get("rows") or [])
        source_coverage_ok=source_count==reconciled_count
        if not source_coverage_ok:errors.append("SOURCE_DIMENSION_RECONCILIATION_INCOMPLETE")
        critical_conflicts=[r for r in source_registry.get("records") or [] if r.get("critical") and r.get("conflict")]
        if critical_conflicts:errors.append("CRITICAL_SOURCE_DIMENSION_CONFLICT")
        unit=(source_registry.get("unit_evidence") or {})
        if intents and unit.get("effective_scale_to_m") is None:errors.append("DIMENSION_UNIT_BASIS_REQUIRED")
    invalid_intents=[]
    for r in intents or []:
        if not _rid(r.get("reference_a")) or not _rid(r.get("reference_b")):invalid_intents.append(r.get("id"))
        if r.get("purpose")=="CODE_CLEARANCE" and not r.get("rule_id"):invalid_intents.append(r.get("id"))
    if invalid_intents:errors.append("INVALID_SEMANTIC_REFERENCE_OR_RULE")
    return {
      "version":"planha-dimension-v2-qa/1","status":"FAIL" if errors else ("HUMAN_REVIEW_REQUIRED" if reviews else "PASS"),
      "errors":sorted(set(errors)),"human_review":reviews,"critical_missing":critical_missing,
      "chain_errors":chain_errors,"invalid_intent_ids":sorted(set(x for x in invalid_intents if x)),
      "metrics":{
        "references":len(reference_model.get("references") or []),"critical_elements":sum(1 for e in elements or [] if e.get("priority_class") in {"P0","P1"}),
        "under_determined":len(critical_missing),"source_review":len(reconciliation.get("human_review") or []),
        "duplicates_removed":int(redundancy.get("duplicate_count") or 0),"placement_failures":int(placement.get("collision_count") or 0),
        "over_dimensioned_elements":len(over),"source_reconciliation_complete":source_coverage_ok,
        "overall_check_required":overall_required,"overall_check_present":overall_present,
      },
      "policy":"printed-drawing construction determinacy, not DIMENSION entity count, is the acceptance authority",
    }
