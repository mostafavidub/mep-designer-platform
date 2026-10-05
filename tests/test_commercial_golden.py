from copy import deepcopy
import pytest
from tests.test_commercial_measurement import bundle,confirm,ENGINE,SHA
from app.commercial_golden import golden_request,validate_golden,benchmark


def test_requests_do_not_copy_model_areas_into_truth():
    q=golden_request('P1',[SHA],[{'frame_id':'F0'}],ENGINE)
    assert q['levels']==[] and q['expected_total_billable_area_m2'] is None
    with pytest.raises(ValueError,match='HUMAN_GOLDEN_REQUIRED'):validate_golden(q)


def test_absent_truth_does_not_claim_zero_errors_or_accuracy():
    b=benchmark([confirm([bundle()])]); assert b['human_verified_project_count']==0
    assert b['metrics']['false_auto_verified_count'] is None
    assert b['metrics']['total_billable_area_error_m2'] is None


def human_contract_fixture():
    # Explicit test-authored contract exercise, never a shipped real-project Golden.
    q=golden_request('P1',[SHA],[],ENGINE)
    q.update(status='HUMAN_VERIFIED',reviewer='test contract author',reviewed_at='fixed',
        authority_source='independent test-only fixture',building_count=1,expected_total_billable_area_m2=100,
        levels=[{'source_sha256':SHA,'frame_id':'F0','building_id':'A','represented_level_ids':['L0'],
            'commercial_level_type':'GROUND','multiplicity':1,'billable':True,'gross_area_m2':100,'authority_note':'test-only exact square'}])
    return q


def test_golden_contract_reconciles_independent_inventory_and_total():
    q=human_contract_fixture(); assert validate_golden(q)
    q['expected_total_billable_area_m2']=101
    with pytest.raises(ValueError,match='TOTAL'):validate_golden(q)


def test_benchmark_does_not_hide_wrong_gross_area():
    q=human_contract_fixture();q['levels'][0]['gross_area_m2']=90;q['expected_total_billable_area_m2']=90
    result=benchmark([confirm([bundle()])],[q])
    assert result['metrics']['false_auto_verified_count']==1
    assert result['metrics']['total_billable_area_error_m2']==[10]


def test_algorithm_truth_and_stale_truth_rejected():
    q=human_contract_fixture();q['authority_source']='PLANHA'
    with pytest.raises(ValueError,match='ALGORITHM'):validate_golden(q)
    q=human_contract_fixture();q['source_sha256s']=['b'*64];q['levels'][0]['source_sha256']='b'*64
    with pytest.raises(ValueError,match='STALE'):benchmark([confirm([bundle()])],[q])
