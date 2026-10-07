import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/rulebook/architecture"

def load(name): return json.loads((DATA / f"{name}.json").read_text())
def hard_rules(): return [x for x in load("rulebook")["rules"] if x["authority_type"] == "HARD_RULE"]

def test_project_baselines_preserve_provenance_boundary():
    sources = {x["source_id"]: x for x in load("sources")["sources"]}
    for sid in ("IR-M3", "IR-M4"):
        assert sources[sid]["document_verified"] is True
        assert sources[sid]["current_source_basis"] == "OWNER_CONFIRMED_CURRENT_PRIMARY_BASELINE"
        assert sources[sid]["independent_government_registry_currentness_verified"] is False
    access = sources["IR-ACCESS"]
    assert access["expected_filename"] == "895917_Code0246-r1-13990324.pdf"
    assert access["local_hash"] is None
    assert access["verification_status"] == "PRIMARY_FILE_REQUIRED_FOR_CLAUSE_MAPPING"

def test_every_rule_has_independent_gates_and_only_two_dependency_blockers():
    rules = hard_rules(); assert len(rules) == 32
    assert Counter(x["activation_state"] for x in rules) == {"READY_FOR_HUMAN_REVIEW": 30, "BLOCKED": 2}
    blocked = {x["rule_id"]: x for x in rules if x["activation_state"] == "BLOCKED"}
    assert set(blocked) == {"ARCH-RES-STAIRS-003", "ARCH-RES-ACCESSIBILITY-001"}
    for rule in rules:
        assert rule["source_gate"] in {"QUALIFIED", "BLOCKED"}
        assert rule["human_review_gate"] == "REQUIRED"
        assert rule["release_enabled"] is False
        assert rule["rule_logic"] is not None
        if rule["check"] is None and rule["activation_state"] == "READY_FOR_HUMAN_REVIEW":
            assert rule["machine_checkable"] is False
            assert rule["logic_gate"] == "READY_FOR_HUMAN_REVIEW"
        assert rule["source_clause"] and rule["source_page"]

def test_missing_input_and_nonapplicability_cannot_be_pass():
    for rule in hard_rules():
        if "predicate" in rule["rule_logic"]:
            assert rule["rule_logic"]["predicate"]["missing_input"] == "INPUT_REQUIRED"
            assert rule["rule_logic"]["predicate"]["not_applicable_result"] == "NOT_APPLICABLE"

def test_cross_code_is_selective_and_no_global_accessibility_flag_exists():
    rules = {x["rule_id"]: x for x in hard_rules()}
    assert rules["ARCH-RES-LIVING-001"]["cross_rule_dependencies"] == []
    assert "IR-ACCESS" in rules["ARCH-RES-ACCESSIBILITY-001"]["cross_rule_dependencies"]
    assert "IR-M3" in rules["ARCH-RES-STAIRS-003"]["cross_rule_dependencies"]
    assert all("accessibility_required = true" not in json.dumps(x) for x in rules.values())

def test_advanced_rules_have_eight_case_qa_specifications():
    cases = [x for x in load("qa-matrix")["cases"] if x["group"] == "RULE_ACTIVATION"]
    by = Counter(x["authority_ref"] for x in cases)
    assert len(by) == 30 and set(by.values()) == {8}
    scenarios = {"PASS", "FAIL", "BOUNDARY_EXACT", "JUST_BELOW", "JUST_ABOVE", "NOT_APPLICABLE", "INPUT_REQUIRED", "EXCEPTION"}
    for rid in by:
        assert {x["scenario"] for x in cases if x["authority_ref"] == rid} == scenarios
        assert all(x["executed"] is False for x in cases if x["authority_ref"] == rid)

def test_human_review_is_not_fabricated():
    package = load("human-architect-review-package")
    assert package["reviewer_decisions"] == []
    assert len(package["items"]) == 32
    assert all(x["human_review_status"] == "REQUIRED" for x in package["items"])

def test_golden_matrix_has_accessibility_diversity_but_is_not_authorized():
    matrix = load("golden-matrix")
    assert len(matrix["cases"]) == 8
    assert len({x["case_type"] for x in matrix["cases"]}) == 8
    assert len({x["accessibility_coverage"] for x in matrix["cases"]}) == 8
    assert all(x["execution_authorized"] is False for x in matrix["cases"])
    assert matrix["status"] == "PREPARED_NOT_AUTHORIZED_CODE246_AND_M3_BLOCKERS"

def test_local_rule_gaps_remain_local_and_inventory_is_unique():
    gaps = load("source-gap-register")["gaps"]
    assert len(gaps) == len({x["gap_id"] for x in gaps}) == 24
    assert {x["gap_id"] for x in gaps if x["status"] == "LOCAL_RULE_REQUIRED"} == {"ARCH-SG-002", "ARCH-SG-003", "ARCH-SG-007"}

def test_owner_questions_are_preferences_not_regulatory_defaults():
    q = load("owner-questionnaire")
    assert q["activation_reaudit_summary"] == {"DERIVE_FROM_CODE":0,"DERIVE_FROM_CITY":0,"DERIVE_FROM_GEOMETRY":0,"DERIVE_FROM_PROJECT_INPUT":0,"KEEP":13,"DELAY":45,"REMOVE":0}
    assert all(x["default_allowed"] is False for x in q["questions"])
