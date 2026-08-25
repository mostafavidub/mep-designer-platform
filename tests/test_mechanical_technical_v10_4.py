import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import ezdxf
from fastapi.testclient import TestClient

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from cad_engine import main_v10_4 as technical


class MechanicalTechnicalV104Tests(unittest.TestCase):
    def architecture(self, path):
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 6
        msp = doc.modelspace()
        for name, ox in [('همکف', 0), ('طبقه اول', 40), ('طبقه دوم', 80)]:
            msp.add_text(f'{name} پلان معماری').set_placement((ox, 0))
            for text, point in [
                ('آشپزخانه', (3, 6)), ('حمام', (7, 7)), ('سرویس', (7, 10)),
                ('اتاق خواب', (12, 6)), ('پذیرایی', (11, 12)), ('شفت', (6, 13)),
            ]:
                msp.add_text(text).set_placement((ox + point[0], point[1]))
        msp.add_text('پشت بام پلان معماری').set_placement((120, 0))
        msp.add_text('بام').set_placement((125, 8))
        msp.add_text('P.V.C 110 RD').set_placement((124, 11))
        doc.saveas(path)

    def manifest(self):
        scope = {
            'all_levels': ['همکف', 'طبقه اول', 'طبقه دوم', 'پشت بام'],
            'conditioned_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
            'heated_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
            'wet_fixture_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
            'sanitary_fixture_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
            'ventilation_required_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
            'gas_consumer_levels': ['همکف', 'طبقه اول', 'طبقه دوم'],
            'roof_exists': True, 'roof_level_name': 'پشت بام',
            'vertical_systems': True, 'typical_groups': [],
        }
        return approve_drawing_set(predict_drawing_set(scope))['approved_manifest']

    def systems(self):
        return [
            'cold_water', 'hot_water', 'sanitary', 'vent', 'gas',
            'heating_supply', 'heating_return', 'cooling', 'condensate',
            'exhaust_ventilation', 'mechanical_risers',
        ]

    def calc(self):
        return {
            '_approved_drawing_manifest': self.manifest(),
            '_design_inputs': {
                'gas': 'yes', 'cooling': 'split', 'heating': 'radiator',
                'location': 'Tehran, Iran', 'heights': '3.20 m floor-to-floor',
                'fixture_schedule': 'sink 3; faucet 3; toilet 3; bath 3',
                'water_source': 'municipal meter, 500 L tank and booster pump',
                'water_inlet_pressure': '3.0 bar at meter',
                'water_design_basis': '3.0 bar at meter; PPR; Hazen-Williams C=150; maximum loss 20 kPa/100 m',
                'sanitary_outlet': 'municipal sewer at project boundary',
                'sanitary_design_basis': 'uPVC; invert +0.00 at boundary; 2 percent branches and 1 percent mains',
                'gas_appliances': 'boiler 24 kW and cooker 10 kW; 21 mbar; meter/regulator at entrance',
                'equipment_schedule': 'per room load; split units 9000/18000 BTU/h; outdoor units on roof',
                'ventilation_design_basis': 'toilets 90 m3/h; parking 500 m3/h; discharge above roof; make-up air from facade',
                'roof_drainage_basis': '120 m2 roof; 2 drains at coordinated low points; 110 mm/h rainfall',
            },
            'design_water_flow_lps': .7, 'target_water_velocity_mps': 1.5,
            'cooling_load_kw': 15.0, 'heating_load_kw': 12.0,
        }

    def test_complete_inputs_generate_evidence_gated_10_of_10(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            meta = technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, self.calc())
            report = meta['technical_quality']
            self.assertEqual(report['score_10'], 10.0)
            self.assertTrue(all(report['checks'].values()))
            self.assertGreater(meta['technical_symbol_blocks'], 0)
            self.assertGreater(meta['technical_schedule_annotations'], 0)
            out = ezdxf.readfile(dst)
            inserts = [
                entity for entity in out.modelspace().query('INSERT')
                if str(entity.dxf.name).startswith('ET_M_')
            ]
            self.assertGreater(len(inserts), 0)

    def test_missing_numeric_airflow_blocks_technical_issue(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            calc = self.calc()
            calc['_design_inputs']['ventilation_design_basis'] = '10 ACH; discharge above roof; make-up air'
            with self.assertRaisesRegex(RuntimeError, r'9(?:\.0)?/10.*ventilation_design'):
                technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, calc)

    def test_room_name_proxies_cannot_claim_fixture_traceability(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            calc = self.calc()
            calc['_design_inputs'].pop('fixture_schedule')
            with self.assertRaisesRegex(RuntimeError, r'9(?:\.0)?/10.*fixture_and_symbol_traceability'):
                technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, calc)

    def test_real_http_design_preserves_manifest_inputs_and_plan_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'block-source.dxf'
            self.architecture(source)
            # Put every plan in an unreferenced named block to reproduce the
            # production failure mode that previously collapsed level geometry.
            original = ezdxf.readfile(source)
            blocked = ezdxf.new('R2013')
            blocked.header['$INSUNITS'] = 6
            block = blocked.blocks.new('HTTP_ARCH_LEVELS')
            for entity in original.modelspace():
                try:
                    block.add_entity(entity.copy())
                except Exception:
                    pass
            blocked.saveas(source)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(source, arcname='architecture.dxf')
            manifest = self.manifest()
            payload = {
                'project_id': 'http-v104', 'discipline': 'mechanical',
                'architecture_archive_b64': base64.b64encode(archive.getvalue()).decode('ascii'),
                'answers': {
                    **self.calc()['_design_inputs'],
                    'design_water_flow_lps': '.7',
                    'target_water_velocity_mps': '1.5',
                    'cooling_load_kw': '15',
                    'heating_load_kw': '12',
                },
                'plan_analysis': {
                    'drawing_set': {'approved': True, 'approved_manifest': manifest},
                    'architectural_auto': {'level_profiles': [
                        {'name': name, 'source_type': 'block', 'source_name': 'HTTP_ARCH_LEVELS'}
                        for name in ('همکف', 'طبقه اول', 'طبقه دوم', 'پشت بام')
                    ]},
                },
                'revision': 1,
                'output_scope': {
                    'discipline': 'mechanical', 'systems': self.systems(),
                    'only_this_discipline': True, 'include_other_disciplines': False,
                },
            }
            response = TestClient(technical.app).post('/design', json=payload)
            self.assertEqual(response.status_code, 200, response.text[:1000])
            body = response.json()
            self.assertEqual(body['engine_version'], '1.0.7')
            report = body['design_reports'][0]
            self.assertEqual(report['technical_quality']['score_10'], 10.0)
            self.assertEqual(report['authority_submission']['expected_sheet_count'], 21)
            self.assertEqual(report['authority_submission']['generated_sheet_count'], 21)
            self.assertEqual(report['authority_submission']['materialized_analyzer_blocks'], ['HTTP_ARCH_LEVELS'])

    def test_short_rulebook_confirmations_generate_10_of_10(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            calc = self.calc()
            inputs = calc['_design_inputs']
            inputs['gas'] = 'تأیید'
            inputs.pop('gas_appliances')
            inputs['fixture_schedule'] = 'پیشنهاد بده'
            inputs['sanitary_outlet'] = 'تأیید'
            inputs.pop('roof_drainage_basis')
            inputs['roof_drainage_geometry'] = 'تأیید'
            meta = technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, calc)
            self.assertEqual(meta['technical_quality']['score_10'], 10.0)
            self.assertEqual(meta['technical_design']['gas_load_kw'], 34.0)
            self.assertGreater(meta['technical_design']['fixture_schedule_count'], 0)
            self.assertGreater(meta['technical_design']['roof_area_m2'], 0)

    def test_resumed_project_uses_architectural_analysis_fallbacks(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            calc = self.calc()
            calc.pop('design_water_flow_lps')
            calc.pop('cooling_load_kw')
            calc.pop('heating_load_kw')
            calc['_design_inputs']['fixture_schedule'] = 'تأیید'
            calc['_plan_analysis'] = {
                'architectural_auto': {
                    'room_counts': {},
                    'fixture_counts': {'sink': 3, 'faucet': 3, 'toilet': 3, 'bath': 3},
                    'estimated_water_flow_lps': .8,
                    'estimated_cooling_load_kw': 15.0,
                    'estimated_heating_load_kw': 12.0,
                    'estimated_route_length_m': 25.0,
                },
            }
            meta = technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, calc)
            self.assertEqual(meta['technical_quality']['score_10'], 10.0)
            model = meta['technical_design']
            self.assertEqual(model['fixture_schedule_count'], 12)
            self.assertEqual(model['design_water_flow_lps'], .8)
            self.assertEqual(model['cooling_load_kw'], 15.0)
            self.assertEqual(model['heating_load_kw'], 12.0)

    def test_unknown_water_pressure_uses_conservative_rulebook_basis(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            calc = self.calc()
            calc['_design_inputs']['water_inlet_pressure'] = 'نمی‌دانم'
            meta = technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, calc)
            self.assertEqual(meta['technical_quality']['score_10'], 10.0)
            self.assertEqual(meta['technical_design']['water_inlet_pressure_bar'], 2.5)

    def test_resumed_short_answers_hydrate_rulebook_calculations(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.dxf'; dst = Path(td) / 'm.dxf'
            self.architecture(src)
            calc = self.calc()
            inputs = calc['_design_inputs']
            inputs.pop('water_design_basis')
            inputs.pop('sanitary_design_basis')
            inputs['ventilation_design_basis'] = 'تأیید'
            inputs['water_inlet_pressure'] = '۲٫۵ بار'
            meta = technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, calc)
            self.assertEqual(meta['technical_quality']['score_10'], 10.0)
            self.assertEqual(meta['technical_design']['water_inlet_pressure_bar'], 2.5)
            self.assertEqual(meta['technical_design']['sanitary_material'], 'uPVC')
            self.assertGreater(meta['technical_design']['ventilation_airflow_m3h'], 0)

    def test_hydraulic_refresh_preserves_architecture_route_without_drawn_network(self):
        model = {
            'water_route_length_m': 24.0,
            'design_water_flow_lps': .7,
            'water_main_dn_mm': 25,
            'hazen_williams_c': 150,
        }
        doc = ezdxf.new('R2013')
        technical._refresh_hydraulic_model(doc, model)
        self.assertEqual(model['water_route_length_m'], 24.0)
        self.assertGreater(model['water_head_loss_m'], 0)

    def test_compact_output_removes_remote_architecture_and_unused_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'large-architecture.dxf'; dst = Path(td) / 'mechanical.dxf'
            self.architecture(src)
            source = ezdxf.readfile(src)
            msp = source.modelspace()
            if 'ARCH-JUNK' not in source.layers:
                source.layers.add('ARCH-JUNK')
            for index in range(500):
                x = 5000 + index * 2
                msp.add_line((x, 5000), (x + 1, 5001), dxfattribs={'layer': 'ARCH-JUNK'})
            unused = source.blocks.new('UNUSED_ARCHITECTURE_LIBRARY')
            for index in range(10000):
                unused.add_line((index, 0), (index, 100))
            source.saveas(src)
            source_bytes = src.stat().st_size

            meta = technical.design_dxf_v10_4(src, dst, 'mechanical', self.systems(), 1, self.calc())
            cleanup = meta['compact_output']
            self.assertEqual(cleanup['status'], 'PASS')
            self.assertEqual(cleanup['architecture_source_files_packaged'], 0)
            self.assertGreaterEqual(cleanup['removed_unneeded_entities'], 500)
            self.assertLess(dst.stat().st_size, source_bytes)
            out = ezdxf.readfile(dst)
            self.assertFalse(any(entity.dxf.layer == 'ARCH-JUNK' for entity in out.modelspace()))
            self.assertNotIn('UNUSED_ARCHITECTURE_LIBRARY', out.blocks)
            self.assertEqual(len(out.dimstyles), 1)
            self.assertFalse(any(len(layout.query('DIMENSION')) for layout in out.layouts))
            self.assertLess(cleanup['retained_block_definitions'], 50)


if __name__ == '__main__':
    unittest.main()
