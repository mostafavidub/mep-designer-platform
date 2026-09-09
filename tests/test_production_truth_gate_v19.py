import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cad_engine.mechanical_authority_site_v19 import _v19_payload, design_mechanical_authority_site
from cad_engine.production_quality_truth import build_pipeline_traceability, evaluate_production_truth
from cad_engine.production_quality_documentation import build_production_context
from cad_engine.version_manifest import active_version_manifest


def _pmm(levels=None):
    return {
        "schema": "project-mechanical-model/v3",
        "valid": True,
        "levels": [{"name": value} for value in (levels or ["GROUND"])],
        "traceability_contract": {"policy": "NO_ORPHAN_ENGINEERING_OUTPUT"},
        "diagnostics": [],
    }


def _approved_analysis():
    return {
        "architectural_auto": {
            "level_profiles": [{
                "name": "GROUND",
                "roof": False,
                "room_counts": {"bathroom": 1},
                "recognized_room_labels": 1,
                "wet_fixture_candidate": True,
                "sanitary_candidate": True,
                "conditioned_candidate": True,
                "ventilation_candidate": True,
                "gas_candidate": False,
            }],
            "fixture_counts": {"toilet": 1},
            "fixture_blocks_detected": 1,
            "roof_drain_count": 0,
        }
    }


def _pipeline(duplicate=False, cross_overlay=False):
    nodes = [
        {"id": "N1", "kind": "basin", "plan_id": "P1"},
        {"id": "S1", "kind": "shaft", "plan_id": "P1"},
    ]
    edges = [{"id": "E1", "system": "cold_water", "from": "N1", "to": "S1", "plan_id": "P1"}]
    routes = [{"id": "R1", "edge_id": "E1", "system": "cold_water", "plan_id": "P1", "points": [(0, 0), (1, 0)], "length": 1.0}]
    segments = [{"route_id": "R1", "system": "cold_water", "downstream_load": 1.0, "size_mm": 16, "slope_percent": None}]
    if duplicate or cross_overlay:
        system = "hot_water" if cross_overlay else "cold_water"
        nodes.append({"id": "N2", "kind": "sink", "plan_id": "P1"})
        edges.append({"id": "E2", "system": system, "from": "N2", "to": "S1", "plan_id": "P1"})
        routes.append({"id": "R2", "edge_id": "E2", "system": system, "plan_id": "P1", "points": [(0, 0), (1, 0)], "length": 1.0})
        segments.append({"route_id": "R2", "system": system, "downstream_load": 1.0, "size_mm": 16, "slope_percent": None})
    return {
        "architecture": {
            "plans": [{"plan_id": "P1", "level": "GROUND"}],
            "primary_floor_plan_ids": ["P1"],
            "rooms": [],
        },
        "recognition": {"fixtures": [], "detections": []},
        "topology": {"nodes": nodes, "edges": edges},
        "routing": {"routes": routes},
        "sizing": {"segments": segments},
        "hvac": {"routes": [], "equipment": []},
    }


class ProductionTruthGateV19Tests(unittest.TestCase):
    def test_v19_payload_preserves_full_pmm_and_calculations_from_analysis(self):
        pmm = _pmm()
        calculations = [{"calc_id": "CALC-1"}]
        payload = _v19_payload({}, {"project_mechanical_model": pmm, "calculation_rows_v19": calculations})
        self.assertEqual(payload["project_mechanical_model"], pmm)
        self.assertEqual(payload["calculation_rows"], calculations)

    def test_v19_payload_derives_pmm_from_approved_legacy_analysis(self):
        answers = {"_approved_drawing_manifest": [{"code": "M-101", "family": "water_supply", "levels": ["GROUND"]}]}
        payload = _v19_payload(answers, _approved_analysis())
        pmm = payload["project_mechanical_model"]
        self.assertEqual(pmm["schema"], "project-mechanical-model/v3")
        self.assertTrue(pmm["valid"])
        self.assertEqual(pmm["level_names"], ["GROUND"])
        self.assertEqual(pmm["drawing_manifest_count"], 1)

    def test_valid_pipeline_builds_unique_traceability_rows(self):
        trace = build_pipeline_traceability(_pipeline())
        self.assertEqual(trace["status"], "PASS")
        self.assertEqual(len(trace["calculation_rows"]), 1)
        edge = trace["network_graph"]["edges"][0]
        self.assertEqual(edge["plan_id"], edge["calc_id"])
        self.assertEqual(edge["riser_id"], edge["calc_id"])
        self.assertEqual(edge["schedule_id"], edge["calc_id"])

    def test_exact_same_system_duplicate_geometry_is_blocking(self):
        trace = build_pipeline_traceability(_pipeline(duplicate=True))
        self.assertEqual(trace["status"], "FAIL")
        self.assertIn("EXACT_DUPLICATE_ROUTE_GEOMETRY", trace["errors"])

    def test_exact_hot_cold_overlay_is_blocking(self):
        trace = build_pipeline_traceability(_pipeline(cross_overlay=True))
        self.assertEqual(trace["status"], "FAIL")
        self.assertIn("EXACT_CROSS_SYSTEM_ROUTE_OVERLAY", trace["errors"])

    def test_pmm_detail_level_cannot_pass_truth_gate(self):
        truth = evaluate_production_truth(_pmm(["GROUND", "DETAIL-1"]), _pipeline(), {"status": "PASS", "errors": []})
        self.assertEqual(truth["status"], "FAIL")
        self.assertTrue(any(value.startswith("PMM_FORBIDDEN_LEVEL:") for value in truth["errors"]))

    def test_missing_pmm_is_input_required(self):
        truth = evaluate_production_truth({}, _pipeline(), {"status": "PASS", "errors": []})
        self.assertEqual(truth["status"], "INPUT_REQUIRED")
        self.assertIn("PROJECT_MECHANICAL_MODEL_V3", truth["missing_inputs"])

    def test_production_context_uses_architecture_levels_not_support_sheet_levels(self):
        report = {"composition": {"manifest": [
            {"family": "WATER", "level": "GROUND"},
            {"family": "GENERAL_DETAIL", "level": "DETAIL-1"},
            {"family": "PLUMBING_RISER", "level": "DETAIL-2"},
        ]}}
        context = build_production_context(report, _pipeline(), {}, "project")
        self.assertEqual(context.levels, ["GROUND"])
        self.assertEqual(context.routes[0]["level"], "GROUND")
        self.assertNotIn("DETAIL-1", context.levels)
        self.assertNotIn("DETAIL-2", context.levels)

    def test_architecture_only_production_calls_legacy_only_after_truth_passes(self):
        answers = {
            "_runtime_contract": active_version_manifest(),
            "_approved_drawing_manifest": [{"code": "M-101"}],
        }
        analysis = {"project_mechanical_model": _pmm()}
        coordination = {"status": "INPUT_REQUIRED", "missing_inputs": ["STRUCTURAL_MODEL", "RCP_MODEL"]}
        with TemporaryDirectory() as directory:
            src = Path(directory) / "source.dxf"
            dst = Path(directory) / "output.dxf"
            src.write_text("synthetic")
            with patch("cad_engine.mechanical_authority_site_v19.build_design_overrides", return_value={}), \
                 patch("cad_engine.mechanical_authority_site_v19.run_engineering_pipeline", return_value=_pipeline()), \
                 patch("cad_engine.mechanical_authority_site_v19.validate_pipeline", return_value={"status": "PASS", "errors": []}), \
                 patch("cad_engine.mechanical_authority_site_v19.build_coordination_model", return_value=coordination), \
                 patch("cad_engine.mechanical_authority_site_v19._design_v17", return_value={"status": "PASS"}) as legacy, \
                 patch("cad_engine.mechanical_authority_site_v19.rebuild_production_documentation", return_value={"status": "PASS", "documentation_package": {}, "enhancement": {}, "exact_file_final_delivery_qa": {"status": "PASS"}}):
                result = design_mechanical_authority_site(src, dst, answers=answers, plan_analysis=analysis)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["submission_state"], "PRE_SUBMISSION")
        self.assertEqual(result["v19_truth_qa"]["status"], "PASS")
        legacy.assert_called_once()

    def test_missing_pmm_blocks_before_legacy_composer(self):
        answers = {
            "_runtime_contract": active_version_manifest(),
            "_approved_drawing_manifest": [{"code": "M-101"}],
        }
        with TemporaryDirectory() as directory:
            src = Path(directory) / "source.dxf"
            dst = Path(directory) / "output.dxf"
            src.write_text("synthetic")
            with patch("cad_engine.mechanical_authority_site_v19.build_design_overrides", return_value={}), \
                 patch("cad_engine.mechanical_authority_site_v19.run_engineering_pipeline", return_value=_pipeline()), \
                 patch("cad_engine.mechanical_authority_site_v19.validate_pipeline", return_value={"status": "PASS", "errors": []}), \
                 patch("cad_engine.mechanical_authority_site_v19._design_v17") as legacy:
                result = design_mechanical_authority_site(src, dst, answers=answers, plan_analysis={})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["stage"], "v19_production_truth_gate")
        self.assertIn("PROJECT_MECHANICAL_MODEL_V3", result["input_required"]["missing_inputs"])
        legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
