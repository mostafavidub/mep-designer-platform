import copy
import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from cad_engine import main_v10_3 as authority


class MechanicalManifestReleaseTests(unittest.TestCase):
    def scope(self, *, typical=False, roof=True):
        levels = ["Ground", "First", "Second"]
        return {
            "all_levels": levels + (["Roof"] if roof else []),
            "conditioned_levels": levels,
            "heated_levels": levels,
            "wet_fixture_levels": levels,
            "sanitary_fixture_levels": levels,
            "ventilation_required_levels": levels,
            "gas_consumer_levels": levels,
            "roof_exists": roof,
            "roof_level_name": "Roof",
            "vertical_systems": True,
            "typical_groups": [{"name": "Typical Floors", "levels": ["First", "Second"]}] if typical else [],
        }

    def architecture(self, path):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = 4
        msp = doc.modelspace()
        dim = msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(3, 0), angle=0)
        dim.render()
        for name, ox in [("Ground", 0), ("First", 40), ("Second", 80)]:
            msp.add_text(f"{name} architectural plan").set_placement((ox, 0))
            msp.add_text("Kitchen").set_placement((ox + 3, 6))
            msp.add_text("Bathroom").set_placement((ox + 7, 7))
            msp.add_text("Toilet").set_placement((ox + 7, 10))
            msp.add_text("Bedroom").set_placement((ox + 12, 6))
            msp.add_text("Living").set_placement((ox + 11, 12))
            msp.add_text("Shaft").set_placement((ox + 6, 13))
        msp.add_text("Roof architectural plan").set_placement((120, 0))
        msp.add_text("Roof").set_placement((125, 8))
        doc.saveas(path)

    def calc(self, manifest):
        return {
            "_approved_drawing_manifest": manifest,
            "_design_inputs": {
            "gas": "yes",
            "cooling": "split",
            "heating": "radiator",
            "location": "Tehran, Iran",
            "heights": "3.20 m floor-to-floor; 0.40 m false ceiling in wet/service zones",
            "water_source": "municipal meter, 500 L tank and booster pump",
            "water_inlet_pressure": "3.0 bar at meter",\n            "water_design_basis": "PPR; Hazen-Williams C=150; maximum design loss 20 kPa/100 m",
            "sanitary_outlet": "municipal sewer at project boundary",
            "sanitary_design_basis": "uPVC; invert +0.00 at boundary; 2 percent branches and 1 percent mains",
            "gas_appliances": "boiler 24 kW and cooker 10 kW; 21 mbar; meter/regulator at entrance",
            "equipment_schedule": "radiators per room load; split units 9k/18k BTU; outdoor units on roof",
            "ventilation_design_basis": "toilets 10 ACH; enclosed parking 6 ACH; discharge above roof with make-up air",
            "roof_drainage_basis": "120 m2 roof; two coordinated drains; 110 mm/h design rainfall"
        },
            "design_water_flow_lps": 0.7,
            "preliminary_nominal_pipe_candidate_mm": 25,
            "cooling_load_kw": 15.0,
            "heating_load_kw": 12.0,
        }

    def systems(self):
        return [
            "cold_water", "hot_water", "sanitary", "vent", "gas",
            "heating_supply", "heating_return", "cooling", "condensate",
            "exhaust_ventilation", "mechanical_risers",
        ]

    def test_duplex_proposal_and_cad_are_exactly_21(self):
        manifest = approve_drawing_set(predict_drawing_set(self.scope()))["approved_manifest"]
        self.assertEqual(manifest["total_sheets"], 21)
        self.assertEqual(len(manifest["sheets"]), 21)
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.dxf", Path(td) / "m.dxf"
            self.architecture(src)
            meta = authority.design_dxf_v10_3(src, dst, "mechanical", self.systems(), 1, self.calc(manifest))
            generated = [x.name for x in ezdxf.readfile(dst).layouts if x.name.startswith("M-")]
            self.assertEqual(len(generated), 21)
            self.assertEqual(meta["authority_submission"]["validation_status"], "PASS")

    def test_afsari_proposal_and_cad_are_exactly_13(self):
        manifest = approve_drawing_set(predict_drawing_set(self.scope(typical=True, roof=False)))["approved_manifest"]
        self.assertEqual(manifest["total_sheets"], 13)
        self.assertEqual(len(manifest["sheets"]), 13)
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.dxf", Path(td) / "m.dxf"
            self.architecture(src)
            meta = authority.design_dxf_v10_3(src, dst, "mechanical", self.systems(), 1, self.calc(manifest))
            generated = [x.name for x in ezdxf.readfile(dst).layouts if x.name.startswith("M-")]
            self.assertEqual(len(generated), 13)
            self.assertEqual(meta["authority_submission"]["expected_sheet_count"], 13)
            self.assertEqual(meta["authority_submission"]["generated_sheet_count"], 13)
            self.assertEqual(meta["authority_submission"]["validation_status"], "PASS")

    def test_five_identical_floors_collapse_to_one_typical_per_family(self):
        levels = ["L1", "L2", "L3", "L4", "L5"]
        scope = self.scope(roof=False)
        for key in ("all_levels", "conditioned_levels", "heated_levels", "wet_fixture_levels",
                    "sanitary_fixture_levels", "ventilation_required_levels", "gas_consumer_levels"):
            scope[key] = levels
        scope["typical_groups"] = [{"name": "Typical L1-L5", "levels": levels}]
        result = predict_drawing_set(scope)
        for family in ("sanitary_vent", "heating", "gas", "ventilation_exhaust"):
            self.assertEqual(result["sheet_families"][family]["count"], 1)
            self.assertTrue(result["sheet_families"][family]["sheets"][0]["typical"])

    def test_mismatch_protection_fails_generation(self):
        manifest = approve_drawing_set(predict_drawing_set(self.scope()))["approved_manifest"]
        broken = copy.deepcopy(manifest)
        broken["total_sheets"] = 20
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "a.dxf", Path(td) / "m.dxf"
            self.architecture(src)
            with self.assertRaises(RuntimeError):
                authority.design_dxf_v10_3(src, dst, "mechanical", self.systems(), 1, self.calc(broken))


if __name__ == "__main__":
    unittest.main()
