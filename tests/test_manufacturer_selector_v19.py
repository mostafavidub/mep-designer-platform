import unittest
from cad_engine.mechanical_manufacturer_selector import (
    ingest_datasheet, select_equipment, select_radiators, select_package,
    select_split_system, select_exhaust_fans,
)


def model(name="M-12", capacity=12, max_length=30):
    return {"manufacturer":"Example HVAC","model":name,"equipment_type":"split","capacity_kw":capacity,
            "dimensions_mm":{"w":900,"d":350,"h":700},"connections":{"liquid_mm":9.52,"gas_mm":15.88},
            "clearance_mm":{"front":1000,"side":300},"max_pipe_length_m":max_length,"max_elevation_m":15,
            "pump":{"max_head_m":5},"fan":{"max_flow_lps":800},
            "datasheet":{"official_url":"https://manufacturer.example/M-12.pdf","revision":"2026-01","sha256":"c"*64}}


def route(length=20):
    return {"status":"PASS","selected":{"length_m":length,"points":[[0,0,0],[1,1,4]]}}


class ManufacturerSelectorV19Tests(unittest.TestCase):
    def test_datasheet_requires_official_provenance(self):
        value = model(); value["datasheet"].pop("sha256")
        self.assertEqual(ingest_datasheet(value)["status"], "INPUT_REQUIRED")

    def test_no_catalogue_returns_non_confirmed_envelope(self):
        result = select_equipment({"design_capacity_kw":10}, [], route())
        self.assertEqual(result["status"], "PRE_SUBMISSION")
        self.assertIsNone(result["manufacturer"])
        self.assertEqual(result["claim"], "NOT_MANUFACTURER_CONFIRMED")

    def test_selection_is_calculation_driven_and_route_revalidated(self):
        result = select_equipment({"design_capacity_kw":10,"clearance_mm":{"front":900}}, [model("M-18",18), model("M-12",12)], route())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["record"]["model"], "M-12")
        self.assertTrue(result["route_revalidated"])

    def test_route_over_limit_blocks_real_model_and_falls_back(self):
        result = select_equipment({"design_capacity_kw":10}, [model(max_length=10)], route(20))
        self.assertEqual(result["status"], "PRE_SUBMISSION")
        self.assertIn("max_pipe_length", result["evaluations"][0]["errors"])

    def test_radiator_selection_returns_exact_model_sections_and_dimensions(self):
        catalogue=[{"manufacturer":"Official Radiator","model":"R500-90","output_w_per_section":130,
                    "height_mm":500,"depth_mm":90,"section_width_mm":80,
                    "rated_supply_c":75,"rated_return_c":65,"rated_room_c":20,
                    "datasheet":{"official_url":"https://manufacturer.example/r.pdf","revision":"1","sha256":"d"*64}}]
        result=select_radiators([{"room_id":"R1","pmm_id":"PMM-R1","calc_id":"CALC-H1","radiator_id":"RAD-R1","heating_w":1950}],catalogue,
                                {"supply_c":75,"return_c":65,"room_c":20})
        self.assertEqual(result["status"],"PASS")
        radiator=result["radiators"][0]
        self.assertEqual(radiator["sections"],15)
        self.assertEqual(radiator["dimensions_mm"],{"width":1200.0,"height":500,"depth":90})
        self.assertEqual(radiator["model"],"R500-90")

    def test_radiator_temperature_mismatch_is_not_silently_corrected(self):
        catalogue=[{"manufacturer":"Official","model":"R","output_w_per_section":130,"height_mm":500,
                    "depth_mm":90,"section_width_mm":80,"rated_supply_c":80,"rated_return_c":70,
                    "rated_room_c":20,"datasheet":{"official_url":"https://manufacturer.example/r.pdf","revision":"1","sha256":"d"*64}}]
        result=select_radiators([{"room_id":"R1","pmm_id":"PMM-R1","calc_id":"CALC-H1","heating_w":1000}],catalogue,{"supply_c":75,"return_c":65,"room_c":20})
        self.assertEqual(result["status"],"INPUT_REQUIRED")

    def test_package_selection_checks_space_dhw_and_simultaneous_capacity(self):
        record={"manufacturer":"Official Boiler","model":"P24","space_heating_capacity_kw":24,
                "dhw_capacity_kw":28,"combined_capacity_kw":30,"gas_consumption_m3h":2.73,
                "dimensions_mm":{"w":400,"h":700,"d":260},"connections":{"gas_mm":20},
                "datasheet":{"official_url":"https://manufacturer.example/p24.pdf","revision":"1","sha256":"e"*64}}
        result=select_package({"space_heating_kw":12,"dhw_kw":20,"simultaneous_factor":0.5},[record])
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["selection"]["model"],"P24")
        self.assertEqual(result["selection"]["gas_consumption_m3h"],2.73)

    def test_split_selection_reports_load_margin_model_route_and_odu_ratio(self):
        cooling={'status':'PASS','zones':[{'zone_id':'Z1','design_load_btu_h':10500}]}
        sheet={'official_url':'https://manufacturer.example/x.pdf','revision':'1','sha256':'e'*64}
        idu={'manufacturer':'Official','model':'I12','capacity_btu_h':12000,'airflow_cfm':400,
             'liquid_size_mm':6.35,'gas_size_mm':12.7,'max_pipe_length_m':25,'max_elevation_m':10,
             'service_clearance_mm':300,'datasheet':sheet}
        odu={'manufacturer':'Official','model':'O12','nominal_capacity_btu_h':12000,
             'airflow_cfm':1200,
             'min_connected_ratio':.8,'max_connected_ratio':1.3,'max_total_pipe_length_m':30,
             'max_elevation_m':12,'service_clearance_mm':500,'datasheet':sheet}
        route={'zone_id':'Z1','length_m':18,'elevation_m':6,'condensate_drain':True,'service_clearance_mm':400}
        result=select_split_system(cooling,[idu],[odu],[route],{'service_clearance_mm':700})
        self.assertEqual(result['status'],'PASS',result)
        row=result['idus'][0]
        self.assertEqual((row['calculated_load_btu_h'],row['selected_capacity_btu_h'],row['manufacturer'],row['model']),
                         (10500,12000.0,'Official','I12'))
        self.assertEqual(row['route_length_m'],18)
        self.assertAlmostEqual(result['odu']['connected_ratio'],1.0)

    def test_split_route_or_condensate_failure_never_passes(self):
        cooling={'status':'PASS','zones':[{'zone_id':'Z1','design_load_btu_h':9000}]}
        result=select_split_system(cooling,[],[],[{'zone_id':'Z1','length_m':1,'elevation_m':0,
                                                  'condensate_drain':False,'service_clearance_mm':1000}],
                                   {'service_clearance_mm':1000})
        self.assertEqual(result['status'],'INPUT_REQUIRED')
        self.assertIn('COMPLIANT_IDU:Z1',result['missing_inputs'])

    def test_exhaust_selector_requires_both_flow_and_esp_and_zero_unserved_rooms(self):
        design={'status':'PASS','rooms':[{'room_id':'WC','required_cfm':100,'required_esp_pa':80,'calc_id':'CALC-EXH-X'}]}
        sheet={'official_url':'https://manufacturer.example/f.pdf','revision':'1','sha256':'f'*64}
        weak={'manufacturer':'Official','model':'F120-LP','airflow_cfm':120,'esp_pa':60,'dimensions_mm':{},
              'sound_db':35,'service_clearance_mm':300,'datasheet':sheet}
        self.assertEqual(select_exhaust_fans(design,[weak])['status'],'FAIL')
        good={**weak,'model':'F120','esp_pa':100}
        result=select_exhaust_fans(design,[weak,good])
        self.assertEqual(result['status'],'PASS',result)
        self.assertEqual(result['unserved_room_ids'],[])
        self.assertEqual(result['fans'][0]['model'],'F120')


if __name__ == "__main__": unittest.main()
