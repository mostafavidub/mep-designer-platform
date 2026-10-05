import ezdxf
import pytest
from shapely.geometry import Polygon

from cad_engine.architectural_space_engine import reconstruct_architecture
from cad_engine.architecture_contract import adapt_current_architecture
from cad_engine.architecture_validator import validate_architecture


@pytest.mark.parametrize('label,cross', [('کمد', False), ('آسانسور', True)])
def test_symbolic_chords_never_create_triangular_physical_spaces(tmp_path, monkeypatch, label, cross):
    monkeypatch.setenv('ARCH_VISION_PROVIDER', 'disabled')
    doc=ezdxf.new();doc.header['$INSUNITS']=6;m=doc.modelspace()
    for a,b in [((0,0),(2,0)),((2,0),(2,2)),((2,2),(0,2)),((0,2),(0,0))]:m.add_line(a,b)
    m.add_line((0,0),(2,2))
    if cross:m.add_line((0,2),(2,0))
    m.add_text(label,dxfattribs={'insert':(.8,.6),'height':.1})
    path=tmp_path/'symbol.dxf';doc.saveas(path)
    model=reconstruct_architecture(path)
    assert len(model['physical_spaces'])==1
    assert Polygon(model['physical_spaces'][0]['polygon']).area==pytest.approx(4)
    assert any('INTERNAL_CORNER_CHORD' in r['evidence'] for r in model['source_role_diagnostics']['items'])
    assert all(r['status']=='REJECTED' for r in model['architectural_segments']
               if 'INTERNAL_CORNER_CHORD' in (r.get('pre_topology_classification') or {}).get('positive_evidence',[]))


def test_real_diagonal_enclosure_still_has_geometry_authority(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCH_VISION_PROVIDER','disabled')
    doc=ezdxf.new();doc.header['$INSUNITS']=6;doc.layers.new('WALL');m=doc.modelspace()
    for a,b in [((0,0),(6,0)),((6,0),(0,6)),((0,6),(0,0))]:m.add_line(a,b,dxfattribs={'layer':'WALL'})
    m.add_text('BEDROOM',dxfattribs={'insert':(1,1),'height':.1})
    m.add_text('GROUND FLOOR PLAN',dxfattribs={'insert':(2,5),'height':.1})
    path=tmp_path/'diagonal.dxf';doc.saveas(path)
    model=reconstruct_architecture(path);canonical=adapt_current_architecture(model)
    assert len(canonical['physical_spaces'])==1
    assert canonical['physical_spaces'][0]['geometry_status']=='VERIFIED'
    assert not canonical['physical_spaces'][0]['authority']['material_geometry']
    from cad_engine.architecture_review_engine import plan_preflight, replay_review_decisions
    from tests.test_architecture_separator_evidence import payload
    plan=plan_preflight(canonical)
    result=replay_review_decisions(canonical,[payload(i,'PHYSICAL_SEPARATOR') for i in plan['review_items'] if i['question_type']=='SOURCE_ROLE_CLASSIFICATION'],plan)
    assert result['reviewed_canonical_model']['physical_spaces'][0]['authority']['material_geometry']
    assert not validate_architecture(canonical)['hard_errors']


def test_open_plan_labels_do_not_create_material_partitions(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCH_VISION_PROVIDER','disabled')
    doc=ezdxf.new();doc.header['$INSUNITS']=6;doc.layers.new('WALL');m=doc.modelspace()
    for a,b in [((0,0),(8,0)),((8,0),(8,6)),((8,6),(0,6)),((0,6),(0,0))]:m.add_line(a,b,dxfattribs={'layer':'WALL'})
    for text,point in [('LIVING',(1,1)),('DINING',(4,2)),('KITCHEN',(6,4))]:m.add_text(text,dxfattribs={'insert':point,'height':.1})
    path=tmp_path/'open.dxf';doc.saveas(path);model=reconstruct_architecture(path)
    assert len(model['physical_spaces'])==1
    assert len(model['functional_zones'])==3
    assert len(model['canonical_walls'])==4
    assert model['physical_spaces'][0]['geometry_status']=='VERIFIED'
    assert all(z['polygon'] is None for z in model['functional_zones'])
