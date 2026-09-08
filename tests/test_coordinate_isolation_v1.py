from app.coordinate_isolation import isolate_detections
from app.fixture_context_v1 import enrich_fixture_context


def _level(name, authority, source_file, origin=(0.0, 0.0), room_id=None):
    x, y = origin
    room_id = room_id or f"R-{authority}"
    return {
        "name": name,
        "authority_id": authority,
        "source_file": source_file,
        "source_type": "layout",
        "source_name": "Model",
        "title_point": [x, y],
        "region_bounds": [x - 20, y - 20, x + 20, y + 20],
        "local_transform": {
            "origin": [x, y], "translation": [-x, -y],
            "rotation_deg": 0.0, "scale": 1.0,
        },
        "rooms": [{
            "id": room_id,
            "type": "bathroom",
            "label_point": [x + 2, y + 2],
            "bounds": [x, y, x + 10, y + 10],
            "polygon": [[x, y], [x + 10, y], [x + 10, y + 10], [x, y + 10]],
        }],
        "wet_cores": [{"id": f"W-{authority}", "room_ids": [room_id]}],
    }


def _row(category="fixture", kind="toilet", x=2.0, y=2.0, **extra):
    row = {
        "category": category, "type": kind, "x": x, "y": y,
        "source_type": "layout", "source_name": "Model",
        "status": "detected", "confidence": 0.99,
    }
    row.update(extra)
    return row


def test_overlapping_coordinates_in_different_files_stay_with_own_level_authority():
    auto = {"architecture_model": {"levels": [
        _level("Ground A", "LVL-A", "a.dxf"),
        _level("Ground B", "LVL-B", "b.dxf"),
    ]}}
    analysis = {"files": [
        {"file": "a.dxf", "fixture_detections": [_row()]},
        {"file": "b.dxf", "fixture_detections": [_row()]},
    ]}

    result = isolate_detections(auto, analysis)
    assert len(result["fixture_detections"]) == 2
    assert [(r["source_file"], r["level_authority_id"]) for r in result["fixture_detections"]] == [
        ("a.dxf", "LVL-A"), ("b.dxf", "LVL-B")
    ]


def test_same_level_name_in_two_files_does_not_share_room_context_or_schedule():
    level_a = _level("طبقه همکف", "LVL-A", "a.dxf", room_id="ROOM-A")
    level_b = _level("طبقه همکف", "LVL-B", "b.dxf", room_id="ROOM-B")
    auto = {"architecture_model": {"levels": [level_a, level_b]}}
    analysis = {"files": [
        {"file": "a.dxf", "fixture_detections": [_row()]},
        {"file": "b.dxf", "fixture_detections": [_row()]},
    ]}

    isolated = isolate_detections(auto, analysis)
    contextual = enrich_fixture_context(isolated)
    rows = contextual["fixture_detections"]
    assert [(r["level_authority_id"], r["room_id"]) for r in rows] == [
        ("LVL-A", "ROOM-A"), ("LVL-B", "ROOM-B")
    ]
    schedules = contextual["fixture_equipment_model"]["levels"]
    assert [s["level_authority_id"] for s in schedules] == ["LVL-A", "LVL-B"]
    assert [s["fixture_counts"] for s in schedules] == [{"toilet": 1}, {"toilet": 1}]


def test_missing_file_provenance_in_multifile_project_fails_closed():
    auto = {
        "architecture_model": {"levels": [
            _level("A", "LVL-A", "a.dxf"),
            _level("B", "LVL-B", "b.dxf"),
        ]},
        "fixture_detections": [_row(source_type="", source_name="")],
    }
    result = isolate_detections(auto, analysis={})
    row = result["fixture_detections"][0]
    assert row.get("level") is None
    assert row.get("level_authority_id") is None
    assert row["coordinate_isolation_status"] == "unassigned_ambiguous_source"
    assert result["coordinate_isolation"]["unassigned_count"] == 1


def test_detection_cannot_be_stolen_by_other_file_when_outside_own_frame():
    auto = {"architecture_model": {"levels": [
        _level("A", "LVL-A", "a.dxf", origin=(0, 0)),
        _level("B", "LVL-B", "b.dxf", origin=(1000, 1000)),
    ]}}
    analysis = {"files": [{
        "file": "a.dxf",
        "fixture_detections": [_row(x=1002, y=1002)],
    }]}
    result = isolate_detections(auto, analysis)
    row = result["fixture_detections"][0]
    assert row.get("level_authority_id") is None
    assert row["coordinate_isolation_status"] == "unassigned_outside_level_frame"


def test_explicit_authority_wins_inside_matching_source_file():
    auto = {"architecture_model": {"levels": [
        _level("A", "LVL-A", "a.dxf", origin=(0, 0)),
        _level("B", "LVL-B", "a.dxf", origin=(100, 0)),
    ]}}
    analysis = {"files": [{
        "file": "a.dxf",
        "fixture_detections": [_row(x=90, y=0, level_authority_id="LVL-A")],
    }]}
    result = isolate_detections(auto, analysis)
    row = result["fixture_detections"][0]
    assert row["level_authority_id"] == "LVL-A"
    assert row["coordinate_isolation_status"] == "assigned_explicit_authority"


def test_invalid_cross_file_explicit_authority_fails_closed():
    auto = {"architecture_model": {"levels": [
        _level("A", "LVL-A", "a.dxf"),
        _level("B", "LVL-B", "b.dxf"),
    ]}}
    analysis = {"files": [{
        "file": "a.dxf",
        "fixture_detections": [_row(level_authority_id="LVL-B")],
    }]}
    result = isolate_detections(auto, analysis)
    row = result["fixture_detections"][0]
    assert row.get("level_authority_id") is None
    assert row["coordinate_isolation_status"] == "unassigned_invalid_authority"


def test_local_coordinate_is_translation_invariant():
    auto = {"architecture_model": {"levels": [
        _level("A", "LVL-A", "a.dxf", origin=(100, 200)),
        _level("B", "LVL-B", "b.dxf", origin=(1000, 2000)),
    ]}}
    analysis = {"files": [
        {"file": "a.dxf", "fixture_detections": [_row(x=105, y=207)]},
        {"file": "b.dxf", "fixture_detections": [_row(x=1005, y=2007)]},
    ]}
    result = isolate_detections(auto, analysis)
    assert [r["level_local_position"] for r in result["fixture_detections"]] == [[5.0, 7.0], [5.0, 7.0]]


def test_equipment_at_identical_coordinates_in_two_files_remains_two_records():
    auto = {"architecture_model": {"levels": [
        _level("A", "LVL-A", "a.dxf"),
        _level("B", "LVL-B", "b.dxf"),
    ]}}
    analysis = {"files": [
        {"file": "a.dxf", "equipment_detections": [_row(category="equipment", kind="boiler")]},
        {"file": "b.dxf", "equipment_detections": [_row(category="equipment", kind="boiler")]},
    ]}
    result = isolate_detections(auto, analysis)
    assert len(result["equipment_detections"]) == 2
    assert {r["level_authority_id"] for r in result["equipment_detections"]} == {"LVL-A", "LVL-B"}


def test_single_file_legacy_detection_without_source_file_remains_supported():
    auto = {
        "architecture_model": {"levels": [_level("Ground", "LVL-A", "a.dxf")]},
        "fixture_detections": [_row()],
    }
    result = isolate_detections(auto, analysis={})
    row = result["fixture_detections"][0]
    assert row["level"] == "Ground"
    assert row["level_authority_id"] == "LVL-A"
    assert row["coordinate_isolation_status"].startswith("assigned_")
