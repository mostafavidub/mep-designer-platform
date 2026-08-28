import tempfile
import unittest
import zipfile
from pathlib import Path

import ezdxf

from app import artifact_storage
from app.dxf_input import read_input_dxf
from cad_engine.main import design_dxf


class ArtifactQualityGateTests(unittest.TestCase):
    def _valid_dxf(self, path):
        doc = ezdxf.new('R2010')
        doc.modelspace().add_line((0, 0), (10, 10))
        doc.saveas(path)

    def test_valid_dxf_passes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'design.dxf'
            self._valid_dxf(path)
            report = artifact_storage.validate_output_artifact(path)
            self.assertEqual(report['status'], 'PASS')
            self.assertGreater(report['files'][0]['entities'], 0)

    def test_empty_dxf_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'empty.dxf'
            path.write_text('', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                artifact_storage.validate_output_artifact(path)

    def test_zip_requires_readable_dxf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dxf = root / 'sheet.dxf'
            self._valid_dxf(dxf)
            package = root / 'output.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.write(dxf, dxf.name)
            report = artifact_storage.validate_output_artifact(package)
            self.assertEqual(report['format'], 'ZIP')
            self.assertEqual(len(report['files']), 1)

    def test_zip_without_dxf_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / 'invalid.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('readme.txt', 'no drawing')
            with self.assertRaises(RuntimeError):
                artifact_storage.validate_output_artifact(package)


class QueueIntegrationContractTests(unittest.TestCase):
    def test_missing_endsec_input_is_recovered_without_losing_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'missing-endsec.dxf'
            output = Path(td) / 'designed.dxf'
            doc = ezdxf.new('R2010')
            doc.modelspace().add_line((0, 0), (1000, 1000))
            doc.modelspace().add_text('LIVING ROOM').set_placement((500, 500))
            doc.saveas(source)

            raw = source.read_text(encoding='utf-8')
            marker = raw.rfind('  0\nENDSEC\n')
            self.assertGreater(marker, 0)
            source.write_text(raw[:marker] + raw[marker + len('  0\nENDSEC\n'):], encoding='utf-8')

            recovered, report = read_input_dxf(source)
            self.assertTrue(report['recovered'])
            self.assertGreater(sum(1 for _ in recovered.modelspace()), 0)

            design_report = design_dxf(source, output, 'mechanical', ['cold_water'], 1)
            self.assertTrue(design_report['input_recovery']['recovered'])
            designed = ezdxf.readfile(output)
            self.assertGreater(sum(1 for _ in designed.modelspace()), 0)

    def test_r12_input_is_upgraded_before_new_symbols_are_added(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'legacy-r12.dxf'
            output = Path(td) / 'designed.dxf'
            doc = ezdxf.new('R12')
            doc.modelspace().add_text('LIVING ROOM', dxfattribs={'height': 200}).set_placement((1000, 1000))
            doc.saveas(source)
            design_dxf(source, output, 'electrical', ['elv'], 1)
            designed = ezdxf.readfile(output)
            self.assertGreaterEqual(designed.dxfversion, 'AC1015')
            self.assertTrue(any(entity.dxftype() == 'LWPOLYLINE' for entity in designed.modelspace()))

    def test_unbounded_thread_calls_removed_from_upload_paths(self):
        main = Path('app/main.py').read_text(encoding='utf-8')
        resumable = Path('app/resumable_upload.py').read_text(encoding='utf-8')
        self.assertIn('schedule_analysis(pid)', main)
        self.assertIn('legacy.schedule_analysis(pid)', resumable)
        self.assertNotIn('threading.Thread(target=legacy.analyze_project_job', resumable)

    def test_production_installs_persistent_queue_last(self):
        source = Path('app/main_health.py').read_text(encoding='utf-8')
        self.assertIn('register_job_queue(app, main_auto.legacy)', source)
        self.assertGreater(
            source.index('register_job_queue(app, main_auto.legacy)'),
            source.index('register_mechanical_review_fix(app, main_auto.legacy)'),
        )


if __name__ == '__main__':
    unittest.main()
