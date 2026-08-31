import copy,json
from pathlib import Path
from cad_engine.mechanical_governance_v1 import validate_repository_governance,validate_release_against_contract

ROOT=Path(__file__).resolve().parents[1]


def _passing_report():
    contract=json.loads((ROOT/'standards/projects/project-1.contract.json').read_text())
    baseline=json.loads((ROOT/'standards/golden/project-1.baseline.json').read_text())
    manifest=[]
    for family,count in baseline['exact_family_counts'].items():manifest += [{'family':family} for _ in range(count)]
    report={'status':'PASS','composition':{'boards':{f'B{i}':{} for i in range(28)},'manifest':manifest},
            'approved_manifest_qa':{'status':'PASS','expected_plan_count':20},
            'titleblock_qa':{'status':'PASS','validated_titleblocks':28},
            'plan_board_population_qa':{'status':'PASS','boards':[{'status':'PASS'} for _ in range(20)]},
            'montage_exact_reopen_qa':{'status':'PASS','entity_count':8183}}
    for gate in contract['required_gates']:report.setdefault(gate,{'status':'PASS'})
    return report


def test_all_ten_governance_steps_and_locked_tests_exist():
    result=validate_repository_governance(ROOT)
    assert result['status']=='PASS',result['errors']
    assert result['steps_checked']==10


def test_complete_approved_release_passes_governance():
    assert validate_release_against_contract(_passing_report())['status']=='PASS'


def test_skipped_required_gate_is_never_treated_as_pass():
    report=_passing_report();report['detail_library_qa']={'status':'SKIPPED'}
    result=validate_release_against_contract(report)
    assert result['status']=='FAIL'
    assert 'required_gate_not_pass:detail_library_qa:SKIPPED' in result['errors']


def test_semantic_content_reduction_fails_closed():
    report=_passing_report();report['composition']['boards'].pop('B0')
    result=validate_release_against_contract(report)
    assert result['status']=='FAIL'
    assert any(x.startswith('golden_minimum_regression:board_count') for x in result['errors'])


def test_family_removal_requires_contract_migration():
    report=_passing_report();report['composition']['manifest'].pop()
    assert 'golden_family_manifest_changed_without_migration' in validate_release_against_contract(report)['errors']

