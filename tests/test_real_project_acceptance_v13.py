import os
import tempfile
import unittest

import ezdxf

from cad_engine.engineering_runner_v13 import run_engineering_pipeline
from cad_engine.acceptance_v13 import evaluate_engineering_acceptance


class RealProjectAcceptanceV13Tests(unittest.TestCase):
    def _fixture(self):
        fd, path = tempfile.mkstemp(suffix='.dxf')
        os.close(fd)
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 4
        for layer in ('WALL', 'SHAFT', 'FIXTURE'):
            doc.layers.add(layer)

        blocks = {
            'WC': 120,
            'Rooshooee': 100,
            'FLOOR_DRAIN': 80,
            'SHOWER': 100,
        }
        for name, radius in blocks.items():
            block = doc.blocks.new(name)
            block.add_circle((0, 0), radius)

        msp = doc.modelspace()
        # One fully enclosed wet core room with real architectural wall evidence.
        room = [(0, 0), (6000, 0), (6000, 4500), (0, 4500)]
        msp.add_lwpolyline(room, close=True, dxfattribs={'layer': 'WALL'})
        for a, b in zip(room, room[1:] + room[:1]):
            msp.add_line(a, b, dxfattribs={'layer': 'WALL'})
        msp.add_text('BATHROOM', dxfattribs={'insert': (2600, 2200), 'height': 200})

        # Real shaft inside the wet core so a correct route requires no wall crossing.
        msp.add_lwpolyline(
            [(4600, 1300), (5400, 1300), (5400, 2600), (4600, 2600)],
            close=True,
            dxfattribs={'layer': 'SHAFT'},
        )
        msp.add_blockref('WC', (900, 900), dxfattribs={'layer': 'FIXTURE'})
        msp.add_blockref('Rooshooee', (1800, 900), dxfattribs={'layer': 'FIXTURE'})
        msp.add_blockref('FLOOR_DRAIN', (2600, 1200), dxfattribs={'layer': 'FIXTURE'})
        msp.add_blockref('SHOWER', (3300, 1100), dxfattribs={'layer': 'FIXTURE'})
        doc.saveas(path)
        return path

    def test_sanitary_vent_family_meets_authority_acceptance_gate(self):
        path = self._fixture()
        try:
            pipeline = run_engineering_pipeline(
                path,
                project_overrides={'levels': ['Ground', 'First', 'Roof']},
            )
            qa = evaluate_engineering_acceptance(pipeline)
            self.assertEqual(qa['status'], 'PASS', qa)
            self.assertTrue(all(g['status'] == 'PASS' for g in qa['gates']), qa)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == '__main__':
    unittest.main()
