import os
import shutil
import tempfile
import unittest

import ezdxf

from cad_engine.engineering_runner_v13 import run_engineering_pipeline
from cad_engine.acceptance_v13 import evaluate_engineering_acceptance
from cad_engine.sheet_composer_v13 import compose_engineering_content, validate_composed_dxf


class RealProjectAcceptanceV13Tests(unittest.TestCase):
    def _fixture(self):
        fd, path = tempfile.mkstemp(suffix='.dxf')
        os.close(fd)
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 4
        for layer in ('WALL', 'SHAFT', 'FIXTURE'):
            doc.layers.add(layer)

        blocks = {'WC': 120, 'Rooshooee': 100, 'FLOOR_DRAIN': 80, 'SHOWER': 100}
        for name, radius in blocks.items():
            block = doc.blocks.new(name)
            block.add_circle((0, 0), radius)

        msp = doc.modelspace()
        room = [(0, 0), (6000, 0), (6000, 4500), (0, 4500)]
        msp.add_lwpolyline(room, close=True, dxfattribs={'layer': 'WALL'})
        for a, b in zip(room, room[1:] + room[:1]):
            msp.add_line(a, b, dxfattribs={'layer': 'WALL'})
        msp.add_text('BATHROOM', dxfattribs={'insert': (2600, 2200), 'height': 200})
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
        src = self._fixture()
        dst = src + '.accepted.dxf'
        shutil.copyfile(src, dst)
        try:
            pipeline = run_engineering_pipeline(
                src,
                project_overrides={'levels': ['Ground', 'First', 'Roof']},
            )
            qa = evaluate_engineering_acceptance(pipeline)
            self.assertEqual(qa['status'], 'PASS', qa)
            self.assertTrue(all(g['status'] == 'PASS' for g in qa['gates']), qa)

            composition = compose_engineering_content(dst, pipeline)
            cad_qa = validate_composed_dxf(dst, pipeline, composition)
            self.assertEqual(cad_qa['status'], 'PASS', cad_qa)

            doc = ezdxf.readfile(dst)
            msp = doc.modelspace()
            self.assertTrue(any(str(getattr(e.dxf, 'layer', '')) == 'WALL' for e in msp))
            self.assertTrue(any(str(getattr(e.dxf, 'layer', '')) == 'ENGITOOLS-M-SANITARY' for e in msp))
            self.assertTrue(any(str(getattr(e.dxf, 'layer', '')) == 'ENGITOOLS-M-VENT' for e in msp))

            texts = []
            for entity in msp:
                if str(getattr(entity.dxf, 'layer', '')) != 'ENGITOOLS-M-ANNOTATION':
                    continue
                if entity.dxftype() == 'MTEXT':
                    texts.append(entity.plain_text().upper())
                elif entity.dxftype() == 'TEXT':
                    texts.append(str(entity.dxf.text or '').upper())
            text_blob = '\n'.join(texts)
            self.assertIn('C.O.', text_blob)
            self.assertIn('SANITARY RISER S1', text_blob)
            self.assertIn('VENT RISER V1', text_blob)
            self.assertIn('VENT / UP TO ROOF', text_blob)
            self.assertIn('FD', text_blob)
            self.assertIn('SLOPE', text_blob)

            sanitary = doc.layers.get('ENGITOOLS-M-SANITARY')
            vent = doc.layers.get('ENGITOOLS-M-VENT')
            self.assertEqual(int(sanitary.dxf.lineweight), 60)
            self.assertEqual(str(vent.dxf.linetype).upper(), 'HIDDEN')
            self.assertEqual(int(vent.dxf.lineweight), 30)
        finally:
            for path in (src, dst):
                if os.path.exists(path):
                    os.remove(path)


if __name__ == '__main__':
    unittest.main()
