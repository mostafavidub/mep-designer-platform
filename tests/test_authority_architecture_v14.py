import unittest
from cad_engine.authority_architecture_v14 import (
    build_project_model, resolve_design_basis, derive_system_requirements,
    build_reference_driven_manifest, build_network_contract,
    build_calculation_contract, validate_authority_contract,
)


class AuthorityArchitectureV14Tests(unittest.TestCase):
    def _gonbad(self):
        levels={
            'GROUND': {'wet': True, 'habitable': True, 'exhaust': True, 'gas_appliance': True},
            'LEVEL-01': {'wet': True, 'habitable': True, 'exhaust': True, 'gas_appliance': True},
            'LEVEL-02': {'wet': True, 'habitable': True, 'exhaust': True, 'gas_appliance': False},
        }
        project=build_project_model(levels, roof_present=True, occupancy='residential', excluded_frames=13)
        basis=resolve_design_basis(project, {
            'city':'Gonbad-e Kavus',
            'cooling_system':'wall_mounted_split_ac',
            'heating_system':'package_boiler_radiators',
            'hot_water_source':'package_boiler',
            'gas_service':True,
            'required_external_inputs':['envelope','utility_pressure','gas_service','manufacturer'],
        })
        req=derive_system_requirements(project,basis)
        manifest=build_reference_driven_manifest(project,req)
        network=build_network_contract(req)
        calc=build_calculation_contract()
        return project,basis,req,manifest,network,calc

    def test_gonbad_reference_driven_set_is_28_without_hardcoding_reference_count(self):
        project,basis,req,manifest,network,calc=self._gonbad()
        self.assertEqual(project['status'],'PASS')
        self.assertEqual(basis['status'],'PASS')
        self.assertEqual(manifest['sheet_count'],28)
        self.assertEqual(manifest['family_counts']['GENERAL_DETAIL'],3)
        self.assertEqual(manifest['family_counts']['SANITARY_VENT'],3)
        self.assertEqual(manifest['family_counts']['WATER'],4)
        self.assertEqual(manifest['family_counts']['HEATING'],3)
        self.assertEqual(manifest['family_counts']['GAS'],2)
        self.assertEqual(manifest['family_counts']['SPLIT_AC'],4)
        self.assertEqual(manifest['family_counts']['EXHAUST'],3)
        self.assertEqual(network['cross_level_physical_edges'],0)
        self.assertEqual(calc['fabricated_final_values'],0)
        qa=validate_authority_contract(project,basis,req,manifest,network,calc)
        self.assertEqual(qa['status'],'PASS',qa)

    def test_sheet_count_changes_with_project_evidence(self):
        levels={'GROUND': {'wet': True, 'habitable': True, 'exhaust': True, 'gas_appliance': False}}
        project=build_project_model(levels, roof_present=False)
        basis=resolve_design_basis(project, {'city':'X','cooling_system':'wall_mounted_split_ac','heating_system':'package_boiler_radiators','gas_service':False})
        req=derive_system_requirements(project,basis)
        manifest=build_reference_driven_manifest(project,req)
        self.assertNotEqual(manifest['sheet_count'],28)
        self.assertEqual(manifest['family_counts'].get('GAS',0),0)
        self.assertEqual(manifest['family_counts'].get('ROOF',0),0)

    def test_missing_design_inputs_are_not_silently_fabricated(self):
        project=build_project_model({'GROUND': {'wet': True}}, roof_present=False)
        basis=resolve_design_basis(project, {})
        self.assertEqual(basis['status'],'INPUT_REQUIRED')
        calc=build_calculation_contract()
        self.assertEqual(calc['fabricated_final_values'],0)
        self.assertEqual(calc['calculations']['gas']['status'],'INPUT_REQUIRED')
        self.assertEqual(calc['calculations']['split_ac']['status'],'INPUT_REQUIRED')


if __name__=='__main__':
    unittest.main()
