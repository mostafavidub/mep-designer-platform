from copy import deepcopy

from cad_engine.project_hvac import design_project_hvac


def _architecture():
    return {
        "plans": [{"plan_id": "P1", "mechanical_role": "PRIMARY_FLOOR", "bounds": [0, 0, 30, 20]}],
        "rooms": [
            {"id": "BED", "plan_id": "P1", "type": "bedroom", "label_point": [5, 5]},
            {"id": "LIV", "plan_id": "P1", "type": "living", "label_point": [15, 8]},
            {"id": "KIT", "plan_id": "P1", "type": "kitchen", "label_point": [20, 5]},
            {"id": "BATH", "plan_id": "P1", "type": "bathroom", "label_point": [22, 5]},
        ],
    }


def _answers(total="12"):
    return {"heating_load_kw": total, "hvac": {"heating": "package_radiator", "cooling": None}}


def test_declared_project_load_recovers_invalid_tiny_room_geometry_without_claiming_final():
    calculations = {"rooms": [
        {"calc_id": f"CALC-{room['id']}", "room_id": room["id"], "area_m2": 0.0005, "heating_w": 0}
        for room in _architecture()["rooms"]
    ]}
    result = design_project_hvac(_architecture(), _answers(), calculations)
    heating = result["heating_engineering"]
    radiators = [row for row in result["equipment"] if row["kind"] == "radiator"]
    routes = [row for row in result["routes"] if row["system"].startswith("heating_")]
    assert result["status"] == "PASS"
    assert heating["basis_status"] == "PRE_SUBMISSION"
    assert heating["load_source"] == "PROJECT_TOTAL_WEIGHTED_ALLOCATION"
    assert heating["resolved_total_w"] == 12000
    assert len(radiators) == 4 and len(routes) == 8
    assert all(row["calc_id"] and row["pipe_mm"] > 0 for row in routes)
    assert all(row["velocity_m_s"] <= 1.0 and row["friction_pa_m"] <= 300 for row in routes)
    assert "OFFICIAL_RADIATOR_CATALOGUE_SELECTION" in heating["final_blockers"]


def test_valid_room_calculations_remain_authoritative_and_reconcile_exactly():
    calculations = {"rooms": [
        {"calc_id": "C-BED", "room_id": "BED", "area_m2": 12, "heating_w": 1500},
        {"calc_id": "C-LIV", "room_id": "LIV", "area_m2": 30, "heating_w": 3000},
        {"calc_id": "C-KIT", "room_id": "KIT", "area_m2": 10, "heating_w": 1000},
        {"calc_id": "C-BATH", "room_id": "BATH", "area_m2": 6, "heating_w": 600},
    ]}
    result = design_project_hvac(_architecture(), _answers("6.1"), calculations)
    assert result["status"] == "PASS"
    assert result["heating_engineering"]["load_source"] == "ROOM_HEAT_LOSS"
    assert result["heating_engineering"]["resolved_total_w"] == 6100
    duties = {row["room_id"]: row["required_capacity_kw"] for row in result["equipment"] if row["kind"] == "radiator"}
    assert duties == {"BED": 1.5, "LIV": 3.0, "KIT": 1.0, "BATH": 0.6}


def test_conflicting_valid_room_and_declared_totals_fail_closed():
    calculations = {"rooms": [
        {"calc_id": f"C-{room['id']}", "room_id": room["id"], "area_m2": 10, "heating_w": 1000}
        for room in _architecture()["rooms"]
    ]}
    result = design_project_hvac(_architecture(), _answers("20"), calculations)
    assert result["status"] == "FAIL"
    assert "ROOM_AND_PROJECT_HEATING_LOAD_CONFLICT" in result["heating_engineering"]["errors"]


def test_explicit_zero_without_authoritative_project_total_fails_closed():
    calculations = {"rooms": [{"room_id": room["id"], "area_m2": 0, "heating_w": 0} for room in _architecture()["rooms"]]}
    result = design_project_hvac(_architecture(), _answers(None), calculations)
    assert result["status"] == "FAIL"
    assert not [row for row in result["equipment"] if row["kind"] == "radiator"]
    assert any(error.startswith("UNSERVED_HEATING_ROOMS:") for error in result["heating_engineering"]["errors"])


def test_no_compliant_hydraulic_diameter_blocks_heating_design():
    answers = _answers()
    answers["heating_design"] = {"candidate_diameters_mm": [2], "max_velocity_m_s": 0.05, "max_friction_pa_m": 10}
    calculations = {"rooms": [{"room_id": room["id"], "area_m2": 0.0005, "heating_w": 0} for room in _architecture()["rooms"]]}
    result = design_project_hvac(_architecture(), answers, calculations)
    assert result["status"] == "FAIL"
    assert any("NO_COMPLIANT_DIAMETER" in error for error in result["heating_engineering"]["errors"])


def test_heating_and_cooling_remain_independent():
    answers = _answers()
    answers["hvac"]["cooling"] = "split_ac"
    calculations = {"rooms": [{"room_id": room["id"], "area_m2": 10, "heating_w": 1000, "cooling_w": 1500} for room in _architecture()["rooms"]]}
    result = design_project_hvac(_architecture(), answers, calculations)
    assert any(row["kind"] == "radiator" for row in result["equipment"])
    assert any(row["kind"] == "split_indoor" for row in result["equipment"])
    assert any(row["system"] == "heating_flow" for row in result["routes"])
    assert any(row["system"] == "refrigerant" for row in result["routes"])
