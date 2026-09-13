from cad_engine.project_hvac_v13 import design_project_hvac


def _architecture():
    return {
        "plans": [{"plan_id": "P1", "mechanical_role": "PRIMARY_FLOOR", "bounds": [0, 0, 30, 20]}],
        "rooms": [
            {"id": "BED", "plan_id": "P1", "type": "bedroom", "label_point": [5, 5]},
            {"id": "LIV", "plan_id": "P1", "type": "living", "label_point": [15, 8]},
            {"id": "KIT", "plan_id": "P1", "type": "kitchen", "label_point": [20, 5]},
            {"id": "BATH", "plan_id": "P1", "type": "bathroom", "label_point": [22, 5]},
            {"id": "TER", "plan_id": "P1", "type": "terrace", "label_point": [28, 8]},
        ],
    }


def test_equipment_capacity_is_driven_by_room_calculation_not_room_type_constant():
    calculations = {"rooms": [
        {"calc_id": "CALC-BED", "room_id": "BED", "cooling_w": 2500, "heating_w": 900},
        {"calc_id": "CALC-LIV", "room_id": "LIV", "cooling_w": 8000, "heating_w": 3200},
        {"room_id": "KIT", "heating_w": 1400},
        {"room_id": "BATH", "heating_w": 600},
    ]}
    result = design_project_hvac(_architecture(), {"hvac": {"cooling": "split_ac", "heating": "package_radiator"}}, calculations)
    units = {row.get("room_id"): row for row in result["equipment"] if row["kind"] == "split_indoor"}
    assert units["BED"]["capacity_btu_h"] == 9000
    assert units["LIV"]["capacity_btu_h"] == 30000
    assert units["LIV"]["required_capacity_btu_h"] == 27297
    assert units["LIV"]["source_calc_id"] == "CALC-LIV"
    radiators = {row.get("room_id"): row for row in result["equipment"] if row["kind"] == "radiator"}
    assert radiators["LIV"]["capacity_kw"] == 3.6
    assert radiators["LIV"]["required_capacity_kw"] == 3.2


def test_missing_room_calculation_does_not_invent_fixed_capacity():
    result = design_project_hvac(_architecture(), {"hvac": {"cooling": "split_ac", "heating": "package_radiator"}}, {"rooms": []})
    assert not [row for row in result["equipment"] if row["kind"] in {"split_indoor", "radiator"}]
