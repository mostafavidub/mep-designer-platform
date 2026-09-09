from cad_engine.annotation_solver import solve_annotations


def config(auto=True):
    return {'minimum_text_height_mm':2.5,'clearance_model_units':5,
            'candidate_offsets':[[10,10],[-40,10],[10,-20]],'auto_enlarge':auto,
            'enlarged_scale':'1:20','enlarged_padding_model_units':20}


def plan(obstacles=None):
    return {'plan_id':'M-101','bounds':[0,0,500,300],'print_scale':10,'obstacles':obstacles or []}


def test_priority_solver_places_readable_leaders_without_collision():
    requests=[{'id':'A','text':'SAN DN110','target':[100,100],'priority':10,'source_id':'E1'},
              {'id':'B','text':'VENT DN50','target':[300,100],'priority':5,'source_id':'E2'}]
    result=solve_annotations(plan(),requests,config())
    assert result['status']=='PASS',result
    assert result['quality']['collisions']==0
    assert result['quality']['unreadable']==0
    assert all(row['plotted_text_height_mm']>=2.5 and row['leader'] for row in result['annotations'])


def test_dense_wet_core_creates_identity_bound_enlarged_plan():
    requests=[{'id':f'A{i}','text':'LONG ANNOTATION DN110','target':[100,100],'priority':10-i,'source_id':f'E{i}'} for i in range(4)]
    blocked=[[0,0,500,300]]
    result=solve_annotations(plan(blocked),requests,config(True))
    assert result['status']=='PASS',result
    assert result['quality']['automatic_enlarged_plans']==1
    view=result['enlarged_plans'][0]
    assert view['source_plan_id']=='M-101'
    assert view['bounds'] and view['scale']=='1:20'


def test_unplaceable_annotation_without_enlargement_fails_closed():
    request=[{'id':'A','text':'SAN DN110','target':[100,100],'priority':1,'source_id':'E1'}]
    result=solve_annotations(plan([[0,0,500,300]]),request,config(False))
    assert result['status']=='FAIL'
    assert result['quality']['unreadable']==1
    assert result['errors']==['UNREADABLE_ANNOTATION:A']
