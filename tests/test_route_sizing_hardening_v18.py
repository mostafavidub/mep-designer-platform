from cad_engine.routing_v13 import _route_candidates, route_topology
from cad_engine.sizing_v13 import size_networks


def test_coincident_endpoint_is_rejected_instead_of_fabricating_connection_loop():
    assert _route_candidates((2,2),(2,2)) == ()
    architecture={'plans':[{'plan_id':'P1','bounds':[0,0,10,10]}]}
    topology={'nodes':[{'id':'A','point':(2,2),'plan_id':'P1'},
                       {'id':'S','point':(2,2),'plan_id':'P1','category':'vertical'}],
              'edges':[{'id':'E1','from':'A','to':'S','plan_id':'P1','system':'sanitary'}]}
    result=route_topology(architecture,topology)
    assert result['routes'] == []
    assert result['rejected'] == [{'edge_id':'E1','reason':'DEGENERATE_TOPOLOGY_SPAN'}]


def test_exhaust_and_locked_gas_endpoints_are_sized_from_design_load():
    topology={'edges':[{'id':'E1','from':'F1'},{'id':'E2','from':'G1'}]}
    routing={'routes':[{'id':'R1','edge_id':'E1','system':'exhaust'},{'id':'R2','edge_id':'E2','system':'gas'}]}
    recognition={'detections':[{'id':'F1','category':'equipment','design_load':150},{'id':'G1','category':'equipment','design_load':12}]}
    result=size_networks(topology,routing,recognition,{'rooms':[]})
    assert all(x['size_mm'] and x['downstream_load']>0 for x in result['segments'])
