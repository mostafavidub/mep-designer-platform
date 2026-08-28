import unittest
from cad_engine.routing_v14 import route_topology

class RoutingV14Tests(unittest.TestCase):
 def test_routes_are_orthogonal_and_avoid_structural_obstacle_when_candidate_exists(self):
  arch={'units':4,'walls':[], 'obstacles':[{'points':[(450,0),(550,0),(550,700),(450,700)]}]}
  topo={'nodes':[{'id':'A','point':(0,0)},{'id':'B','point':(1000,1000)}],
        'edges':[{'id':'E1','system':'cold_water','from':'A','to':'B','role':'floor_main','endpoint_ids':['F1']}]}
  out=route_topology(arch,topo,clearance=300)
  self.assertEqual(out['version'],'geometry-routing-v14.6')
  self.assertEqual(out['quality']['routed_edges'],1)
  self.assertTrue(out['quality']['all_orthogonal'])
  self.assertEqual(out['routes'][0]['obstacle_hits'],0)
  self.assertEqual(out['quality']['unrouted_edges'],0)
  self.assertEqual(out['routes'][0]['endpoint_ids'],['F1'])

 def test_missing_node_is_reported_as_unrouted(self):
  out=route_topology({'units':4,'walls':[],'obstacles':[]},{'nodes':[{'id':'A','point':(0,0)}],'edges':[{'id':'E','system':'sanitary','from':'A','to':'MISSING'}]})
  self.assertEqual(out['quality']['unrouted_edges'],1)

if __name__=='__main__': unittest.main()
