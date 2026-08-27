import os
import shutil
import tempfile
import unittest
import ezdxf

from cad_engine.production_engineering_v13 import apply_engineering_pipeline_v13


class Stage10ProductionHookTests(unittest.TestCase):
    def test_production_hook_composes_only_after_pipeline_pass(self):
        fd,src=tempfile.mkstemp(suffix='.dxf'); os.close(fd); dst=src+'.dst.dxf'
        doc=ezdxf.new('R2013'); doc.header['$INSUNITS']=4
        for layer in ('WALL','SHAFT','FIXTURE'): doc.layers.add(layer)
        basin=doc.blocks.new('Rooshooee'); basin.add_circle((0,0),100)
        msp=doc.modelspace()
        msp.add_lwpolyline([(0,0),(5000,0),(5000,4000),(0,4000)],close=True,dxfattribs={'layer':'WALL'})
        msp.add_line((0,0),(5000,0),dxfattribs={'layer':'WALL'})
        msp.add_text('BATHROOM',dxfattribs={'insert':(2200,2000),'height':200})
        msp.add_lwpolyline([(4200,500),(4800,500),(4800,1500),(4200,1500)],close=True,dxfattribs={'layer':'SHAFT'})
        msp.add_blockref('Rooshooee',(1000,1000),dxfattribs={'layer':'FIXTURE'})
        doc.saveas(src); shutil.copyfile(src,dst)
        try:
            result=apply_engineering_pipeline_v13(src,dst,{'_engineering_project_overrides':{'levels':['Ground','Roof']}})
            self.assertEqual(result['status'],'PASS',result)
            self.assertEqual(result['pipeline_qa']['status'],'PASS')
            self.assertEqual(result['cad_qa']['status'],'PASS')
            out=ezdxf.readfile(dst)
            self.assertTrue(any(str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-') for e in out.modelspace()))
        finally:
            for p in (src,dst):
                if os.path.exists(p): os.remove(p)


if __name__=='__main__': unittest.main()
