from cad_engine.routing_v13 import _route_candidates
from cad_engine.sizing_v13 import size_networks


def test_coincident_endpoint_gets_measurable_orthogonal_connection_loop():
    candidates=_route_candidates((2,2),(2,2))
    assert all(len(points)>=4 for points in candidates)
    assert all(sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(points,points[1:]))>0 for points in candidates)
    assert all(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(points,points[1:])) for points in candidates)


def test_exhaust_and_locked_gas_endpoints_are_sized_from_design_load():
    topology={'edges':[{'id':'E1','from':'F1'},{'id':'E2','from':'G1'}]}
    routing={'routes':[{'id':'R1','edge_id':'E1','system':'exhaust'},{'id':'R2','edge_id':'E2','system':'gas'}]}
    recognition={'detections':[{'id':'F1','category':'equipment','design_load':150},{'id':'G1','category':'equipment','design_load':12}]}
    result=size_networks(topology,routing,recognition,{'rooms':[]})
    assert all(x['size_mm'] and x['downstream_load']>0 for x in result['segments'])
