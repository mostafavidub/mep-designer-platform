import unittest

from cad_engine.system_requirements_v13 import derive_system_requirements


class Stage03RequirementTests(unittest.TestCase):
    def test_bathroom_fixture_and_equipment_requirements_are_merged(self):
        architecture = {'rooms':[{'id':'ROOM-001','type':'bathroom'}]}
        recognition = {'detections':[
            {'category':'fixture','type':'basin','room_id':'ROOM-001'},
            {'category':'equipment','type':'exhaust_fan','room_id':'ROOM-001'},
        ]}
        result = derive_system_requirements(architecture, recognition)
        self.assertEqual(result['version'], 'system-requirements-v13.3')
        systems = set(result['rooms'][0]['systems'])
        self.assertTrue({'cold_water','hot_water','sanitary','vent','exhaust','heating'} <= systems)
        self.assertEqual(result['quality']['rooms_with_requirements'], 1)


if __name__ == '__main__': unittest.main()
