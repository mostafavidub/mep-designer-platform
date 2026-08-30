import unittest

from cad_engine.engineering_runner_v13 import _merge_browser_fixture_evidence


class FixtureEvidenceResilienceTests(unittest.TestCase):
    def _architecture(self):
        return {
            'plans': [
                {'plan_id':'P1','bounds':[0,0,10000,8000]},
            ],
            'primary_floor_plan_ids':['P1'],
            'rooms': [
                # Deliberately tiny bad polygons emulate annotation boxes chosen
                # instead of true room boundaries in consultant DXFs.
                {'id':'R-WC','type':'toilet','plan_id':'P1','label_point':(2200,2000),
                 'polygon':[(2150,1950),(2250,1950),(2250,2050),(2150,2050)]},
                {'id':'R-K','type':'kitchen','plan_id':'P1','label_point':(6200,2200),
                 'polygon':[(6150,2150),(6250,2150),(6250,2250),(6150,2250)]},
            ],
        }

    def test_strong_nearby_fixture_is_recovered_when_bad_polygon_misses_it(self):
        arch=self._architecture(); rec={'detections':[],'quality':{}}
        evidence=[{'kind':'toilet','name':'FARANGI','x':2600,'y':2100,'source_file':'arch.dxf'}]
        result=_merge_browser_fixture_evidence(arch,rec,evidence)
        self.assertEqual(len(result['detections']),1)
        row=result['detections'][0]
        self.assertEqual(row['room_id'],'R-WC')
        self.assertTrue(row['installed'])
        self.assertIn('bounded_same_plan_semantic_room_fallback',row['evidence'])

    def test_sink_only_associates_to_compatible_kitchen(self):
        arch=self._architecture(); rec={'detections':[],'quality':{}}
        evidence=[{'kind':'sink','name':'SINK-2','x':6500,'y':2300,'source_file':'arch.dxf'}]
        result=_merge_browser_fixture_evidence(arch,rec,evidence)
        self.assertEqual(result['detections'][0]['room_id'],'R-K')

    def test_distant_legend_symbol_stays_unassigned(self):
        arch=self._architecture(); rec={'detections':[],'quality':{}}
        evidence=[{'kind':'toilet','name':'WC-LEGEND','x':9800,'y':7800,'source_file':'arch.dxf'}]
        result=_merge_browser_fixture_evidence(arch,rec,evidence)
        self.assertEqual(result['detections'],[])
        self.assertEqual(result['quality']['browser_evidence_fallback_accepted'],0)


if __name__ == '__main__':
    unittest.main()
