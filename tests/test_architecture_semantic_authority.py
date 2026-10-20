"""Semantic labels cannot supply physical boundary or void authority."""
import pytest
from shapely.affinity import rotate
from shapely.geometry import box, Polygon
from cad_engine.architectural_space_engine import (
    _space_record, _architectural_void_candidates, _label_bindings, _classify_text,
    _filter_wall_solid_cells,
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


def test_roof_lightwell_with_complete_local_canonical_enclosure_is_verified():
    extracted=source('نورگیر'); extracted['primitives']=[]
    proof={'status':'VERIFIED','coverage_ratio':1.0,'uncovered_boundary_segments':[],
           'unresolved_internal_segment_ids':[],'negative_evidence':[],
           'wall_ids':['W1','W2','W3','W4'],'source_handles':['A','B','C','D'],
           'evidence':[],'tolerance':.001}
    frame={'frame_id':'F','frame_type':'ROOF','bounds':[-10,-10,10,10]}
    row=_space_record(box(0,0,4,4),frame,'source',extracted,1,
                      geometry_evidence=proof)
    assert row['category']=='lightwell'
    assert row['semantic_status']=='VERIFIED'
    assert row['geometry_evidence']['local_semantic_host_verified'] is True
    assert row['geometry_evidence']['local_semantic_host_basis']==\
        'COMPLETE_CANONICAL_ENCLOSURE_STRICTLY_INSIDE_PLAN_FRAME'


def test_roof_lightwell_accepts_four_independent_confirmed_native_faces():
    extracted=source('نورگیر'); extracted['primitives']=[]
    witnesses=[{'segment_id':f'S{i}','evidence':[{'class':'RECURRING_PARALLEL_FACE_PAIR'}]}
               for i in range(4)]
    proof={'status':'VERIFIED','coverage_ratio':1.0,'uncovered_boundary_segments':[],
           'unresolved_internal_segment_ids':[],'negative_evidence':[],
           'wall_ids':[],'source_handles':['A','B','C','D'],'evidence':[],
           'source_witness_records':witnesses,'tolerance':.001}
    row=_space_record(box(1,1,3,3),
                      {'frame_id':'F','frame_type':'ROOF','bounds':[0,0,10,10]},
                      'source',extracted,1,geometry_evidence=proof)
    assert row['category']=='lightwell'
    assert row['semantic_status']=='VERIFIED'


@pytest.mark.parametrize('scale',[.01,1,1000])
@pytest.mark.parametrize('angle',[0,17,43])
def test_roof_local_host_gate_is_scale_and_rotation_invariant(scale,angle):
    extracted=source('نورگیر'); extracted['primitives']=[]
    extracted['texts'][0]['point']=[4*scale,4*scale]
    proof={'status':'VERIFIED','coverage_ratio':1.0,'uncovered_boundary_segments':[],
           'unresolved_internal_segment_ids':[],'negative_evidence':[],
           'wall_ids':['W1','W2','W3','W4'],'source_handles':['A','B','C','D'],
           'evidence':[],'tolerance':.001*scale}
    poly=rotate(box(3*scale,3*scale,5*scale,5*scale),angle,origin=(4*scale,4*scale))
    row=_space_record(poly,{'frame_id':'F','frame_type':'ROOF',
                           'bounds':[0,0,10*scale,10*scale]},
                      'source',extracted,1,geometry_evidence=proof)
    assert row['category']=='lightwell'
    assert row['semantic_status']=='VERIFIED'


def test_roof_local_host_requires_four_independent_boundary_witnesses():
    extracted=source('نورگیر'); extracted['primitives']=[]
    proof={'status':'VERIFIED','coverage_ratio':1.0,'uncovered_boundary_segments':[],
           'unresolved_internal_segment_ids':[],'negative_evidence':[],
           'wall_ids':['W1','W2','W3'],'source_handles':['A','B','C'],
           'evidence':[],'tolerance':.001}
    row=_space_record(box(3,3,5,5),{'frame_id':'F','frame_type':'ROOF','bounds':[0,0,10,10]},
                      'source',extracted,1,geometry_evidence=proof)
    assert row['category']=='unknown'
    assert row['semantic_status']=='INPUT_REQUIRED'


def test_roof_local_host_over_quarter_frame_remains_reviewable():
    extracted=source('نورگیر'); extracted['primitives']=[]
    proof={'status':'VERIFIED','coverage_ratio':1.0,'uncovered_boundary_segments':[],
           'unresolved_internal_segment_ids':[],'negative_evidence':[],
           'wall_ids':['W1','W2','W3','W4'],'source_handles':['A','B','C','D'],
           'evidence':[],'tolerance':.001}
    row=_space_record(box(1,1,7,7),{'frame_id':'F','frame_type':'ROOF','bounds':[0,0,10,10]},
                      'source',extracted,1,geometry_evidence=proof)
    assert row['category']=='unknown'
    assert row['semantic_status']=='INPUT_REQUIRED'


def test_roof_field_or_incomplete_cell_cannot_borrow_lightwell_label():
    extracted=source('نورگیر'); extracted['primitives']=[]
    frame={'frame_id':'F','frame_type':'ROOF','bounds':[0,0,10,10]}
    complete={'status':'VERIFIED','coverage_ratio':1.0,'uncovered_boundary_segments':[],
              'unresolved_internal_segment_ids':[],'negative_evidence':[],
              'wall_ids':['W1','W2','W3','W4'],'source_handles':['A','B','C','D'],
              'evidence':[],'tolerance':.001}
    roof=_space_record(box(0,0,10,10),frame,'source',extracted,1,
                       geometry_evidence=complete)
    assert roof['category']=='unknown'
    assert 'lightwell' in roof['semantic_candidates']
    incomplete={**complete,'coverage_ratio':.99,'status':'INPUT_REQUIRED',
                'negative_evidence':['PHYSICAL_BOUNDARY_UNSUPPORTED']}
    cell=_space_record(box(1,1,3,3),frame,'source',extracted,1,
                       geometry_evidence=incomplete)
    assert cell['category']=='unknown'
    assert 'lightwell' in cell['semantic_candidates']


def test_sub_tolerance_wall_face_sliver_is_not_a_physical_space():
    accepted,rejected=_filter_wall_solid_cells(
        [box(0,0,.000025,8)],[],{'texts':[],'objects':[]},1,
        canonical_walls=[],tolerance=.002)
    assert accepted==[]
    assert rejected[0]['reason']=='NO_RESOLVABLE_INTERIOR_AT_EVIDENCE_TOLERANCE'


def test_small_but_resolvable_unlabelled_room_is_not_size_deleted():
    room=box(0,0,.2,.2)
    accepted,rejected=_filter_wall_solid_cells(
        [room],[],{'texts':[],'objects':[]},1,
        canonical_walls=[],tolerance=.002)
    assert accepted==[room]
    assert rejected==[]


def test_concave_wall_band_without_resolvable_interior_is_rejected():
    band=Polygon([(0,0),(1.7,0),(1.7,2),(1.1,2),(1.1,.6),(0,.6)])
    evidence=[{'evidence':[{'class':'RECURRING_PARALLEL_FACE_PAIR','thicknesses':[.6]}]}]
    accepted,rejected=_filter_wall_solid_cells(
        [band],evidence,{'texts':[],'objects':[]},1,canonical_walls=[],tolerance=.008)
    assert accepted==[]
    assert rejected[0]['reason']=='WALL_BAND_NO_RESOLVABLE_INTERIOR'


def test_concave_room_with_interior_core_survives_wall_band_guard():
    room=Polygon([(0,0),(5,0),(5,5),(2,5),(2,2),(0,2)])
    evidence=[{'evidence':[{'class':'RECURRING_PARALLEL_FACE_PAIR','thicknesses':[.2]}]}]
    accepted,rejected=_filter_wall_solid_cells(
        [room],evidence,{'texts':[],'objects':[]},1,canonical_walls=[],tolerance=.008)
    assert accepted==[room]
    assert rejected==[]


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
