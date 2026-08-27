import tempfile
import unittest
import zipfile
from pathlib import Path

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from app.mechanical_site_manifest_v12 import review_question_html_v12
from data.rulebook.generate_rulebook_v4 import BENCHMARK, VERSION, build as build_rulebook


class Stage12SiteRulebookContractTests(unittest.TestCase):
    def _benchmark_scope(self):
        levels = ['Ground', 'First Duplex', 'Second Duplex']
        return {
            'all_levels': levels + ['Roof'],
            'conditioned_levels': levels,
            'heated_levels': levels,
            'wet_fixture_levels': levels,
            'sanitary_fixture_levels': levels,
            'ventilation_required_levels': levels,
            'gas_consumer_levels': levels,
            'roof_exists': True,
            'roof_level_name': 'Roof',
            'vertical_systems': True,
            'typical_groups': [],
        }

    def test_stage_12_site_shows_exact_29_sheet_manifest_before_approval(self):
        proposal = predict_drawing_set(self._benchmark_scope())
        manifest = proposal['drawing_manifest']
        self.assertEqual(manifest['total_sheets'], 29)
        html = review_question_html_v12(proposal)
        self.assertIn('تعداد شیت‌های تحویلی مکانیک: 29 شیت', html)
        self.assertIn('Manifest ID:', html)
        self.assertIn(manifest['manifest_id'][:12], html)
        self.assertNotIn('15 پلان', html)
        for sheet in manifest['sheets']:
            self.assertIn(sheet['code'], html)

    def test_stage_12_approval_freezes_the_same_manifest_shown_to_customer(self):
        proposal = predict_drawing_set(self._benchmark_scope())
        shown_id = proposal['drawing_manifest']['manifest_id']
        approved = approve_drawing_set(proposal)
        self.assertEqual(approved['approved_manifest']['manifest_id'], shown_id)
        self.assertEqual(approved['approved_manifest']['total_sheets'], 29)
        self.assertEqual(approved['approved_manifest'], approved['drawing_manifest'])
        approved['drawing_manifest']['sheets'][0]['label'] = 'MUTATED AFTER APPROVAL'
        self.assertNotEqual(approved['approved_manifest']['sheets'][0]['label'], 'MUTATED AFTER APPROVAL')

    def test_stage_12_runtime_rulebook_v4_contains_manifest_and_29_benchmark_contract(self):
        self.assertEqual(VERSION, '4.0')
        self.assertEqual(BENCHMARK['base_architectural_views'], 4)
        self.assertEqual(BENCHMARK['approved_deliverables'], 29)
        self.assertEqual(BENCHMARK['independent_issued_drawing_content'], 29)
        self.assertEqual(BENCHMARK['issued_layouts'], 29)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'MEP_Design_Rulebook.docx'
            build_rulebook(path)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 10000)
            with zipfile.ZipFile(path) as zf:
                xml = zf.read('word/document.xml').decode('utf-8')
            for token in (
                'Approved Drawing Manifest',
                'Layout count alone is not proof',
                '29',
                'CAD output does not match approved drawing manifest',
                'approved deliverables = independent issued drawing content = issued layouts',
            ):
                self.assertIn(token, xml)

    def test_stage_12_startup_installs_rulebook_v4_generator_not_legacy_v3_payload(self):
        startup = Path('start_services.sh').read_text(encoding='utf-8')
        self.assertIn('generate_rulebook_v4.py', startup)
        self.assertNotIn('MEP_Design_Rulebook_v3.docx.b64', startup)

    def test_stage_12_main_app_installs_exact_manifest_review_before_review_routes(self):
        text = Path('app/main_health.py').read_text(encoding='utf-8')
        install_pos = text.index('install_manifest_site_v12(mechanical_review_fix)')
        register_pos = text.index('mechanical_review_fix.register_mechanical_review_fix')
        self.assertLess(install_pos, register_pos)


if __name__ == '__main__':
    unittest.main()
