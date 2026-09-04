from pathlib import Path
from types import SimpleNamespace

from app.dxf_output import _cad_error_message, customer_safe_error
from app.mechanical_workflow import reopen_basis_questions
from app.design_recovery import classify_recovery


class Response:
    def json(self):
        return {'detail': {'status':'INPUT_REQUIRED','missing_inputs':[
            'city','rainfall_intensity','mechanical_shaft_route']}}


def test_structured_cad_error_is_safe_and_machine_resumable():
    message=_cad_error_message(Response())
    assert message.startswith('INPUT_REQUIRED[city,rainfall_intensity,mechanical_shaft_route]')
    assert 'pipeline_qa' not in message
    decision=classify_recovery(message,attempt=1,max_attempts=3)
    assert decision.strategy=='request_user_input'
    assert decision.resume_stage=='failed'


def test_raw_internal_qa_is_never_shown_to_customer():
    raw="{'pipeline_qa': {'status': 'PASS'}, 'authority_qa': {'status': 'FAIL'}}"
    safe=customer_safe_error(raw)
    assert 'pipeline_qa' not in safe and 'authority_qa' not in safe
    assert 'تیم فنی' in safe


def test_structured_cad_failure_shows_only_actionable_gate_codes():
    raw = "CAD_QA_FAILURE: {'status':'FAIL','errors':['split_visual_no_equipment:M-161','board_overlap:M-1:M-2']}"
    safe = customer_safe_error(raw)
    assert 'split_visual_no_equipment:m-161' in safe
    assert 'board_overlap:m-1:m-2' in safe
    assert "{'status'" not in safe


def test_cad_error_retains_failed_stage_and_nested_gate_error():
    class FailedResponse:
        def json(self):
            return {'detail': {'code':'MECHANICAL_QA_FAILED', 'status':'FAIL',
                'stage':'equipment_linkage_gate',
                'failed_stage_qa':{'status':'FAIL','errors':['equipment_or_route_missing:M-161:indoor_unit']}}}
    raw = _cad_error_message(FailedResponse())
    assert 'equipment_linkage_gate' in raw
    assert 'equipment_or_route_missing:M-161:indoor_unit' in raw
    safe = customer_safe_error(raw)
    assert 'equipment_linkage_gate' in safe
    assert 'equipment_or_route_missing:m-161:indoor_unit' in safe


def test_approved_manifest_gate_is_in_failed_stage_contract():
    source = Path('cad_engine/main_v15.py').read_text()
    assert '"approved_manifest_gate":"approved_manifest_qa"' in source


def test_failed_stage_errors_survive_large_earlier_reports():
    class LargeResponse:
        def json(self):
            return {'detail': {'code':'MECHANICAL_QA_FAILED', 'status':'FAIL',
                'pipeline_qa':{'metrics':{'blob':'x' * 3000}},
                'stage':'approved_manifest_gate',
                'failed_stage_qa':{'status':'FAIL','errors':['total_plan_count_mismatch:approved=17:generated=16']}}}
    raw = _cad_error_message(LargeResponse())
    assert raw.index('total_plan_count_mismatch') < 300
    assert 'approved_manifest_gate' in customer_safe_error(raw)
    assert 'total_plan_count_mismatch:approved=17:generated=16' in customer_safe_error(raw)


def test_late_input_failure_reopens_only_missing_questions_and_preserves_analysis():
    project=SimpleNamespace(
        answers={'discipline':'mechanical','city':'مشهد','location':'مشهد',
                 'rainfall_intensity':'95 mm/h','rainfall_intensity_mm_h':95,
                 'mechanical_shaft_route':'use_existing_architectural_shafts',
                 'mechanical_shaft_approval':{'status':'APPROVED'},'cooling':'اسپلیت'},
        questions=[],current_question=0,status='failed',
        analysis={'architectural_auto':{'rooms':13},'drawing_set':{'approved':True}},
    )
    assert reopen_basis_questions(project,['city','rainfall_intensity','mechanical_shaft_route'])
    assert project.status=='asking'
    assert [q['key'] for q in project.questions]==['city','rainfall_intensity','mechanical_shaft_route']
    assert project.answers['cooling']=='اسپلیت'
    assert 'city' not in project.answers and 'location' not in project.answers
    assert project.analysis['architectural_auto']['rooms']==13
    assert project.analysis['basis_preflight']['resume_stage']=='authority_contract'


def test_project_85_cooling_failure_reopens_exact_question_and_clears_unsupported_answer():
    project=SimpleNamespace(
        answers={'discipline':'mechanical','city':'مشهد','cooling':'اسپلیت یا داکت‌اسپلیت'},
        questions=[],current_question=9,status='failed',
        analysis={'architectural_auto':{'rooms':13},'drawing_set':{'approved':True}},
    )
    assert reopen_basis_questions(project,['cooling_system'])
    assert project.status == 'asking'
    assert project.questions[0]['key'] == 'cooling_system'
    assert project.questions[0]['options'] == ['اسپلیت دیواری']
    assert 'cooling' not in project.answers and 'cooling_system' not in project.answers
    assert project.analysis['architectural_auto']['rooms'] == 13


def test_nested_authority_gas_pressure_failure_reopens_numeric_contract_key():
    class NestedResponse:
        def json(self):
            return {'detail': {'authority_qa': {
                'status': 'FAIL',
                'errors': ['design_basis_input_required:gas_service_pressure'],
            }}}
    message = _cad_error_message(NestedResponse())
    assert message.startswith('INPUT_REQUIRED[gas_pressure]')
    project = SimpleNamespace(
        answers={'discipline':'mechanical','gas':'گاز برای پکیج','gas_pressure':'ساختمان گاز ندارد'},
        questions=[],current_question=0,status='failed',analysis={},
    )
    assert reopen_basis_questions(project, ['gas_pressure'])
    question = project.questions[0]
    assert question['key'] == 'gas_pressure'
    assert question['input_type'] == 'number'
    assert question['unit'] == 'mbar'
    assert question['options'] == []
