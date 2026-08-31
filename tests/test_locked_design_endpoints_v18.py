from cad_engine.engineering_runner_v13 import _add_locked_design_endpoints


def test_locked_gas_and_architectural_exhaust_create_traceable_design_endpoints():
    arch={'rooms':[{'id':'K','type':'kitchen','plan_id':'P1','label_point':(2,2)},
                   {'id':'B','type':'bathroom','plan_id':'P1','label_point':(5,5)}]}
    rec={'detections':[]}
    out=_add_locked_design_endpoints(arch,rec,{'gas_service':True})
    assert {x['type'] for x in out['detections']} == {'stove','hood','exhaust_fan'}
    assert all('user_locked_design_basis' in x['evidence'] for x in out['detections'])


def test_gas_endpoint_is_not_invented_without_locked_gas_service():
    arch={'rooms':[{'id':'K','type':'kitchen','plan_id':'P1','label_point':(2,2)}]}
    out=_add_locked_design_endpoints(arch,{'detections':[]},{'gas_service':False})
    assert all(x['type']!='stove' for x in out['detections'])
