import unittest
from types import SimpleNamespace

from app.electrical_runtime_patch import install as install_runtime
from app.electrical_design_integration import missing_from_error
from app.electrical_review_fix import analyzer_needs_refresh, review_question_html
from app.electrical_basis_contract import normalize_answers
from app import electrical_drawing_set
from cad_engine.electrical_v1.production_v19 import build_engine_config
from cad_engine.electrical_v1.release_contract_v19 import release_contract_status


class FakeAuto:
    pass


class ElectricalRuntimeV19Tests(unittest.TestCase):
    def test_architecture_proxies_are_not_promoted_to_answers(self):
        fake = FakeAuto()
        def original(analysis, discipline, supplied_answers=None):
            analysis['architectural_auto'] = {
                'estimated_electrical_load_kw': 18.2,
                'estimated_cable_route_m': 42.0,
                'levels':[{'name':'همکف'}],
                'room_counts':{'living':1},
            }
            return analysis['architectural_auto'], {
                'discipline':'electrical', 'design_load_kw':'18.2', 'cable_length_m':'42',
                'power_factor':'0.90', 'max_voltage_drop_pct':'3.0',
            }, []
        fake.build_unified_questionnaire = original
        install_runtime(fake)
        analysis = {}
        _auto, answers, questions = fake.build_unified_questionnaire(analysis, 'electrical', {})
        for key in ('design_load_kw','cable_length_m','power_factor','max_voltage_drop_pct'):
            self.assertNotIn(key, answers)
        self.assertEqual(analysis['electrical_preliminary_evidence']['estimated_connected_load_kw']['status'], 'PRELIMINARY')
        self.assertTrue(questions)

    def test_late_cad_missing_inputs_map_to_exact_questions(self):
        error = 'INPUT_REQUIRED[supply_voltage_v,earthing_system,lighting_basis]: برای ادامه اطلاعات تکمیل شود'
        missing = missing_from_error(error)
        self.assertIn('supply_configuration', missing)
        self.assertIn('earthing_system', missing)
        self.assertIn('lighting_design_basis', missing)

    def test_analyzer_refresh_is_one_time_version_guard(self):
        self.assertFalse(analyzer_needs_refresh({'architecture_analyzer_version':'3.5-project-evidence-gate'}, True))
        self.assertTrue(analyzer_needs_refresh({'architecture_analyzer_version':'legacy'}, True))
        self.assertFalse(analyzer_needs_refresh({'architecture_analyzer_version':'legacy'}, False))

    def test_review_html_exposes_exact_manifest(self):
        p = SimpleNamespace(
            answers=normalize_answers({
                'discipline':'electrical','location':'تهران','supply':'همه واحدها تک‌فاز',
                'earthing':'ارت فونداسیون','main_panel':'اجازه پیشنهاد محل مناسب را دارید',
                'dedicated_load_schedule':'ندارد','fire_alarm_requirement':'خارج از محدوده این پروژه',
                'low_current_systems':'خارج از محدوده','lighting_design_basis':'Rule Book و استاندارد مصوب پروژه',
                'codes':'ضابطه پروژه','heights':'مطابق پلان',
            }),
            analysis={'architectural_auto':{'levels':[{'name':'همکف'}],'room_counts':{'living':1}}}
        )
        proposal = electrical_drawing_set.proposal(p)
        html = review_question_html(proposal)
        self.assertIn('E-000', html)
        self.assertIn(str(proposal['sheet_count']), html)

    def test_production_config_does_not_invent_voltage_or_sizing_tables(self):
        cfg = build_engine_config({'discipline':'electrical','supply':'همه واحدها تک‌فاز'}, {})
        self.assertNotIn('supply_voltage_v', cfg['design_basis'])
        self.assertEqual(cfg['sizing_tables'], {})
        self.assertEqual(cfg['panel_rules'], {})

    def test_release_contract_imports_all_v19_capabilities(self):
        status = release_contract_status()
        self.assertEqual(status['status'], 'PASS', status)
        self.assertEqual(status['passed_count'], status['required_count'])


if __name__ == '__main__':
    unittest.main()
