from cad_engine.plan_segmentation_v13 import _promote_room_evidenced_floor_plans


def test_unknown_frame_with_wet_and_habitable_rooms_becomes_primary_floor():
    plans=[{"plan_id":"P1","drawing_type":"UNKNOWN","mechanical_role":"EXCLUDE"}]
    rooms=[{"plan_id":"P1","type":"toilet"},{"plan_id":"P1","type":"bedroom"}]

    promoted=_promote_room_evidenced_floor_plans(plans,rooms)

    assert promoted == ["P1"]
    assert plans[0]["mechanical_role"] == "PRIMARY_FLOOR"
    assert plans[0]["source"] == "room_evidence_floor_recovery"


def test_known_non_floor_and_weak_unknown_evidence_stay_excluded():
    plans=[
        {"plan_id":"E","drawing_type":"ELEVATION","mechanical_role":"EXCLUDE"},
        {"plan_id":"U","drawing_type":"UNKNOWN","mechanical_role":"EXCLUDE"},
    ]
    rooms=[
        {"plan_id":"E","type":"toilet"},{"plan_id":"E","type":"bedroom"},
        {"plan_id":"U","type":"bedroom"},
    ]

    promoted=_promote_room_evidenced_floor_plans(plans,rooms)

    assert promoted == []
    assert all(plan["mechanical_role"] == "EXCLUDE" for plan in plans)
