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
            'city':'Gonbad-e Kavus','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator',
            'gas_service':True,'gas_service_pressure':'22 mbar','water_inlet_pressure':'2.5 bar',
            'rainfall_intensity':'75 mm/h','water_service_mode':'tank_pump',
        })
        req=derive_system_requirements(project,basis)
        manifest=build_reference_driven_manifest(project,req,basis)
        network=build_network_contract(req);calc=build_calculation_contract()
        return project,basis,req,manifest,network,calc

    def test_reference_driven_set_contains_only_evidence_backed_families(self):
        project,basis,req,manifest,network,calc=self._gonbad()
        self.assertEqual(project['status'],'PASS');self.assertEqual(basis['status'],'PASS')
        counts=manifest['family_counts']
        self.assertEqual(counts['SANITARY_VENT'],3);self.assertEqual(counts['HEATING'],3);self.assertEqual(counts['GAS'],2)
        self.assertEqual(counts['SPLIT_AC'],4);self.assertEqual(counts['EXHAUST'],3)
        self.assertEqual(counts['GENERAL_DETAIL'],3)
        self.assertIn('ROOF',counts);self.assertIn('WATER_SERVICE_CALC',counts)
        self.assertEqual(network['cross_level_physical_edges'],0);self.assertEqual(calc['fabricated_final_values'],0)
        qa=validate_authority_contract(project,basis,req,manifest,network,calc);self.assertEqual(qa['status'],'PASS',qa)

    def test_sheet_count_changes_with_project_evidence(self):
        levels={'GROUND': {'wet': True, 'habitable': True, 'exhaust': False, 'gas_appliance': False}}
        project=build_project_model(levels, roof_present=False)
        basis=resolve_design_basis(project, {'city':'X','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':False,'water_inlet_pressure':'2 bar','water_service_mode':'direct_city'})
        req=derive_system_requirements(project,basis);manifest=build_reference_driven_manifest(project,req,basis)
        self.assertEqual(manifest['family_counts'].get('GAS',0),0);self.assertEqual(manifest['family_counts'].get('ROOF',0),0)
        self.assertEqual(manifest['family_counts'].get('WATER_SERVICE_CALC',0),0)
        self.assertLess(manifest['sheet_count'],20)

    def test_missing_design_inputs_are_not_silently_fabricated(self):
        project=build_project_model({'GROUND': {'wet': True}}, roof_present=False)
        basis=resolve_design_basis(project, {})
        self.assertEqual(basis['status'],'INPUT_REQUIRED');self.assertIn('water_inlet_pressure',basis['missing'])
        calc=build_calculation_contract();self.assertEqual(calc['fabricated_final_values'],0)
        self.assertEqual(calc['calculations']['gas']['status'],'INPUT_REQUIRED');self.assertEqual(calc['calculations']['split_ac']['status'],'INPUT_REQUIRED')

    def test_unsupported_system_is_not_silently_converted_to_split_or_package(self):
        project=build_project_model({'GROUND': {'wet':False,'habitable':True,'exhaust':False,'gas_appliance':False}},False)
        basis=resolve_design_basis(project,{'city':'X','cooling_system':'vrf','heating_system':'floor_heating','gas_service':False})
        self.assertEqual(basis['status'],'UNSUPPORTED')
        self.assertTrue(any(x.startswith('cooling_system:') for x in basis['unsupported']))
        self.assertTrue(any(x.startswith('heating_system:') for x in basis['unsupported']))
        req=derive_system_requirements(project,basis)
        self.assertNotIn('split_ac',req['project_systems']);self.assertNotIn('heating',req['project_systems'])


if __name__=='__main__':unittest.main()
