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

if __name__=='__main__': unittest.main()
