"""Semantic labels cannot supply physical boundary or void authority."""
from shapely.geometry import box
from cad_engine.architectural_space_engine import (
    _space_record, _architectural_void_candidates, _label_bindings, _classify_text,
)


def source(text='bedroom', layer='WALL'):
    return {'texts':[{'handle':'T','text':text,'point':[2,2]}], 'objects':[], 'dimensions':[],
            'primitives':[{'handle':'B','entity_type':'LWPOLYLINE','layer':layer,'closed':True,
                           'points':[[0,0],[4,0],[4,4],[0,4]]}]}


def test_positive_source_bounded_room_has_independent_geometry_and_semantics():
    row=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',source(),1)
    assert row['geometry_status']==row['semantic_status']=='VERIFIED'
    assert row['source_handles']==['B']
    assert row['category']=='bedroom'


def test_label_does_not_supply_missing_boundary_authority():
    extracted=source(); extracted['primitives']=[]
    row=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',extracted,1)
    assert row['geometry_status']==row['status']=='INPUT_REQUIRED'
    assert row['source_handles']==[]


def test_shared_boundary_label_does_not_get_verified_host():
    spaces=[{'physical_space_id':'A','polygon':[[0,0],[2,0],[2,4],[0,4]]},
            {'physical_space_id':'B','polygon':[[2,0],[4,0],[4,4],[2,4]]}]
    bindings=_label_bindings(spaces,source()['texts'],.001)
    assert bindings[0]['status']=='CONFLICT'
    assert bindings[0]['host_space_id'] is None


def test_roof_containing_service_label_requires_local_host_extent():
    extracted=source('داکت'); extracted['primitives']=[]
    proof={'status':'VERIFIED','source_handles':['W1'],'evidence':[]}
    row=_space_record(box(0,0,4,4),{'frame_id':'F','frame_type':'ROOF'},'source',extracted,1,
                      geometry_evidence=proof)
    assert row['category']=='unknown'
    assert row['semantic_status']=='INPUT_REQUIRED'
    assert row['geometry_status']=='VERIFIED'
    assert 'duct' in row['semantic_candidates']


def test_contained_duct_label_in_source_closed_host_retained():
    extracted=source('داکت','DUCT'); extracted['texts'][0]['point']=[.2,.2]
    extracted['primitives'][0]['points']=[[0,0],[.4,0],[.4,.4],[0,.4]]
    rows=_architectural_void_candidates(extracted,[{'frame_id':'F','bounds':[-5,-5,5,5]}],'s',.001)
    assert len(rows)==1 and rows[0]['status']=='VERIFIED'
    assert rows[0]['association_basis']=='CONTAINED_LABEL_AND_SOURCE_CLOSED_HOST'


def test_column_never_becomes_void_even_with_contained_duct_label():
    extracted=source('داکت','COLUMN'); extracted['texts'][0]['point']=[.2,.2]
    extracted['primitives'][0]['points']=[[0,0],[.4,0],[.4,.4],[0,.4]]
    assert _architectural_void_candidates(extracted,[{'frame_id':'F','bounds':[-5,-5,5,5]}],'s',.001)==[]


def test_repeated_offset_without_independent_void_semantics_is_insufficient():
    extracted={'texts':[],'primitives':[]}
    for n in range(2):
        extracted['texts'].append({'handle':f'T{n}','text':'داکت','point':[n*3+.7,.2]})
        extracted['primitives'].append({'handle':f'P{n}','entity_type':'LWPOLYLINE','closed':True,
                                       'points':[[n*3,0],[n*3+.4,0],[n*3+.4,.4],[n*3,.4]]})
    assert _architectural_void_candidates(extracted,[{'frame_id':'F','bounds':[-5,-5,10,5]}],'s',.001)==[]


def test_full_backyard_label_preserves_specific_meaning():
    assert _classify_text('حیاط خلوت')[0]=='backyard'


def test_point_only_object_does_not_promote_room_semantics():
    extracted=source(); extracted['texts']=[]
    extracted['objects']=[{'handle':'I','name':'bed','point':[2,2],'object_types':['bed']}]
    row=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',extracted,1)
    assert row['category']=='unknown'
    assert row['semantic_status']=='INPUT_REQUIRED'
    extracted['objects'][0]['footprint']=[[1,1],[3,1],[3,3],[1,3]]
    row=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',extracted,1)
    assert row['category']=='bedroom'
    assert row['semantic_status']=='HIGH_CONFIDENCE'


def test_generic_rectangle_and_label_do_not_prove_geometry():
    row=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',source(layer='0'),1)
    assert row['geometry_status']==row['status']=='INPUT_REQUIRED'
    assert row['source_handles']==[]


def test_duct_label_on_closed_boundary_does_not_receive_void_authority():
    extracted=source('داکت','DUCT'); extracted['texts'][0]['point']=[0,.2]
    extracted['primitives'][0]['points']=[[0,0],[.4,0],[.4,.4],[0,.4]]
    assert _architectural_void_candidates(extracted,[{'frame_id':'F','bounds':[-5,-5,5,5]}],'s',.001)==[]


def test_reused_text_handle_is_not_a_shared_semantic_occurrence():
    extracted=source()
    extracted['texts']=[{'handle':'T','text':'bedroom','point':[2,2],'source_insert_handle':'A'},
                        {'handle':'T','text':'toilet','point':[3,2],'source_insert_handle':'B'}]
    first=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',source(),1)
    bindings=[{'source_handle':'T','point':[2,2],'source_insert_handle':'A',
               'host_space_id':first['physical_space_id'],'status':'VERIFIED'}]
    row=_space_record(box(0,0,4,4),{'frame_id':'F'},'source',extracted,1,label_bindings=bindings)
    assert row['category']=='bedroom'
    assert row['semantic_status']=='INPUT_REQUIRED'
    assert row['unresolved_label_evidence'][0]['source_insert_handle']=='B'
