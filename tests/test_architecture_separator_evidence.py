"""Generic source-role controls: no private coordinates or answer mappings."""
from copy import deepcopy
import pytest
from shapely.geometry import Polygon
from cad_engine.architecture_contract import SCHEMA, assign_canonical_model_hash
from cad_engine.architecture_separator_evidence import bind_boundary, refresh_separator_authority, review_candidate
from cad_engine.architecture_separator_validator import separator_errors
from cad_engine.architecture_review_contract import create_review_item
from cad_engine.architecture_review_engine import replay_review_decisions, plan_preflight
from cad_engine.architecture_validator import validate_architecture


def fixture():
    from tests.test_architecture_preflight_review_engine import model
    m = model(); m['schema'] = SCHEMA; m['source']['source_type']='RAW_DXF'
    m['text_evidence'] = {'schema': 'planha-architectural-text-evidence/1.0',
                          'contract_version': SCHEMA, 'items': [], 'metrics': {}}
    m['title_block_fields'] = []
    m['physical_spaces'] = m['physical_spaces'][:1]
    m['graphs']['enclosure'] = []; m['walls'] = []; m['apertures'] = []
    s=m['physical_spaces'][0]; points=s['polygon']; sha=m['source']['source_sha256']
    records=[dict(segment_id='line-'+str(i),source_handle='H'+str(i),geometry=[a,b]) for i,(a,b) in enumerate(zip(points,points[1:]+points[:1]))]
    s['geometry_status']='VERIFIED'; s['geometry_evidence']=dict(status='VERIFIED',source_handles=[r['source_handle'] for r in records],segments=[r['geometry'] for r in records],tolerance=.001,source_witness_records=records)
    s['source_handles']=s['geometry_evidence']['source_handles']
    m['evidence_registry']=bind_boundary(s,sha); refresh_separator_authority(m)
    return assign_canonical_model_hash(m)


def payload(item, answer):
    return dict(review_item_id=item['review_item_id'],decision=answer,**{k:item[k] for k in ('source_sha256','frame_or_level_id','object_or_region_id','geometry_fingerprint','evidence_fingerprint','review_scope','review_fingerprint')})


def reviewed(answer='PHYSICAL_SEPARATOR'):
    m=fixture(); plan=plan_preflight(m)
    return replay_review_decisions(m,[payload(i,answer) for i in plan['review_items']],plan)


def test_closed_geometry_alone_is_not_material():
    m=fixture();s=m['physical_spaces'][0]
    assert s['geometry_status']=='VERIFIED'
    assert not s['authority']['material_geometry']
    assert plan_preflight(m)['primary_state']=='QUICK_REVIEW_REQUIRED'


def test_validator_rejects_promotion_without_separator():
    m=fixture();m['physical_spaces'][0]['authority'].update(status='VERIFIED',material_geometry=True)
    assert any(c=='MATERIAL_AUTHORITY_WITHOUT_SEPARATOR_EVIDENCE' for c,_ in separator_errors(m))


def test_reviewed_single_line_separator_preserves_geometry():
    before=fixture(); result=reviewed();after=result['reviewed_canonical_model']
    assert after['physical_spaces'][0]['polygon']==before['physical_spaces'][0]['polygon']
    assert after['physical_spaces'][0]['authority']['material_geometry']
    assert separator_errors(after)==[]
    assert result['validator_report']['status']=='PASS'


def test_nonseparator_does_not_create_material():
    result=reviewed('NON_SEPARATOR')
    assert not result['reviewed_canonical_model']['physical_spaces'][0]['authority']['material_geometry']


def test_legacy_gap_review_registry_cannot_break_or_authorize_separator_replay():
    m=fixture()
    legacy={'schema':'architectural-human-gap-review-result/1.0',
            'accepted_review_decisions':[{'decision':'VERIFIED'}],
            'review_application_status':'APPLIED'}
    m['review_registry']=legacy
    plan=plan_preflight(m,review_registry=legacy)
    assert plan['review_registry']['legacy_registry_schema']==legacy['schema']
    assert plan['review_registry']['accepted_decisions']==[]
    item=plan['review_items'][0]
    result=replay_review_decisions(m,[payload(item,'PHYSICAL_SEPARATOR')],plan,legacy)
    assert len(result['accepted_review_decisions'])==1
    assert result['review_registry']['legacy_registry_fingerprint']
    reviewed_entry=next(e for e in result['reviewed_canonical_model']['evidence_registry']
                        if e['evidence_id']==item['object_or_region_id'])
    assert reviewed_entry['payload']['separator']['origin']=='HUMAN_SOURCE_INTERPRETATION'


@pytest.mark.parametrize('key,value',[('source_sha256','c'*64),('geometry_fingerprint','changed'),('evidence_fingerprint','changed'),('review_scope','WHOLE_ROOM')])
def test_stale_or_overbroad_payload_rejected(key,value):
    m=fixture();p=plan_preflight(m);d=payload(p['review_items'][0],'PHYSICAL_SEPARATOR');d[key]=value
    result=replay_review_decisions(m,[d],p)
    assert result['stale_review_decisions'] or result['rejected_review_decisions']
    assert not result['reviewed_canonical_model']['physical_spaces'][0]['authority']['material_geometry']


@pytest.mark.parametrize('mutation',['source','geometry','reference','scope','negative'])
def test_independent_validator_detects_tampered_authority(mutation):
    m=reviewed()['reviewed_canonical_model']; p=m['evidence_registry'][0]['payload']
    if mutation=='source': p['source_sha256']='d'*64
    if mutation=='geometry': p['geometry'][0][0]+=1
    if mutation=='reference': m['physical_spaces'][0]['geometry_evidence']['boundary_witnesses'][0]['evidence_id']='missing'
    if mutation=='scope': p['separator']['review_item']['review_scope']='WHOLE_ROOM'
    if mutation=='negative': p['negative_evidence']=['GRAPHIC']
    assert separator_errors(m)


def test_structured_role_requires_source_bound_profile():
    m=fixture();m['source']['source_type']='CERTIFIED_DXF'
    for e in m['evidence_registry']:
        p=e['payload'];p['separator']=dict(role='PHYSICAL_SEPARATOR',status='VERIFIED',origin='STRUCTURED_INPUT',assertion=dict(source_sha256=p['source_sha256'],evidence_fingerprint=p['evidence_fingerprint'],profile_id='synthetic-explicit-role'))
    refresh_separator_authority(m)
    assert m['physical_spaces'][0]['authority']['material_geometry']
    assert separator_errors(m)==[]
    m['source']['source_type']='RAW_DXF'
    assert separator_errors(m)


def test_validator_read_only():
    m=reviewed()['reviewed_canonical_model'];before=deepcopy(m)
    validate_architecture(m)
    assert m==before


def test_snapshot_refuses_ambiguous_and_forged_old_report():
    from cad_engine.architecture_snapshot import create_snapshot
    from cad_engine.architecture_contract import content_hash
    m=fixture();r=validate_architecture(m)
    with pytest.raises(ValueError): create_snapshot(m,r,engine_identity={},created_at='fixed')
    r['status']='PASS';r.pop('report_hash');r['report_hash']=content_hash(r)
    with pytest.raises(ValueError): create_snapshot(m,r,engine_identity={},created_at='fixed')


def test_legacy_adapter_cannot_repromote():
    from tests.test_architecture_input_foundation_v2 import legacy_model
    from cad_engine.architecture_contract import adapt_current_architecture
    m=adapt_current_architecture(legacy_model())
    assert m['schema']==SCHEMA
    assert all(not s['authority']['material_geometry'] for s in m['physical_spaces'])


def test_room_answer_does_not_grant_separator_role():
    from tests.test_architecture_preflight_review_engine import add_issue,candidate
    m=fixture();add_issue(m,cand=candidate(object_id='S1'))
    p=plan_preflight(m);item=next(i for i in p['review_items'] if i['question_type']=='SPACE_CLASSIFICATION')
    r=replay_review_decisions(m,[payload(item,'LIVING')],p)
    assert all(e['payload']['separator']['role']=='UNKNOWN' for e in r['reviewed_canonical_model']['evidence_registry'])
    assert not r['reviewed_canonical_model']['physical_spaces'][0]['authority']['material_geometry']


@pytest.mark.parametrize('mode',['translate','rotate','reverse','shuffle','nested'])
def test_geometry_representations_keep_role_requirement(mode):
    m=fixture();s=m['physical_spaces'][0];points=deepcopy(s['polygon'])
    def transform(p):
        x,y=p
        return [x+17,y-23] if mode=='translate' else [-y,x] if mode in {'rotate','nested'} else [x,y]
    points=[transform(p) for p in points];s['polygon']=points
    records=[dict(segment_id=str(i),source_handle=str(i),geometry=[a,b]) for i,(a,b) in enumerate(zip(points,points[1:]+points[:1]))]
    if mode=='reverse':
        for r in records:r['geometry'].reverse()
    if mode=='shuffle':records.reverse()
    if mode=='nested':
        for r in records:r.update(source_insert_handle='INSERT',source_block_path=['OUTER','INNER'])
    s['geometry_evidence']['source_witness_records']=records
    s['geometry_evidence']['segments']=[r['geometry'] for r in records]
    m['evidence_registry']=bind_boundary(s,m['source']['source_sha256']);refresh_separator_authority(m)
    assert not s['authority']['material_geometry']
    m['source']['source_type']='CERTIFIED_DXF'
    for e in m['evidence_registry']:
        p=e['payload'];p['separator']=dict(role='PHYSICAL_SEPARATOR',status='VERIFIED',origin='STRUCTURED_INPUT',assertion=dict(source_sha256=p['source_sha256'],evidence_fingerprint=p['evidence_fingerprint'],profile_id='synthetic'))
    refresh_separator_authority(m)
    assert s['authority']['material_geometry'] and separator_errors(m)==[]


def test_identical_review_is_idempotent_and_no_auto_relabel():
    from cad_engine.architecture_review_engine import execute_preflight
    r=reviewed();m=r['reviewed_canonical_model']
    again=execute_preflight(m)
    assert again['snapshot']['validation_state']=='VALIDATED'
    assert m==again['canonical_model']


def test_changed_geometry_invalidates_stored_negative_too():
    m=reviewed('NON_SEPARATOR')['reviewed_canonical_model']
    m['evidence_registry'][0]['payload']['geometry'][0][0]+=1
    assert separator_errors(m)


def test_region_review_replay_preserves_scope_and_is_idempotent():
    from cad_engine.architecture_separator_evidence import register_source_region_review
    m=fixture();key=register_source_region_review(m,frame_id='F1',geometry_fingerprint='existing-region-hash',source_handles=['H0'],question='Is this region an independent enclosed space?',allowed_interpretations=['NOT_INDEPENDENT_SPACE','INDEPENDENT_ENCLOSURE','UNKNOWN'],evidence_fingerprint='original-source-packet-hash')
    assign_canonical_model_hash(m);p=plan_preflight(m);item=next(i for i in p['review_items'] if i['object_or_region_id']==key)
    result=replay_review_decisions(m,[payload(item,'NOT_INDEPENDENT_SPACE')],p)
    after=result['reviewed_canonical_model']
    assert not after['physical_spaces'][0]['authority']['material_geometry']
    assert all(e['payload']['separator']['role']=='UNKNOWN' for e in after['evidence_registry'] if e.get('kind')=='SOURCE_BOUNDARY_SUPPORT')
    assert next(e for e in after['evidence_registry'] if e['evidence_id']==key)['payload']['interpretation']['separator_authority'] is False
    again=replay_review_decisions(after,[payload(item,'NOT_INDEPENDENT_SPACE')],p,result['review_registry'])
    assert len(again['review_registry']['accepted_decisions'])==1
    assert again['reviewed_canonical_model']==after


def test_nonseparator_graphic_does_not_veto_independent_separator():
    m=fixture(); s=m['physical_spaces'][0]
    # Two coincident source entities: one explicit separator, one graphic.
    from cad_engine.architecture_separator_evidence import witness
    original=m['evidence_registry'][0];p=original['payload']
    graphic=witness(dict(segment_id='graphic',source_handle='graphic',geometry=p['geometry']),p['source_sha256'],p['frame_id'],p['level_id'])
    m['evidence_registry'].append(graphic)
    refs=[dict(r,evidence_id=graphic['evidence_id']) for r in s['geometry_evidence']['boundary_witnesses'] if r['evidence_id']==original['evidence_id']]
    s['geometry_evidence']['boundary_witnesses']+=refs
    refresh_separator_authority(m);assign_canonical_model_hash(m);plan=plan_preflight(m)
    result=replay_review_decisions(m,[payload(i,'NON_SEPARATOR' if i['object_or_region_id']==graphic['evidence_id'] else 'PHYSICAL_SEPARATOR') for i in plan['review_items']],plan)
    after=result['reviewed_canonical_model']
    assert after['physical_spaces'][0]['authority']['material_geometry']
    assert separator_errors(after)==[]


def test_ambiguous_status_cannot_be_erased_to_make_snapshot():
    m=fixture();m['unresolved_items']=[];m['release']={'status':'VERIFIED','release_allowed':True,'downstream_engineering_allowed':True}
    assign_canonical_model_hash(m)
    assert validate_architecture(m)['status']!='PASS'
    m['physical_spaces'][0]['geometry_evidence']['separator_status']='REJECTED'
    assert any(c=='SEPARATOR_REJECTION_WITHOUT_EVIDENCE' for c,_ in separator_errors(m))


def test_contradictory_role_uses_existing_conflict_state():
    m=fixture();m['evidence_registry'][0]['payload']['separator']={'role':'PHYSICAL_SEPARATOR','status':'CONFLICT','origin':'SOURCE_GEOMETRIC'}
    refresh_separator_authority(m);assign_canonical_model_hash(m)
    assert plan_preflight(m)['primary_state']=='CONFLICT'


def test_candidate_origin_cannot_grant_separator_authority():
    outcomes=[]
    for origin in ['SOURCE_FACE','EXISTING_SUBDIVISION']:
        m=fixture();s=m['physical_spaces'][0];s['candidate_origin']=origin
        refresh_separator_authority(m)
        outcomes.append((s['authority'],s['geometry_evidence']['boundary_witnesses']))
    assert outcomes[0]==outcomes[1]


def test_old_canonical_identity_cannot_create_current_snapshot():
    from cad_engine.architecture_snapshot import create_snapshot
    m=reviewed()['reviewed_canonical_model'];m['schema']='planha-canonical-architecture/2.0';assign_canonical_model_hash(m)
    r=validate_architecture(m)
    assert r['status']=='FAIL'
    with pytest.raises(ValueError,match='CANONICAL_SCHEMA_MISMATCH'):
        create_snapshot(m,r,engine_identity={},created_at='fixed')


def test_negative_region_blocks_only_exact_reviewed_region_not_source_lines():
    from cad_engine.architecture_separator_evidence import register_source_region_review,region_geometry_fingerprint
    m=fixture();s=m['physical_spaces'][0]
    key=register_source_region_review(m,frame_id='F1',geometry_fingerprint='source-packet-region',source_handles=s['source_handles'],question='Is this an independent space?',allowed_interpretations=['NOT_INDEPENDENT_SPACE','UNKNOWN'],evidence_fingerprint='packet',region_fingerprints=[region_geometry_fingerprint(s)])
    assign_canonical_model_hash(m);plan=plan_preflight(m);item=next(i for i in plan['review_items'] if i['object_or_region_id']==key)
    result=replay_review_decisions(m,[payload(item,'NOT_INDEPENDENT_SPACE')],plan)
    after=result['reviewed_canonical_model'];s=after['physical_spaces'][0]
    assert s['independent_space_status']=='REJECTED'
    assert not s['authority']['material_geometry']
    assert all(e['payload']['separator']['role']=='UNKNOWN' for e in after['evidence_registry'] if e.get('kind')=='SOURCE_BOUNDARY_SUPPORT')
    assert not result['preflight_plan']['review_items']
    s['authority'].update(status='VERIFIED',material_geometry=True)
    assert any(c=='REVIEWED_NON_SPACE_MATERIAL_AUTHORITY' for c,_ in separator_errors(after))
    s['polygon'][0][0]+=.01
    assert any(c=='REGION_REJECTION_WITHOUT_EVIDENCE' for c,_ in separator_errors(after))
