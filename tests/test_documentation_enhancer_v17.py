import unittest, tempfile
from pathlib import Path
import ezdxf
from cad_engine.reference_parity_engine_v17 import ProjectContext
from cad_engine.documentation_enhancer_v17 import apply_documentation_enhancements, DETAIL_LAYER

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
            self.assertEqual(out['riser_integrity']['status'],'PASS')
            self.assertEqual(out['detail_materialization']['status'],'PASS')
            reopened=ezdxf.readfile(p); walls=[e for e in reopened.modelspace() if e.dxf.layer=='WALL']
            self.assertEqual(len(walls),1); self.assertGreater(out['generated_entity_count'],4)

    def test_zero_branch_riser_fails_closed_before_dxf_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.dxf'; doc=ezdxf.new('R2010'); doc.modelspace().add_line((0,0),(1,0),dxfattribs={'layer':'WALL'}); doc.saveas(p)
            before=p.read_bytes()
            report={'composition':{'manifest':[{'old_sheet':'R','code':'M-151','family':'PLUMBING_RISER'}],
                                   'boards':{'R':{'bounds':[0,0,21,29.7]}}}}
            ctx=ProjectContext(project_id='X',levels=['GROUND','L1'],active_systems=['WATER'],routes=[])
            out=apply_documentation_enhancements(p,report,ctx)
            self.assertEqual(out['status'],'INPUT_REQUIRED')
            self.assertFalse(out['exact_file_reopened'])
            self.assertIn('CW1/HW1:WATER',out['riser_integrity']['zero_branch_risers'])
            self.assertIn('PLAN_BRANCH:CW1/HW1:WATER',out['riser_integrity']['missing_inputs'])
            self.assertEqual(before,p.read_bytes())

    def test_step7_every_registered_detail_has_exact_geometry_and_tags(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'details.dxf'; ezdxf.new('R2010').saveas(p)
            report={'composition':{'manifest':[
                {'old_sheet':'D','code':'M-006','family':'GENERAL_DETAIL','title_fa':'HVAC PROJECT-APPLICABLE DETAILS'},
            ],'boards':{'D':{'bounds':[0,0,21,29.7],'plan_area':[1,1,20,28]}}}}
            ctx=ProjectContext(project_id='DETAILS',levels=['GROUND'],active_systems=['SPLIT_AC','EXHAUST'],routes=[])
            out=apply_documentation_enhancements(p,report,ctx)
            self.assertEqual(out['status'],'PASS',out)
            qa=out['detail_materialization']; self.assertEqual(qa['status'],'PASS',qa)
            self.assertEqual(qa['expected_count'],5); self.assertEqual(qa['materialized_count'],5)
            doc=ezdxf.readfile(p); detail_entities=[e for e in doc.modelspace() if str(e.dxf.layer).upper()==DETAIL_LAYER]
            geometry=sum(e.dxftype() not in {'TEXT','MTEXT'} for e in detail_entities)
            self.assertGreaterEqual(geometry,60)
            texts=[]
            for e in detail_entities:
                if e.dxftype()=='TEXT': texts.append(str(e.dxf.text or ''))
                elif e.dxftype()=='MTEXT': texts.append(str(e.plain_text() or ''))
            joined='\n'.join(texts).upper()
            for detail in out['documentation_package']['details']['selected_details']:
                detail_id=detail.split(' ',1)[0].upper()
                self.assertGreaterEqual(sum(detail_id in text.upper() for text in texts),2,detail_id)
            self.assertIn('VERIFY FINAL PROJECT / MANUFACTURER VALUES',joined)

    def test_step7_materializes_all_details_without_register_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'all-details.dxf'; ezdxf.new('R2010').saveas(p)
            report={'composition':{'manifest':[
                {'old_sheet':'DP','code':'M-004','family':'GENERAL_DETAIL','title_fa':'PLUMBING PROJECT-APPLICABLE DETAILS'},
                {'old_sheet':'DH','code':'M-005','family':'GENERAL_DETAIL','title_fa':'HVAC PROJECT-APPLICABLE DETAILS'},
                {'old_sheet':'DG','code':'M-006','family':'GENERAL_DETAIL','title_fa':'GAS PROJECT-APPLICABLE DETAILS'},
                {'old_sheet':'R','code':'M-151','family':'PLUMBING_RISER'},
            ],'boards':{
                'DP':{'bounds':[0,0,21,29.7],'plan_area':[1,1,20,28]},
                'DH':{'bounds':[30,0,51,29.7],'plan_area':[31,1,50,28]},
                'DG':{'bounds':[60,0,81,29.7],'plan_area':[61,1,80,28]},
                'R':{'bounds':[90,0,111,29.7]},
            }}}
            # `storm` is an explicit RAINWATER alias and avoids the legacy
            # substring ambiguity of the literal RAINWATER token in this v17 helper.
            active=['SANITARY_VENT','WATER','HEATING','GAS','SPLIT_AC','EXHAUST','storm']
            routes=[{'system':system,'level':'GROUND'} for system in ['SANITARY_VENT','WATER','HEATING','GAS']]
            ctx=ProjectContext(project_id='ALL',levels=['GROUND'],active_systems=active,routes=routes)
            out=apply_documentation_enhancements(p,report,ctx)
            self.assertEqual(out['status'],'PASS',out)
            selected=out['documentation_package']['details']['selected_details']
            self.assertEqual(len(selected),20)
            qa=out['detail_materialization']; self.assertEqual(qa['status'],'PASS',qa)
            self.assertEqual(qa['expected_count'],20); self.assertEqual(qa['materialized_count'],20)
            doc=ezdxf.readfile(p); all_text=[]
            for e in doc.modelspace():
                if e.dxftype()=='TEXT': all_text.append(str(e.dxf.text or ''))
                elif e.dxftype()=='MTEXT': all_text.append(str(e.plain_text() or ''))
            whole='\n'.join(all_text).upper()
            self.assertIn('PROJECT-SPECIFIC DETAIL REGISTER',whole)
            for detail in selected:
                detail_id=detail.split(' ',1)[0].upper()
                self.assertGreaterEqual(whole.count(detail_id),3,detail_id)

    def test_step7_empty_detail_selection_fails_before_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'empty.dxf'; doc=ezdxf.new('R2010'); doc.modelspace().add_line((0,0),(1,0),dxfattribs={'layer':'WALL'}); doc.saveas(p)
            before=p.read_bytes()
            report={'composition':{'manifest':[{'old_sheet':'D','code':'M-004','family':'GENERAL_DETAIL','title_fa':'PLUMBING PROJECT-APPLICABLE DETAILS'}],
                                   'boards':{'D':{'bounds':[0,0,21,29.7],'plan_area':[1,1,20,28]}}}}
            out=apply_documentation_enhancements(p,report,ProjectContext(project_id='EMPTY',active_systems=[]))
            self.assertEqual(out['status'],'INPUT_REQUIRED')
            self.assertEqual(out['detail_materialization']['status'],'INPUT_REQUIRED')
            self.assertFalse(out['exact_file_reopened'])
            self.assertEqual(before,p.read_bytes())

if __name__=='__main__': unittest.main()