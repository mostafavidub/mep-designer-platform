from copy import deepcopy
import json
from pathlib import Path
import zipfile
from io import BytesIO

import pytest

from cad_engine.architecture_benchmark import compare_architecture
from cad_engine.architecture_contract import adapt_current_architecture, assign_canonical_model_hash, content_hash
from cad_engine.architecture_review_contract import create_review_item, validate_review_decision
from cad_engine.architecture_snapshot import create_snapshot, supersede_snapshot, validate_snapshot
from cad_engine.architecture_validator import validate_architecture
from cad_engine.planha_package import pack_planha, unpack_planha


SHA = "a" * 64


def legacy_model():
    return {
        "schema": "canonical-architectural-model/1.0",
        "source": {"source_sha256": SHA, "insunits": "METERS", "metres_per_unit": 1.0},
        "frames": [{"frame_id": "F1", "level_candidate": "L1", "frame_type": "PLAN",
                    "bounds": [0, 0, 12, 10], "status": "SUPPORTED"}],
        "canonical_walls": [{"wall_id": "W1", "frame_id": "F1", "centerline": [[5, 0], [5, 10]],
                             "thickness": .2, "representation": "CENTERLINE",
                             "source_handles": ["10"], "status": "SUPPORTED"}],
        "physical_spaces": [
            {"physical_space_id": "S1", "level_id": "L1", "frame_id": "F1",
             "polygon": [[0, 0], [5, 0], [5, 10], [0, 10]], "interior_rings": [],
             "area_m2": 50, "perimeter_m": 30, "status": "VERIFIED", "source_handles": ["20"]},
            {"physical_space_id": "S2", "level_id": "L1", "frame_id": "F1",
             "polygon": [[5, 0], [10, 0], [10, 10], [5, 10]], "interior_rings": [],
             "area_m2": 50, "perimeter_m": 30, "status": "VERIFIED", "source_handles": ["21"]}],
        "functional_zones": [{"zone_id": "Z1", "physical_space_id": "S1", "category": "LIVING",
                              "boundary_status": "approximate", "status": "SUPPORTED"}],
        "internal_wall_gaps": {"items": [{"gap_id": "G1", "frame_id": "F1", "classification": "DOOR",
                                            "status": "SUPPORTED", "geometry": [[5, 4], [5, 5]],
                                            "host_wall_ids": ["W1"], "source_handles": ["30"]}]},
        "openings": [{"opening_id": "O1", "portal_id": "P1", "kind": "door", "frame_id": "F1",
                      "host_wall_id": "W1", "host_gap_id": "G1", "space_a": "S1", "space_b": "S2",
                      "portal_geometry": [[5, 4], [5, 5]], "source_handles": ["30"], "status": "VERIFIED"}],
        "architectural_voids": {"items": [{"void_id": "V1", "frame_id": "F1", "void_type": "DUCT",
                                             "boundary": [[10.5, 1], [11.5, 1], [11.5, 2], [10.5, 2]],
                                             "area": 1, "source_handles": ["40"], "status": "VERIFIED"}]},
        "dimensions": [{"dimension_id": "D1", "handle": "50", "measurement": 5,
                        "association_status": "INPUT_REQUIRED"}],
        "enclosure_graph": {"edges": [["S1", "S2"]]},
        "access_graph": {"edges": [{"portal_id": "P1", "gap_id": "G1", "host_wall_id": "W1",
                                      "space_a": "S1", "space_b": "S2", "source_handles": ["30"]}]},
        "completeness": {"issues": [], "downstream_engineering_allowed": False, "release_allowed": False}}


def contract():
    from tests.architecture_separator_fixtures import declare_structured_separators
    return assign_canonical_model_hash(declare_structured_separators(adapt_current_architecture(legacy_model(), {"sha": "engine"})))


def qualified_contract():
    row = contract()
    row["release"] = {"status": "VERIFIED", "downstream_engineering_allowed": True,
                      "release_allowed": True}
    return rehash(row)


def rehash(model):
    return assign_canonical_model_hash(model)


def codes(report):
    return {row["code"] for row in report["hard_errors"]}


def test_schemas_are_machine_readable_and_named():
    root = Path(__file__).parents[1] / "standards" / "test-suites"
    names = ["planha-canonical-architecture-v2.schema.json", "planha-canonical-architecture-v3.schema.json",
             "planha-validated-architecture-snapshot-v1.schema.json",
             "planha-architecture-review-v1.schema.json",
             "planha-architecture-truth-v1.schema.json",
             "planha-package-manifest-v1.schema.json"]
    for name in names:
        schema = json.loads((root / name).read_text())
        assert schema["$schema"].endswith("2020-12/schema")
        assert "required" in schema


def test_adapter_preserves_meaning_is_deterministic_and_does_not_mutate():
    current = legacy_model(); before = content_hash(current)
    first = adapt_current_architecture(current); second = adapt_current_architecture(current)
    assert first == second
    assert content_hash(current) == before
    assert first["source"]["source_sha256"] == SHA
    assert first["physical_spaces"][0]["polygon"] == current["physical_spaces"][0]["polygon"]
    assert first["functional_zones"][0]["category"] == "LIVING"
    assert first["voids"][0]["boundary"] == current["architectural_voids"]["items"][0]["boundary"]
    assert first["graphs"]["access"] == current["access_graph"]["edges"]
    assert first["release"]["release_allowed"] is False
    assert all(origin != "VISION_SUPPORT_ONLY" for row in first["walls"] for origin in row["authority"]["origins"])


def test_structural_obstacle_adapter_preserves_source_geometry_without_authority():
    current = legacy_model()
    current["structural_obstacles"] = {"items": [{
        "structural_obstacle_id":"COLUMN-" + "A"*20, "obstacle_type":"COLUMN",
        "frame_id":"F1", "level_id":"L1", "footprint":[[1,1],[1.4,1],[1.4,1.4],[1,1.4]],
        "world_coordinates":[[1,1],[1.4,1],[1.4,1.4],[1,1.4]],
        "source_handle":"C1", "source_occurrence_id":"SRC-" + "1"*16,
        "source_geometry_fingerprint":"COL-GEO-" + "2"*20,
        "geometry_qualification":"SOURCE_BACKED", "obstacle_classification":"OBSTACLE_EVIDENCE_ONLY",
        "authority":{"status":"SUPPORTED","origins":["SOURCE_GEOMETRIC"],
                     "material_geometry":True,"wall":True,"routing":True,"release":True}
    }]}
    adapted = adapt_current_architecture(current)
    row = adapted["structural_obstacles"][0]
    assert row["footprint"] == current["structural_obstacles"]["items"][0]["footprint"]
    assert not any(row["authority"].get(key) for key in
                   ("material_geometry", "wall", "portal", "access", "routing", "release", "envelope"))


def test_validator_rejects_column_authority_and_invalid_column_geometry():
    model = contract()
    model["structural_obstacles"] = [{
        "structural_obstacle_id":"COLUMN-" + "A"*20, "obstacle_type":"COLUMN", "frame_id":"F1",
        "footprint":[[1,1],[1.4,1],[1.4,1.4],[1,1.4]],
        "source_occurrence_id":"SRC-" + "1"*16,
        "source_geometry_fingerprint":"COL-GEO-" + "2"*20,
        "geometry_qualification":"SOURCE_BACKED", "obstacle_classification":"OBSTACLE_EVIDENCE_ONLY",
        "authority":{"status":"SUPPORTED","origins":["SOURCE_GEOMETRIC"],
                     "material_geometry":False,"wall":False,"portal":False,"access":False,
                     "routing":True,"release":False,"envelope":False}
    }]
    rehash(model)
    assert "COLUMN_ENGINEERING_AUTHORITY_FORBIDDEN" in codes(validate_architecture(model))
    model["structural_obstacles"][0]["authority"]["routing"] = False
    model["structural_obstacles"][0]["footprint"] = [[0,0],[1,1],[0,1],[1,0]]
    rehash(model)
    assert "STRUCTURAL_OBSTACLE_GEOMETRY_INVALID" in codes(validate_architecture(model))


def test_validator_valid_model_is_read_only_and_no_score_masking():
    model = contract(); before = content_hash(model)
    report = validate_architecture(model)
    assert report["status"] == "INPUT_REQUIRED"
    assert report["critical_score_masking"] is False
    assert report["input_hash_before"] == report["input_hash_after"]
    assert content_hash(model) == before


@pytest.mark.parametrize("mutator, expected", [
    (lambda m: m["walls"].append(deepcopy(m["walls"][0])), "DUPLICATE_WALL_ID"),
    (lambda m: m["physical_spaces"][0].update(polygon=[[0, 0], [1, 1], [0, 1], [1, 0]]), "PHYSICAL_SPACE_POLYGON_INVALID"),
    (lambda m: m["physical_spaces"][1].update(polygon=[[4, 0], [9, 0], [9, 10], [4, 10]]), "ILLEGAL_PHYSICAL_SPACE_OVERLAP"),
    (lambda m: m["portals"][0].update(host_wall_id="NOPE"), "PORTAL_HOST_WALL_INVALID"),
    (lambda m: m["portals"][0].update(host_aperture_id=None), "PORTAL_HOST_APERTURE_INVALID"),
    (lambda m: m["graphs"]["access"][0].update(portal_id="NOPE"), "ACCESS_EDGE_PORTAL_REFERENCE_INVALID"),
    (lambda m: m["voids"][0].update(boundary=[[1, 1], [2, 1], [2, 2], [1, 2]]), "VOID_OCCUPIED_SPACE_OVERLAP"),
    (lambda m: m["voids"][0].update(source_handles=[], authority={"status": "VERIFIED", "origins": ["SOURCE_SEMANTIC"], "material_geometry": False}), "VOID_SOURCE_GEOMETRY_REQUIRED"),
    (lambda m: m["source"].update(source_sha256=None), "SOURCE_SHA256_MISSING_OR_INVALID"),
    (lambda m: m["walls"][0]["authority"].update(origins=["UNKNOWN"]), "UNKNOWN_AUTHORITY_ORIGIN"),
    (lambda m: m["dimensions"][0].update(association_status="VERIFIED"), "DIMENSION_FALSE_VERIFIED_ASSOCIATION"),
    (lambda m: m["functional_zones"][0].update(polygon=[[0, 0], [1, 0], [1, 1]], authority={"status": "VERIFIED", "origins": ["SOURCE_SEMANTIC"], "material_geometry": True}), "APPROXIMATE_ZONE_MATERIAL_AUTHORITY_FORBIDDEN"),
])
def test_validator_destructive_mutations(mutator, expected):
    model = contract(); mutator(model); rehash(model)
    assert expected in codes(validate_architecture(model))


def test_window_access_and_cross_level_and_stale_review_fail():
    model = contract(); model["portals"][0]["type"] = "WINDOW"; rehash(model)
    assert {"WINDOW_ACCESS_AUTHORITY_FORBIDDEN", "WINDOW_ACCESS_EDGE_FORBIDDEN"} <= codes(validate_architecture(model))
    model = contract()
    model["levels"].append({"level_id": "L2", "status": "SUPPORTED", "source_frame_ids": ["F2"]})
    model["frames"].append({"frame_id": "F2", "level_id": "L2", "source_identity": SHA, "status": "SUPPORTED"})
    model["physical_spaces"].append({**deepcopy(model["physical_spaces"][1]), "physical_space_id": "S3", "frame_id": "F2", "level_id": "L2"})
    model["portals"][0]["space_b"] = "S3"; rehash(model)
    assert "CROSS_LEVEL_PORTAL_FORBIDDEN" in codes(validate_architecture(model))
    model = contract(); model["review_registry"] = {"stale_review_decisions": [{"question_id": "Q", "review_authority": "HUMAN_SOURCE_INTERPRETATION"}]}; rehash(model)
    assert "STALE_REVIEW_AUTHORITY_FORBIDDEN" in codes(validate_architecture(model))


def test_review_is_bounded_and_stale_identity_is_rejected():
    identity = {"source_sha256": SHA, "frame_or_level_id": "F1", "object_or_region_id": "G1",
                "geometry_fingerprint": "geo", "evidence_fingerprint": "ev", "review_scope": "TOPOLOGY_CLASSIFICATION_ONLY"}
    item = create_review_item(**identity, candidate_interpretations=["DOOR", "UNKNOWN"],
                              allowed_answers=["DOOR", "UNKNOWN"], impact={"access": True},
                              ai_recommendation="DOOR", ai_recommendation_confidence="MEDIUM")
    accepted = validate_review_decision(item, "DOOR", identity)
    assert accepted["authority"] == "HUMAN_SOURCE_INTERPRETATION"
    assert accepted["material_geometry_authority"] is False
    stale = dict(identity, geometry_fingerprint="changed")
    assert validate_review_decision(item, "DOOR", stale)["errors"] == ["REVIEW_DECISION_STALE"]


def test_snapshot_identity_and_staleness():
    model = qualified_contract(); report = validate_architecture(model)
    snap = create_snapshot(model, report, engine_identity={"sha": "engine"}, created_at="2026-01-01T00:00:00Z")
    assert validate_snapshot(snap, model, report)["status"] == "PASS"
    assert create_snapshot(model, report, engine_identity={"sha": "engine"}, created_at="2026-01-01T00:00:00Z") == snap
    changed = deepcopy(model); changed["physical_spaces"][0]["category"] = "OTHER"; rehash(changed)
    assert "SNAPSHOT_CANONICAL_MODEL_STALE" in validate_snapshot(snap, changed, validate_architecture(changed))["errors"]
    assert "SNAPSHOT_SOURCE_CHANGED" in validate_snapshot(snap, model, report, current_source_sha256="b" * 64)["errors"]
    assert "SNAPSHOT_REVIEW_MANIFEST_STALE" in validate_snapshot(snap, model, report, review_manifest={"x": 1})["errors"]
    assert validate_snapshot(supersede_snapshot(snap), model, report)["current_authority"] is False


def test_planha_package_round_trip_is_deterministic_and_corruption_fails():
    model = qualified_contract(); report = validate_architecture(model)
    snap = create_snapshot(model, report, engine_identity={"sha": "engine"}, created_at="2026-01-01T00:00:00Z")
    first = pack_planha(architecture=model, snapshot=snap, validation=report, review={})
    second = pack_planha(architecture=model, snapshot=snap, validation=report, review={})
    assert first == second
    reopened = unpack_planha(first)
    assert reopened["snapshot"]["snapshot_id"] == snap["snapshot_id"]
    assert reopened["manifest"]["source_embedding"] == "REFERENCE_BY_SHA256_ONLY"
    broken = bytearray(first); broken[-10] ^= 1
    with pytest.raises(ValueError):
        unpack_planha(bytes(broken))
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", "{}")
    with pytest.raises(ValueError):
        unpack_planha(stream.getvalue())


def truth():
    model = contract()
    return {"schema": "planha-architecture-truth/1.0", "source_sha256": SHA,
            "review_source": "SYNTHETIC", "review_version": "1", "cohort": "DEVELOPMENT",
            "blind_output_sealed": True, "levels": model["levels"],
            "physical_spaces": [{"truth_space_id": "T1", "polygon": model["physical_spaces"][0]["polygon"]},
                                {"truth_space_id": "T2", "polygon": model["physical_spaces"][1]["polygon"]}],
            "portals": [{"type": "DOOR", "host_wall_id": "W1", "host_aperture_id": "G1", "status": "VERIFIED"}],
            "voids": [{"truth_void_id": "TV1", "boundary": model["voids"][0]["boundary"]}],
            "access_graph": model["graphs"]["access"], "ambiguities": [], "release_allowed": False}


def test_benchmark_is_deterministic_and_hard_gates_cannot_be_masked():
    model = contract(); reviewed = truth()
    first = compare_architecture(model, reviewed)
    assert first == compare_architecture(model, reviewed)
    assert first["status"] == "PASS" and first["critical_score_masking"] is False
    assert {"level_precision", "mean_space_iou", "relevant_wall_recall", "void_precision",
            "access_accuracy", "false_authority_count", "determinism_identity"} <= set(first["metrics"])
    reviewed["portals"] = []
    failed = compare_architecture(model, reviewed)
    assert failed["status"] == "FAIL" and failed["hard_gates"]["false_portal_authority"] == 1
    reviewed = truth(); reviewed["cohort"] = "EVALUATION_HELD_OUT"; reviewed["blind_output_sealed"] = False
    with pytest.raises(ValueError, match="HELD_OUT_BLIND_OUTPUT_NOT_SEALED"):
        compare_architecture(model, reviewed)


def test_benchmark_includes_review_metrics_and_hard_gates_review_authority():
    model = contract(); reviewed = truth()
    preflight = {"reviewed_validation_pass": True, "metrics": {
        "validator_issue_count": 3, "critical_issue_count": 2,
        "reviewable_issue_count": 2, "nonreviewable_issue_count": 1,
        "generated_review_item_count": 1, "issue_to_question_reduction_ratio": 0.5,
        "resolved_issue_count": 2, "remaining_issue_count": 1,
        "stale_decision_count": 0, "duplicate_question_count": 0,
        "repeated_question_after_same_decision_count": 0,
        "manual_geometry_creation_count": 0, "snapshot_created": True,
    }}
    report = compare_architecture(model, reviewed, preflight)
    assert report["status"] == "PASS"
    assert report["metrics"]["generated_review_item_count"] == 1
    assert report["metrics"]["validated_after_review"] is True
    unsafe = deepcopy(preflight)
    unsafe["metrics"]["synthetic_portal_from_review_count"] = 1
    failed = compare_architecture(model, reviewed, unsafe)
    assert failed["status"] == "FAIL"
    assert failed["hard_gates"]["synthetic_portal_from_review"] == 1
