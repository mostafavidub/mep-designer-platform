import os, shutil, tempfile, unittest
import ezdxf
from cad_engine.engineering_runner_v14 import run_engineering_pipeline, validate_pipeline
from cad_engine.sheet_composer_v14 import compose_engineering_content, validate_composed_dxf

class EngineeringPipelineV14E2E(unittest.TestCase):
 def _fixture(self):
  fd,src=tempfile.mkstemp(suffix='.dxf'); os.close(fd)
  fd,dst=tempfile.mkstemp(suffix='.dxf'); os.close(fd)
  doc=ezdxf.new('R2013'); doc.header['$INSUNITS']=4
  for l in ('WALL','SHAFT','FIXTURE'): doc.layers.add(l)
  basin=doc.blocks.new('Rooshooee'); basin.add_circle((0,0),100)
  fdblk=doc.blocks.new('FLOOR_DRAIN'); fdblk.add_circle((0,0),80)
  m=doc.modelspace()
  m.add_lwpolyline([(0,0),(6000,0),(6000,4500),(0,4500)],close=True,dxfattribs={'layer':'WALL'})
  m.add_line((0,0),(6000,0),dxfattribs={'layer':'WALL'})
  m.add_text('BATHROOM',dxfattribs={'insert':(2500,2000),'height':150})
  m.add_lwpolyline([(5000,700),(5600,700),(5600,1500),(5000,1500)],close=True,dxfattribs={'layer':'SHAFT'})
  m.add_blockref('Rooshooee',(1200,1600),dxfattribs={'layer':'FIXTURE'})
  m.add_blockref('FLOOR_DRAIN',(2200,1200),dxfattribs={'layer':'FIXTURE'})
  doc.saveas(src); shutil.copyfile(src,dst); return src,dst

 def test_full_pipeline_produces_architecture_based_routes_not_schematic_only_zones(self):
  src,dst=self._fixture()
  try:
   pipeline=run_engineering_pipeline(src,project_overrides={'levels':['GROUND']})
   qa=validate_pipeline(pipeline)
   self.assertEqual(qa['status'],'PASS',qa)
   self.assertGreater(qa['metrics']['routes'],0)
   self.assertEqual(qa['metrics']['routes'],qa['metrics']['sized_routes'])
   self.assertGreaterEqual(qa['metrics']['route_labels'],qa['metrics']['routes'])
   comp=compose_engineering_content(dst,pipeline)
   cadqa=validate_composed_dxf(dst,pipeline,comp)
   self.assertEqual(cadqa['status'],'PASS',cadqa)
   self.assertGreater(cadqa['metrics']['architectural_underlay_entities'],0)
   self.assertGreater(cadqa['metrics']['fixture_equipment_entities'],0)
   self.assertEqual(cadqa['metrics']['drawn_routes'],cadqa['metrics']['expected_routes'])
   doc=ezdxf.readfile(dst); m=doc.modelspace()
   underlay=[e for e in m if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-A-')]
   mech_routes=[e for e in m if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-') and e.dxftype()=='LWPOLYLINE']
   self.assertTrue(underlay); self.assertTrue(mech_routes)
   # At least one actual system route must lie inside the real architectural plan extents.
   inside=False
   for e in mech_routes:
    pts=[(x,y) for x,y,*_ in e.get_points()]
    if pts and all(-1<=x<=6001 and -1<=y<=4501 for x,y in pts): inside=True; break
   self.assertTrue(inside,'No mechanical route was composed on the architectural plan coordinates')
  finally:
   for p in (src,dst):
    if os.path.exists(p): os.remove(p)

if __name__=='__main__': unittest.main()
