import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.electrical_runtime_patch import install as install_runtime
from app.electrical_design_integration import (
    CONSTRUCTION_DETAIL_QUESTION_SPECS,
    RECOVERY_QUESTION_SPECS,
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
        self.assertIn('supply_voltage_v', missing)
        self.assertIn('earthing_final_basis', missing)
        self.assertIn('lighting_basis_values', missing)

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


    def test_cad_recovery_contract_collapses_internal_ids_and_system_names(self):
        report = {
            'data': {
                'basis': {'values': {
                    'city': {'status':'FINAL'}, 'building_type': {'status':'FINAL'},
                    'number_of_units': {'status':'INPUT_REQUIRED'},
                    'supply_voltage_v': {'status':'INPUT_REQUIRED'},
                    'phase_configuration': {'status':'INPUT_REQUIRED'},
                    'utility_service': {'status':'INPUT_REQUIRED'},
                    'earthing_system': {'status':'INPUT_REQUIRED'},
                }},
                'equipment': [
                    {'id':'REQ-0001','equipment_type':'LIGHT_FIXTURE'},
                    {'id':'REQ-0002','equipment_type':'LIGHT_SWITCH'},
                    {'id':'REQ-0003','equipment_type':'GENERAL_SOCKET'},
                    {'id':'REQ-0007','equipment_type':'DEDICATED_APPLIANCE_OUTLET'},
                ],
            },
            'gates': {
                'SYSTEM_REQUIREMENTS': {'warnings': [
                    'scope_input_required:HVAC_POWER', 'scope_input_required:TELECOM',
                    'scope_input_required:DATA', 'scope_input_required:ELEVATOR_POWER',
                ]},
                'EQUIPMENT_REQUIREMENTS': {'warnings': [
                    'quantity_not_final:REQ-0001','quantity_not_final:REQ-0002',
                    'quantity_not_final:REQ-0003','quantity_not_final:REQ-0007',
                ]},
                'EQUIPMENT_PLACEMENT': {'warnings':['opening_clearance_rule_missing','wall_host_tolerance_missing']},
                'SINGLE_LINE': {'warnings':['service_or_feeder_input_required:service','service_or_feeder_input_required:meter','service_or_feeder_input_required:main_distribution']},
                'RISER': {'warnings':['riser_input_required:LVL-001->LVL-002']},
                'GROUNDING': {'warnings':['grounding_input_required:earth_electrode','grounding_input_required:main_earth_bar','grounding_input_required:protective_conductors','grounding_input_required:panel_grounding']},
                'CONSTRUCTION_DETAIL_AUTHORITY': {'warnings':['detail_parameters_input_required:D-EL-EARTHING:conductor']},
            },
        }
        missing = electrical_api._missing_inputs(report)
        self.assertNotIn('REQ-0001', missing)
        self.assertNotIn('HVAC_POWER', missing)
        self.assertNotIn('TELECOM', missing)
        for key in (
            'number_of_units','supply_voltage_v','supply_configuration','earthing_final_basis',
            'hvac_electrical_loads','low_current_systems','elevator','lighting_basis_values',
            'luminaire_schedule','switch_control_requirements','socket_power_requirements',
            'dedicated_appliance_requirements','opening_clearance_m','wall_host_tolerance_m',
            'service','meter','main_distribution','riser_feeder_schedule',
            'grounding_earth_electrode','grounding_main_earth_bar',
            'grounding_protective_conductors','grounding_panel_grounding',
            'D-EL-EARTHING.conductor',
        ):
            self.assertIn(key, missing, key)

    def test_site_recovery_never_exposes_internal_requirement_ids(self):
        error = 'INPUT_REQUIRED[REQ-0001,HVAC_POWER,TELECOM,supply_voltage_v,D-EL-EARTHING.conductor]:'
        missing = missing_from_error(error)
        self.assertNotIn('REQ-0001', missing)
        self.assertIn('hvac_electrical_loads', missing)
        self.assertIn('low_current_systems', missing)
        self.assertIn('supply_voltage_v', missing)
        self.assertIn('detail_earthing_conductor', missing)
        for key in missing:
            self.assertIn(key, electrical_workflow.REQUIRED_BASIS_QUESTION_SPECS)

    def test_production_config_translates_recovery_answers_without_defaults(self):
        cfg = build_engine_config({
            'discipline':'electrical',
            'supply':'همه واحدها تک‌فاز',
            'supply_voltage_v':'230',
            'number_of_units':'2',
            'low_current_systems':'آنتن، تلفن، شبکه و آیفون',
            'emergency_lighting':'نیاز ندارد',
            'generator':'ندارد', 'ups':'ندارد', 'ev_charging':'ندارد', 'solar_pv':'ندارد',
            'lighting_basis_values':'default=150; bedroom=100',
            'luminaire_schedule':'lumens=1200; utilization_factor=0.60; maintenance_factor=0.80; input_power_w=12',
            'switch_control_requirements':'default=1; stair=2',
            'socket_power_requirements':'minimum_count=2; design_load_w_per_outlet=200; reference=project rule',
            'service':'utility service evidence', 'meter':'meter evidence', 'main_distribution':'MDP evidence',
            'riser_feeder_schedule':'cable=3x6 Cu; protection=C32A; tag=F-01',
            'grounding_earth_electrode':'foundation electrode',
            'grounding_main_earth_bar':'MEB-01',
            'grounding_protective_conductors':'PE schedule',
            'grounding_panel_grounding':'panel PE bar',
            'opening_clearance_m':'0.2','wall_host_tolerance_m':'0.03',
            'ceiling_layout_basis_confirmed':'بله','switch_door_relation_confirmed':'بله',
            'power_factor':'0.95',
        }, {})
        basis = cfg['design_basis']
        self.assertEqual(basis['supply_voltage_v'], 230.0)
        self.assertEqual(basis['number_of_units'], 2)
        self.assertEqual(basis['low_current_systems'], ['TELECOM','DATA','TV','INTERCOM'])
        self.assertFalse(basis['emergency_lighting'])
        self.assertFalse(basis['generator'])
        self.assertEqual(basis['lighting_basis']['default'], 150.0)
        self.assertEqual(basis['switch_control_requirements']['stair'], 2.0)
        self.assertEqual(basis['socket_power_requirements']['default']['minimum_count'], 2)
        self.assertEqual(cfg['manufacturer_data']['luminaires']['default']['lumens'], 1200.0)
        self.assertEqual(cfg['service_inputs']['service'], 'utility service evidence')
        self.assertEqual(cfg['service_inputs']['riser_feeders']['LVL-001->LVL-002']['tag'], 'F-01')
        self.assertEqual(cfg['optional_system_inputs']['grounding']['main_earth_bar'], 'MEB-01')
        self.assertEqual(cfg['placement_rules']['opening_clearance_m'], 0.2)
        self.assertTrue(cfg['placement_rules']['ceiling_layout_basis_confirmed'])
        self.assertEqual(basis['power_factor'], 0.95)
        self.assertNotIn('frequency_hz', basis)

    def test_recovery_questions_are_on_demand_and_registered(self):
        self.assertIn('luminaire_schedule', RECOVERY_QUESTION_SPECS)
        self.assertIn('service', RECOVERY_QUESTION_SPECS)
        self.assertIn('grounding_main_earth_bar', RECOVERY_QUESTION_SPECS)
        self.assertEqual(electrical_workflow.question_payload('supply_voltage_v')['unit'], 'V')

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

    def test_server_rendered_project_page_has_electrical_manifest_review(self):
        template = Path('app/templates/project.html').read_text(encoding='utf-8')
        self.assertIn("discipline=='electrical'", template)
        self.assertIn('/approve-electrical-drawing-set', template)
        source = inspect.getsource(__import__('app.electrical_review_fix', fromlist=['register_electrical_review_fix']).register_electrical_review_fix)
        self.assertIn('/projects/{pid}/approve-electrical-drawing-set', source)

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

    def test_range_style_unit_answer_is_not_promoted_to_exact_unit_count(self):
        cfg = build_engine_config({'discipline':'electrical','units':'۲ تا ۵ واحد'}, {})
        self.assertNotIn('number_of_units', cfg['design_basis'])

    def test_final_earthing_recovery_overrides_unresolved_preflight_option(self):
        cfg = build_engine_config({
            'discipline':'electrical',
            'earthing_system':'طبق گزارش خاک و نظر مشاور تعیین شود',
            'earthing_final_basis':'TN-S',
        }, {})
        self.assertEqual(cfg['design_basis']['earthing_system'], 'tn-s')

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
