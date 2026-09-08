import unittest
from pathlib import Path
from unittest.mock import patch

from cad_engine.calculation_evidence_step8 import (
    validate_calculation_evidence,
    apply_canonical_pressure,
)
from cad_engine.mechanical_authority_site_v19 import design_mechanical_authority_site
from cad_engine.version_manifest import active_version_manifest


def _water_answers(**extra):
    out={
        "_approved_drawing_manifest":{
            "sheets":[
                {"code":"M-W-01","family":"WATER_SUPPLY","drawing_type":"FLOOR_PLAN","levels":["GROUND"]},
                {"code":"M-W-CALC","family":"WATER_SUPPLY","drawing_type":"CALCULATION_SHEET","levels":["GROUND"]},
            ]
        }
    }
    out.update(extra)
    return out


class CalculationEvidenceStep8Tests(unittest.TestCase):
    def test_no_water_scope_is_not_applicable(self):
        result=validate_calculation_evidence({})
        self.assertEqual(result["status"],"NOT_APPLICABLE")
        self.assertFalse(result["required"])

    def test_water_scope_without_pressure_is_input_required(self):
        result=validate_calculation_evidence(_water_answers())
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        self.assertIn("water_inlet_pressure",result["missing_inputs"])

    def test_explicit_positive_project_pressure_passes_and_is_canonicalized(self):
        result=validate_calculation_evidence(_water_answers(water_inlet_pressure_bar="2.5 bar"))
        self.assertEqual(result["status"],"PASS",result)
        self.assertEqual(result["value_bar"],2.5)
        self.assertEqual(result["provenance"],"PROJECT_INPUT")
        canonical=apply_canonical_pressure(_water_answers(),result)
        self.assertEqual(canonical["water_inlet_pressure"],2.5)
        self.assertEqual(canonical["water_pressure"],2.5)
        self.assertEqual(canonical["_water_pressure_evidence"]["status"],"PROJECT_INPUT")

    def test_benchmark_or_assumed_pressure_cannot_become_project_evidence(self):
        result=validate_calculation_evidence(_water_answers(
            water_inlet_pressure={"value":1.5,"status":"ASSUMED_FOR_COMPLETENESS_TEST","source":"benchmark"}
        ))
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("assumed_pressure_not_project_evidence:water_inlet_pressure",result["errors"])

    def test_invalid_or_nonpositive_pressure_fails(self):
        for value in ("unknown",0,-1):
            with self.subTest(value=value):
                result=validate_calculation_evidence(_water_answers(water_pressure=value))
                self.assertEqual(result["status"],"FAIL",result)
                self.assertIn("invalid_project_pressure:water_pressure",result["errors"])

    def test_conflicting_pressure_aliases_fail(self):
        result=validate_calculation_evidence(_water_answers(water_pressure=2.0,water_inlet_pressure=2.5))
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any(x.startswith("conflicting_project_pressure_values:") for x in result["errors"]))

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_active_runtime_blocks_missing_water_pressure_before_designer(self,designer):
        answers=_water_answers(_runtime_contract=active_version_manifest(),_v19_input_contract={})
        result=design_mechanical_authority_site(Path("architecture.dxf"),Path("mechanical.dxf"),answers=answers,plan_analysis={})
        designer.assert_not_called()
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["stage"],"calculation_evidence_gate")
        self.assertEqual(result["calculation_evidence_qa"]["status"],"INPUT_REQUIRED")

    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_active_runtime_passes_only_canonical_project_pressure_to_designer(self,designer,integrity):
        designer.return_value={"status":"PASS"}
        integrity.return_value={"status":"PASS","errors":[],"warnings":[],"exact_file_reopened":True}
        answers=_water_answers(_runtime_contract=active_version_manifest(),_v19_input_contract={},water_inlet_pressure_bar="2.75 bar")
        result=design_mechanical_authority_site(Path("architecture.dxf"),Path("mechanical.dxf"),answers=answers,plan_analysis={})
        self.assertEqual(result["status"],"PASS",result)
        passed=designer.call_args.kwargs["answers"]
        self.assertEqual(passed["water_inlet_pressure"],2.75)
        self.assertEqual(passed["water_pressure"],2.75)
        self.assertEqual(passed["_water_pressure_evidence"]["status"],"PROJECT_INPUT")
        self.assertEqual(result["calculation_evidence_qa"]["status"],"PASS")


if __name__=="__main__":
    unittest.main()
