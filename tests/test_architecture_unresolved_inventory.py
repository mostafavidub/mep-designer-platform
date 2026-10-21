from copy import deepcopy

from cad_engine.architecture_review_engine import build_unresolved_inventory
from cad_engine.architecture_contract import SCHEMA, canonical_model_hash
from cad_engine.architecture_snapshot import create_snapshot
from cad_engine.architecture_validator import validate_architecture


SHA = "a" * 64


def fixture():
    evidence = {"evidence_id": "E1", "kind": "SOURCE_BOUNDARY_SUPPORT",
                "origin": "SOURCE_GEOMETRIC", "payload": {
                    "source_sha256": SHA, "frame_id": "F1", "level_id": "L1",
                    "source_handle": "H1", "segment_id": "SEG1",
                    "evidence_fingerprint": "EF1", "geometry_fingerprint": "GF1"}}
    item = {"review_item_id": "R1", "review_fingerprint": "RF1",
            "source_sha256": SHA, "frame_or_level_id": "F1",
            "object_or_region_id": "E1", "evidence_fingerprint": "EF1",
            "geometry_fingerprint": "GF1", "question_type": "SOURCE_ROLE_CLASSIFICATION",
            "evidence_summary": {"source_handles": ["H1"], "segment_ids": ["SEG1"]},
            "validator_issue_ids_covered": ["I1"]}
    space = {"physical_space_id": "S-NEW", "frame_id": "F1", "level_id": "L1",
             "source_handles": ["H1"], "authority": {"material_geometry": False,
             "release": False, "routing": False, "status": "INPUT_REQUIRED"},
             "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]], "evidence_ids": ["E1"]}
    model = {"schema": SCHEMA, "source": {"source_sha256": SHA}, "frames": [{"frame_id": "F1"}],
             "levels": [{"level_id": "L1"}], "physical_spaces": [space],
             "walls": [], "voids": [], "apertures": [], "portals": [],
             "evidence_registry": [evidence], "unresolved_items": [{
                 "unresolved_item_id": "U1", "object_or_region_id": "S-NEW",
                 "issue_type": "UNRESOLVED_SPACE", "downstream_impact": "BLOCKS_RELEASE"}],
             "review_registry": {}, "functional_zones": [], "dimensions": [],
             "graphs": {}, "release": {"status": "INPUT_REQUIRED", "release_allowed": False,
             "downstream_engineering_allowed": False}}
    model["canonical_model_hash"] = canonical_model_hash(model)
    plan = {"source_sha256": SHA, "review_items": [item],
            "normalized_issues": [{"issue_id": "I1"}]}
    return model, plan


def build(model=None, plan=None, history=()):
    model0, plan0 = fixture()
    return build_unresolved_inventory({"P": model or model0}, {"P": plan or plan0}, history)


def test_current_unresolved_item_is_active():
    result = build()
    assert result["status"] == "PASS"
    assert result["metrics"]["active_count"] == 1
    assert result["active"][0]["state"] == "ACTIVE"


def test_historical_id_without_current_registry_object_is_audit_only():
    result = build(history=[{"project_id": "P", "object_or_region_id": "S-OLD",
                             "source_sha256": SHA, "frame_id": "F1", "level_id": "L1",
                             "source_handles": ["MISSING"]}])
    assert result["metrics"]["active_count"] == 1
    assert result["audit"][0]["state"] == "STALE_REFERENCE"


def test_canonical_id_change_rebinds_only_by_exact_source_identity():
    history = [{"project_id": "P", "object_or_region_id": "S-OLD",
                "source_sha256": SHA, "frame_id": "F1", "level_id": "L1",
                "source_handles": ["H1"]}]
    row = build(history=history)["audit"][0]
    assert (row["state"], row["current_id"]) == ("SUPERSEDED", "S-NEW")


def test_owner_invalidated_historical_candidate_is_not_active():
    history = [{"project_id": "P", "object_or_region_id": "S-OLD",
                "source_sha256": SHA, "invalidated_by_current_evidence": True}]
    assert build(history=history)["audit"][0]["state"] == "INVALIDATED"


def test_stale_review_binding_cannot_be_active_or_grant_authority():
    model, plan = fixture(); plan = deepcopy(plan)
    plan["review_items"][0]["source_sha256"] = "b" * 64
    result = build(model, plan)
    assert result["metrics"]["active_count"] == 0
    assert "CURRENT_SOURCE_SHA_MISMATCH" in result["audit"][0]["errors"]
    assert model["physical_spaces"][0]["authority"]["material_geometry"] is False


def test_missing_current_provenance_fails_closed():
    model, plan = fixture(); model = deepcopy(model)
    model["evidence_registry"] = []
    result = build(model, plan)
    assert result["metrics"]["active_count"] == 0
    assert result["status"] == "FAIL"
    assert result["metrics"]["software_reconciliation_count"] == 1
    assert result["audit"][0]["state"] == "STALE_REFERENCE"


def test_duplicate_current_references_produce_one_active_identity():
    model, plan = fixture(); plan = deepcopy(plan)
    duplicate = deepcopy(plan["review_items"][0]); duplicate["review_item_id"] = "R2"
    plan["review_items"].append(duplicate)
    result = build(model, plan)
    assert result["metrics"]["active_count"] == 1
    assert any(row.get("reason") == "DUPLICATE_CURRENT_UNRESOLVED_IDENTITY" for row in result["audit"])


def test_historical_and_current_references_produce_one_current_blocker():
    history = [{"project_id": "P", "object_or_region_id": "S-OLD",
                "source_sha256": SHA, "frame_id": "F1", "level_id": "L1",
                "source_handles": ["H1"]}]
    result = build(history=history)
    assert result["metrics"]["active_count"] == 1
    assert result["audit"][0]["state"] == "SUPERSEDED"
    assert result["audit"][0]["current_id"] == "S-NEW"


def test_active_count_equals_unique_current_identity_and_snapshot_stays_blocked():
    model, plan = fixture(); result = build(model, plan)
    assert result["metrics"]["active_count"] == result["metrics"]["unique_active_identity_count"]
    report = validate_architecture(model)
    assert report["status"] in {"INPUT_REQUIRED", "FAIL"}
    try:
        create_snapshot(model, report, engine_identity={"sha": "test"}, created_at="fixed")
    except ValueError as error:
        assert str(error) == "VALIDATOR_PASS_REQUIRED"
    else:
        raise AssertionError("snapshot must remain fail-closed")
