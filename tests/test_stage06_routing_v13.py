import unittest
from cad_engine.routing_v13 import route_topology

class Stage06RoutingTests(unittest.TestCase):
    def test_routes_are_orthogonal_and_end_at_topology_nodes(self):
        architecture={'walls':[{'start':(2500,-1000),'end':(2500,3000)}]}
        topology={'nodes':[{'id':'MEP-001','point':(1000,1000)},{'id':'SHAFT-01','point':(4500,2000)}],
                  'edges':[{'id':'SANITARY-E001','system':'sanitary','from':'MEP-001','to':'SHAFT-01'}]}
        result=route_topology(architecture,topology)
        self.assertEqual(result['version'],'geometry-routing-v13.12')
        self.assertEqual(len(result['routes']),1)
        route=result['routes'][0]
        self.assertEqual(route['points'][0],(1000,1000))
        self.assertEqual(route['points'][-1],(4500,2000))
        self.assertTrue(result['quality']['all_orthogonal'])

    def test_route_uses_real_opening_in_wall_instead_of_crossing_it(self):
        architecture={'plans':[{'plan_id':'P1','bounds':[0,0,10,10]}],
                      'walls':[{'start':(5,0),'end':(5,4)},{'start':(5,6),'end':(5,10)}]}
        topology={'nodes':[{'id':'A','point':(2,2),'plan_id':'P1'},{'id':'B','point':(8,2),'plan_id':'P1'}],
                  'edges':[{'id':'E1','system':'sanitary','from':'A','to':'B','plan_id':'P1'}]}
        result=route_topology(architecture,topology)
        self.assertEqual(result['routes'][0]['wall_crossings'],0)
        self.assertEqual(result['routes'][0]['routing'],'orthogonal_open_space_astar')
        self.assertTrue(any(y>=4 for _,y in result['routes'][0]['points']))

    def test_shaft_entry_is_coordinated_penetration_not_wall_clash(self):
        architecture={'plans':[{'plan_id':'P1','bounds':[0,0,10,10]}],
                      'walls':[{'start':(5,0),'end':(5,10)}]}
        topology={'nodes':[{'id':'A','point':(2,5),'plan_id':'P1'},
                           {'id':'S','point':(6,5),'plan_id':'P1','category':'vertical'}],
                  'edges':[{'id':'E','from':'A','to':'S','plan_id':'P1','system':'cold_water'}]}
        result=route_topology(architecture,topology)
        self.assertEqual(result['routes'][0]['wall_crossings'],0)
        self.assertEqual(result['routes'][0]['coordinated_terminal_penetrations'],1)

if __name__=='__main__': unittest.main()
