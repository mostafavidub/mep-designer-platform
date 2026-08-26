import copy
import unittest

from app import dxf_output, mechanical_drawing_set as planner, mechanical_workflow
from app.manifest_contract_v2 import install, validate_manifest


class ManifestContractV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install(mechanical_workflow, planner, dxf_output)

    def _proposal(self):
        return planner.predict_drawing_set({
            'all_levels': ['L1'], 'conditioned_levels': ['L1'], 'heated_levels': ['L1'],
            'wet_fixture_levels': ['L1'], 'sanitary_fixture_levels': ['L1'],
            'ventilation_required_levels': ['L1'], 'gas_consumer_levels': [],
            'roof_exists': False, 'vertical_systems': False, 'typical_groups': [],
        })

    def test_hash_matches_original_manifest(self):
        manifest = self._proposal()['drawing_manifest']
        self.assertTrue(validate_manifest(manifest, planner.MANIFEST_SCHEMA_VERSION))

    def test_any_sheet_tamper_invalidates_manifest(self):
        manifest = copy.deepcopy(self._proposal()['drawing_manifest'])
        manifest['sheets'][0]['levels'] = ['OTHER']
        self.assertFalse(validate_manifest(manifest, planner.MANIFEST_SCHEMA_VERSION))

    def test_approval_freezes_exact_manifest_identity(self):
        approved = planner.approve_drawing_set(self._proposal())
        self.assertEqual(approved['drawing_manifest']['manifest_id'], approved['approved_manifest']['manifest_id'])
        self.assertEqual(approved['approved_manifest_id'], approved['approved_manifest']['manifest_id'])
        self.assertEqual(approved['approval_contract_version'], '2.0')

    def test_post_approval_manifest_change_blocks_generation(self):
        approved = planner.approve_drawing_set(self._proposal())
        changed = copy.deepcopy(approved)
        changed['drawing_manifest']['sheets'][0]['pattern'] = 'tampered'
        with self.assertRaisesRegex(RuntimeError, 'invalid or stale|changed after approval'):
            dxf_output.validate_generated_manifest(changed, [])

    def test_exact_cad_parity_passes(self):
        approved = planner.approve_drawing_set(self._proposal())
        manifest = approved['approved_manifest']
        report = {
            'authority_submission': {
                'layouts': [row['code'] for row in manifest['sheets']],
                'validation_status': 'PASS',
                'manifest_id': manifest['manifest_id'],
            }
        }
        result = dxf_output.validate_generated_manifest(approved, [report])
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['content_hash_verified'])


if __name__ == '__main__':
    unittest.main()
