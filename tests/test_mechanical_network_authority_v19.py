import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.mechanical_network_topology import build_authoritative_topology_from_evidence
from cad_engine.mechanical_segment_execution import design_authoritative_segments
from cad_engine.mechanical_network_materializer import materialize_authoritative_network


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
    def test_multilevel_without_bounds_or_assignment_fails_closed(self):
        result = build_authoritative_topology_from_evidence(
            pmm([{'name': 'Ground'}, {'name': 'First'}]),
            {'shafts': [], 'wet_cores': [], 'walls': [], 'obstacles': []},
            {'detections': [detection()]},
        )
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.assertTrue(any(value.startswith('LEVEL_ASSIGNMENT_REQUIRED:') for value in result['missing_inputs']))

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
