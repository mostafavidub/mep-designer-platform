from cad_engine.routing_v13 import _open_space_route,route_topology
from cad_engine.mechanical_network_topology import _orthogonal_path
from cad_engine.routing import route_topology as route_canonical_topology

def test_astar_is_bounded_for_oversized_export_frame():
    route=_open_space_route((10.0,10.0),(14.0,14.0),(-5000.0,-5000.0,5000.0,5000.0),[])
    assert route[0]==(10.0,10.0)
    assert route[-1]==(14.0,14.0)
    assert len(route)<=4

def test_bounded_astar_retains_passage_around_wall_endpoint():
    walls=[{'start':(12.0,9.0),'end':(12.0,13.0)}]
    route=_open_space_route((10.0,10.0),(14.0,10.0),(-5000.0,-5000.0,5000.0,5000.0),walls)
    assert route[0]==(10.0,10.0)
    assert route[-1]==(14.0,10.0)
    assert route!=[(10.0,10.0),(14.0,10.0)]

def test_single_terminal_shaft_penetration_is_coordinated_not_a_wall_clash():
    architecture={'plans':[{'plan_id':'P1','bounds':(0,0,20,20)}],
                  'walls':[{'start':(9,0),'end':(9,20)}]}
    topology={'nodes':[{'id':'F','point':(5,10),'plan_id':'P1','category':'fixture'},
                       {'id':'S','point':(10,10),'plan_id':'P1','category':'vertical'}],
              'edges':[{'id':'E1','from':'F','to':'S','system':'sanitary','plan_id':'P1'}]}
    routed=route_topology(architecture,topology)
    assert routed['quality']['wall_crossings']==0
    assert routed['quality']['coordinated_terminal_penetrations']==1


def test_authoritative_topology_routes_around_wall_endpoint():
    walls = [{'start': (12.0, 9.0), 'end': (12.0, 13.0)}]

    route, metadata = _orthogonal_path((10.0, 10.0), (14.0, 10.0), walls, [])

    assert route[0] == (10.0, 10.0)
    assert route[-1] == (14.0, 10.0)
    assert len(route) > 2
    assert metadata == {'wall_crossings': 0, 'routing': 'ORTHOGONAL_OPEN_SPACE_ASTAR'}


def test_authoritative_topology_records_one_terminal_sleeve_without_waiving_middle_crossings():
    walls = [
        {'start': (9.0, 9.0), 'end': (11.0, 9.0)},
        {'start': (11.0, 9.0), 'end': (11.0, 11.0)},
        {'start': (11.0, 11.0), 'end': (9.0, 11.0)},
        {'start': (9.0, 11.0), 'end': (9.0, 9.0)},
    ]

    route, metadata = _orthogonal_path((10.0, 10.0), (14.0, 10.0), walls, [])

    assert route == [(10.0, 10.0), (14.0, 10.0)]
    assert metadata['wall_crossings'] == 0
    assert metadata['coordinated_terminal_penetrations'] == 1
    assert metadata['routing'] == 'ORTHOGONAL_WITH_TERMINAL_SLEEVES'


def test_canonical_router_coordinates_both_endpoint_sleeves_without_waiving_middle_walls():
    architecture = {
        'plans': [{'plan_id': 'P1', 'bounds': (0, 0, 20, 20)}],
        'walls': [
            {'start': (4, 9), 'end': (6, 9)}, {'start': (6, 9), 'end': (6, 11)},
            {'start': (6, 11), 'end': (4, 11)}, {'start': (4, 11), 'end': (4, 9)},
            {'start': (10, 8), 'end': (10, 12)},
            {'start': (14, 9), 'end': (16, 9)}, {'start': (16, 9), 'end': (16, 11)},
            {'start': (16, 11), 'end': (14, 11)}, {'start': (14, 11), 'end': (14, 9)},
        ],
    }
    topology = {
        'nodes': [
            {'id': 'F', 'point': (5, 10), 'plan_id': 'P1'},
            {'id': 'S', 'point': (15, 10), 'plan_id': 'P1'},
        ],
        'edges': [{'id': 'E1', 'from': 'F', 'to': 'S', 'system': 'sanitary', 'plan_id': 'P1'}],
    }
    routed = route_canonical_topology(architecture, topology)
    route = routed['routes'][0]
    assert route['wall_crossings'] == 0
    assert route['coordinated_terminal_penetrations'] == 2
    assert route['routing'] == 'orthogonal_open_space_astar'
