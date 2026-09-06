import inspect
import unittest
from types import SimpleNamespace

from app.electrical_runtime_patch import install as install_runtime
from app.electrical_design_integration import (
    CONSTRUCTION_DETAIL_QUESTION_SPECS,
    missing_from_error,
    _ensure_approved_manifest,
)
from app.electrical_review_fix import analyzer_needs_refresh, review_question_html
from app.electrical_basis_contract import normalize_answers
from app.electrical_site_release_contract import release_contract_status as site_release_status
from app import electrical_drawing_set, electrical_workflow
from cad_engine.electrical_v1.production import build_engine_config
from cad_engine.electrical_v1.release_contract import release_contract_status as cad_release_status
import cad_engine.electrical_v1.production as production
import cad_engine.electrical_v1.release_contract as cad_contract
import cad_engine.electrical_v1.runtime_support as runtime_support
import cad_engine.electrical_api as electrical_api


class FakeAuto:
    pass


class ElectricalRuntimeTests(unittest.TestCase):
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

    def test_late_detail_inputs_map_to_exact_site_questions(self):
        error = (
            'INPUT_REQUIRED[D-EL-PANEL-MOUNT.mounting_height,'
            'D-EL-PANEL-MOUNT.clearance,D-EL-EARTHING.conductor]:'
        )
        missing = missing_from_error(error)
        self.assertEqual(
            missing,
            ['detail_panel_mounting_height_mm', 'detail_panel_clearance_mm', 'detail_earthing_conductor'],
        )
        for key in missing:
            self.assertIn(key, CONSTRUCTION_DETAIL_QUESTION_SPECS)
            self.assertEqual(electrical_workflow.question_payload(key)['key'], key)

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

    def test_public_design_never_silently_approves_manifest(self):
        p = SimpleNamespace(
            answers=normalize_answers({
                'discipline':'electrical','location':'تهران','supply':'همه واحدها تک‌فاز',
                'earthing':'ارت فونداسیون','main_panel':'اجازه پیشنهاد محل مناسب را دارید',
                'dedicated_load_schedule':'ندارد','fire_alarm_requirement':'خارج از محدوده این پروژه',
                'low_current_systems':'خارج از محدوده','lighting_design_basis':'Rule Book و استاندارد مصوب پروژه',
                'codes':'ضابطه پروژه','heights':'مطابق پلان',
            }),
            analysis={'architectural_auto':{'levels':[{'name':'همکف'}],'room_counts':{'living':1}}},
            status='ready_to_design', last_error=''
        )
        self.assertFalse(_ensure_approved_manifest(p))
        self.assertEqual(p.status, 'drawing_set_review')
        self.assertEqual(p.analysis['drawing_set']['status'], 'PROPOSED')
        self.assertFalse(electrical_drawing_set.approved_manifest_is_valid(p.analysis['drawing_set']))

    def test_production_config_does_not_invent_voltage_or_sizing_tables(self):
        cfg = build_engine_config({'discipline':'electrical','supply':'همه واحدها تک‌فاز'}, {})
        self.assertNotIn('supply_voltage_v', cfg['design_basis'])
        self.assertEqual(cfg['sizing_tables'], {})
        self.assertEqual(cfg['panel_rules'], {})
        self.assertEqual(cfg['detail_parameters'], {})

    def test_production_config_maps_only_explicit_construction_inputs(self):
        cfg = build_engine_config({
            'discipline':'electrical',
            'detail_panel_mounting_height_mm':'1500',
            'detail_panel_clearance_mm':'1000',
            'detail_wall_type':'masonry',
            'detail_earthing_conductor':'1x6 Cu',
        }, {})
        panel = cfg['detail_parameters']['D-EL-PANEL-MOUNT']
        self.assertEqual(panel['mounting_height'], '1500')
        self.assertEqual(panel['clearance'], '1000')
        self.assertEqual(panel['wall_type'], 'masonry')
        self.assertNotIn('D-EL-METER', cfg['detail_parameters'])
        self.assertEqual(cfg['detail_parameters']['D-EL-EARTHING']['conductor'], '1x6 Cu')

    def test_api_missing_input_contract_preserves_detail_and_parameter(self):
        report = {
            'data': {'basis': {'values': {}}},
            'gates': {
                'CONSTRUCTION_DETAIL_AUTHORITY': {
                    'warnings': [
                        'detail_parameters_input_required:D-EL-PANEL-MOUNT:mounting_height,clearance',
                        'detail_parameters_input_required:D-EL-EARTHING:conductor',
                    ]
                },
                'DETAIL_COVERAGE': {'warnings': ['detail_not_final:D-EL-PANEL-MOUNT']},
            },
        }
        missing = electrical_api._missing_inputs(report)
        self.assertEqual(
            missing,
            [
                'D-EL-PANEL-MOUNT.mounting_height',
                'D-EL-PANEL-MOUNT.clearance',
                'D-EL-EARTHING.conductor',
            ],
        )

    def test_api_does_not_overstate_pre_submission_report(self):
        state = electrical_api._aggregate_release_state([
            {
                'submission_state':'PRE_SUBMISSION',
                'acceptance':{'real_project_acceptance':False, 'production_release_allowed':False},
            }
        ])
        self.assertEqual(state['submission_state'], 'PRE_SUBMISSION')
        self.assertTrue(state['preliminary'])
        self.assertFalse(state['real_project_acceptance'])
        self.assertFalse(state['production_release_allowed'])

    def test_api_aggregates_multi_file_release_state_fail_closed(self):
        state = electrical_api._aggregate_release_state([
            {'submission_state':'EXECUTION_REVIEW_READY', 'acceptance':{'real_project_acceptance':True, 'production_release_allowed':True}},
            {'submission_state':'PRE_SUBMISSION', 'acceptance':{'real_project_acceptance':False, 'production_release_allowed':False}},
        ])
        self.assertEqual(state['submission_state'], 'PRE_SUBMISSION')
        self.assertFalse(state['real_project_acceptance'])
        self.assertFalse(state['production_release_allowed'])

    def test_cad_runtime_has_no_web_app_dependency(self):
        for module in (production, cad_contract, runtime_support, electrical_api):
            source = inspect.getsource(module)
            self.assertNotIn('from app', source, module.__name__)
            self.assertNotIn('import app', source, module.__name__)

    def test_split_release_contracts_are_green(self):
        cad = cad_release_status()
        site = site_release_status()
        self.assertEqual(cad['status'], 'PASS', cad)
        self.assertEqual(site['status'], 'PASS', site)
        self.assertEqual(cad['scope'], 'cad-runtime')
        self.assertEqual(site['scope'], 'site-ui-panel-runtime')


if __name__ == '__main__':
    unittest.main()
