import os,tempfile,unittest
import ezdxf
from cad_engine.architecture_reconstruction_v14 import reconstruct_architecture
from cad_engine.fixture_recognition_v14 import recognize_fixtures_equipment

class FixtureRecognitionV14Tests(unittest.TestCase):
 def test_installed_objects_get_rooms_ports_and_legend_objects_stay_candidates(self):
  fd,path=tempfile.mkstemp(suffix='.dxf'); os.close(fd)
  try:
   doc=ezdxf.new('R2013')
   for l in ('WALL','FIXTURE','EQUIP'): doc.layers.add(l)
   b=doc.blocks.new('Rooshooee'); b.add_circle((0,0),100)
   f=doc.blocks.new('EXH_FAN'); f.add_circle((0,0),100)
   m=doc.modelspace(); m.add_lwpolyline([(0,0),(5000,0),(5000,4000),(0,4000)],close=True,dxfattribs={'layer':'WALL'})
   m.add_text('BATHROOM',dxfattribs={'insert':(2500,2000),'height':120})
   m.add_blockref('Rooshooee',(1000,1000),dxfattribs={'layer':'FIXTURE'})
   m.add_blockref('EXH_FAN',(3500,1000),dxfattribs={'layer':'EQUIP'})
   m.add_blockref('Rooshooee',(9000,9000),dxfattribs={'layer':'FIXTURE'})
   doc.saveas(path)
   arch=reconstruct_architecture(path); r=recognize_fixtures_equipment(arch)
   self.assertEqual(r['version'],'fixture-equipment-recognition-v14.2')
   self.assertEqual(r['quality']['installed_detected'],2)
   self.assertEqual(r['quality']['unassigned_candidates'],1)
   basin=next(x for x in r['detections'] if x['type']=='basin')
   self.assertEqual(basin['room_type'],'bathroom')
   self.assertTrue({'cold_water','hot_water','sanitary','vent'}.issubset(basin['ports']))
   fan=next(x for x in r['detections'] if x['type']=='exhaust_fan')
   self.assertEqual(fan['ports'],['exhaust'])
   self.assertTrue(all(x['installed'] for x in r['detections']))
  finally:
   if os.path.exists(path): os.remove(path)
if __name__=='__main__': unittest.main()
