from copy import deepcopy

from cad_engine.architecture_contract import (
    adapt_current_architecture, assign_canonical_model_hash, canonical_model_hash, content_hash,
)
from cad_engine.architecture_review_contract import create_review_item, validate_review_decision
from cad_engine.architecture_snapshot import create_snapshot
from cad_engine.architecture_validator import validate_architecture
from cad_engine.architectural_topology_quality import reconstruct_canonical_walls
from cad_engine.plan_segmentation import _level, _levels


SHA = "c" * 64


def legacy(frames=None, walls=None):
    return {"schema": "canonical-architectural-model/1.0",
            "source": {"source_sha256": SHA, "insunits": "METERS", "metres_per_unit": 1.0},
            "frames": frames or [{"frame_id": "F1", "level_candidate": "LEVEL-01",
                                    "represented_levels": ["LEVEL-01"], "frame_type": "PRIMARY_FLOOR",
                                    "bounds": [0, 0, 10, 10], "status": "SUPPORTED"}],
            "canonical_walls": walls or [{"wall_id": "W1", "frame_id": "F1",
                                            "centerline": [[0, 0], [10, 0]], "source_handles": ["10"],
                                            "status": "SUPPORTED", "evidence": [{"class": "SOURCE"}]}],
            "physical_spaces": [], "functional_zones": [], "internal_wall_gaps": {"items": []},
            "openings": [], "architectural_voids": {"items": []}, "dimensions": [],
            "enclosure_graph": {"edges": []}, "access_graph": {"edges": []},
            "completeness": {"issues": [], "downstream_engineering_allowed": False,
                             "release_allowed": False}}


def error_codes(report):
    return {row["code"] for row in report["hard_errors"]}


def test_semantic_identity_excludes_runtime_and_collection_order_but_not_architecture():
    first = legacy(); first["diagnostics"] = {"runtime_seconds": 1.0, "stage_runtime_seconds": {"walls": .1}}
    second = deepcopy(first); second["diagnostics"]["runtime_seconds"] = 9.0
    a = adapt_current_architecture(first, {"sha": "engine", "build_timestamp": "A"})
    b = adapt_current_architecture(second, {"sha": "engine", "build_timestamp": "B"})
    assert a["canonical_model_hash"] == b["canonical_model_hash"]
    assert a["traceability"]["canonical_identity_version"] == "planha-canonical-identity/2.1"
    assert a["traceability"]["legacy_model_hash"] == b["traceability"]["legacy_model_hash"]
    assert a["traceability"]["legacy_content_hash"] != b["traceability"]["legacy_content_hash"]
    reordered = deepcopy(a); reordered["walls"] = list(reversed(reordered["walls"])); assign_canonical_model_hash(reordered)
    assert reordered["canonical_model_hash"] == a["canonical_model_hash"]
    changed = deepcopy(a); changed["walls"][0]["centerline"][1][0] = 11; assign_canonical_model_hash(changed)
    assert changed["canonical_model_hash"] != a["canonical_model_hash"]


def test_wall_ids_include_world_position_and_ignore_endpoint_and_source_order():
    def row(segment, points):
        return {"frame_id": "F1", "status": "ACCEPTED", "geometry": points,
                "segment_id": segment, "source_handle": None}
    source = [row("A", [[0, 0], [10, 0]]), row("B", [[0, 5], [10, 5]])]
    first = reconstruct_canonical_walls(source, frame_id="F1", tolerance=.001)["walls"]
    reversed_run = reconstruct_canonical_walls([
        row("B", [[10, 5], [0, 5]]), row("A", [[10, 0], [0, 0]])],
        frame_id="F1", tolerance=.001)["walls"]
    assert len({wall["wall_id"] for wall in first}) == 2
    assert sorted(wall["wall_id"] for wall in first) == sorted(wall["wall_id"] for wall in reversed_run)


def test_represented_levels_and_title_evidence_survive_without_geometry_duplication():
    frames = [{"frame_id": "F-TYP", "level_candidate": None,
               "represented_levels": ["LEVEL-03", "LEVEL-01", "LEVEL-02"],
               "frame_type": "PRIMARY_FLOOR", "bounds": [0, 0, 10, 10], "status": "SUPPORTED",
               "title_text": ["پلان معماری طبقات اول تا سوم"], "title_source_handles": ["AA"]}]
    model = adapt_current_architecture(legacy(frames=frames))
    frame = model["frames"][0]
    assert frame["represented_level_ids"] == ["LEVEL-01", "LEVEL-02", "LEVEL-03"]
    assert frame["primary_level_id"] is None and frame["level_relationship"] == "TYPICAL"
    assert {level["level_id"] for level in model["levels"]} == {"LEVEL-01", "LEVEL-02", "LEVEL-03"}
    assert frame["title_evidence"]["raw_text"] == ["پلان معماری طبقات اول تا سوم"]
    assert model["physical_spaces"] == []


def test_five_level_and_roof_headroom_semantics_and_unknown_remain_governed():
    assert _levels("پلان تیپ طبقات اول تا پنجم") == [f"LEVEL-0{i}" for i in range(1, 6)]
    assert _level("پلان خرپشته") == "ROOF_HEADROOM"
    assert _levels("پلان خرپشته") == ["ROOF_HEADROOM"]
    assert _levels("یادداشت شماره ۵ و اندازه ۳") == []
    unknown = adapt_current_architecture(legacy(frames=[{"frame_id": "FU", "level_candidate": None,
        "represented_levels": [], "frame_type": "UNKNOWN", "bounds": [0, 0, 1, 1], "status": "INPUT_REQUIRED"}]))
    assert unknown["frames"][0]["level_relationship"] == "UNRESOLVED"
    assert unknown["levels"][0]["status"] == "INPUT_REQUIRED"


def test_unresolved_authority_is_neutralized_and_external_contradiction_fails():
    unresolved_wall = {"wall_id": "WU", "frame_id": "F1", "centerline": [[0, 0], [1, 0]],
                       "source_handles": ["1"], "status": "INPUT_REQUIRED"}
    model = adapt_current_architecture(legacy(walls=[unresolved_wall]))
    authority = model["walls"][0]["authority"]
    assert authority["status"] == "INPUT_REQUIRED"
    assert not authority["wall"] and not authority["material_geometry"]
    model["walls"][0]["authority"]["wall"] = True; assign_canonical_model_hash(model)
    assert "UNRESOLVED_ENGINEERING_AUTHORITY_FORBIDDEN" in error_codes(validate_architecture(model))


def test_critical_duplicate_and_evidence_references_fail_closed():
    model = adapt_current_architecture(legacy())
    model["portals"] = [{"opening_id": "O1", "portal_id": "P", "type": "UNKNOWN", "status": "INPUT_REQUIRED",
                         "authority": {"status": "INPUT_REQUIRED", "origins": ["SOURCE_GEOMETRIC"],
                                       "material_geometry": False, "wall": False, "portal": False,
                                       "access": False, "routing": False, "release": False}},
                        {"opening_id": "O2", "portal_id": "P", "type": "UNKNOWN", "status": "INPUT_REQUIRED",
                         "authority": {"status": "INPUT_REQUIRED", "origins": ["SOURCE_GEOMETRIC"],
                                       "material_geometry": False, "wall": False, "portal": False,
                                       "access": False, "routing": False, "release": False}}]
    model["dimensions"] = [{"dimension_id": "D", "association_status": "INPUT_REQUIRED",
                            "authority": {"status": "INPUT_REQUIRED", "origins": ["SOURCE_EXPLICIT"]}},
                           {"dimension_id": "D", "association_status": "INPUT_REQUIRED",
                            "authority": {"status": "INPUT_REQUIRED", "origins": ["SOURCE_EXPLICIT"]}}]
    model["walls"][0]["evidence_ids"] = ["MISSING"]; assign_canonical_model_hash(model)
    codes = error_codes(validate_architecture(model))
    assert {"DUPLICATE_PORTAL_ID", "DUPLICATE_DIMENSION_ID", "ENTITY_EVIDENCE_REFERENCE_INVALID"} <= codes


def test_handleless_nested_dimension_gets_stable_source_placement_identity():
    source = legacy()
    source["dimensions"] = [{"handle": "", "entity_type": "DIMENSION", "source_insert_handle": "I1",
                             "source_block_path": ["B1"], "definition_points": [[0, 0], [2, 0]],
                             "witness_points": [[0, 0], [2, 0]], "dimension_type": 0, "layer": "DIM"}]
    first = adapt_current_architecture(source)
    second = adapt_current_architecture(deepcopy(source))
    dimension_id = first["dimensions"][0]["dimension_id"]
    assert dimension_id.startswith("DIMENSION-")
    assert dimension_id == second["dimensions"][0]["dimension_id"]


def test_review_authority_fingerprint_ignores_advisory_presentation_but_not_evidence():
    kwargs = dict(source_sha256=SHA, frame_or_level_id="F1", object_or_region_id="G1",
                  geometry_fingerprint="geo", evidence_fingerprint="ev",
                  candidate_interpretations=["DOOR", "UNKNOWN"], allowed_answers=["DOOR", "UNKNOWN"],
                  impact="REVIEW_CRITICAL", review_scope="TOPOLOGY_CLASSIFICATION_ONLY")
    first = create_review_item(**kwargs, preview_spec={"crop_bounds": [0, 0, 1, 1]}, ai_recommendation="DOOR")
    second = create_review_item(**kwargs, preview_spec={"crop_bounds": [0, 0, 2, 2]}, ai_recommendation="UNKNOWN")
    assert first["review_fingerprint"] == second["review_fingerprint"]
    identity = {key: kwargs[key] for key in ("source_sha256", "frame_or_level_id", "object_or_region_id",
                                             "geometry_fingerprint", "evidence_fingerprint", "review_scope")}
    assert validate_review_decision(first, "DOOR", identity)["status"] == "ACCEPTED"
    stale = dict(identity, evidence_fingerprint="changed")
    assert validate_review_decision(first, "DOOR", stale)["status"] == "REJECTED"


def test_snapshot_id_excludes_creation_time():
    model = adapt_current_architecture(legacy())
    model["release"] = {"status": "VERIFIED", "downstream_engineering_allowed": True, "release_allowed": True}
    assign_canonical_model_hash(model)
    report = validate_architecture(model)
    assert report["status"] == "PASS"
    a = create_snapshot(model, report, engine_identity={"sha": "engine", "build_timestamp": "A"},
                        created_at="2026-01-01T00:00:00Z")
    b = create_snapshot(model, report, engine_identity={"sha": "engine", "build_timestamp": "B"},
                        created_at="2026-01-02T00:00:00Z")
    assert a["snapshot_id"] == b["snapshot_id"]
    assert a["created_at"] != b["created_at"]
