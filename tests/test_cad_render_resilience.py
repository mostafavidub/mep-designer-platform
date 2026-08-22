import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ezdxf
from pypdf import PdfReader

from cad_engine import main_v5


class CadRenderResilienceTests(unittest.TestCase):
    def test_falls_back_to_entity_by_entity_rendering_instead_of_placeholder_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            dxf_path = td / 'plan.dxf'
            pdf_path = td / 'plan.pdf'

            doc = ezdxf.new('R2018')
            msp = doc.modelspace()
            msp.add_line((0, 0), (1000, 0))
            msp.add_circle((500, 500), 150)
            msp.add_text('ROOM', dxfattribs={'height': 80}).set_placement((300, 300))
            doc.saveas(dxf_path)

            with patch.object(main_v5.Frontend, 'draw_layout', side_effect=RuntimeError('synthetic unsupported entity')):
                main_v5.render_pdf_resilient(dxf_path, pdf_path, 'mechanical')

            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 1000)
            text = '\n'.join((page.extract_text() or '') for page in PdfReader(str(pdf_path)).pages)
            normalized = ''.join(text.split())
            self.assertNotIn('DXFpreviewrenderingunavailable', normalized)
            self.assertIn('EngiToolsMechanical', normalized)


if __name__ == '__main__':
    unittest.main()
