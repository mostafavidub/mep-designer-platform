from cad_engine.topology_v13 import build_system_topology
from cad_engine.routing_v13 import route_topology


def _plan_arch(room_point=(5,5), shafts=None):
    return {'plans':[{'plan_id':'P1','bounds':[0,0,10,10]}],
            'primary_floor_plan_ids':['P1'],'bounds':[0,0,10,10],
            'shafts':list(shafts or []),
            'rooms':[{'id':'R1','plan_id':'P1','type':'bathroom','label_point':room_point}]}


def _wc(point):
    return {'detections':[{'id':'WC1','category':'fixture','type':'wc','point':point,'room_id':'R1','plan_id':'P1'}]}


def test_unapproved_proposed_vertical_core_is_input_required_not_routable():
    topology=build_system_topology(_plan_arch(),_wc((3,3)),{'project_systems':['sanitary']},{})
    assert topology['edges'] == []
    assert topology['unresolved'][0]['status'] == 'INPUT_REQUIRED'
    assert topology['unresolved'][0]['reason'] == 'UNAPPROVED_LOCAL_SHAFT'
    assert topology['quality']['unresolved_reasons']['UNAPPROVED_LOCAL_SHAFT'] == 1


def test_approved_distinct_vertical_core_creates_real_route():
    topology=build_system_topology(
        _plan_arch(),_wc((3,3)),{'project_systems':['sanitary']},{},
        {'mechanical_shaft_route':'propose_near_wet_core'},
    )
    assert len(topology['edges']) == 1
    routed=route_topology(_plan_arch(),topology)
    assert not routed['rejected']
    assert len(routed['routes']) == 1
    assert routed['routes'][0]['length'] > 0
    assert routed['routes'][0]['points'][0] != routed['routes'][0]['points'][-1]


def test_approved_but_coincident_representative_points_fail_closed():
    topology=build_system_topology(
        _plan_arch(),_wc((5,5)),{'project_systems':['sanitary']},{},
        {'mechanical_shaft_route':'propose_near_wet_core'},
    )
    assert topology['edges'] == []
    assert topology['unresolved'][0]['reason'] == 'DEGENERATE_LOCAL_CONNECTION'
    assert topology['unresolved'][0]['status'] == 'INPUT_REQUIRED'


def test_invalid_endpoint_point_becomes_input_required_instead_of_crashing():
    arch=_plan_arch(shafts=[{'point':(8,8),'plan_id':'P1'}])
    topology=build_system_topology(arch,_wc(None),{'project_systems':['sanitary']},{})
    assert topology['edges'] == []
    assert topology['unresolved'][0]['reason'] == 'INVALID_ENDPOINT_POINT'


def test_router_defense_rejects_manual_edge_to_unapproved_core():
    arch={'plans':[{'plan_id':'P1','bounds':[0,0,10,10]}]}
    topology={'nodes':[{'id':'A','point':(2,2),'plan_id':'P1'},
                       {'id':'S','point':(8,8),'plan_id':'P1','category':'vertical','provisional':True,'proposal_approved':False}],
              'edges':[{'id':'E1','from':'A','to':'S','system':'sanitary','plan_id':'P1'}]}
    result=route_topology(arch,topology)
    assert result['routes'] == []
    assert result['rejected'][0]['reason'] == 'UNAPPROVED_VERTICAL_CORE'


def test_real_architectural_shaft_remains_backward_compatible():
    arch=_plan_arch(shafts=[{'point':(8,8),'plan_id':'P1','source':'geometry'}])
    topology=build_system_topology(arch,_wc((2,2)),{'project_systems':['sanitary']},{})
    assert len(topology['edges']) == 1
    routed=route_topology(arch,topology)
    assert len(routed['routes']) == 1
    assert routed['quality']['rejected_edges'] == 0
