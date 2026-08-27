import os
import tempfile
import unittest

import ezdxf

from cad_engine.engineering_pipeline_v13 import reconstruct_architecture, recognize_fixtures_equipment


class EngineeringPipelineV13Tests(unittest.TestCase):
    def _arch_fixture(self):
        fd, path = tempfile.mkstemp(suffix='.dxf'); os.close(fd)
        doc = ezdxf.new('R2013'); doc.header['$INSUNITS'] = 4
        for layer in ('WALL','SHAFT','DOOR','FIXTURE','EQUIP'):
            doc.layers.add(layer)
        basin = doc.blocks.new('Rooshooee'); basin.add_circle((0,0), 150)
        fan = doc.blocks.new('EXH_FAN'); fan.add_circle((0,0), 120)
        msp = doc.modelspace()
        msp.add_lwpolyline([(0,0),(5000,0),(5000,4000),(0,4000)], close=True, dxfattribs={'layer':'WALL'})
        msp.add_text('BATHROOM', dxfattribs={'insert':(2500,2000),'height':200})
        msp.add_line((0,0),(5000,0), dxfattribs={'layer':'WALL'})
        msp.add_lwpolyline([(4200,500),(4800,500),(4800,1500),(4200,1500)], close=True, dxfattribs={'layer':'SHAFT'})
        msp.add_blockref('Rooshooee',(1000,1000), dxfattribs={'layer':'FIXTURE'})
        msp.add_blockref('EXH_FAN',(3500,1000), dxfattribs={'layer':'EQUIP'})
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

    def test_stage_02_recognizes_installed_fixture_and_equipment(self):
        path = self._arch_fixture()
        try:
            arch = reconstruct_architecture(path)
            result = recognize_fixtures_equipment(arch)
            self.assertEqual(result['version'], 'fixture-equipment-recognition-v13.2')
            self.assertIn('basin', {x['type'] for x in result['fixtures']})
            self.assertIn('exhaust_fan', {x['type'] for x in result['equipment']})
            self.assertEqual(result['quality']['room_assigned'], 2)
            self.assertTrue(all(x['room_id'] == 'ROOM-001' for x in result['detections']))
        finally:
            os.remove(path)


if __name__ == '__main__':
    unittest.main()
