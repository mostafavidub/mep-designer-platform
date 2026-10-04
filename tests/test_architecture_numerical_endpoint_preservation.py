"""Source-topology recall and destructive controls for numerical endpoint noding."""
from copy import deepcopy
import math
import pytest
from shapely.geometry import Polygon
from cad_engine.architecture_enclosure_candidates import reconcile_enclosure_candidates, _source_topology


def source_room(delta=1e-11, angle=0, offset=(0, 0), reverse=False):
    pts=[(0,0),(4,0),(4,3),(0,3)]
    edges=[(pts[i],pts[(i+1)%4]) for i in range(4)]
    edges[2]=((4-delta,3), (0,3))
    c,s=math.cos(angle),math.sin(angle)
    def place(p):return (p[0]*c-p[1]*s+offset[0],p[0]*s+p[1]*c+offset[1])
    return [{'segment_id':str(i),'source_handle':str(i),'status':'ACCEPTED',
             'geometry':list(reversed([place(a),place(b)])) if reverse else [place(a),place(b)],
             'evidence':[{'class':'LOCAL_PARALLEL_FACE_PAIR','thickness':.2}]}
            for i,(a,b) in enumerate(edges)]


def solve(rows):return reconcile_enclosure_candidates([],rows,[],[],.002,'F')


@pytest.mark.parametrize('angle',[0,.71,math.pi/2])
@pytest.mark.parametrize('offset',[(0,0),(7000,-4000),(-300,20)])
@pytest.mark.parametrize('reverse',[False,True])
def test_numerically_equivalent_room_preserved_without_source_mutation(angle,offset,reverse):
    rows=source_room(angle=angle,offset=offset,reverse=reverse); before=deepcopy(rows)
    selected,diag=solve(rows)
    assert rows==before
    assert len(selected)==1 and selected[0].area==pytest.approx(12,abs=1e-7)
    assert diag['candidates'][0]['boundary_evidence']['status']=='VERIFIED'
    assert all(not j['material'] for j in diag['endpoint_coincidences'])
    assert solve(list(reversed(rows)))[1]==diag


@pytest.mark.parametrize('gap',[1e-7,1e-5,.001,.02])
def test_actual_endpoint_gap_is_not_filled(gap):
    assert not solve(source_room(delta=gap))[0]


@pytest.mark.parametrize('excluded',['weak','hard'])
def test_no_authority_from_weak_or_excluded_endpoint(excluded):
    rows=source_room()
    if excluded=='weak': rows[2]['evidence']=[{'class':'ITERATIVE_PARTITION_RECOVERY'}]
    else: rows[2]['wall_evidence_state']='HARD_EXCLUDED_NON_ENCLOSURE_OBJECT'
    assert not solve(rows)[0]


def test_parallel_faces_remain_distinct():
    rows=source_room()[:2]
    rows[1]['geometry']=[(0,1e-11),(4,1e-11)]
    lines,joins=_source_topology(rows,.002)
    assert not joins and list(lines[1].coords)==rows[1]['geometry']


def test_numerical_coincidence_never_accumulates_transitively():
    rows=source_room()[:3]
    rows[0]['geometry']=[(0,0),(-2,0)]
    rows[1]['geometry']=[(1.5e-9,0),(1,2)]
    rows[2]['geometry']=[(3e-9,0),(2,-1)]
    _,joins=_source_topology(rows,.002)
    assert not [j for j in joins if j['reason']=='NUMERICAL_TRANSVERSE_ENDPOINT_EQUIVALENCE']


def test_paired_source_room_survives_extraction_adapter_and_validator(tmp_path,monkeypatch):
    import ezdxf
    from cad_engine.architectural_space_engine import reconstruct_architecture
    from cad_engine.architecture_contract import adapt_current_architecture
    from cad_engine.architecture_validator import validate_architecture
    monkeypatch.setenv('ARCH_VISION_PROVIDER','disabled')
    doc=ezdxf.new();doc.header['$INSUNITS']=6;doc.layers.new('WALL')
    inner=source_room(offset=(7100,-3200))
    for row in inner:doc.modelspace().add_line(*row['geometry'],dxfattribs={'layer':'WALL'})
    points=[(7099.8,-3200.2),(7104.2,-3200.2),(7104.2,-3196.8),(7099.8,-3196.8)]
    for a,b in zip(points,points[1:]+points[:1]):doc.modelspace().add_line(a,b,dxfattribs={'layer':'WALL'})
    path=tmp_path/'paired.dxf';doc.saveas(path)
    model=adapt_current_architecture(reconstruct_architecture(path))
    assert all(not s['authority']['material_geometry'] for s in model['physical_spaces'])
    from cad_engine.architecture_review_engine import plan_preflight, replay_review_decisions
    from tests.test_architecture_separator_evidence import payload
    plan=plan_preflight(model)
    model=replay_review_decisions(model,[payload(i,'PHYSICAL_SEPARATOR') for i in plan['review_items'] if i['question_type']=='SOURCE_ROLE_CLASSIFICATION'],plan)['reviewed_canonical_model']
    rooms=[s for s in model['physical_spaces'] if s['authority']['material_geometry']]
    assert len(rooms)==1 and rooms[0]['area_m2']==pytest.approx(12,abs=1e-6)
    report=validate_architecture(model)
    assert not report['hard_errors'] and report['input_hash_before']==report['input_hash_after']
