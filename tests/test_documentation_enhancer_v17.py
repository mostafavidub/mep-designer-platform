import unittest, tempfile
from pathlib import Path
import ezdxf
from cad_engine.reference_parity_engine_v17 import ProjectContext
from cad_engine.documentation_enhancer_v17 import apply_documentation_enhancements

class DocumentationEnhancerV17Tests(unittest.TestCase):
    def test_enhancement_is_non_plan_and_preserves_architecture(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.dxf'; doc=ezdxf.new('R2010'); m=doc.modelspace()
            m.add_line((100,100),(110,100),dxfattribs={'layer':'WALL'})
            doc.saveas(p)
            report={'composition':{'manifest':[
                {'old_sheet':'D','code':'M-001','family':'GENERAL_DETAIL'},
                {'old_sheet':'R','code':'M-151','family':'PLUMBING_RISER'},
                {'old_sheet':'C','code':'M-152','family':'WATER_SERVICE_CALC'},
                {'old_sheet':'N','code':'M-003','family':'GENERAL_NOTES'},
            ],'boards':{
                'D':{'bounds':[0,0,21,29.7]},'R':{'bounds':[24,0,45,29.7]},
                'C':{'bounds':[48,0,69,29.7]},'N':{'bounds':[72,0,93,29.7]},
            }}}
            ctx=ProjectContext(project_id='X',levels=['GROUND','L1'],active_systems=['WATER','HEATING','SPLIT_AC'],routes=[
                {'system':'WATER','level':'GROUND'},{'system':'WATER','level':'L1'},
                {'system':'HEATING','level':'GROUND'},{'system':'HEATING','level':'L1'}])
            out=apply_documentation_enhancements(p,report,ctx)
            self.assertEqual(out['status'],'PASS'); self.assertEqual(len(out['written']),4); self.assertTrue(out['exact_file_reopened'])
            reopened=ezdxf.readfile(p); walls=[e for e in reopened.modelspace() if e.dxf.layer=='WALL']
            self.assertEqual(len(walls),1); self.assertGreater(out['generated_entity_count'],4)

if __name__=='__main__': unittest.main()
