import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ezdxf

from cad_engine.required_scope_gate_step9 import (
    required_scope,
    validate_required_scope_support,
    validate_required_scope_artifact,
)
from cad_engine.mechanical_authority_site_v19 import design_mechanical_authority_site
from cad_engine.version_manifest import active_version_manifest


class RequiredScopeStep9Tests(unittest.TestCase):
    def test_no_explicit_scope_is_not_applicable(self):
        result=validate_required_scope_support({})
        self.assertEqual(result["status"],"NOT_APPLICABLE")
        self.assertEqual(result["required_systems"],[])

    def test_false_string_flags_do_not_trigger_required_scope(self):
        result=required_scope({"septic_required":"false","fire_water_required":"no","fire_fighting_required":"خیر"})
        self.assertEqual(result["required_systems"],[])

    def test_septic_disposal_basis_is_explicit_requirement(self):
        result=validate_required_scope_support({"wastewater_disposal":"septic tank"})
        self.assertEqual(result["status"],"UNSUPPORTED")
        self.assertIn("SEPTIC",result["required_systems"])
        self.assertIn("SEPTIC",result["unsupported_systems"])

    def test_fire_water_flag_is_explicit_requirement(self):
        result=validate_required_scope_support({"fire_water_required":True})
        self.assertEqual(result["status"],"UNSUPPORTED")
        self.assertIn("FIRE_WATER",result["unsupported_systems"])

    def test_manifest_can_require_septic_or_fire_water(self):
        answers={"_approved_drawing_manifest":{"sheets":[
            {"family":"SEPTIC_SYSTEM","drawing_type":"SITE_PLAN"},
            {"family":"FIRE_WATER","drawing_type":"FLOOR_PLAN"},
        ]}}
        result=validate_required_scope_support(answers)
        self.assertEqual(result["required_systems"],["FIRE_WATER","SEPTIC"])
        self.assertEqual(result["status"],"UNSUPPORTED")

    def test_future_supported_scope_can_pass_preflight(self):
        answers={"septic_required":True,"fire_water_required":True}
        result=validate_required_scope_support(answers,supported_systems={"SEPTIC","FIRE_WATER"})
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["unsupported_systems"],[])

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_active_runtime_blocks_required_septic_before_designer(self,designer):
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{},"septic_required":True}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_not_called()
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["stage"],"required_scope_preflight_gate")
        self.assertEqual(result["required_scope_qa"]["status"],"UNSUPPORTED")
        self.assertIn("SEPTIC",result["required_scope_qa"]["unsupported_systems"])

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_active_runtime_blocks_required_fire_water_before_designer(self,designer):
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{},"fire_water_required":True}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_not_called()
        self.assertEqual(result["stage"],"required_scope_preflight_gate")
        self.assertIn("FIRE_WATER",result["required_scope_qa"]["unsupported_systems"])

    def test_text_only_septic_mention_does_not_satisfy_exact_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"text-only.dxf"; doc=ezdxf.new("R2010")
            doc.modelspace().add_mtext("SEPTIC SYSTEM PROVIDED",dxfattribs={"layer":"ENGITOOLS-M-NOTES"})
            doc.saveas(p)
            result=validate_required_scope_artifact(p,{"septic_required":True})
            self.assertEqual(result["status"],"FAIL")
            self.assertIn("required_scope_geometry_missing:SEPTIC",result["errors"])

    def test_real_septic_layer_geometry_plus_tag_satisfies_exact_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"septic.dxf"; doc=ezdxf.new("R2010")
            if "ENGITOOLS-M-SEPTIC" not in doc.layers: doc.layers.add("ENGITOOLS-M-SEPTIC")
            m=doc.modelspace(); m.add_line((0,0),(5,0),dxfattribs={"layer":"ENGITOOLS-M-SEPTIC"})
            m.add_mtext("SEPTIC TANK CONNECTION",dxfattribs={"layer":"ENGITOOLS-M-SEPTIC"})
            doc.saveas(p)
            result=validate_required_scope_artifact(p,{"septic_required":True})
            self.assertEqual(result["status"],"PASS",result)
            self.assertGreaterEqual(result["systems"]["SEPTIC"]["geometry_count"],1)
            self.assertGreaterEqual(result["systems"]["SEPTIC"]["tag_count"],1)

    def test_real_fire_water_layer_geometry_plus_tag_satisfies_exact_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"fire.dxf"; doc=ezdxf.new("R2010")
            if "ENGITOOLS-M-FIRE-WATER" not in doc.layers: doc.layers.add("ENGITOOLS-M-FIRE-WATER")
            m=doc.modelspace(); m.add_lwpolyline([(0,0),(3,0),(3,2)],dxfattribs={"layer":"ENGITOOLS-M-FIRE-WATER"})
            m.add_mtext("FIRE WATER MAIN",dxfattribs={"layer":"ENGITOOLS-M-FIRE-WATER"})
            doc.saveas(p)
            result=validate_required_scope_artifact(p,{"fire_water_required":True})
            self.assertEqual(result["status"],"PASS",result)
            self.assertGreaterEqual(result["systems"]["FIRE_WATER"]["geometry_count"],1)
            self.assertGreaterEqual(result["systems"]["FIRE_WATER"]["tag_count"],1)


if __name__=="__main__":
    unittest.main()
