from copy import deepcopy

import ezdxf

from cad_engine.architecture_text_evidence import (
    apply_text_review_decision,
    bind_text_hosts,
    build_title_block_fields,
    compare_text_evidence,
    create_text_review_item,
    extract_text_evidence,
    functional_composition,
    normalize_text,
    review_is_current,
    text_review_identity,
    validate_text_contract,
)


SOURCE_SHA = "a" * 64


def _document_with_reused_attribute_block():
    doc = ezdxf.new()
    block = doc.blocks.new("ROOM_TAG")
    block.add_attdef("ROOM", insert=(0, 0), text="Template")
    block.add_text("STATIC", dxfattribs={"insert": (0, 1)})
    msp = doc.modelspace()
    first = msp.add_blockref("ROOM_TAG", (2, 2))
    first.add_attrib("ROOM", "Kitchen", insert=(2, 2))
    second = msp.add_blockref("ROOM_TAG", (12, 2))
    second.add_attrib("ROOM", "Dining", insert=(12, 2))
    return doc


def test_normalization_is_unicode_and_digit_stable():
    assert normalize_text("  آشپزخانه\u200c ۰۱  ") == "آشپزخانه 01"
    assert normalize_text("كريدور") == "کریدور"


def test_attribute_occurrences_preserve_insert_identity_and_attdef_is_template_only():
    evidence = extract_text_evidence(_document_with_reused_attribute_block(), source_sha256=SOURCE_SHA)
    attributes = [x for x in evidence["items"] if x["occurrence_kind"] == "ATTRIBUTE_INSTANCE"]
    assert {x["normalized_text"] for x in attributes} == {"kitchen", "dining"}
    assert len({tuple(x["instance_path"]) for x in attributes}) == 2
    assert len({x["source_insert_handle"] for x in attributes}) == 2
    assert len({x["text_evidence_id"] for x in attributes}) == 2
    templates = [x for x in evidence["items"] if x["entity_type"] == "ATTDEF"]
    assert templates
    assert all(not x["instance_value_authority"] for x in templates)
    assert evidence["metrics"]["geometry_authority_count"] == 0


def test_nested_attribute_preserves_world_transform_and_full_insert_path():
    doc = ezdxf.new()
    child = doc.blocks.new("CHILD")
    child.add_attdef("ROOM", insert=(0, 0), text="Template")
    parent = doc.blocks.new("PARENT")
    nested = parent.add_blockref("CHILD", (2, 3))
    nested.add_attrib("ROOM", "Kitchen", insert=(2, 3))
    root = doc.modelspace().add_blockref("PARENT", (10, 20), dxfattribs={"rotation": 30})
    item = next(x for x in extract_text_evidence(doc, source_sha256=SOURCE_SHA)["items"]
                if x["occurrence_kind"] == "ATTRIBUTE_INSTANCE")
    assert item["block_path"] == ["PARENT", "CHILD"]
    assert len(item["instance_path"]) == 2
    assert len(item["insert_handle_path"]) == 2
    assert item["source_insert_handle"] == root.dxf.handle
    assert item["position"] != [2.0, 3.0]
    assert item["transform_fingerprint"]


def test_space_labels_bind_only_by_containment_and_form_composition():
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("Kitchen", dxfattribs={"insert": (2, 2)})
    msp.add_text("Dining", dxfattribs={"insert": (3, 3)})
    msp.add_text("Bedroom", dxfattribs={"insert": (30, 30)})
    evidence = extract_text_evidence(doc, source_sha256=SOURCE_SHA)
    bound = bind_text_hosts(
        evidence,
        frames=[{"frame_id": "F1", "bounds": [0, 0, 40, 40]}],
        spaces=[{"physical_space_id": "S1", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}],
        tolerance=0.001,
    )
    assert functional_composition(bound, "S1") == ["dining", "kitchen"]
    outside = next(x for x in bound["items"] if x["normalized_text"] == "bedroom")
    assert outside["host_binding"]["status"] == "INPUT_REQUIRED"
    assert outside["host_binding"]["method"] is None
    assert outside["authority"]["semantic"] is False


def test_title_block_attribute_does_not_become_room_semantics_or_engineering_authority():
    doc = ezdxf.new()
    block = doc.blocks.new("TITLE_BLOCK")
    block.add_attdef("SCALE", insert=(0, 0), text="1:100")
    insert = doc.modelspace().add_blockref("TITLE_BLOCK", (20, 20))
    insert.add_attrib("SCALE", "Scale 1:100", insert=(20, 20))
    evidence = extract_text_evidence(doc, source_sha256=SOURCE_SHA)
    bound = bind_text_hosts(evidence, frames=[{"frame_id": "F1", "bounds": [0, 0, 30, 30]}], spaces=[], tolerance=.001)
    fields = build_title_block_fields(bound)
    assert [field["field_role"] for field in fields] == ["SCALE_TEXT"]
    assert fields[0]["authority"]["engineering_scale"] is False
    item = next(x for x in bound["items"] if x["occurrence_kind"] == "ATTRIBUTE_INSTANCE")
    assert item["authority"]["material_geometry"] is False
    assert item["authority"]["engineering_scale"] is False
    assert item["semantic_candidates"] == []


def test_title_context_cannot_leak_room_semantics():
    doc = ezdxf.new()
    block = doc.blocks.new("TITLE_BLOCK")
    block.add_attdef("TITLE", insert=(0, 0), text="Kitchen")
    insert = doc.modelspace().add_blockref("TITLE_BLOCK", (20, 20))
    insert.add_attrib("TITLE", "Kitchen", insert=(20, 20))
    evidence = extract_text_evidence(doc, source_sha256=SOURCE_SHA)
    bound = bind_text_hosts(evidence, frames=[{"frame_id": "F1", "bounds": [0, 0, 30, 30]}],
                            spaces=[{"physical_space_id": "S1", "polygon": [[10, 10], [25, 10], [25, 25], [10, 25], [10, 10]]}],
                            tolerance=.001)
    item = next(x for x in bound["items"] if x["occurrence_kind"] == "ATTRIBUTE_INSTANCE")
    assert item["semantic_candidates"] == ["kitchen"]
    assert item["host_binding"]["host_kind"] == "FRAME"
    assert item["authority"]["document_metadata"] is True
    assert item["authority"]["semantic"] is False


def test_north_text_never_grants_north_or_geometry_authority():
    doc = ezdxf.new()
    doc.modelspace().add_text("NORTH", dxfattribs={"insert": (1, 1)})
    evidence = extract_text_evidence(doc, source_sha256=SOURCE_SHA)
    item = evidence["items"][0]
    assert item["authority"]["north"] is False
    assert item["authority"]["material_geometry"] is False


def test_review_binding_is_stale_when_any_required_scope_identity_changes():
    doc = ezdxf.new()
    doc.modelspace().add_text("Living", dxfattribs={"insert": (1, 1)})
    item = extract_text_evidence(doc, source_sha256=SOURCE_SHA)["items"][0]
    expected = text_review_identity(item, question_scope="SPACE_LABEL_ROLE", frame_id="F1", host_fingerprint="host-a")
    assert review_is_current(expected, deepcopy(expected))
    for key, value in {
        "source_sha256": "b" * 64,
        "frame_id": "F2",
        "entity_handle": "changed",
        "source_insert_handle": "changed",
        "instance_path": ["changed"],
        "insert_handle_path": ["changed"],
        "position_fingerprint": "changed",
        "provenance_fingerprint": "changed",
        "host_fingerprint": "changed",
        "question_scope": "OTHER_SCOPE",
    }.items():
        stale = deepcopy(expected)
        stale[key] = value
        assert not review_is_current(expected, stale), key


def test_validator_rejects_text_engineering_authority_and_attdef_promotion():
    evidence = extract_text_evidence(_document_with_reused_attribute_block(), source_sha256=SOURCE_SHA)
    bad = deepcopy(evidence)
    bad["items"][0]["authority"]["material_geometry"] = True
    template = next(x for x in bad["items"] if x["entity_type"] == "ATTDEF")
    template["instance_value_authority"] = True
    codes = {x["code"] for x in validate_text_contract(bad, source_sha256=SOURCE_SHA)}
    assert "TEXT_ENGINEERING_AUTHORITY_FORBIDDEN" in codes
    assert "ATTDEF_INSTANCE_AUTHORITY_FORBIDDEN" in codes


def test_human_text_review_is_source_bound_and_cannot_create_geometry():
    doc = ezdxf.new()
    doc.modelspace().add_text("Living", dxfattribs={"insert": (1, 1)})
    evidence = extract_text_evidence(doc, source_sha256=SOURCE_SHA)
    item = evidence["items"][0]
    review = create_text_review_item(item, question_scope="TEXT_ROLE", frame_id="F1",
                                     host_fingerprint="host-a",
                                     allowed_answers=["SPACE_LABEL", "NOT_SPACE_LABEL", "UNCERTAIN"])
    decision = {**{key: review[key] for key in (
        "source_sha256", "frame_id", "text_evidence_id", "entity_handle", "source_insert_handle",
        "instance_path", "insert_handle_path", "position_fingerprint", "provenance_fingerprint", "host_fingerprint",
        "question_scope", "review_fingerprint")}, "answer": "SPACE_LABEL"}
    applied = apply_text_review_decision(evidence, review, decision)
    assert applied["status"] == "APPLIED"
    reviewed = applied["text_evidence"]["items"][0]
    assert reviewed["human_review"]["material_geometry"] is False
    assert reviewed["human_review"]["geometry_created"] is False
    stale = deepcopy(decision); stale["position_fingerprint"] = "changed"
    assert apply_text_review_decision(evidence, review, stale)["errors"] == ["TEXT_REVIEW_STALE"]


def test_text_benchmark_reports_dimensions_separately_without_overall_accuracy():
    doc = ezdxf.new()
    doc.modelspace().add_text("Kitchen", dxfattribs={"insert": (1, 1)})
    evidence = extract_text_evidence(doc, source_sha256=SOURCE_SHA)
    item = evidence["items"][0]
    truth = {"schema": "planha-architectural-text-truth/1.0", "review_source": "HUMAN_CURATED",
             "items": [{"text_evidence_id": item["text_evidence_id"],
                        "roles": ["SPACE_LABEL"], "semantics": ["kitchen"],
                        "host_id": None, "is_title_field": False}]}
    report = compare_text_evidence(evidence, truth)
    assert report["overall_accuracy"] is None
    assert set(report["metrics"]) == {"extraction", "role_classification", "host_binding",
                                      "semantic_classification", "title_block_extraction"}
    assert all(row["accuracy"] == 1 for row in report["metrics"].values())


def test_canonical_30_is_not_silently_validated_as_31():
    from cad_engine.architecture_contract import assign_canonical_model_hash
    from cad_engine.architecture_validator import validate_architecture
    from tests.test_architecture_input_foundation_v2 import contract

    model = contract()
    model["schema"] = "planha-canonical-architecture/3.0"
    assign_canonical_model_hash(model)
    report = validate_architecture(model)
    assert "SCHEMA_MISMATCH" in {row["code"] for row in report["hard_errors"]}
    compare_text_evidence,
    create_text_review_item,
