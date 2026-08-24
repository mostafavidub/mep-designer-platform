import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine import main_v10_3 as authority
from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set


class MechanicalAuthorityV103Tests(unittest.TestCase):
    def _build_reference_architecture(self, path):
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 4
        msp = doc.modelspace()
        dim = msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(3, 0), angle=0)
        dim.render()
        for name, ox in [('همکف', 0), ('طبقه اول', 40), ('طبقه دوم', 80)]:
            msp.add_text(f'{name} پلان معماری').set_placement((ox, 0))
            msp.add_text('آشپزخانه').set_placement((ox + 3, 6))
            msp.add_text('حمام').set_placement((ox + 7, 7))
            msp.add_text('سرویس').set_placement((ox + 7, 10))
            msp.add_text('اتاق خواب').set_placement((ox + 12, 6))
            msp.add_text('پذیرایی').set_placement((ox + 11, 12))
            msp.add_text('شفت').set_placement((ox + 6, 13))
        msp.add_text('پشت بام پلان معماری').set_placement((120, 0))
        msp.add_text('بام').set_placement((125, 8))
        msp.add_text('P.V.C 110 RD').set_placement((124, 11))
        doc.saveas(path)

    def test_reference_profile_issues_21_separate_authority_sheets(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            self._build_reference_architecture(src)
            systems = [
                'cold_water', 'hot_water', 'sanitary', 'vent', 'gas',
                'heating_supply', 'heating_return', 'cooling', 'condensate',
                'exhaust_ventilation', 'mechanical_risers',
            ]
            scope = {
                'all_levels': ['همکف', 'طبقه اول', 'طبقه دوم', 'پشت بام'],
                'conditioned_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
                'heated_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
                'wet_fixture_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
                'sanitary_fixture_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
                'ventilation_required_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
                'gas_consumer_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
                'roof_exists': True,
                'roof_level_name': 'پشت بام',
                'vertical_systems': True,
                'typical_groups': [],
            }
            manifest = approve_drawing_set(predict_drawing_set(scope))['approved_manifest']
            calc = {
                '_approved_drawing_manifest': manifest,
                '_design_inputs': {
            "gas": "yes",
            "cooling": "split",
            "heating": "radiator",
            "location": "Tehran, Iran",
            "heights": "3.20 m floor-to-floor; 0.40 m false ceiling in wet/service zones",
            "water_source": "municipal meter, 500 L tank and booster pump",
            "water_inlet_pressure": "3.0 bar at meter",
            "water_design_basis": "3.0 bar at meter; PPR; Hazen-Williams C=150; maximum design loss 20 kPa/100 m",
            "sanitary_outlet": "municipal sewer at project boundary",
            "sanitary_design_basis": "uPVC; invert +0.00 at boundary; 2 percent branches and 1 percent mains",
            "gas_appliances": "boiler 24 kW and cooker 10 kW; 21 mbar; meter/regulator at entrance",
            "equipment_schedule": "radiators per room load; split units 9k/18k BTU; outdoor units on roof",
            "ventilation_design_basis": "toilets 10 ACH; enclosed parking 6 ACH; discharge above roof with make-up air",
            "roof_drainage_basis": "120 m2 roof; two coordinated drains; 110 mm/h design rainfall"
        },
                'design_water_flow_lps': 0.7,
                'preliminary_nominal_pipe_candidate_mm': 25,
                'cooling_load_kw': 15.0,
                'heating_load_kw': 12.0,
            }
            meta = authority.design_dxf_v10_3(src, dst, 'mechanical', systems, 1, calc)
            out = ezdxf.readfile(dst)
            names = [x.name for x in out.layouts if x.name.startswith('M-')]
            self.assertEqual(len(names), meta['authority_submission']['layout_count'])
            self.assertEqual(len(names), 21)
            self.assertEqual(meta['authority_submission']['counts'], {
                'W': 4, 'S': 3, 'H': 3, 'C': 4, 'G': 3, 'V': 3, 'R': 1,
            })
            self.assertEqual(len(out.audit().errors), 0)
            self.assertEqual(meta['authority_submission']['validation_status'], 'PASS')
            self.assertEqual(meta['authority_submission']['expected_sheet_count'], 21)
            self.assertEqual(meta['authority_submission']['generated_sheet_count'], 21)
            self.assertNotIn('M-RISER-CALC', names)
            self.assertFalse(any(x.startswith('M-P-') for x in names))
            for prefix in ('M-W-', 'M-S-', 'M-H-', 'M-C-', 'M-G-', 'M-V-', 'M-R-'):
                self.assertTrue(any(x.startswith(prefix) for x in names), prefix)

    def test_unresolved_engineering_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            self._build_reference_architecture(src)
            scope = {
                'all_levels': ['همکف'], 'conditioned_levels': ['همکف'],
                'heated_levels': ['همکف'], 'wet_fixture_levels': ['همکف'],
                'sanitary_fixture_levels': ['همکف'],
                'ventilation_required_levels': ['همکف'],
                'gas_consumer_levels': ['همکف'], 'roof_exists': False,
                'vertical_systems': False, 'typical_groups': [],
            }
            manifest = approve_drawing_set(predict_drawing_set(scope))['approved_manifest']
            with self.assertRaisesRegex(RuntimeError, 'unresolved engineering inputs'):
                authority.design_dxf_v10_3(
                    src, dst, 'mechanical', ['cold_water'], 1,
                    {'_approved_drawing_manifest': manifest, '_design_inputs': {}},
                )

    def test_generation_without_approved_manifest_fails(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            self._build_reference_architecture(src)
            with self.assertRaisesRegex(RuntimeError, 'manifest'):
                authority.design_dxf_v10_3(
                    src, dst, 'mechanical', ['cold_water'], 1,
                    {'_design_inputs': {}},
                )

    def test_analyzer_named_block_is_materialized_for_cad_level_detection(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture-block.dxf'
            expanded = Path(td) / 'architecture-expanded.dxf'
            doc = ezdxf.new('R2013')
            block = doc.blocks.new('APPROVED_ARCH_LEVELS')
            block.add_text('طبقه همکف پلان معماری').set_placement((0, 0))
            block.add_text('آشپزخانه').set_placement((3, 5))
            block.add_text('حمام').set_placement((7, 7))
            doc.saveas(src)
            calc = {
                '_plan_analysis': {
                    'architectural_auto': {
                        'level_profiles': [{
                            'name': 'طبقه همکف', 'source_type': 'block',
                            'source_name': 'APPROVED_ARCH_LEVELS',
                        }]
                    }
                }
            }
            source, names = authority._materialize_analyzer_blocks(src, expanded, calc)
            out = ezdxf.readfile(source)
            texts = [x.dxf.text for x in out.modelspace().query('TEXT')]
            self.assertEqual(names, ['APPROVED_ARCH_LEVELS'])
            self.assertIn('طبقه همکف پلان معماری', texts)
            self.assertIn('آشپزخانه', texts)

    def test_missing_analyzer_block_definition_is_ignored_without_http_500(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'orphan-source.dxf'
            expanded = Path(td) / 'orphan-expanded.dxf'
            doc = ezdxf.new('R2013')
            doc.modelspace().add_text('پلان معماری طبقه همکف').set_placement((0, 0))
            doc.saveas(src)
            calc = {
                '_plan_analysis': {
                    'architectural_auto': {
                        'level_profiles': [{
                            'name': 'طبقه همکف', 'source_type': 'block',
                            'source_name': 'PURGED_ORPHAN_BLOCK',
                        }]
                    }
                }
            }
            source, names = authority._materialize_analyzer_blocks(src, expanded, calc)
            self.assertEqual(source, src)
            self.assertEqual(names, [])

    def test_missing_manifest_level_never_reuses_another_floor_geometry(self):
        levels = [{'level': 'طبقه همکف', 'rooms': [], 'fixtures': []}]
        sheet = {'code': 'M-W-02', 'levels': ['طبقه اول']}
        with self.assertRaisesRegex(RuntimeError, 'exact level geometry'):
            authority._manifest_level(sheet, levels)

    def test_architectural_stove_does_not_fail_explicit_no_gas_scope(self):
        """Furniture symbols must not force a gas deliverable into a no-gas project."""
        doc = ezdxf.new('R2013')
        msp = doc.modelspace()
        level = {
            'level': 'طبقه همکف',
            'title': {'point': (0, 0)},
            'rooms': [],
            'fixtures': [{'kind': 'gas', 'point': (2, 2), 'block': 'STOVE'}],
        }
        stats = authority.v7.defaultdict(int)
        qa = {'assumptions': [], 'unresolved': [], 'checks': {}}
        authority.v7.design_level_v7(
            msp, level, {'cold_water', 'sanitary'},
            {'_design_inputs': {'gas': 'بدون گاز'}}, stats, qa,
        )
        self.assertEqual(qa['fixtures_expected'], 0)
        self.assertEqual(qa['fixtures_connected'], 0)
        self.assertFalse(qa['unresolved'])
        self.assertTrue(any('no gas service' in value for value in qa['assumptions']))


if __name__ == '__main__':
    unittest.main()
