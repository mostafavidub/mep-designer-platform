import os, tempfile, unittest
import ezdxf
from cad_engine.architecture_reconstruction_v14 import reconstruct_architecture

class ArchitectureReconstructionV14Tests(unittest.TestCase):
    def test_preserves_underlay_rooms_shafts_wet_cores_and_obstacles(self):
        fd,path=tempfile.mkstemp(suffix='.dxf'); os.close(fd)
        try:
            doc=ezdxf.new('R2013'); doc.header['$INSUNITS']=4
            for name in ('WALL','SHAFT','COLUMN','DOOR'): doc.layers.add(name)
            door=doc.blocks.new('DOOR'); door.add_line((0,0),(900,0))
            msp=doc.modelspace()
            msp.add_lwpolyline([(0,0),(5000,0),(5000,4000),(0,4000)],close=True,dxfattribs={'layer':'WALL'})
            msp.add_text('BATHROOM',dxfattribs={'insert':(2000,2000),'height':150})
            msp.add_text('GROUND FLOOR',dxfattribs={'insert':(500,4500),'height':180})
            msp.add_lwpolyline([(4200,700),(4800,700),(4800,1500),(4200,1500)],close=True,dxfattribs={'layer':'SHAFT'})
            msp.add_lwpolyline([(3000,1000),(3300,1000),(3300,1300),(3000,1300)],close=True,dxfattribs={'layer':'COLUMN'})
            msp.add_line((0,0),(5000,0),dxfattribs={'layer':'WALL'})
            msp.add_blockref('DOOR',(1000,0),dxfattribs={'layer':'DOOR'})
            doc.saveas(path)
            model=reconstruct_architecture(path)
            self.assertEqual(model['version'],'architecture-reconstruction-v14.1')
            self.assertEqual(model['units'],4)
            self.assertEqual(model['quality']['room_count'],1)
            self.assertEqual(model['quality']['rooms_with_polygon'],1)
            self.assertEqual(model['quality']['shaft_count'],1)
            self.assertEqual(model['quality']['wet_core_count'],1)
            self.assertEqual(len(model['obstacles']),1)
            self.assertGreaterEqual(model['quality']['underlay_entities'],6)
            self.assertTrue(model['doors'])
            self.assertTrue(model['level_labels'])
            self.assertIsNotNone(model['wet_cores'][0]['nearest_shaft_distance'])
        finally:
            if os.path.exists(path): os.remove(path)

if __name__=='__main__': unittest.main()
