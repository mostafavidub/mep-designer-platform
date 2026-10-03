from shapely.geometry import box, Polygon
from cad_engine.architecture_enclosure_candidates import reconcile_enclosure_candidates


def rows(coords):
    return [{'segment_id':str(i),'source_handle':str(i),'status':'ACCEPTED',
             'geometry':[a,b],'evidence':[{'class':'SOURCE_CONTEXT'}]}
            for i,(a,b) in enumerate(zip(coords,coords[1:]))]


def run(polys,segments,**kwargs):
    return reconcile_enclosure_candidates(polys,segments,[],[],.002,'frame',**kwargs)


def rectangle():
    return rows([(0,0),(2,0),(2,1),(0,1),(0,0)])


def test_source_loop_survives_unrelated_axis_cells():
    selected,diag=run([box(4,4,5,5)],rectangle())
    assert len(selected)==2 and any(p.equals(box(0,0,2,1)) for p in selected)
    assert next(r for r in diag['candidates'] if r['area']==2)['boundary_evidence']['status']=='VERIFIED'


def test_supported_endpoint_to_face_precision():
    segments=rectangle(); segments[3]['geometry']=[(0,1),(0,.001)]
    segments[0]['geometry']=[(-1,0),(2,0)]
    selected,diag=run([],segments)
    assert len(selected)==1 and selected[0].area>1.99
    assert diag['endpoint_coincidences']


def test_large_gap_and_parallel_near_lines_not_joined():
    segments=rectangle();segments[3]['geometry']=[(0,1),(0,.03)]
    assert not run([],segments)[0]
    segments=rows([(0,0),(2,0)])+rows([(0,.001),(2,.001)])
    assert not run([],segments)[1]['endpoint_coincidences']


def test_hard_excluded_diagonal_cannot_split():
    segments=rectangle();segments.append({'segment_id':'symbol','status':'ACCEPTED','geometry':[(0,0),(2,1)],'wall_evidence_state':'HARD_EXCLUDED_NON_ENCLOSURE_OBJECT','evidence':[{'class':'SOURCE_CONTEXT'}]})
    selected,diag=run([],segments)
    assert len(selected)==1 and selected[0].area==2


def test_weak_bottom_stays_input_required():
    segments=rectangle();segments[0]['evidence']=[{'class':'ITERATIVE_PARTITION_RECOVERY'}]
    selected,diag=run([],segments)
    assert len(selected)==1 and diag['candidates'][0]['boundary_evidence']['status']=='INPUT_REQUIRED'


def test_child_displaces_unsupported_parent():
    selected,diag=run([box(-1,-1,3,3)],rectangle())
    assert len(selected)==1 and selected[0].area==2
    assert next(r for r in diag['candidates'] if r['area']==16)['candidate_role']=='PARENT_CONTAINER'


def test_wall_material_filter():
    assert not run([],rectangle(),candidate_filter=lambda _:[])[0]


def test_order_determinism():
    segments=rectangle()
    assert run([],segments)[1]==run([],list(reversed(segments)))[1]


def test_invalid_stays_diagnostic():
    selected,diag=run([Polygon([(0,0),(1,1),(0,1),(1,0)])],[])
    assert not selected and len(diag['invalid_candidates'])==1


def test_ambiguous_near_faces_do_not_snap():
    segments=rows([(0,.001),(0,1)])
    for index,y in enumerate([0,-.0005],10):
        segments.append({'segment_id':str(index),'status':'ACCEPTED','geometry':[(-1,y),(1,y)],'evidence':[{'class':'SOURCE_CONTEXT'}]})
    assert not run([],segments)[1]['endpoint_coincidences']


def test_weak_endpoint_cannot_anchor_recovery():
    segments=rectangle();segments[3]['geometry']=[(0,1),(0,.001)]
    segments[0]['geometry']=[(-1,0),(2,0)]
    segments[3]['evidence']=[{'class':'ITERATIVE_PARTITION_RECOVERY'}]
    assert not run([],segments)[0]


def test_real_diagonal_wall_and_short_partition_preserved():
    segments=rows([(0,0),(2,0),(2,.2),(0,1),(0,0)])
    selected,diag=run([],segments)
    assert len(selected)==1
    assert diag['candidates'][0]['boundary_evidence']['status']=='VERIFIED'


def test_existing_verified_room_not_displaced_by_weak_small_candidate():
    segments=rectangle()
    weak=rows([(.5,.25),(1,.25),(1,.5),(.5,.5),(.5,.25)])
    for i,r in enumerate(weak):
        r['segment_id']='weak'+str(i);r['evidence']=[{'class':'ITERATIVE_PARTITION_RECOVERY'}]
    selected,diag=run([box(0,0,2,1)],segments+weak)
    assert len(selected)==1 and selected[0].area==2


def grid(explicit=False):
    segments=[]
    for x in range(5): segments.append([(x,0),(x,2)])
    segments.extend([[(-1,0),(5,0)],[(-1,1),(5,1)]])
    return [{'segment_id':str(i),'status':'ACCEPTED','geometry':line,
             'evidence':[{'class':'SOURCE_CONTEXT'}, {'class':'RECURRING_PARALLEL_FACE_PAIR','thicknesses':[.2]}] if explicit else
             [{'class':'RECURRING_PARALLEL_FACE_PAIR','thicknesses':[.1,.2,.3]}]}
            for i,line in enumerate(segments)]


def test_repeated_grid_is_not_independent_room_authority():
    selected,diag=run([],grid())
    assert not selected
    assert len([r for r in diag['candidates'] if r['candidate_role']=='REPEATED_CELL_ARRAY'])==4


def test_independent_unambiguous_wall_family_rooms_are_preserved():
    selected,diag=run([],grid(explicit=True))
    assert len(selected)==4
    assert all(r['candidate_role']=='SPACE_CANDIDATE' for r in diag['candidates'])


def test_two_competing_face_spacings_still_ambiguous():
    segments=grid()
    for r in segments: r['evidence'][0]['thicknesses']=[.3,.6]
    selected,diag=run([],segments)
    assert not selected
    assert all(r['candidate_role']=='REPEATED_CELL_ARRAY' for r in diag['candidates'])


def test_filtered_array_context_still_vetoes_remaining_cells():
    selected,diag=run([],grid(),candidate_filter=lambda cells:[p for p in cells if int(p.centroid.x)%2==0])
    assert not selected
    assert len(diag['candidates'])==2
    assert all(r['candidate_role']=='REPEATED_CELL_ARRAY' for r in diag['candidates'])


def test_one_explicit_edge_does_not_certify_repeated_grid():
    segments=grid()
    segments[-1]['evidence']=[{'class':'SOURCE_CONTEXT'}]
    assert not run([],segments)[0]


def test_numerically_adjacent_arrays_use_existing_tolerance_only():
    from cad_engine.architecture_enclosure_candidates import _ambiguous_cell_arrays
    def assess(gap):
        cells=[box(i*(1+gap),0,i*(1+gap)+1,1) for i in range(3)]
        segments=[]
        for j,p in enumerate(cells):
            for i,(a,b) in enumerate(zip(list(p.exterior.coords),list(p.exterior.coords)[1:])):
                segments.append({'segment_id':f'{j}-{i}','status':'ACCEPTED','geometry':[a,b],
                                 'evidence':[{'class':'RECURRING_PARALLEL_FACE_PAIR','thicknesses':[.1,.2]}]})
        entries=[(p,{'candidate_id':str(i),'origins':['SOURCE_FACE'],'candidate_role':'SPACE_CANDIDATE'}) for i,p in enumerate(cells)]
        _ambiguous_cell_arrays(entries,segments,.002)
        return [r['candidate_role'] for _,r in entries]
    assert assess(.001)==['REPEATED_CELL_ARRAY']*3
    assert assess(.02)==['SPACE_CANDIDATE']*3


def test_wall_layer_cannot_override_conflicting_array_geometry():
    segments=grid()
    for r in segments: r['evidence'].append({'class':'SOURCE_CONTEXT','value':'Wall'})
    assert not run([],segments)[0]


def test_wall_layer_only_array_lacks_material_family():
    segments=grid()
    for r in segments: r['evidence']=[{'class':'SOURCE_CONTEXT'}]
    assert not run([],segments)[0]


def wall_at(x):
    return {'thickness':.2,'wall_solid':{'axis_origin':[x,0],'axis_direction':[0,1],'occupied_intervals':[[0,1]]}}


def test_material_occupancy_inside_source_room_blocks_authority():
    selected,diag=reconcile_enclosure_candidates([],rectangle(),[wall_at(1)],[],.002,'frame')
    assert not selected
    assert diag['candidates'][0]['candidate_role']=='WALL_MATERIAL_CONFLICT'


def test_source_face_room_next_to_occupied_wall_remains_valid():
    selected,diag=reconcile_enclosure_candidates([],rectangle(),[wall_at(-.1)],[],.002,'frame')
    assert len(selected)==1 and diag['candidates'][0]['boundary_evidence']['status']=='VERIFIED'


def test_dxf_repeated_rooms_with_real_paired_wall_faces(tmp_path, monkeypatch):
    import ezdxf
    from cad_engine.architectural_space_engine import reconstruct_architecture
    monkeypatch.setenv('ARCH_VISION_PROVIDER','disabled')
    doc=ezdxf.new();doc.header['$INSUNITS']=6;doc.layers.new('WALL');m=doc.modelspace()
    # Three clear 2 x 2 interiors separated by actual 0.2-thick wall faces.
    # No evidence metadata is injected: classification and pairing run on DXF.
    for offset in [0,2.2,4.4]:
        corners=[(offset+.2,.2),(offset+2.2,.2),(offset+2.2,2.2),(offset+.2,2.2),(offset+.2,.2)]
        for a,b in zip(corners,corners[1:]):m.add_line(a,b,dxfattribs={'layer':'WALL'})
    outer=[(0,0),(6.8,0),(6.8,2.4),(0,2.4),(0,0)]
    for a,b in zip(outer,outer[1:]):m.add_line(a,b,dxfattribs={'layer':'WALL'})
    m.add_text('GROUND FLOOR PLAN',dxfattribs={'insert':(1,2.8),'height':.1})
    path=tmp_path/'paired-rooms.dxf';doc.saveas(path)
    model=reconstruct_architecture(path)
    spaces=[s for s in model['physical_spaces'] if s['geometry_status']=='VERIFIED']
    assert len(spaces)>=3
    for x in [1.2,3.4,5.6]:
        from shapely.geometry import Point
        assert any(Polygon(s['polygon'],s['interior_rings']).contains(Point(x,1.2)) for s in spaces)
    assert any(w.get('face_a') and w.get('face_b') for w in model['canonical_walls'])
