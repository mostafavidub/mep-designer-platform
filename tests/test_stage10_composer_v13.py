import os
import shutil
import tempfile
import unittest
import ezdxf

from cad_engine.engineering_runner_v13 import run_engineering_pipeline, validate_pipeline
from cad_engine.sheet_composer_v13 import compose_engineering_content, validate_composed_dxf

class Stage10ComposerTests(unittest.TestCase):
    def _fixture(self):
        fd,path=tempfile.mkstemp(suffix='.dxf'); os.close(fd)
        doc=ezdxf.new('R2013'); doc.header['$INSUNITS']=4
        for layer in ('WALL','SHAFT','FIXTURE'): doc.layers.add(layer)
        basin=doc.blocks.new('Rooshooee'); basin.add_circle((0,0),100)
        msp=doc.modelspace()
        msp.add_lwpolyline([(0,0),(5000,0),(5000,4000),(0,4000)],close=True,dxfattribs={'layer':'WALL'})
        msp.add_line((0,0),(5000,0),dxfattribs={'layer':'WALL'})
        msp.add_text('BATHROOM',dxfattribs={'insert':(2200,2000),'height':200})
        msp.add_lwpolyline([(4200,500),(4800,500),(4800,1500),(4200,1500)],close=True,dxfattribs={'layer':'SHAFT'})
        msp.add_blockref('Rooshooee',(1000,1000),dxfattribs={'layer':'FIXTURE'})
        doc.saveas(path); return path

    def test_full_pipeline_creates_real_routed_annotated_content_over_architecture(self):
        src=self._fixture(); dst=src+'.out.dxf'; shutil.copyfile(src,dst)
        try:
            pipeline=run_engineering_pipeline(src,project_overrides={'levels':['Ground','Roof']})
            pipeline_qa=validate_pipeline(pipeline)
            self.assertEqual(pipeline_qa['status'],'PASS',pipeline_qa)
            composition=compose_engineering_content(dst,pipeline)
            cad_qa=validate_composed_dxf(dst,pipeline,composition)
            self.assertEqual(cad_qa['status'],'PASS',cad_qa)
            doc=ezdxf.readfile(dst); msp=doc.modelspace()
            self.assertTrue(any(str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-SANITARY') for e in msp))
            self.assertTrue(any(str(getattr(e.dxf,'layer',''))=='ENGITOOLS-M-ANNOTATION' for e in msp))
            # Architectural underlay remains in the composed drawing.
            self.assertTrue(any(str(getattr(e.dxf,'layer',''))=='WALL' for e in msp))
        finally:
            for p in (src,dst):
                if os.path.exists(p): os.remove(p)

if __name__=='__main__': unittest.main()
