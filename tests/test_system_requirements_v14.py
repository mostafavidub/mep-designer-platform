import unittest
from cad_engine.system_requirements_v14 import derive_system_requirements

class SystemRequirementsV14Tests(unittest.TestCase):
 def test_base_services_are_required_and_hvac_gas_stay_conditional_without_equipment(self):
  arch={'rooms':[{'id':'R1','type':'kitchen'},{'id':'R2','type':'bedroom'}]}
  rec={'detections':[{'id':'E1','room_id':'R1','category':'equipment','type':'stove'}]}
  out=derive_system_requirements(arch,rec)
  self.assertEqual(out['version'],'system-requirements-v14.3')
  kitchen=next(x for x in out['rooms'] if x['room_id']=='R1')
  bedroom=next(x for x in out['rooms'] if x['room_id']=='R2')
  self.assertTrue({'cold_water','hot_water','sanitary','vent','exhaust','gas'}.issubset(kitchen['required']))
  self.assertIn('cooling',kitchen['conditional'])
  self.assertIn('heating',bedroom['conditional'])
  self.assertNotIn('cooling',out['project_systems'])
  self.assertIn('gas',out['project_systems'])
  self.assertGreater(out['quality']['unresolved_conditionals'],0)

 def test_project_options_can_resolve_or_disable_scope(self):
  arch={'rooms':[{'id':'R1','type':'bedroom'}]}; rec={'detections':[]}
  out=derive_system_requirements(arch,rec,{'required_systems':['cooling'],'disabled_systems':['heating']})
  row=out['rooms'][0]
  self.assertIn('cooling',row['required']); self.assertNotIn('heating',row['conditional'])

if __name__=='__main__': unittest.main()
