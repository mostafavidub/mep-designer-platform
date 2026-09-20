import ezdxf

from app.unit_sanity import _aggregate_unit_inference, _infer_scale


def _unknown_unit_doc(*, complete_evidence=True):
    doc=ezdxf.new('R2013');doc.header['$INSUNITS']=0;msp=doc.modelspace()
    msp.add_lwpolyline([(0,0),(21,0),(21,29.7),(0,29.7)],close=True)
    msp.add_text('SC:1/100',dxfattribs={'insert':(1,1),'height':.2})
    values=['0.75','1.00','1.20','2.20'] if complete_evidence else ['2.20']
    for index,value in enumerate(values):
        msp.add_text(value,dxfattribs={'insert':(2+index,2),'height':.2})
    return doc


def test_unknown_unit_requires_three_agreeing_architectural_evidence_families():
    result=_infer_scale(_unknown_unit_doc())
    assert result['effective_scale_to_m']==1.0
    assert result['confidence']=='high'
    assert result['source']=='multi-evidence-paper-frame-scale-and-architectural-dimensions'
    assert result['paper_space_metre_evidence']['status']=='PASS'


def test_scale_label_and_frame_alone_do_not_create_an_engineering_unit():
    result=_infer_scale(_unknown_unit_doc(complete_evidence=False))
    assert result['effective_scale_to_m'] is None
    assert result['confidence']=='low'
    assert result['paper_space_metre_evidence']['status']=='INSUFFICIENT_EVIDENCE'


def test_project_unit_is_published_only_when_every_file_agrees():
    result=_aggregate_unit_inference({'files':[
        {'file':'a.dxf','effective_unit_to_m':1.0,'unit_inference':{'confidence':'high'}},
        {'file':'b.dxf','effective_unit_to_m':1.0,'unit_inference':{'confidence':'medium'}},
    ]})
    assert result['status']=='PASS'
    assert result['effective_scale_to_m']==1.0


def test_conflicting_file_units_remain_input_required():
    result=_aggregate_unit_inference({'files':[
        {'file':'a.dxf','effective_unit_to_m':1.0,'unit_inference':{'confidence':'high'}},
        {'file':'b.dxf','effective_unit_to_m':.001,'unit_inference':{'confidence':'high'}},
    ]})
    assert result['status']=='INPUT_REQUIRED'
    assert result['effective_scale_to_m'] is None
    assert result['errors']==['CONFLICTING_ARCHITECTURAL_FILE_UNITS']
