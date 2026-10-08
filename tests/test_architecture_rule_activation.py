import json
import hashlib
import csv
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
    assert access["local_hash"] == "1604a568abd5ac8d1066a181f0d5ce7aa4755fd27c3a4786ac098232ce57a751"
    assert access["page_count"] == 122
    assert access["file_size_bytes"] == 5_843_208
    assert access["content_identity_verified"] is True
    assert access["verification_status"] == "DOCUMENT_HASH_PAGE_AND_RESIDENTIAL_CLAUSES_VERIFIED"

def test_every_rule_has_independent_gates_and_all_are_ready_for_one_human_review():
    rules = hard_rules(); assert len(rules) == 32
    assert Counter(x["activation_state"] for x in rules) == {"READY_FOR_HUMAN_REVIEW": 32}
    for rule in rules:
        assert rule["source_gate"] in {"QUALIFIED", "BLOCKED"}
        assert rule["human_review_gate"] == "REQUIRED"
        assert rule["release_enabled"] is False
        assert rule["rule_logic"] is not None
        if rule["check"] is None and rule["activation_state"] == "READY_FOR_HUMAN_REVIEW" and rule["rule_id"] not in {"ARCH-RES-STAIRS-003", "ARCH-RES-ACCESSIBILITY-001"}:
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

def test_every_rule_has_minimum_eight_case_qa_specification():
    cases = [x for x in load("qa-matrix")["cases"] if x["group"] == "RULE_ACTIVATION"]
    by = Counter(x["authority_ref"] for x in cases)
    assert len(by) == 32
    scenarios = {"PASS", "FAIL", "BOUNDARY_EXACT", "JUST_BELOW", "JUST_ABOVE", "NOT_APPLICABLE", "INPUT_REQUIRED", "EXCEPTION"}
    for rid in by:
        assert scenarios <= {x["scenario"] for x in cases if x["authority_ref"] == rid}
        assert all(x["executed"] is False for x in cases if x["authority_ref"] == rid)

def test_human_review_is_not_fabricated():
    package = load("human-architect-review-package")
    assert package["status"] == "AWAITING_LICENSED_ARCHITECT_REVIEW"
    assert package["reviewer_decisions"] == []
    assert len(package["items"]) == 32
    assert all(x["reviewer_decision"] is None for x in package["items"])
    assert all(x["post_review_status"] == "NOT_REVIEWED" for x in package["items"])
    assert all(x["proposed_reviewer_decision"] is None for x in package["items"])
    assert all(x["reviewer_name"] is None and x["professional_license_or_registration"] is None for x in package["items"])
    assert package["dedicated_decisions"]["code246_five_percent"]["decision"] is None
    assert package["dedicated_decisions"]["m3_m4_group8_stair"]["decision"] is None

def test_shareable_human_review_artifacts_cover_all_rules():
    review_dir = ROOT / "docs/residential/review"
    docx = review_dir / "planha-licensed-architect-rule-review-book.docx"
    pdf = review_dir / "planha-licensed-architect-rule-review-book.pdf"
    sheet = review_dir / "architecture-rule-review-decision-sheet.csv"
    assert docx.stat().st_size > 50_000
    assert pdf.stat().st_size > 500_000
    with sheet.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 32
    assert len({row["Rule ID"] for row in rows}) == 32
    assert all(row["Decision"] == "" and row["Reviewer Name"] == "" for row in rows)

def test_golden_matrix_has_accessibility_diversity_but_is_not_authorized():
    matrix = load("golden-matrix")
    assert len(matrix["cases"]) == 8
    assert len({x["case_type"] for x in matrix["cases"]}) == 8
    assert len({x["accessibility_coverage"] for x in matrix["cases"]}) == 8
    assert all(x["execution_authorized"] is False for x in matrix["cases"])
    assert matrix["status"] == "PREPARED_NOT_AUTHORIZED_PENDING_CONSOLIDATED_LICENSED_ARCHITECT_REVIEW"

def _residential_complex(units_per_floor, floor_count, total_units):
    return units_per_floor > 4 or (floor_count > 1 and total_units > 8)

def _group8(height_m, floor_count):
    return height_m > 23 or floor_count > 7

def test_code246_residential_complex_exact_boundaries():
    assert _residential_complex(4, 1, 4) is False
    assert _residential_complex(5, 1, 5) is True
    assert _residential_complex(4, 2, 8) is False
    assert _residential_complex(4, 3, 9) is True

def test_code246_accessible_unit_branches_fail_closed_without_invented_rounding():
    rule = {x["rule_id"]: x for x in hard_rules()}["ARCH-RES-ACCESSIBILITY-001"]
    allocation = rule["rule_logic"]["accessible_unit_requirement"]
    assert allocation["private_or_general_complex"]["calculation_raw"] == "total_residential_units * 0.05"
    assert allocation["private_or_general_complex"]["integer_conversion"] == "HUMAN_INTERPRETATION_REQUIRED"
    assert allocation["fully_government_funded_under_20"]["minimum_accessible_units"] == 1
    assert rule["rule_logic"]["common_area_scope"]["unknown_local_elevator_requirement"] == "LOCAL_RULE_REQUIRED"

def test_m4_group8_boundaries_and_m3_single_stair_exception_do_not_overlap():
    assert _group8(23, 7) is False
    assert _group8(23.001, 7) is True
    assert _group8(23, 8) is True
    rule = {x["rule_id"]: x for x in hard_rules()}["ARCH-RES-STAIRS-003"]
    assert rule["rule_logic"]["required_exit_count"]["value"] == 2
    assert rule["rule_logic"]["required_exit_count"]["group8_exception_eligibility"] is False
    assert rule["rule_logic"]["stair_capacity"]["unknown_sprinkler"] == "INPUT_REQUIRED"

def test_only_the_two_target_rules_changed_dependency_detail():
    targeted = {"ARCH-RES-STAIRS-003", "ARCH-RES-ACCESSIBILITY-001"}
    preserved = [x for x in hard_rules() if x["rule_id"] not in targeted]
    encoded = json.dumps(preserved, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert len(preserved) == 30
    assert hashlib.sha256(encoded).hexdigest() == "a2aeae09802488e59be6d9a4b3f98380b8c0b48aba1004d1e16c4f760027ff04"

def test_local_rule_gaps_remain_local_and_inventory_is_unique():
    gaps = load("source-gap-register")["gaps"]
    assert len(gaps) == len({x["gap_id"] for x in gaps}) == 24
    assert {x["gap_id"] for x in gaps if x["status"] == "LOCAL_RULE_REQUIRED"} == {"ARCH-SG-002", "ARCH-SG-003", "ARCH-SG-007"}

def test_owner_questions_are_preferences_not_regulatory_defaults():
    q = load("owner-questionnaire")
    assert q["activation_reaudit_summary"] == {"DERIVE_FROM_CODE":0,"DERIVE_FROM_CITY":0,"DERIVE_FROM_GEOMETRY":0,"DERIVE_FROM_PROJECT_INPUT":0,"KEEP":13,"DELAY":45,"REMOVE":0}
    assert all(x["default_allowed"] is False for x in q["questions"])
