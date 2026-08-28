import os,tempfile,unittest
import ezdxf
from cad_engine.plan_segmentation_v13 import detect_print_plans
from cad_engine.project_hvac_v13 import design_project_hvac

class DrawingTypeAndHVACTests(unittest.TestCase):
    def test_only_canonical_arch_floor_is_primary(self):
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,'frames.dxf');doc=ezdxf.new('R2013');doc.layers.add('suport');msp=doc.modelspace()
            titles=[('پلان معماری طبقه همکف',None),('پلان معماری طبقه همکف','Arc - 02'),('پلان مبلمان طبقه همکف','Arc - 05'),('برش A-A','Arc - 08')]
            for i,(title,arc) in enumerate(titles):
                x=i*25.0;msp.add_lwpolyline([(x,0),(x+21,0),(x+21,29.7),(x,29.7)],close=True,dxfattribs={'layer':'suport'})
                msp.add_text(title,dxfattribs={'height':0.2}).dxf.insert=(x+2,20)
                if arc:msp.add_text(arc,dxfattribs={'height':0.2}).dxf.insert=(x+2,1)
            doc.saveas(path);plans=detect_print_plans(path)
            primary=[p for p in plans if p.get('mechanical_role')=='PRIMARY_FLOOR']
            self.assertEqual(len(primary),1);self.assertEqual(primary[0].get('arc_sheet'),'Arc - 02')
            self.assertEqual([p['drawing_type'] for p in plans],['ARCH_FLOOR_PLAN','ARCH_FLOOR_PLAN','FURNITURE_PLAN','SECTION'])

    def test_split_package_hvac_never_routes_to_excluded_frame(self):
        arch={'plans':[{'plan_id':'P1','bounds':[0,0,21,29.7],'level':'GROUND','mechanical_role':'PRIMARY_FLOOR'},
                       {'plan_id':'P2','bounds':[25,0,46,29.7],'level':'GROUND','mechanical_role':'FURNITURE_PLAN'}],
              'rooms':[{'id':'R1','plan_id':'P1','type':'kitchen','label_point':(5,10)},
                       {'id':'R2','plan_id':'P1','type':'living','label_point':(8,15)},
                       {'id':'R3','plan_id':'P1','type':'bedroom','label_point':(10,20)},
                       {'id':'X1','plan_id':'P2','type':'living','label_point':(30,15)}]}
        result=design_project_hvac(arch,{'hvac':{'cooling':'split_ac','heating':'package_radiator','city':'Gonbad Kavus'}})
        self.assertEqual(result['status'],'PASS');self.assertTrue(result['routes']);self.assertTrue(result['equipment'])
        self.assertTrue(all(r['plan_id']=='P1' for r in result['routes']))
        self.assertTrue(all(e['plan_id']=='P1' for e in result['equipment']))
        self.assertEqual(result['quality']['cross_plan_routes'],0);self.assertEqual(result['quality']['out_of_bounds'],0)

if __name__=='__main__':unittest.main()
