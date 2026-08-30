import unittest

from cad_engine.mechanical_authority_site_v17 import validate_approved_manifest


def web_sheet(family, drawing_type, code, levels=None):
    return {
        'family': family,
        'drawing_type': drawing_type,
        'code': code,
        'levels': levels or ['GROUND'],
        'pattern': (levels or ['GROUND'])[0],
        'special': drawing_type != 'floor_plan',
    }


def cad_sheet(family, level='GROUND', purpose='PLAN', code='M-X', title=''):
    return {'family': family, 'level': level, 'purpose': purpose, 'code': code, 'title': title}


class ManifestSupportRolesV17Tests(unittest.TestCase):
    def qa(self, approved, generated):
        return validate_approved_manifest(
            {'composition': {'manifest': generated}},
            {'_approved_drawing_manifest': {'sheets': approved}},
        )

    def test_water_service_and_calc_require_explicit_approved_roles(self):
        approved = [web_sheet('water_supply', 'floor_plan', 'M-W-01')]
        generated = [
            cad_sheet('WATER', code='M-111'),
            cad_sheet('WATER', level='SERVICE', code='M-112'),
            cad_sheet('WATER_SERVICE_CALC', level='MULTI', purpose='CALC', code='M-152'),
        ]
        qa = self.qa(approved, generated)
        self.assertEqual(qa['status'], 'FAIL')
        self.assertIn('unapproved_support_role:WATER/SERVICE:requires=WATER/EQUIPMENT', qa['errors'])
        self.assertIn('unapproved_support_role:WATER_SERVICE_CALC:requires=WATER/CALC', qa['errors'])

    def test_water_service_and_calc_pass_after_both_roles_are_approved(self):
        approved = [
            web_sheet('water_supply', 'floor_plan', 'M-W-01'),
            web_sheet('water_supply', 'equipment_plan', 'M-W-EQUIP'),
            web_sheet('water_supply', 'calculation_sheet', 'M-W-CALC'),
        ]
        generated = [
            cad_sheet('WATER', code='M-111'),
            cad_sheet('WATER', level='SERVICE', code='M-112'),
            cad_sheet('WATER_SERVICE_CALC', level='MULTI', purpose='CALC', code='M-152'),
        ]
        qa = self.qa(approved, generated)
        self.assertEqual(qa['status'], 'PASS')
        self.assertIn('WATER/EQUIPMENT', qa['approved_support_roles'])
        self.assertIn('WATER/CALC', qa['approved_support_roles'])

    def test_plumbing_riser_is_derived_only_from_approved_plumbing_primary(self):
        approved = [web_sheet('sanitary_vent', 'floor_plan', 'M-S-01')]
        generated = [
            cad_sheet('SANITARY_VENT', code='M-101'),
            cad_sheet('PLUMBING_RISER', level='MULTI', purpose='RISER', code='M-151'),
        ]
        qa = self.qa(approved, generated)
        self.assertEqual(qa['status'], 'PASS')
        self.assertIn('PLUMBING_RISER<-approved_plumbing_primary', qa['derived_support_documents'])

        no_plumbing = [web_sheet('heating', 'floor_plan', 'M-H-01')]
        bad_generated = [
            cad_sheet('HEATING', code='M-131'),
            cad_sheet('PLUMBING_RISER', level='MULTI', purpose='RISER', code='M-151'),
        ]
        bad = self.qa(no_plumbing, bad_generated)
        self.assertEqual(bad['status'], 'FAIL')
        self.assertIn('unapproved_support_family:PLUMBING_RISER:no_approved_plumbing_system', bad['errors'])

    def test_roof_split_sheet_requires_equipment_or_roof_support_role(self):
        approved = [web_sheet('cooling', 'floor_plan', 'M-C-01')]
        generated = [
            cad_sheet('SPLIT_AC', code='M-161'),
            cad_sheet('SPLIT_AC', level='ROOF', code='M-164'),
        ]
        qa = self.qa(approved, generated)
        self.assertEqual(qa['status'], 'FAIL')
        self.assertIn('unapproved_support_role:SPLIT_AC/ROOF:requires=SPLIT_AC/EQUIPMENT_OR_ROOF_SUPPORT', qa['errors'])

        approved.append(web_sheet('cooling', 'equipment_plan', 'M-C-EQUIP', ['ROOF']))
        self.assertEqual(self.qa(approved, generated)['status'], 'PASS')

    def test_equipment_schedule_is_derived_from_approved_equipment_system_primary(self):
        approved = [web_sheet('heating', 'floor_plan', 'M-H-01')]
        generated = [
            cad_sheet('HEATING', code='M-131'),
            cad_sheet('EQUIPMENT_SCHEDULE', level='MULTI', purpose='SCHEDULE', code='M-181'),
        ]
        qa = self.qa(approved, generated)
        self.assertEqual(qa['status'], 'PASS')
        self.assertIn('EQUIPMENT_SCHEDULE<-HEATING', qa['derived_support_documents'])

        water_only = [web_sheet('water_supply', 'floor_plan', 'M-W-01')]
        bad = self.qa(water_only, [cad_sheet('WATER', code='M-111'), cad_sheet('EQUIPMENT_SCHEDULE', purpose='SCHEDULE', code='M-181')])
        self.assertEqual(bad['status'], 'FAIL')
        self.assertIn('unapproved_support_family:EQUIPMENT_SCHEDULE:no_approved_equipment_system', bad['errors'])

    def test_generic_detail_group_cannot_introduce_unapproved_system(self):
        approved = [web_sheet('water_supply', 'floor_plan', 'M-W-01')]
        plumbing = [cad_sheet('WATER', code='M-111'), cad_sheet('GENERAL_DETAIL', purpose='DETAIL', code='M-004', title='PLUMBING PROJECT-APPLICABLE DETAILS')]
        self.assertEqual(self.qa(approved, plumbing)['status'], 'PASS')

        gas_detail = [cad_sheet('WATER', code='M-111'), cad_sheet('GENERAL_DETAIL', purpose='DETAIL', code='M-006', title='GAS PROJECT-APPLICABLE DETAILS')]
        qa = self.qa(approved, gas_detail)
        self.assertEqual(qa['status'], 'FAIL')
        self.assertIn('unapproved_support_family:GENERAL_DETAIL/GAS:requires=GAS', qa['errors'])

    def test_generated_unapproved_primary_family_still_fails(self):
        approved = [web_sheet('sanitary_vent', 'floor_plan', 'M-S-01')]
        generated = [
            cad_sheet('SANITARY_VENT', code='M-101'),
            cad_sheet('GAS', code='M-141'),
        ]
        qa = self.qa(approved, generated)
        self.assertEqual(qa['status'], 'FAIL')
        self.assertIn('generated_unapproved_system_families:GAS', qa['errors'])


if __name__ == '__main__':
    unittest.main()
