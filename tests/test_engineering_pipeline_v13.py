import os
import tempfile
import unittest

import ezdxf

from cad_engine.engineering_pipeline_v13 import reconstruct_architecture


class EngineeringPipelineV13Tests(unittest.TestCase):
    def _arch_fixture(self):
        fd, path = tempfile.mkstemp(suffix='.dxf'); os.close(fd)
        doc = ezdxf.new('R2013'); doc.header['$INSUNITS'] = 4
        doc.layers.add('WALL'); doc.layers.add('SHAFT'); doc.layers.add('DOOR')
        msp = doc.modelspace()
        # Room enclosure + room label.
        msp.add_lwpolyline([(0,0),(5000,0),(5000,4000),(0,4000)], close=True, dxfattribs={'layer':'WALL'})
        msp.add_text('BATHROOM', dxfattribs={'insert':(2500,2000),'height':200})
        # Real wall segments and shaft.
        msp.add_line((0,0),(5000,0), dxfattribs={'layer':'WALL'})
        msp.add_lwpolyline([(4200,500),(4800,500),(4800,1500),(4200,1500)], close=True, dxfattribs={'layer':'SHAFT'})
        doc.saveas(path)
        return path

    def test_stage_01_reconstructs_room_geometry_and_shaft(self):
        path = self._arch_fixture()
        try:
            model = reconstruct_architecture(path)
            self.assertEqual(model['version'], 'architecture-reconstruction-v13.1')
            self.assertEqual(model['units'], 4)
            self.assertEqual(model['quality']['room_count'], 1)
            self.assertEqual(model['rooms'][0]['type'], 'bathroom')
            self.assertIsNotNone(model['rooms'][0]['polygon'])
            self.assertEqual(model['quality']['shaft_count'], 1)
            self.assertGreaterEqual(model['quality']['wall_segments'], 1)
        finally:
            os.remove(path)


if __name__ == '__main__':
    unittest.main()
