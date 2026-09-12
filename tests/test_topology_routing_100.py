from copy import deepcopy

import pytest

from cad_engine.topology_routing_gate import (
    CONTROL_WEIGHTS, CONTRACT_VERSION, assert_topology_routing_100,
    evaluate_topology_routing,
)


def passing_case():
    calc = "CALC-1"
    network = {
        "schema": "mechanical-network-graph/1", "graph_id": "GRAPH-SEALED-1",
        "levels": [{"id": "L1", "type": "GROUND", "order": 0}],
        "nodes": [
            {"id": "F1", "kind": "basin", "category": "fixture", "level": "L1",
             "room_id": "ROOM-1", "ports": ["cold_water"]},
            {"id": "S1", "kind": "shaft", "category": "vertical_core", "level": "L1",
             "source": "ARCHITECTURAL_SHAFT_GEOMETRY"},
        ],
        "edges": [{
            "id": "E1", "system": "cold_water", "from": "F1", "to": "S1",
            "role": "floor_main", "levels": ["L1"], "endpoint_ids": ["F1"],
            "draw_on_plan": True, "plan_path": [[1, 1], [5, 1], [5, 5]],
            "wall_crossings": 0, "coordinated_terminal_penetrations": 1,
            "constructability_status": "PASS", "requires_slope": False,
            "calc_id": calc, "plan_id": calc, "riser_id": calc, "schedule_id": calc,
        }],
    }
    calculations = [{"network_edge_id": "E1", "calc_id": calc, "size_mm": 20,
                     "material": "PPR", "slope_percent": None}]
    exact = {"edge_ids": ["E1"], "reopened": True, "immutable": True}
    return network, calculations, exact


def report_for(network=None, calculations=None, exact=None, coordination=None, equipment=None):
    good_network, good_calcs, good_exact = passing_case()
    return evaluate_topology_routing(network or good_network, calculations or good_calcs,
                                     coordination=coordination or {}, equipment_routes=equipment or [],
                                     exact_output=good_exact if exact is None else exact)


def test_all_eighteen_controls_are_required_and_total_exactly_100():
    report = report_for()
    assert len(CONTROL_WEIGHTS) == 18
    assert sum(CONTROL_WEIGHTS.values()) == 100
    assert report["contract_version"] == CONTRACT_VERSION
    assert report["status"] == "PASS"
    assert report["score"] == 100
    assert report["release_allowed"] is True
    assert_topology_routing_100(report)


@pytest.mark.parametrize("mutation,error", [
    (lambda n: n["levels"][0].pop("type"), "TYPED_LEVEL_GRAPH_REQUIRED"),
    (lambda n: n["nodes"][0].pop("room_id"), "ENDPOINT_HOST_REQUIRED:F1"),
    (lambda n: n["edges"][0].update({"to": "UNKNOWN"}), "INVALID_TYPED_EDGE:E1"),
    (lambda n: n["edges"][0].update({"to": "F1"}), "SELF_LOOP_FORBIDDEN:E1"),
    (lambda n: n["edges"][0].update({"endpoint_ids": []}), "UNSERVED_ENDPOINT:F1:cold_water"),
    (lambda n: n["nodes"][1].update({"kind": "header", "category": "aggregation"}), "DANGLING_AGGREGATION:S1"),
    (lambda n: n["nodes"][1].update({"source": "PROVISIONAL"}), "PROVISIONAL_SHAFT_FORBIDDEN"),
    (lambda n: n["edges"][0].update({"plan_path": [[1, 1], [2, 2]]}), "NON_ORTHOGONAL_OR_EMPTY_ROUTE:E1"),
    (lambda n: n["edges"][0].update({"wall_crossings": 1}), "INTERMEDIATE_WALL_CROSSING:E1"),
    (lambda n: n["edges"][0].update({"access_blocked": True}), "ROUTE_NOT_CONSTRUCTIBLE:E1"),
    (lambda n: n["edges"][0].update({"schedule_id": "OTHER"}), "IDENTITY_MISMATCH:E1"),
])
def test_each_destructive_mutation_fails_its_control(mutation, error):
    network, calculations, exact = passing_case(); mutation(network)
    report = evaluate_topology_routing(network, calculations, exact_output=exact)
    assert report["status"] == "FAIL"
    assert report["score"] < 100
    assert error in report["errors"]
    with pytest.raises(ValueError):
        assert_topology_routing_100(report)


def test_vertical_discontinuity_and_undeclared_offset_fail_closed():
    network, calculations, _ = passing_case()
    network["levels"] += [{"id": "L2", "type": "FIRST", "order": 1},
                           {"id": "L3", "type": "SECOND", "order": 2}]
    network["nodes"] += [
        {"id": "S2", "kind": "shaft", "category": "vertical_core", "level": "L2", "source": "ARCHITECTURAL_SHAFT_GEOMETRY"},
        {"id": "S3", "kind": "shaft", "category": "vertical_core", "level": "L3", "source": "ARCHITECTURAL_SHAFT_GEOMETRY"},
    ]
    edge = {"id": "V1", "system": "cold_water", "from": "S1", "to": "S3", "role": "vertical_riser",
            "levels": ["L1", "L3"], "endpoint_ids": ["F1"], "draw_on_plan": False,
            "vertical_offset_xy": [1, 0], "offset_declared": False, "requires_slope": False,
            "calc_id": "C2", "plan_id": "C2", "riser_id": "C2", "schedule_id": "C2"}
    network["edges"].append(edge)
    calculations.append({"network_edge_id": "V1", "calc_id": "C2", "size_mm": 25, "material": "PPR"})
    report = evaluate_topology_routing(network, calculations,
        exact_output={"edge_ids": ["E1"], "reopened": True, "immutable": True})
    assert "NON_CONSECUTIVE_VERTICAL_EDGE:V1" in report["errors"]
    assert "UNDECLARED_VERTICAL_OFFSET:V1" in report["errors"]


def test_gravity_route_requires_positive_slope():
    network, calculations, exact = passing_case()
    network["edges"][0].update({"system": "sanitary", "requires_slope": True})
    network["nodes"][0]["ports"] = ["sanitary"]
    calculations[0]["slope_percent"] = 0
    report = evaluate_topology_routing(network, calculations, exact_output=exact)
    assert "POSITIVE_SLOPE_REQUIRED:E1" in report["errors"]


def test_applicable_coordination_and_equipment_envelopes_fail_closed():
    report = report_for(coordination={"status": "FAIL", "claim": "NO_VALID_ROUTE", "clashes": ["BEAM-1"]},
                        equipment=[{"equipment_id": "ODU-1", "required": True, "status": "FAIL"}])
    assert "COORDINATION_NOT_PASS" in report["errors"]
    assert "CRITICAL_CLASH_OR_WARNING_PRESENT" in report["errors"]
    assert "EQUIPMENT_ROUTE_ENVELOPE:ODU-1" in report["errors"]


def test_exact_output_missing_extra_or_unreopened_fails():
    report = report_for(exact={"edge_ids": ["UNKNOWN"], "reopened": False, "immutable": False})
    assert "EXACT_OUTPUT_EDGE_PARITY_FAILED" in report["errors"]
    assert "EXACT_REOPEN_IMMUTABILITY_REQUIRED" in report["errors"]


def test_unknown_or_missing_control_cannot_be_asserted_as_100():
    report = report_for()
    damaged = deepcopy(report); damaged["controls"].pop()
    with pytest.raises(ValueError):
        assert_topology_routing_100(damaged)
    damaged = deepcopy(report); damaged["controls"][0]["status"] = "UNKNOWN"
    with pytest.raises(ValueError):
        assert_topology_routing_100(damaged)
