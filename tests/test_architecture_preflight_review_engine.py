from copy import deepcopy

import pytest

from cad_engine.architecture_contract import content_hash
from cad_engine.architecture_review_engine import (
    empty_review_registry, execute_preflight, plan_preflight, replay_review_decisions)
from cad_engine.architecture_snapshot import create_snapshot, validate_snapshot
from cad_engine.architecture_validator import validate_architecture


SHA = "b" * 64


def authority(status="SUPPORTED", **grants):
    return {"status": status, "origins": ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
            "material_geometry": grants.get("material_geometry", False),
            "wall": grants.get("wall", False), "portal": grants.get("portal", False),
            "access": grants.get("access", False), "routing": False, "release": False}


def model(release=True):
    row = {"schema": "planha-canonical-architecture/2.0", "contract_status": "EXPERIMENTAL_INTERNAL",
           "source": {"source_type": "RAW_DXF", "source_sha256": SHA,
                      "source_revision_identity": SHA, "units": "METERS", "effective_scale": 1.0,
                      "coordinate_system": {"status": "SUPPORTED"},
                      "adapter": {"adapter_id": "test", "adapter_version": "1"}},
           "levels": [{"level_id": "L1", "status": "SUPPORTED", "source_frame_ids": ["F1"]}],
           "frames": [{"frame_id": "F1", "level_id": "L1", "source_identity": SHA, "status": "SUPPORTED"}],
           "walls": [{"wall_id": "W1", "frame_id": "F1", "centerline": [[5, 0], [5, 10]],
                      "source_handles": ["10"], "authority": authority(wall=True, material_geometry=True)}],
           "physical_spaces": [{"physical_space_id": "S1", "level_id": "L1", "frame_id": "F1",
                                "polygon": [[0, 0], [5, 0], [5, 10], [0, 10]], "interior_rings": [],
                                "topology_status": "VERIFIED", "source_handles": ["20"],
                                "authority": authority("VERIFIED", material_geometry=True)},
                               {"physical_space_id": "S2", "level_id": "L1", "frame_id": "F1",
                                "polygon": [[5, 0], [10, 0], [10, 10], [5, 10]], "interior_rings": [],
                                "topology_status": "VERIFIED", "source_handles": ["21"],
                                "authority": authority("VERIFIED", material_geometry=True)}],
           "functional_zones": [],
           "apertures": [{"aperture_id": "G1", "frame_id": "F1", "classification": "UNKNOWN",
                          "status": "SUPPORTED", "geometry": [[5, 4], [5, 5]], "host_wall_ids": ["W1"],
                          "source_handles": ["30"], "authority": authority()}],
           "portals": [], "voids": [], "dimensions": [],
           "graphs": {"adjacency": [], "enclosure": [["S1", "S2"]], "access": []},
           "unresolved_items": [], "evidence_registry": [], "review_registry": empty_review_registry(),
           "authority_model": {"dimensions": [], "allowed_origins": [], "vision_independent_grants": []},
           "traceability": {"source_sha256": SHA, "adapter_id": "test", "adapter_version": "1",
                            "legacy_model_hash": "c" * 64},
           "release": {"status": "VERIFIED" if release else "INPUT_REQUIRED",
                       "downstream_engineering_allowed": release, "release_allowed": release}}
    return rehash(row)


def rehash(row):
    row.pop("canonical_model_hash", None); row["canonical_model_hash"] = content_hash(row); return row


def candidate(question="SPACE_CLASSIFICATION", object_id="S1", root="ROOT-1", answers=None):
    answers = answers or (["LIVING", "TOILET", "UNKNOWN"] if question == "SPACE_CLASSIFICATION" else ["UNKNOWN"])
    return {"question_type": question, "frame_or_level_id": "F1", "object_or_region_id": object_id,
            "geometry_fingerprint": "geo-" + object_id, "evidence_fingerprint": "ev-" + object_id,
            "review_scope": "BOUNDED_SOURCE_INTERPRETATION", "candidate_interpretations": answers,
            "allowed_answers": answers, "can_resolve_without_geometry_creation": True,
            "impact_classification": "REVIEW_CRITICAL", "root_cause_key": root,
            "evidence_summary": {"source_handles": ["30"]},
            "preview_spec": {"frame_id": "F1", "crop_bounds": [0, 0, 6, 10],
                             "primary_object_ids": [object_id], "related_wall_ids": ["W1"],
                             "related_gap_ids": ["G1"], "related_space_ids": ["S1", "S2"],
                             "source_handles": ["30"], "overlay_layers_requested": ["SOURCE", "TOPOLOGY"],
                             "highlight_geometry": [[5, 4], [5, 5]], "question_focus": question}}


def add_issue(row, code="SPACE_SEMANTICS_UNRESOLVED", cand=None, suffix="1", noncritical=False):
    row["unresolved_items"].append({"unresolved_item_id": "U" + suffix,
                                    "object_or_region_id": (cand or {}).get("object_or_region_id", "S1"),
                                    "issue_type": code, "evidence": {"source": "synthetic"},
                                    "downstream_impact": "NONCRITICAL_DIAGNOSTIC" if noncritical else "BLOCKS_RELEASE",
                                    "impact_classification": "NONCRITICAL_DIAGNOSTIC" if noncritical else "REVIEW_CRITICAL",
                                    "review_candidate": deepcopy(cand) if cand else None})
    row["release"] = {"status": "INPUT_REQUIRED", "downstream_engineering_allowed": False,
                      "release_allowed": False}
    return rehash(row)


def decision(item, answer):
    keys = ("source_sha256", "frame_or_level_id", "object_or_region_id", "geometry_fingerprint",
            "evidence_fingerprint", "review_scope", "review_fingerprint")
    return {"review_item_id": item["review_item_id"], "decision": answer,
            **{key: item[key] for key in keys}}


def test_validator_pass_auto_validates_and_allows_snapshot():
    result = execute_preflight(model(), engine_identity={"sha": "engine"}, created_at="2026-10-03T00:00:00Z")
    assert result["preflight_plan"]["primary_state"] == "AUTO_VALIDATED"
    assert result["snapshot"]["validation_state"] == "AUTO_VALIDATED"


def test_one_semantic_question_replays_revalidates_and_creates_reviewed_snapshot():
    current = add_issue(model(False), cand=candidate())
    initial = execute_preflight(current)
    assert initial["preflight_plan"]["primary_state"] == "QUICK_REVIEW_REQUIRED"
    item = initial["preflight_plan"]["review_items"][0]
    result = execute_preflight(current, [decision(item, "LIVING")],
                               engine_identity={"sha": "engine"}, created_at="2026-10-03T00:00:00Z")
    assert result["validator_report"]["status"] == "PASS"
    assert result["snapshot"]["validation_state"] == "VALIDATED"
    assert result["snapshot"]["review_manifest_hash"]
    assert len(result["snapshot"]["review_decision_ids"]) == 1


def test_two_issues_with_one_root_cause_become_one_question():
    current = model(False); cand = candidate(root="SAME")
    add_issue(current, "PORTAL_HOST_APERTURE_REQUIRED", cand, "1")
    add_issue(current, "ACCESS_EDGE_MISSING", cand, "2")
    plan = plan_preflight(current)
    assert len(plan["normalized_issues"]) == 2
    assert len(plan["review_items"]) == 1
    assert len(plan["review_items"][0]["validator_issue_ids_covered"]) == 2


def test_independent_critical_questions_are_stably_ordered_and_deterministic():
    current = model(False)
    add_issue(current, cand=candidate(object_id="S2", root="B"), suffix="2")
    add_issue(current, cand=candidate(object_id="S1", root="A"), suffix="1")
    first = plan_preflight(current); second = plan_preflight(current)
    assert first == second
    assert len(first["review_items"]) == 2
    assert [x["review_item_id"] for x in first["review_items"]] == sorted(x["review_item_id"] for x in first["review_items"])


def test_harmless_diagnostic_creates_no_blocking_question():
    current = model(); add_issue(current, code="DRAFTING_FRAGMENT", cand=candidate(), noncritical=True)
    current["release"] = {"status": "VERIFIED", "downstream_engineering_allowed": True, "release_allowed": True}; rehash(current)
    plan = plan_preflight(current)
    assert plan["primary_state"] == "AUTO_VALIDATED"
    assert plan["review_items"] == []
    assert len(plan["noncritical_diagnostics"]) == 1


@pytest.mark.parametrize("field,value", [("source_sha256", "d" * 64),
                                          ("geometry_fingerprint", "changed"),
                                          ("evidence_fingerprint", "changed")])
def test_stale_decision_identity_is_rejected(field, value):
    current = add_issue(model(False), cand=candidate())
    plan = plan_preflight(current); payload = decision(plan["review_items"][0], "LIVING"); payload[field] = value
    result = replay_review_decisions(current, [payload], plan)
    assert result["accepted_review_decisions"] == []
    assert result["stale_review_decisions"][0]["errors"] == ["STALE_REVIEW_DECISION"]


def test_duplicate_review_application_is_idempotent():
    current = add_issue(model(False), cand=candidate()); plan = plan_preflight(current)
    payload = decision(plan["review_items"][0], "LIVING")
    result = replay_review_decisions(current, [payload, payload], plan)
    assert len(result["review_registry"]["accepted_decisions"]) == 1
    assert len(result["review_registry"]["decision_history"]) == 1


def test_unknown_records_no_authority_and_suppresses_same_question():
    current = add_issue(model(False), cand=candidate()); plan = plan_preflight(current)
    result = replay_review_decisions(current, [decision(plan["review_items"][0], "UNKNOWN")], plan)
    assert result["reviewed_canonical_model"]["physical_spaces"][0].get("review_status") is None
    assert result["preflight_plan"]["review_items"] == []
    assert result["preflight_plan"]["primary_state"] == "ARCHITECTURE_INPUT_REQUIRED"


def test_existing_aperture_and_portal_can_be_semantically_classified_without_new_geometry():
    current = model(False)
    current["portals"] = [{"opening_id": "O1", "portal_id": "P1", "type": "UNKNOWN", "frame_id": "F1",
                           "host_wall_id": "W1", "host_aperture_id": "G1", "material_aperture_status": "SUPPORTED",
                           "space_a": "S1", "space_b": "S2", "geometry": [[5, 4], [5, 5]],
                           "source_handles": ["30"], "evidence_ids": [], "status": "INPUT_REQUIRED",
                           "authority": authority("INPUT_REQUIRED")}]
    cand = candidate("PORTAL_INTERPRETATION", "G1", answers=["DOOR", "WINDOW", "OPEN_PASSAGE", "CONTINUOUS_WALL", "UNKNOWN"])
    add_issue(current, "PORTAL_TOPOLOGY_UNRESOLVED", cand)
    before = content_hash(current["apertures"][0]["geometry"])
    plan = plan_preflight(current); result = replay_review_decisions(current, [decision(plan["review_items"][0], "DOOR")], plan)
    reviewed = result["reviewed_canonical_model"]
    assert reviewed["portals"][0]["type"] == "DOOR"
    assert reviewed["portals"][0]["review_status"] == "CONFIRMED"
    assert reviewed["portals"][0]["authority"]["access"] is False
    assert content_hash(reviewed["apertures"][0]["geometry"]) == before
    assert reviewed["graphs"]["access"] == []


def test_door_motif_without_aperture_is_source_input_required_not_a_question():
    current = model(False); current["apertures"] = []
    cand = candidate("PORTAL_INTERPRETATION", "G-MISSING", answers=["DOOR", "UNKNOWN"])
    add_issue(current, "PORTAL_TOPOLOGY_UNRESOLVED", cand)
    plan = plan_preflight(current)
    assert plan["primary_state"] == "ARCHITECTURE_INPUT_REQUIRED"
    assert plan["review_items"] == []
    assert plan["source_input_requirements"][0]["missing_evidence"] == "PORTAL_TOPOLOGY_UNRESOLVED"


def test_window_interpretation_never_creates_access():
    current = model(False)
    current["portals"] = [{"opening_id": "O1", "portal_id": "P1", "type": "UNKNOWN", "frame_id": "F1",
                           "host_wall_id": "W1", "host_aperture_id": "G1", "material_aperture_status": "SUPPORTED",
                           "space_a": "S1", "space_b": "S2", "geometry": [[5, 4], [5, 5]],
                           "source_handles": ["30"], "evidence_ids": [], "status": "INPUT_REQUIRED",
                           "authority": authority("INPUT_REQUIRED")}]
    add_issue(current, "PORTAL_TOPOLOGY_UNRESOLVED",
              candidate("PORTAL_INTERPRETATION", "G1", answers=["WINDOW", "UNKNOWN"]))
    plan = plan_preflight(current); result = replay_review_decisions(current, [decision(plan["review_items"][0], "WINDOW")], plan)
    assert result["reviewed_canonical_model"]["graphs"]["access"] == []
    assert result["reviewed_canonical_model"]["portals"][0]["authority"]["access"] is False


def test_duct_review_requires_existing_source_boundary():
    current = model(False)
    current["voids"] = [{"void_id": "V1", "frame_id": "F1", "type": "UNKNOWN",
                         "boundary": [[11, 1], [12, 1], [12, 2], [11, 2]], "source_handles": ["40"],
                         "geometry_status": "SUPPORTED", "topology_role": "VOID", "routing_authority": "NONE",
                         "authority": authority()}]
    add_issue(current, "VOID_CLASSIFICATION_UNRESOLVED",
              candidate("VOID_INTERPRETATION", "V1", answers=["DUCT", "SHAFT", "VOID", "NOT_A_VOID", "UNKNOWN"]))
    plan = plan_preflight(current); result = replay_review_decisions(current, [decision(plan["review_items"][0], "DUCT")], plan)
    assert result["reviewed_canonical_model"]["voids"][0]["type"] == "DUCT"
    assert result["review_registry"]["manual_geometry_creation_count"] == 0
    missing = model(False); missing["voids"] = []
    add_issue(missing, "VOID_CLASSIFICATION_UNRESOLVED",
              candidate("VOID_INTERPRETATION", "V-MISSING", answers=["DUCT", "UNKNOWN"]))
    assert plan_preflight(missing)["primary_state"] == "ARCHITECTURE_INPUT_REQUIRED"


def test_open_plan_confirmation_creates_no_wall_or_partition():
    current = add_issue(model(False), "OPEN_PLAN_UNRESOLVED",
                        candidate("OPEN_PLAN_CONFIRMATION", "S1", answers=["SAME_PHYSICAL_SPACE", "UNKNOWN"]))
    wall_hash = content_hash(current["walls"])
    plan = plan_preflight(current); result = replay_review_decisions(current, [decision(plan["review_items"][0], "SAME_PHYSICAL_SPACE")], plan)
    assert content_hash(result["reviewed_canonical_model"]["walls"]) == wall_hash
    assert result["reviewed_canonical_model"]["physical_spaces"][0]["category"] == "OPEN_PLAN"


def test_cross_level_topology_is_not_a_user_question():
    current = model(); current["levels"].append({"level_id": "L2", "status": "SUPPORTED", "source_frame_ids": ["F2"]})
    current["frames"].append({"frame_id": "F2", "level_id": "L2", "source_identity": SHA, "status": "SUPPORTED"})
    current["physical_spaces"][1]["frame_id"] = "F2"; current["physical_spaces"][1]["level_id"] = "L2"
    current["portals"] = [{"opening_id": "O1", "portal_id": "P1", "type": "DOOR", "frame_id": "F1",
                           "host_wall_id": "W1", "host_aperture_id": "G1", "space_a": "S1", "space_b": "S2",
                           "geometry": [[5, 4], [5, 5]], "source_handles": ["30"], "status": "VERIFIED",
                           "authority": authority("VERIFIED", portal=True)}]
    rehash(current); plan = plan_preflight(current)
    assert plan["primary_state"] == "CONFLICT" and plan["review_items"] == []


def test_invalid_canonical_reference_is_engine_defect_not_question():
    current = model(); current["apertures"][0]["host_wall_ids"] = ["NOPE"]; rehash(current)
    plan = plan_preflight(current)
    assert plan["primary_state"] == "CONFLICT"
    assert plan["engine_defects"][0]["classification"] == "ENGINE_DEFECT_OR_CONTRACT_ERROR"
    assert plan["review_items"] == []


def test_same_decision_with_unchanged_validator_blocker_does_not_loop():
    current = model(False); current["source"]["effective_scale"] = None
    add_issue(current, "EFFECTIVE_SCALE_REQUIRED", candidate())
    plan = plan_preflight(current); assert plan["review_items"]
    result = replay_review_decisions(current, [decision(plan["review_items"][0], "LIVING")], plan)
    assert result["preflight_plan"]["review_items"] == []
    assert result["preflight_plan"]["primary_state"] == "ARCHITECTURE_INPUT_REQUIRED"


def test_changed_source_fingerprint_makes_old_decision_stale():
    current = add_issue(model(False), cand=candidate()); old = plan_preflight(current)["review_items"][0]
    changed = deepcopy(current); changed["source"]["source_sha256"] = "e" * 64
    changed["source"]["source_revision_identity"] = "e" * 64; rehash(changed)
    plan = plan_preflight(changed); payload = decision(old, "LIVING")
    result = replay_review_decisions(changed, [payload], plan)
    assert result["stale_review_decisions"] or result["rejected_review_decisions"]


def test_review_item_tamper_and_validator_report_tamper_fail_closed():
    current = add_issue(model(False), cand=candidate()); report = validate_architecture(current)
    tampered = deepcopy(report); tampered["status"] = "PASS"
    plan = plan_preflight(current, tampered)
    assert plan["primary_state"] == "CONFLICT"
    item = plan_preflight(current)["review_items"][0]; item["allowed_answers"].append("FABRICATE")
    payload = decision(item, "FABRICATE")
    result = replay_review_decisions(current, [payload], {**plan_preflight(current), "review_items": [item]})
    assert "REVIEW_ITEM_INTEGRITY_INVALID" in result["rejected_review_decisions"][0]["errors"]


def test_non_pass_validator_cannot_create_snapshot_or_self_pass():
    current = add_issue(model(False), cand=candidate()); report = validate_architecture(current)
    with pytest.raises(ValueError, match="VALIDATOR_PASS_REQUIRED"):
        create_snapshot(current, report, engine_identity={}, created_at="now", validation_state="VALIDATED",
                        review_manifest={"x": 1})
    plan = plan_preflight(current)
    assert plan["review_engine_self_pass"] is False and plan["validator_bypass_count"] == 0


def test_reviewed_snapshot_binding_and_staleness():
    current = add_issue(model(False), cand=candidate()); plan = plan_preflight(current)
    result = execute_preflight(current, [decision(plan["review_items"][0], "LIVING")],
                               engine_identity={"sha": "engine"}, created_at="now")
    assert validate_snapshot(result["snapshot"], result["reviewed_canonical_model"],
                             result["validator_report"], review_manifest=result["review_registry"])["status"] == "PASS"
    assert validate_snapshot(result["snapshot"], result["reviewed_canonical_model"],
                             result["validator_report"], review_manifest={"changed": True})["status"] == "FAIL"


def test_review_quality_hard_targets_are_zero():
    current = add_issue(model(False), cand=candidate()); plan = plan_preflight(current)
    metrics = plan["metrics"]
    assert metrics["critical_unresolved_hidden"] == 0
    assert metrics["duplicate_question_count"] == 0
    assert metrics["repeated_question_after_same_decision_count"] == 0
    assert metrics["manual_geometry_creation_count"] == 0
