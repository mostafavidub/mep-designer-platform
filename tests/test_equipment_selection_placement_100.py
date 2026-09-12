from copy import deepcopy

from cad_engine.equipment_selection_placement_gate import (
    CONTROL_WEIGHTS,
    evaluate_equipment_selection_placement,
)


def good_context():
    equipment = {
        "equipment_id": "IDU-R1", "kind": "split_indoor", "room_id": "R1",
        "level_id": "L1", "host_id": "W1", "inside_host": True,
        "manufacturer": "Official Co", "model": "S12", "selected_capacity": 3.5,
        "datasheet": {"official_url": "https://manufacturer.example/S12", "sha256": "a" * 64},
        "evaluated_candidate_ids": ["S09", "S12"], "selected_candidate_id": "S12",
        "selection_rule": "lowest compliant capacity", "chosen_candidate_id": "LOC-1",
        "highest_ranked_candidate_id": "LOC-1", "placement_scores": {"route": 98, "access": 100},
        "service_clearance_status": "PASS", "replacement_access": True,
        "safety_status": "PASS", "code_clearance_status": "PASS",
        "required_ports": ["refrigerant", "condensate"],
        "architectural_collision": False, "egress_obstruction": False,
    }
    doc_row = {"equipment_id": "IDU-R1", "selected_capacity": 3.5}
    return {
        "rooms": [{"id": "R1", "level_id": "L1", "use": "bedroom", "bounds": [0, 0, 5, 4], "area_m2": 20, "height_m": 3.2}],
        "existing_equipment_inventory": [],
        "required_design_basis_fields": ["summer_design_c", "oversize_policy"],
        "design_basis": {"summer_design_c": 40, "oversize_policy": "project-code", "source": "OWNER_AND_CODE"},
        "required_equipment": [{"equipment_id": "IDU-R1", "room_id": "R1", "calc_id": "CALC-R1", "max_oversize_ratio": 1.2}],
        "calculations": [{"calc_id": "CALC-R1", "demand": 3.2, "unit": "kW", "formula": "room cooling load"}],
        "selected_equipment": [equipment],
        "placement_candidates": [{"equipment_id": "IDU-R1", "id": "LOC-1", "status": "VALID"}],
        "routes": [
            {"id": "REF-1", "from": "IDU-R1", "to": "ODU-1", "system": "refrigerant"},
            {"id": "COND-1", "from": "IDU-R1", "to": "DRAIN-1", "system": "condensate"},
        ],
        "plan_equipment": [deepcopy(doc_row)], "risers": [deepcopy(doc_row)], "schedules": [deepcopy(doc_row)],
        "visual_qa": {"status": "PASS", "equipment_ids": ["IDU-R1"], "critical_defects": []},
    }


def exact():
    return {"reopened": True, "immutable": True, "equipment_ids": ["IDU-R1"]}


def control(report, name):
    return next(row for row in report["controls"] if row["id"] == name)


def test_all_eighteen_controls_total_100_and_release():
    report = evaluate_equipment_selection_placement(good_context(), exact())
    assert len(CONTROL_WEIGHTS) == 18
    assert sum(CONTROL_WEIGHTS.values()) == 100
    assert report["status"] == "PASS"
    assert report["score"] == 100
    assert report["all_controls_pass"] is True
    assert report["release_allowed"] is True


def test_preflight_passes_first_seventeen_but_never_claims_release_without_exact_file():
    report = evaluate_equipment_selection_placement(good_context())
    assert report["preflight_allowed"] is True
    assert report["status"] == "INPUT_REQUIRED"
    assert report["release_allowed"] is False
    assert control(report, "exact_output_release_evidence")["status"] == "INPUT_REQUIRED"


def test_capacity_under_or_over_selection_fails_closed():
    context = good_context()
    context["selected_equipment"][0]["selected_capacity"] = 5.0
    for collection in (context["plan_equipment"], context["risers"], context["schedules"]):
        collection[0]["selected_capacity"] = 5.0
    report = evaluate_equipment_selection_placement(context, exact())
    assert control(report, "capacity_match")["status"] == "FAIL"
    assert report["release_allowed"] is False


def test_missing_official_datasheet_and_nonoptimal_location_do_not_pass():
    context = good_context(); equipment = context["selected_equipment"][0]
    equipment["datasheet"].pop("sha256")
    equipment["chosen_candidate_id"] = "LOC-2"
    report = evaluate_equipment_selection_placement(context, exact())
    assert control(report, "official_catalogue_evidence")["status"] == "INPUT_REQUIRED"
    assert control(report, "multi_criteria_placement")["status"] == "FAIL"


def test_architectural_collision_service_safety_and_port_defects_are_blocking():
    context = good_context(); equipment = context["selected_equipment"][0]
    equipment["architectural_collision"] = True
    equipment["replacement_access"] = False
    equipment["safety_status"] = "FAIL"
    context["routes"] = context["routes"][:1]
    report = evaluate_equipment_selection_placement(context, exact())
    for name in ("architectural_host_validity", "service_clearance", "network_connection_complete", "safety_and_code_clearance"):
        assert control(report, name)["status"] == "FAIL"


def test_plan_riser_schedule_visual_and_exact_output_identity_are_fail_closed():
    context = good_context()
    context["schedules"] = []
    context["visual_qa"]["equipment_ids"] = []
    report = evaluate_equipment_selection_placement(context, {"reopened": True, "immutable": True, "equipment_ids": []})
    for name in ("plan_riser_schedule_identity", "equipment_visual_qa", "exact_output_release_evidence"):
        assert control(report, name)["status"] == "FAIL"


def test_reference_derived_design_basis_is_forbidden():
    context = good_context(); context["design_basis"]["source"] = "MECHANICAL_REFERENCE_DRAWING"
    report = evaluate_equipment_selection_placement(context, exact())
    assert control(report, "design_basis_complete")["status"] == "FAIL"
