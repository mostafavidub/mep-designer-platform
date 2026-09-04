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
