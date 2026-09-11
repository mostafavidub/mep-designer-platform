from cad_engine.engineering_pipeline import recognize_fixtures_equipment


def _inside(point, polygon):
    x, y = point
    hit = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            hit = not hit
        j = i
    return hit


def test_room_program_fixture_proposals_scale_to_room_and_stay_inside():
    polygon = [(100.0, 200.0), (119.0, 200.0), (119.0, 227.7), (100.0, 227.7)]
    architecture = {
        "rooms": [{"id": "R1", "type": "bathroom", "label_point": (107.7, 215.0), "polygon": polygon}],
        "blocks": [],
        "texts": [],
    }

    recognition = recognize_fixtures_equipment(architecture)
    proposed = [row for row in recognition["detections"] if row.get("status") == "proposed"]

    assert {row["type"] for row in proposed} == {"shower", "basin", "floor_drain"}
    assert all(_inside(row["point"], polygon) for row in proposed)
    assert all(abs(row["point"][0] - 107.7) <= 0.761 and abs(row["point"][1] - 215.0) <= 0.761 for row in proposed)
