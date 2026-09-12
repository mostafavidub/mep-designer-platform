"""Fail-closed questionnaire and immutable design-basis acceptance."""
from __future__ import annotations

from hashlib import sha256
import json
import math


CONTRACT_VERSION = "questionnaire-design-basis/1"
CONTROL_WEIGHTS = {
    "architecture_fact_extraction": 5, "fact_source_classification": 5,
    "system_scope_resolution": 7, "dynamic_question_applicability": 5,
    "governed_prior_answer_reuse": 5, "cross_project_answer_scope": 5,
    "canonical_answer_normalization": 5, "numeric_value_unit_validation": 7,
    "climate_location_basis": 6, "system_engineering_basis": 8,
    "equipment_owner_preferences": 5, "regulatory_project_facts": 5,
    "architecture_answer_consistency": 6, "question_dependency_graph": 4,
    "human_readable_basis_summary": 4, "immutable_approved_revision": 7,
    "persistence_and_destructive_qa": 5, "generation_release_gate": 6,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100


def _stable(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _positive(value):
    try: return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError): return False


def evaluate_questionnaire_design_basis(context):
    """Require explicit, attributable and revision-locked design facts."""
    context=context or {}; missing={k:[] for k in CONTROL_WEIGHTS}; errors={k:[] for k in CONTROL_WEIGHTS}
    architecture=context.get("architecture_facts") or {}
    for key in ("source_sha256","levels","spaces","areas","equipment","roof","shafts","wet_spaces"):
        if architecture.get(key) is None: missing["architecture_fact_extraction"].append("ARCHITECTURE_FACT:"+key)

    records=context.get("answer_records") or []
    if not records: missing["fact_source_classification"].append("ANSWER_RECORDS_REQUIRED")
    for row in records:
        if row.get("source") not in {"ARCHITECTURE","USER","CALCULATION"} or not row.get("key"):
            errors["fact_source_classification"].append("UNATTRIBUTED_FACT:"+str(row.get("key")))
        if row.get("source") == "MECHANICAL_REFERENCE":
            errors["fact_source_classification"].append("MECHANICAL_REFERENCE_INPUT_FORBIDDEN")

    scope=context.get("system_scope") or {}
    required_systems=set(context.get("required_systems") or [])
    if not required_systems: missing["system_scope_resolution"].append("REQUIRED_SYSTEM_INVENTORY_REQUIRED")
    unresolved=[s for s in required_systems if scope.get(s) not in {True,False}]
    if unresolved: missing["system_scope_resolution"].append("SYSTEM_SCOPE:"+",".join(sorted(unresolved)))

    applicability=context.get("question_applicability") or {}
    if applicability.get("status") != "PASS" or applicability.get("irrelevant_questions") or applicability.get("missing_questions"):
        errors["dynamic_question_applicability"].append("QUESTION_APPLICABILITY_NOT_PASS")

    reuse=context.get("prior_answer_reuse")
    if reuse is None: missing["governed_prior_answer_reuse"].append("PRIOR_ANSWER_REUSE_AUDIT_REQUIRED")
    elif any(not row.get("source_conversation_id") or not row.get("source_revision") or row.get("verified") is not True for row in reuse):
        errors["governed_prior_answer_reuse"].append("UNVERIFIED_PRIOR_ANSWER_REUSE")
    if any(row.get("target_scope") not in {"THIS_PROJECT","ALL_PROJECTS_EXPLICIT"} or
           (row.get("target_scope")=="ALL_PROJECTS_EXPLICIT" and row.get("owner_authorized") is not True)
           for row in (reuse or [])):
        errors["cross_project_answer_scope"].append("CROSS_PROJECT_REUSE_NOT_AUTHORIZED")

    normalization=context.get("normalization_qa") or {}
    if normalization.get("status") != "PASS" or normalization.get("unknown_terms") or normalization.get("noncanonical_keys"):
        errors["canonical_answer_normalization"].append("ANSWER_NORMALIZATION_NOT_PASS")

    numeric=context.get("numeric_inputs") or []
    required_numeric=set(context.get("required_numeric_keys") or [])
    present={row.get("key") for row in numeric}
    if not required_numeric: missing["numeric_value_unit_validation"].append("REQUIRED_NUMERIC_KEY_LIST_REQUIRED")
    if required_numeric-present: missing["numeric_value_unit_validation"].append("NUMERIC_INPUT:"+",".join(sorted(required_numeric-present)))
    for row in numeric:
        if not _positive(row.get("value")) or not row.get("unit") or row.get("range_status") != "PASS":
            errors["numeric_value_unit_validation"].append("INVALID_NUMERIC_INPUT:"+str(row.get("key")))

    climate=context.get("climate_basis") or {}
    for key in ("city","elevation_m","summer_design","winter_design","rainfall_intensity","water_pressure","source","source_revision"):
        if climate.get(key) is None: missing["climate_location_basis"].append("CLIMATE_FIELD:"+key)

    engineering=context.get("system_design_basis") or {}
    for system in sorted(s for s in required_systems if scope.get(s) is True):
        row=engineering.get(system) or {}
        absent=[k for k in ("method","simultaneity","velocity_limit","pressure_drop_limit","material","insulation","code_source") if row.get(k) is None]
        if absent: missing["system_engineering_basis"].append(f"SYSTEM_BASIS:{system}:{','.join(absent)}")

    preferences=context.get("equipment_preferences") or {}
    for key in context.get("required_equipment_preference_keys") or []:
        if preferences.get(key) is None: missing["equipment_owner_preferences"].append("EQUIPMENT_PREFERENCE:"+key)

    regulatory=context.get("regulatory_facts") or {}
    for key in context.get("required_regulatory_keys") or []:
        if regulatory.get(key) is None: missing["regulatory_project_facts"].append("REGULATORY_FACT:"+key)

    consistency=context.get("architecture_consistency_qa") or {}
    if consistency.get("status") != "PASS" or consistency.get("contradictions"):
        errors["architecture_answer_consistency"].append("ARCHITECTURE_ANSWER_CONTRADICTION")
    dependency=context.get("dependency_qa") or {}
    if dependency.get("status") != "PASS" or dependency.get("invalid_activated") or dependency.get("missing_activated"):
        errors["question_dependency_graph"].append("QUESTION_DEPENDENCY_NOT_PASS")

    summary=context.get("basis_summary") or {}
    if summary.get("status") != "APPROVED" or not summary.get("rendered_text") or not summary.get("approved_by") or not summary.get("approved_at"):
        missing["human_readable_basis_summary"].append("OWNER_APPROVED_BASIS_SUMMARY_REQUIRED")
    locked=context.get("locked_revision") or {}
    expected_hash=_stable({"architecture_facts":architecture,"answer_records":records,"system_scope":scope,
                           "numeric_inputs":numeric,"climate_basis":climate,"system_design_basis":engineering,
                           "equipment_preferences":preferences,"regulatory_facts":regulatory})
    if not locked.get("revision_id") or not locked.get("architecture_sha256") or not locked.get("rules_revision") or not locked.get("approved_at"):
        missing["immutable_approved_revision"].append("LOCKED_DESIGN_BASIS_REVISION_REQUIRED")
    elif locked.get("content_hash") != expected_hash or locked.get("architecture_sha256") != architecture.get("source_sha256") or locked.get("mutated") is True:
        errors["immutable_approved_revision"].append("DESIGN_BASIS_LOCK_IDENTITY_FAILED")

    persistence=context.get("persistence_qa") or {}
    if persistence.get("status") != "PASS" or persistence.get("roundtrip_mismatches") or persistence.get("destructive_test_failures"):
        errors["persistence_and_destructive_qa"].append("PERSISTENCE_OR_DESTRUCTIVE_QA_NOT_PASS")
    release=context.get("release_decision") or {}
    if release.get("status") != "PASS" or release.get("open_questions") or release.get("hidden_assumptions") or release.get("contradictions"):
        errors["generation_release_gate"].append("DESIGN_BASIS_RELEASE_NOT_PASS")

    controls=[]
    for name,weight in CONTROL_WEIGHTS.items():
        status="FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
        controls.append({"id":name,"weight":weight,"status":status,"errors":errors[name],"missing_inputs":missing[name]})
    score=sum(row["weight"] for row in controls if row["status"]=="PASS")
    status="FAIL" if any(row["status"]=="FAIL" for row in controls) else ("INPUT_REQUIRED" if any(row["status"]=="INPUT_REQUIRED" for row in controls) else "PASS")
    return {"contract":CONTRACT_VERSION,"status":status,"score":score,"controls":controls,
            "all_controls_pass":all(row["status"]=="PASS" for row in controls),
            "release_allowed":status=="PASS" and score==100,"expected_content_hash":expected_hash,
            "errors":sorted({x for row in controls for x in row["errors"]}),
            "missing_inputs":sorted({x for row in controls for x in row["missing_inputs"]}),
            "evidence_hash":_stable(context)}
