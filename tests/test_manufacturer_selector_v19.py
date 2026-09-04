import unittest
from cad_engine.manufacturer_selector_v19 import ingest_datasheet, select_equipment


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


if __name__ == "__main__": unittest.main()
