import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import ezdxf

from app import artifact_storage
from app.job_queue import backup_input_without_blocking, legacy_basis_missing
from app.dxf_input import read_input_dxf
from app.dxf_output import validate_generated_manifest
from app.manifest_contract_v2 import manifest_digest
from cad_engine.main import design_dxf


class ArtifactQualityGateTests(unittest.TestCase):
    def _approved_set(self, sheets):
        manifest = {'schema_version': '3.1', 'discipline': 'mechanical',
                    'total_sheets': len(sheets), 'sheets': sheets}
        manifest['manifest_id'] = manifest_digest(manifest)
        return {'approved': True, 'drawing_manifest': dict(manifest),
                'approved_manifest': dict(manifest),
                'approved_manifest_id': manifest['manifest_id']}
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

    def test_v17_manifest_accepts_complete_authority_package(self):
        drawing_set = self._approved_set([
                    {'code': 'M-W-01', 'family': 'water_supply', 'drawing_type': 'floor_plan'},
                    {'code': 'M-S-01', 'family': 'sanitary_vent', 'drawing_type': 'floor_plan'},
                    {'code': 'M-S-RISER', 'family': 'sanitary_vent', 'drawing_type': 'riser_diagram'},
                    {'code': 'M-S-RAIN', 'family': 'sanitary_vent', 'drawing_type': 'roof_plan'},
                ])
        rows = [
            {'code': 'M-001', 'family': 'COVER'},
            {'code': 'M-101', 'family': 'SANITARY_VENT'},
            {'code': 'M-111', 'family': 'WATER'},
            {'code': 'M-151', 'family': 'PLUMBING_RISER'},
            {'code': 'M-011', 'family': 'ROOF'},
            {'code': 'M-181', 'family': 'EQUIPMENT_SCHEDULE'},
        ]
        result = validate_generated_manifest(drawing_set, [{
            'status': 'PASS', 'dxf_qa': {'status': 'PASS'},
            'composition': {'manifest': rows},
        }])
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['generated_sheets'], len(rows))

    def test_v17_manifest_rejects_missing_approved_family(self):
        drawing_set = self._approved_set([{'code': 'M-W-01', 'family': 'water_supply',
                                           'drawing_type': 'floor_plan'}])
        with self.assertRaisesRegex(RuntimeError, 'coverage is incomplete'):
            validate_generated_manifest(drawing_set, [{
                'status': 'PASS',
                'composition': {'manifest': [{'code': 'M-001', 'family': 'COVER'}]},
            }])


class QueueIntegrationContractTests(unittest.TestCase):
    def test_legacy_authority_failure_reopens_only_allow_listed_inputs(self):
        raw = (
            "{'authority_qa': {'errors': "
            "['design_basis_input_required:rainfall_intensity']}, "
            "'engineering_acceptance': {'errors': "
            "['topology:provisional_shaft_not_authority_acceptable']}}"
        )
        self.assertEqual(
            legacy_basis_missing(raw),
            ['rainfall_intensity', 'mechanical_shaft_route'],
        )
        self.assertEqual(legacy_basis_missing('traceback: unrelated failure'), [])

    def test_object_storage_outage_does_not_block_local_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'architecture.dxf'
            source.write_bytes(b'valid local upload')
            with patch(
                'app.job_queue.artifact_storage.upload_input',
                side_effect=ConnectionError('temporary object storage outage'),
            ):
                warning = backup_input_without_blocking(81, source)
            self.assertIn('ConnectionError', warning)
            self.assertTrue(source.exists())

    def test_upload_failure_ui_never_uses_opaque_cannot_continue_message(self):
        source = Path('app/static/resumable-upload.js').read_text(encoding='utf-8')
        self.assertNotIn("d.error||'امکان ادامه وجود ندارد.'", source)
        self.assertIn('انتخاب مجدد فایل و ادامه', source)

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

    def test_missing_mid_section_endsec_is_repaired_before_entities(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'missing-header-endsec.dxf'
            doc = ezdxf.new('R2010')
            doc.modelspace().add_line((0, 0), (1000, 1000))
            doc.saveas(source)

            raw = source.read_text(encoding='utf-8')
            first_endsec = raw.find('  0\nENDSEC\n')
            self.assertGreater(first_endsec, 0)
            source.write_text(
                raw[:first_endsec] + raw[first_endsec + len('  0\nENDSEC\n'):],
                encoding='utf-8',
            )

            recovered, report = read_input_dxf(source)
            self.assertTrue(report['recovered'])
            self.assertGreater(sum(1 for _ in recovered.modelspace()), 0)

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
