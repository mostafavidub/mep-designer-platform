import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.mechanical_network_topology import (
    build_authoritative_topology_from_evidence, _architecture_from_evidence,
    _recognition_from_evidence, _assign_level, _resolve_level_for_point, _typed_level,
)
from cad_engine.mechanical_segment_execution import design_authoritative_segments
from cad_engine.mechanical_network_materializer import materialize_authoritative_network
from cad_engine.topology_routing_gate import evaluate_topology_routing


def pmm(levels, vertical=False):
    return {
        'schema': 'project-mechanical-model/v3',
        'levels': levels,
        'systems': {'vertical_systems': vertical},
        'identity_registry': {'entities': [], 'alias_to_entity_id': {}},
        'traceability_contract': {'policy': 'NO_ORPHAN_ENGINEERING_OUTPUT'},
    }


def detection(item_id='MEP-1', point=(2.0, 2.0), ports=None, kind='basin', room='R1'):
    return {
        'id': item_id, 'category': 'fixture', 'type': kind, 'point': point,
        'room_id': room, 'ports': list(ports or ['cold_water']),
        'evidence': ['block_name'], 'block': kind, 'layer': 'FIXTURE',
    }


class TopologyAuthorityV19Tests(unittest.TestCase):
    def test_unreliable_roof_scope_cannot_host_declared_fixtures(self):
        architecture = _architecture_from_evidence({
            "roof_scope_reliable": False,
            "levels": [
                {"name": "Roof", "roof": True,
                 "wet_cores": [{"id": "WR", "center": [200, 200]}]},
                {"name": "Ground", "roof": False,
                 "wet_cores": [{"id": "WG", "center": [2, 2]}]},
            ],
        }, {"walls": [], "obstacles": []})
        self.assertEqual([row["level"] for row in architecture["wet_cores"]], ["Ground"])
        recognition = _recognition_from_evidence(
            [], {"detections": []}, architecture, "shower 1; toilet 1",
        )
        self.assertTrue(recognition["detections"])
        self.assertEqual({row["level"] for row in recognition["detections"]}, {"Ground"})

    def test_unreliable_roof_scope_cannot_be_revived_by_fixture_evidence(self):
        architecture = _architecture_from_evidence({
            "roof_scope_reliable": False,
            "levels": [
                {"name": "بام", "roof": True,
                 "rooms": [{"id": "R-ROOF", "type": "kitchen", "center": [20, 20]}]},
                {"name": "طبقه اول", "roof": False,
                 "rooms": [{"id": "R-FIRST", "type": "kitchen", "center": [2, 2]}]},
            ],
        }, {"walls": [], "obstacles": []})
        recognition = _recognition_from_evidence([
            {"status": "detected", "type": "gas", "x": 20, "y": 20,
             "level": "بام", "room_id": "R-ROOF"},
            {"status": "detected", "type": "gas", "x": 2, "y": 2,
             "level": "طبقه اول", "room_id": "R-FIRST"},
        ], {"detections": []}, architecture)
        self.assertEqual(len(recognition["detections"]), 1)
        self.assertEqual(recognition["detections"][0]["level"], "طبقه اول")
        self.assertEqual(recognition["detections"][0]["type"], "stove")

    def test_architecture_room_shaft_is_authoritative_not_provisional(self):
        architecture = _architecture_from_evidence({"levels": [{
            "name": "طبقه همکف", "rooms": [{"id": "R-S", "type": "shaft", "center": [8, 8],
                                                   "polygon": [[7, 7], [9, 7], [9, 9], [7, 9]]}],
            "wet_cores": [{"id": "W1", "center": [2, 2]}],
        }]}, {"walls": [], "obstacles": []})
        self.assertEqual(architecture["shafts"][0]["source"], "ARCHITECTURAL_SHAFT_ROOM")
        result = build_authoritative_topology_from_evidence(
            pmm([{"name": "طبقه همکف", "region_bounds": [0, 0, 10, 10]}]), architecture,
            {"detections": [detection(point=(2, 2), ports=["cold_water"])]},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("PROVISIONAL_SHAFT_FORBIDDEN", str(result))

    def test_owner_declared_fixture_count_creates_designed_not_detected_endpoints(self):
        architecture = {"wet_cores": [{"room_id": "W1", "centroid": (2, 2), "level": "Ground"}]}
        recognition = _recognition_from_evidence([], {"detections": []}, architecture,
                                                 "sink 2; toilet 1; bath 1")
        self.assertEqual(len(recognition["detections"]), 4)
        self.assertTrue(all(row["installed"] is False for row in recognition["detections"]))
        self.assertTrue(all(row["design_status"] == "DESIGNED_FROM_OWNER_DECLARED_COUNT"
                            for row in recognition["detections"]))
        points = [tuple(row["point"]) for row in recognition["detections"]]
        self.assertEqual(len(points), len(set(points)))
        self.assertTrue(all(point != (2, 2) for point in points))

    def test_owner_declared_endpoint_routes_are_not_zero_length(self):
        architecture = {"wet_cores": [{"room_id": "W1", "centroid": (2, 2), "level": "Ground"}],
                        "rooms": [{"id": "W1", "polygon": [(1, 1), (3, 1), (3, 3), (1, 3)]}],
                        "shafts": [], "walls": [], "obstacles": []}
        recognition = _recognition_from_evidence([], {"detections": []}, architecture, "sink 1")
        result = build_authoritative_topology_from_evidence(
            pmm([{"name": "Ground", "region_bounds": [0, 0, 10, 10]}]), architecture, recognition)
        self.assertEqual(result["status"], "PASS", result)
        for edge in result["network"]["edges"]:
            if edge.get("draw_on_plan"):
                self.assertGreater(sum(
                    __import__("math").dist(edge["plan_path"][index - 1], edge["plan_path"][index])
                    for index in range(1, len(edge["plan_path"]))), 0)

    def test_candidate_fixture_evidence_is_not_promoted_to_installed(self):
        recognition = _recognition_from_evidence(
            [{"status": "candidate", "type": "toilet", "x": 2, "y": 2}],
            {"detections": []}, {"wet_cores": []}, None,
        )
        self.assertEqual(recognition["detections"], [])

    def test_duplicate_roof_view_fixture_is_not_routed_on_canonical_roof(self):
        model = pmm([
            {"name": "بام", "roof": True, "region_bounds": [0, 0, 10, 10]},
            {"name": "پشت بام", "roof": True, "region_bounds": [20, 0, 30, 10]},
        ])
        result = build_authoritative_topology_from_evidence(
            model, {"shafts": [{"centroid": (8, 8), "polygon": []}], "wet_cores": [], "walls": [], "obstacles": []},
            {"detections": [
                {**detection('CANONICAL', point=(2, 2), ports=["cold_water"]), "level": "بام"},
                {**detection('DUPLICATE', point=(22, 2), ports=["cold_water"], room=None), "level": "پشت بام"},
            ]},
        )
        self.assertEqual(result["status"], "PASS")
        qa = evaluate_topology_routing(result["network"])
        self.assertFalse(any(
            value.startswith("NO_SYSTEM_TERMINATION:") for value in qa["errors"]
        ))
        self.assertEqual(len(result["network"]["levels"]), 1)
        self.assertEqual(
            result["evidence"]["excluded_unhosted_out_of_plan_detections"],
            ["DUPLICATE"],
        )

    def test_single_active_plumbing_level_does_not_require_cross_level_shaft(self):
        model = pmm([
            {"name": "Ground", "region_bounds": [0, 0, 10, 10]},
            {"name": "First", "region_bounds": [20, 0, 30, 10]},
        ])
        result = build_authoritative_topology_from_evidence(
            model, {"shafts": [], "wet_cores": [{"centroid": (8, 8)}], "walls": [], "obstacles": []},
            {"detections": [detection(point=(2, 2), ports=["cold_water"])]},
        )
        self.assertEqual(result["status"], "PASS")

    def test_explicit_typical_floor_ranges_are_source_backed_level_types(self):
        self.assertEqual(_typed_level('طبقات اول تا سوم'), 'TYPICAL_1_3')
        self.assertEqual(_typed_level('Typical floors 2 to 5'), 'TYPICAL_2_5')

    def test_multilevel_without_bounds_or_assignment_fails_closed(self):
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'Ground'}, {'name': 'First'}]),
            {'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': []},
            {'detections': [detection()]},
        )
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertTrue(any(value.startswith('LEVEL_ASSIGNMENT_REQUIRED:') for value in result['missing_inputs']))

    def test_unique_most_specific_nested_level_region_resolves_source_point(self):
        levels = [
            {'id': 'L0', 'name': 'Ground', 'type': 'GROUND', 'region_bounds': [0, 0, 20, 20]},
            {'id': 'L1', 'name': 'First', 'type': 'FIRST', 'region_bounds': [0, 0, 10, 10]},
        ]
        level, error = _assign_level('MEP-1', (2, 2), levels, {})
        self.assertIsNone(error)
        self.assertEqual(level['type'], 'FIRST')

    def test_equal_overlapping_level_regions_remain_ambiguous(self):
        levels = [
            {'id': 'L0', 'name': 'Ground', 'type': 'GROUND', 'region_bounds': [0, 0, 10, 10]},
            {'id': 'L1', 'name': 'First', 'type': 'FIRST', 'region_bounds': [0, 0, 10, 10]},
        ]
        level, error = _assign_level('MEP-1', (2, 2), levels, {})
        self.assertIsNone(level)
        self.assertEqual(error, 'AMBIGUOUS_LEVEL_ASSIGNMENT:MEP-1')

    def test_explicit_level_label_is_reassigned_to_unique_spatial_owner(self):
        levels = [
            {'id': 'L0', 'name': 'Ground', 'type': 'GROUND', 'region_bounds': [0, 0, 10, 10]},
            {'id': 'L1', 'name': 'First', 'type': 'FIRST', 'region_bounds': [20, 0, 30, 10]},
        ]
        level, error = _resolve_level_for_point('MEP-1', 'First', (2, 2), levels, {})
        self.assertIsNone(error)
        self.assertEqual(level['type'], 'GROUND')

    def test_explicit_level_geometry_mismatch_without_spatial_owner_fails_closed(self):
        levels = [
            {'id': 'L0', 'name': 'Ground', 'type': 'GROUND', 'region_bounds': [0, 0, 10, 10]},
            {'id': 'L1', 'name': 'First', 'type': 'FIRST', 'region_bounds': [20, 0, 30, 10]},
        ]
        level, error = _resolve_level_for_point('MEP-1', 'First', (200, 200), levels, {})
        self.assertIsNone(level)
        self.assertEqual(error, 'EXPLICIT_LEVEL_GEOMETRY_MISMATCH:MEP-1:First')

    def test_unhosted_fixture_block_outside_all_plan_regions_is_excluded(self):
        model = pmm([{'name': 'Ground', 'region_bounds': [0, 0, 10, 10]}])
        architecture = {
            'shafts': [], 'walls': [], 'obstacles': [],
            'wet_cores': [{'room_id': 'W1', 'centroid': (8, 8), 'level': 'Ground'}],
        }
        valid = {**detection('VALID', point=(2, 2), ports=['cold_water']), 'level': 'Ground'}
        parked = {**detection('PARKED', point=(-200, 2), ports=['cold_water'], room=None),
                  'level': 'Ground'}
        result = build_authoritative_topology_from_evidence(
            model, architecture, {'detections': [valid, parked]},
        )
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(result['evidence']['installed_detections'], 1)
        self.assertEqual(result['evidence']['excluded_unhosted_out_of_plan_detections'], ['PARKED'])

    def test_detail_pseudo_level_is_rejected(self):
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'DETAIL-1'}]),
            {'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': []},
            {'detections': [detection()]},
        )
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertIn('LEVEL_TYPE_REQUIRED:DETAIL-1', result['missing_inputs'])

    def test_no_provisional_shaft_or_fake_termination(self):
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'Ground', 'region_bounds': [0, 0, 10, 10]}]),
            {'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': []},
            {'detections': [detection()]},
        )
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertTrue(any(value.startswith('SYSTEM_TERMINATION_REQUIRED:') for value in result['missing_inputs']))
        self.assertNotIn('SHAFT-PROVISIONAL', str(result))

    def test_explicit_owner_authorization_materializes_deterministic_multilevel_shafts(self):
        model = pmm([
            {'name': 'Ground', 'region_bounds': [0, 0, 10, 10]},
            {'name': 'First', 'region_bounds': [20, 0, 30, 10]},
        ], vertical=True)
        architecture = {
            'shafts': [], 'walls': [], 'obstacles': [],
            'wet_cores': [
                {'room_id': 'WG', 'centroid': (8, 8), 'level': 'Ground'},
                {'room_id': 'WF', 'centroid': (28, 8), 'level': 'First'},
            ],
        }
        recognition = {'detections': [
            {**detection('G', point=(2, 2), ports=['cold_water']), 'level': 'Ground'},
            {**detection('F', point=(22, 2), ports=['cold_water']), 'level': 'First'},
        ]}
        result = build_authoritative_topology_from_evidence(
            model, architecture, recognition, shaft_strategy='proposal_authorized',
        )
        self.assertEqual(result['status'], 'PASS', result)
        proposed = [node for node in result['network']['nodes']
                    if node.get('source') == 'USER_AUTHORIZED_PROPOSED_SHAFT']
        self.assertEqual(len(proposed), 2)
        self.assertEqual({node['shaft_key'] for node in proposed},
                         {'USER-AUTHORIZED-PROPOSED-CORE'})
        self.assertTrue(any(edge['role'] == 'vertical_riser'
                            for edge in result['network']['edges']))

    def test_installed_multilevel_system_builds_riser_even_when_pmm_flag_is_stale(self):
        model = pmm([
            {'name': 'Ground', 'region_bounds': [0, 0, 10, 10]},
            {'name': 'First', 'region_bounds': [20, 0, 30, 10]},
        ], vertical=False)
        architecture = {
            'shafts': [], 'walls': [], 'obstacles': [],
            'wet_cores': [
                {'room_id': 'WG', 'centroid': (8, 8), 'level': 'Ground'},
                {'room_id': 'WF', 'centroid': (28, 8), 'level': 'First'},
            ],
        }
        recognition = {'detections': [
            {**detection('G', point=(2, 2), ports=['cold_water']), 'level': 'Ground'},
            {**detection('F', point=(22, 2), ports=['cold_water']), 'level': 'First'},
        ]}
        result = build_authoritative_topology_from_evidence(
            model, architecture, recognition, shaft_strategy='proposal_authorized',
        )
        self.assertEqual(result['status'], 'PASS', result)
        vertical = [edge for edge in result['network']['edges']
                    if edge.get('role') == 'vertical_riser']
        self.assertEqual(len(vertical), 1)
        qa = evaluate_topology_routing(result['network'])
        self.assertNotIn('MISSING_VERTICAL_CONTINUITY:cold_water', qa['errors'])

    def test_unknown_shaft_strategy_cannot_create_geometry(self):
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'Ground', 'region_bounds': [0, 0, 10, 10]}]),
            {'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': []},
            {'detections': [detection()]}, shaft_strategy='pick_anywhere',
        )
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertNotIn('USER_AUTHORIZED_PROPOSED_SHAFT', str(result))

    def test_authorized_proposal_disambiguates_multiple_architectural_shafts(self):
        model = pmm([
            {'name': 'Ground', 'region_bounds': [0, 0, 10, 10]},
            {'name': 'First', 'region_bounds': [20, 0, 30, 10]},
            {'name': 'Second', 'region_bounds': [40, 0, 50, 10]},
        ], vertical=True)
        architecture = {
            'shafts': [
                {'centroid': (42, 8), 'level': 'Second', 'shaft_id': 'ARCH-A'},
                {'centroid': (48, 8), 'level': 'Second', 'shaft_id': 'ARCH-B'},
            ],
            'wet_cores': [
                {'room_id': 'WG', 'centroid': (8, 8), 'level': 'Ground'},
                {'room_id': 'WF', 'centroid': (28, 8), 'level': 'First'},
                {'room_id': 'WS', 'centroid': (48, 8), 'level': 'Second'},
            ],
            'walls': [], 'obstacles': [],
        }
        recognition = {'detections': [
            {**detection('G', point=(2, 2), ports=['cold_water']), 'level': 'Ground'},
            {**detection('F', point=(22, 2), ports=['cold_water']), 'level': 'First'},
            {**detection('S', point=(42, 2), ports=['cold_water']), 'level': 'Second'},
        ]}
        result = build_authoritative_topology_from_evidence(
            model, architecture, recognition, shaft_strategy='proposal_authorized',
        )
        self.assertEqual(result['status'], 'PASS', result)
        second_shafts = [node for node in result['network']['nodes']
                         if node.get('kind') == 'shaft' and node.get('level_name') == 'Second']
        self.assertEqual(len(second_shafts), 3)
        self.assertEqual(sum(node.get('source') == 'USER_AUTHORIZED_PROPOSED_SHAFT'
                             for node in second_shafts), 1)
        risers = [edge for edge in result['network']['edges']
                  if edge.get('role') == 'vertical_riser']
        self.assertEqual(len(risers), 2)
        self.assertEqual({edge.get('shaft_key') for edge in risers},
                         {'USER-AUTHORIZED-PROPOSED-CORE'})

    def test_unique_architectural_room_envelope_hosts_unassigned_endpoint(self):
        architecture = {
            'rooms': [{'id': 'ROOM-1', 'level': 'Ground',
                       'polygon': [(0, 0), (6, 0), (6, 6), (0, 6)]}],
            'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': [],
        }
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'Ground', 'region_bounds': [0, 0, 10, 10]}]),
            architecture, {'detections': [detection(point=(2, 2), room=None)]},
            shaft_strategy='proposal_authorized',
        )
        self.assertEqual(result['status'], 'PASS', result)
        endpoint = next(node for node in result['network']['nodes']
                        if node.get('category') == 'fixture')
        self.assertEqual(endpoint['host_id'], 'ROOM-1')
        self.assertEqual(endpoint['host_evidence'], 'UNIQUE_ARCHITECTURAL_ROOM_ENVELOPE')
        qa = evaluate_topology_routing(result['network'])
        self.assertFalse(any(value.startswith('ENDPOINT_HOST_REQUIRED:') for value in qa['errors']))
        self.assertNotIn('PROVISIONAL_SHAFT_FORBIDDEN', qa['errors'])

    def test_installed_architectural_entity_is_valid_host_at_room_boundary(self):
        installed = detection(point=(6, 2), room=None)
        installed['installed'] = True
        installed['evidence'] = ['ARCHITECTURE_FIXTURE_DETECTION']
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'Ground', 'region_bounds': [0, 0, 10, 10]}]),
            {'rooms': [], 'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': []},
            {'detections': [installed]}, shaft_strategy='proposal_authorized',
        )
        self.assertEqual(result['status'], 'PASS', result)
        endpoint = next(node for node in result['network']['nodes']
                        if node.get('category') == 'fixture')
        self.assertEqual(endpoint['host_id'], installed['id'])
        self.assertEqual(endpoint['host_evidence'], 'INSTALLED_ARCHITECTURAL_ENTITY')
        qa = evaluate_topology_routing(result['network'])
        self.assertFalse(any(value.startswith('ENDPOINT_HOST_REQUIRED:') for value in qa['errors']))

    def test_real_shaft_builds_deterministic_identity_graph(self):
        architecture = {
            'shafts': [{'centroid': (8.0, 8.0), 'polygon': [(7, 7), (9, 7), (9, 9), (7, 9)]}],
            'wet_cores': [], 'walls': [], 'obstacles': [],
        }
        model = pmm([{'name': 'Ground', 'region_bounds': [0, 0, 10, 10]}])
        recognition = {'detections': [detection(ports=['cold_water'])]}
        first = build_authoritative_topology_from_evidence(model, architecture, recognition)
        second = build_authoritative_topology_from_evidence(model, architecture, recognition)
        self.assertEqual(first['status'], 'PASS')
        self.assertEqual(first['network']['graph_id'], second['network']['graph_id'])
        self.assertEqual(first['network']['edges'], second['network']['edges'])
        self.assertEqual(first['network']['quality']['provisional_shaft_count'], 0)
        edge = first['network']['edges'][0]
        self.assertEqual(len({edge['plan_id'], edge['calc_id'], edge['riser_id'], edge['schedule_id']}), 1)
        self.assertTrue(edge['draw_on_plan'])


class SegmentExecutionAuthorityV19Tests(unittest.TestCase):
    def graph(self, paired=False, duplicate=False):
        edges = [{
            'id': 'E-CW', 'calc_id': 'CALC-CW', 'plan_id': 'CALC-CW', 'riser_id': 'CALC-CW', 'schedule_id': 'CALC-CW',
            'from': 'N1', 'to': 'N2', 'system': 'cold_water', 'levels': ['L1'], 'endpoint_ids': ['F1'],
            'plan_path': [(1, 1), (8, 1), (8, 8)], 'draw_on_plan': True,
        }]
        if paired:
            edges.append({
                'id': 'E-HW', 'calc_id': 'CALC-HW', 'plan_id': 'CALC-HW', 'riser_id': 'CALC-HW', 'schedule_id': 'CALC-HW',
                'from': 'N1', 'to': 'N2', 'system': 'hot_water', 'levels': ['L1'], 'endpoint_ids': ['F1'],
                'plan_path': [(1, 1), (8, 1), (8, 8)], 'draw_on_plan': True,
            })
        if duplicate:
            edges.append({
                'id': 'E-CW-2', 'calc_id': 'CALC-CW-2', 'plan_id': 'CALC-CW-2', 'riser_id': 'CALC-CW-2', 'schedule_id': 'CALC-CW-2',
                'from': 'N3', 'to': 'N4', 'system': 'cold_water', 'levels': ['L1'], 'endpoint_ids': ['F2'],
                'plan_path': [(1, 1), (8, 1), (8, 8)], 'draw_on_plan': True,
            })
        return {'schema': 'mechanical-network-graph/1', 'graph_id': 'G',
                'levels': [{'id': 'L1', 'name': 'Ground', 'type': 'GROUND', 'region_bounds': [0, 0, 10, 10]}],
                'nodes': [{'id': 'N1'}, {'id': 'N2'}, {'id': 'N3'}, {'id': 'N4'}], 'edges': edges}

    def explicit_rows(self, graph):
        return [{
            'network_edge_id': edge['id'], 'calc_id': edge['calc_id'], 'size_mm': 20,
            'material': 'PROJECT-SPEC-MATERIAL', 'material_source': 'PROJECT_SPEC',
            'requires_slope': False,
        } for edge in graph['edges']]

    def test_explicit_segment_rows_complete_without_numeric_defaults(self):
        graph = self.graph()
        result = design_authoritative_segments(graph, calculation_rows=self.explicit_rows(graph))
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['qa']['one_calc_row_per_edge'])
        self.assertFalse(result['qa']['hidden_numeric_defaults'])
        self.assertEqual(result['network']['edges'][0]['size_mm'], 20.0)
        self.assertEqual(result['network']['edges'][0]['material'], 'PROJECT-SPEC-MATERIAL')

    def test_missing_size_basis_is_input_required_not_defaulted(self):
        result = design_authoritative_segments(self.graph(), calculation_rows=[])
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertIn('SIZE_TABLE:cold_water', result['missing_inputs'])
        self.assertIn('ENDPOINT_LOADS:cold_water', result['missing_inputs'])

    def test_versioned_rulebook_profile_materializes_explicit_endpoint_load(self):
        from app.mechanical_rulebook import network_design_basis
        graph = self.graph()
        graph['nodes'].append({'id': 'F1', 'kind': 'basin', 'category': 'fixture'})
        result = design_authoritative_segments(graph, design_basis=network_design_basis())
        self.assertEqual(result['status'], 'PASS')
        row = result['calculation_rows'][0]
        self.assertEqual(row['downstream_load'], 1.0)
        self.assertEqual(row['load_unit'], 'WSFU')
        self.assertEqual(row['size_mm'], 16.0)
        self.assertEqual(row['material'], 'PPR')
        self.assertIn('MECHANICAL_RULEBOOK/mechanical-rulebook', row['material_source'])
        self.assertEqual(row['selected_capacity'], 1.0)
        self.assertEqual(row['capacity_utilization'], 1.0)
        self.assertEqual(row['reserve_capacity'], 0.0)
        self.assertEqual(row['sizing_method'], 'DETERMINISTIC_SMALLEST_COMPLIANT_CANDIDATE')
        self.assertEqual(row['sizing_iterations'], [
            {'size_mm': 16.0, 'capacity': 1.0, 'demand': 1.0, 'passes': True}])

    def test_rulebook_recomputes_load_and_rejects_nonminimum_supplied_size(self):
        from app.mechanical_rulebook import network_design_basis
        graph = self.graph()
        graph['nodes'].append({'id': 'F1', 'kind': 'basin', 'category': 'fixture'})
        rows = self.explicit_rows(graph)
        rows[0]['downstream_load'] = 99
        result = design_authoritative_segments(graph, design_basis=network_design_basis(), calculation_rows=rows)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('SEGMENT_CUMULATIVE_LOAD_MISMATCH:E-CW', result['errors'])
        self.assertIn('SEGMENT_SIZE_NOT_MINIMUM_COMPLIANT:E-CW:EXPECTED_DN16', result['errors'])

    def test_candidate_search_records_failed_candidates_before_selection(self):
        from app.mechanical_rulebook import network_design_basis
        graph = self.graph()
        graph['nodes'].append({'id': 'F1', 'kind': 'wc', 'category': 'fixture'})
        result = design_authoritative_segments(graph, design_basis=network_design_basis())
        self.assertEqual(result['status'], 'PASS')
        iterations = result['calculation_rows'][0]['sizing_iterations']
        self.assertEqual([x['passes'] for x in iterations], [False, True])
        self.assertEqual(result['calculation_rows'][0]['size_mm'], 20.0)

    def test_unknown_canonical_endpoint_kind_remains_fail_closed(self):
        from app.mechanical_rulebook import network_design_basis
        graph = self.graph()
        graph['nodes'].append({'id': 'F1', 'kind': 'unclassified_fixture', 'category': 'fixture'})
        result = design_authoritative_segments(graph, design_basis=network_design_basis())
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertIn('ENDPOINT_LOAD:cold_water:F1', result['missing_inputs'])

    def test_paired_system_exact_overlay_requires_explicit_separation(self):
        graph = self.graph(paired=True)
        result = design_authoritative_segments(graph, calculation_rows=self.explicit_rows(graph))
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertIn('PLAN_SEPARATION_OFFSET:cold_water:hot_water', result['missing_inputs'])
        result = design_authoritative_segments(
            graph,
            design_basis={'systems': {'hot_water': {'plan_offset_xy': [0.25, 0]}}},
            calculation_rows=self.explicit_rows(graph),
        )
        self.assertEqual(result['status'], 'PASS')

    def test_separation_offset_reverses_to_the_in_bounds_side(self):
        graph = self.graph()
        graph['levels'] = [{'id':'L1','type':'GROUND','region_bounds':[0,0,10,10]}]
        graph['edges'][0]['levels'] = ['L1']
        graph['edges'][0]['plan_path'] = [(9,2),(9,8)]
        result = design_authoritative_segments(
            graph,
            design_basis={'systems': {'cold_water': {'plan_offset_xy': [2,0]}}},
            calculation_rows=self.explicit_rows(graph),
        )
        self.assertEqual(result['status'], 'PASS', result)
        edge=result['network']['edges'][0]
        self.assertEqual(edge['plan_path'], [(7.0,2.0),(7.0,8.0)])
        self.assertEqual(edge['plan_offset_xy_requested'], [2,0])
        self.assertEqual(edge['plan_offset_xy_applied'], [-2.0,0.0])

    def test_separation_offset_fails_when_neither_side_fits(self):
        graph = self.graph()
        graph['levels'] = [{'id':'L1','type':'GROUND','region_bounds':[0,0,10,10]}]
        graph['edges'][0]['levels'] = ['L1']
        graph['edges'][0]['plan_path'] = [(1,2),(9,8)]
        result = design_authoritative_segments(
            graph,
            design_basis={'systems': {'cold_water': {'plan_offset_xy': [2,0]}}},
            calculation_rows=self.explicit_rows(graph),
        )
        self.assertEqual(result['status'], 'PASS', result)
        edge=result['network']['edges'][0]
        self.assertEqual(edge['plan_path'], [(2.0,2.0),(10.0,8.0)])
        self.assertEqual(edge['plan_offset_xy_requested'], [2,0])
        self.assertEqual(edge['plan_offset_xy_applied'], [1.0,0.0])

    def test_separation_offset_fails_only_when_path_spans_both_boundaries(self):
        graph = self.graph()
        graph['levels'] = [{'id':'L1','type':'GROUND','region_bounds':[0,0,10,10]}]
        graph['edges'][0]['levels'] = ['L1']
        graph['edges'][0]['plan_path'] = [(0,2),(10,8)]
        result = design_authoritative_segments(
            graph,
            design_basis={'systems': {'cold_water': {'plan_offset_xy': [2,0]}}},
            calculation_rows=self.explicit_rows(graph),
        )
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('PLAN_OFFSET_OUTSIDE_LEVEL_BOUNDS:E-CW', result['errors'])

    def test_same_system_duplicate_geometry_fails(self):
        graph = self.graph(duplicate=True)
        result = design_authoritative_segments(graph, calculation_rows=self.explicit_rows(graph))
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['errors'][0].startswith('DUPLICATE_EXECUTION_GEOMETRY:'))


class NetworkMaterializerV19Tests(unittest.TestCase):
    def test_exact_file_reopen_has_each_authority_segment_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / 'src.dxf'; dst = root / 'dst.dxf'
            source = ezdxf.new('R2010'); smsp = source.modelspace()
            smsp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
            source.saveas(src)
            out = ezdxf.new('R2010'); omsp = out.modelspace()
            out.layers.add('ENGITOOLS-M-COLD_WATER', color=5)
            omsp.add_line((21, 21), (29, 21), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            out.saveas(dst)
            network = {
                'levels': [{'id': 'L1', 'name': 'Ground', 'type': 'GROUND', 'region_bounds': [0, 0, 10, 10]}],
                'nodes': [{'id': 'N1'}, {'id': 'N2'}],
                'edges': [{
                    'id': 'E1', 'calc_id': 'CALC-1', 'plan_id': 'CALC-1', 'riser_id': 'CALC-1', 'schedule_id': 'CALC-1',
                    'from': 'N1', 'to': 'N2', 'system': 'cold_water', 'levels': ['L1'],
                    'plan_path': [(1, 1), (8, 1), (8, 8)], 'draw_on_plan': True,
                    'size': 20.0, 'size_mm': 20.0, 'material': 'PROJECT-SPEC-MATERIAL',
                }],
            }
            report = {'composition': {
                'manifest': [{'family': 'WATER', 'level': 'GROUND', 'purpose': 'PLAN', 'old_sheet': 'B1', 'code': 'M-101'}],
                'boards': {'B1': {'plan_area': [20, 20, 30, 30]}},
            }}
            result = materialize_authoritative_network(src, dst, report, network)
            self.assertEqual(result['status'], 'PASS')
            self.assertTrue(result['exact_file_reopened'])
            self.assertEqual(result['expected_segments'], 1)
            self.assertEqual(result['reopen_counts'], {'E1': 1})
            self.assertGreaterEqual(result['removed_legacy_entities'], 1)


if __name__ == '__main__':
    unittest.main()
