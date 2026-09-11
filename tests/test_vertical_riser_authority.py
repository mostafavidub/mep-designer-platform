import unittest

from cad_engine.mechanical_documentation import generate_riser_from_network
from cad_engine.mechanical_network_topology import build_authoritative_topology_from_evidence
from cad_engine.mechanical_segment_execution import design_authoritative_segments


def _pmm():
    return {"schema": "project-mechanical-model/v3", "levels": [
        {"name": "Ground", "region_bounds": [0, 0, 10, 10], "elevation_m": 0},
        {"name": "First", "region_bounds": [20, 0, 30, 10], "elevation_m": 3.2}],
        "systems": {"vertical_systems": True},
        "identity_registry": {"entities": [], "alias_to_entity_id": {}},
        "traceability_contract": {"policy": "NO_ORPHAN_ENGINEERING_OUTPUT"}}


def _inputs(second_key="S-01"):
    architecture = {"shafts": [
        {"centroid": [8, 8], "polygon": [[7, 7], [9, 7], [9, 9], [7, 9]], "vertical_alignment_key": "S-01"},
        {"centroid": [28, 8], "polygon": [[27, 7], [29, 7], [29, 9], [27, 9]], "vertical_alignment_key": second_key}],
        "wet_cores": [], "walls": [], "obstacles": []}
    recognition = {"detections": [
        {"id": "F-G", "category": "fixture", "type": "basin", "point": [2, 2], "room_id": "RG", "ports": ["cold_water"]},
        {"id": "F-1", "category": "fixture", "type": "basin", "point": [22, 2], "room_id": "R1", "ports": ["cold_water"]}]}
    return architecture, recognition


class VerticalRiserAuthorityTests(unittest.TestCase):
    def test_multilevel_riser_has_exact_geometry_load_and_identity_evidence(self):
        architecture, recognition = _inputs()
        topology = build_authoritative_topology_from_evidence(_pmm(), architecture, recognition)
        self.assertEqual(topology["status"], "PASS", topology)
        vertical = next(row for row in topology["network"]["edges"] if row["role"] == "vertical_riser")
        endpoint_loads = {row["id"]: 1.25 for row in topology["network"]["nodes"]
                          if row.get("category") == "fixture"}
        design = design_authoritative_segments(topology["network"], {"systems": {"cold_water": {
            "endpoint_loads": endpoint_loads, "load_unit": "FU", "size_table": [{"max_load": 10, "size_mm": 25}],
            "material": "PPR", "material_source": "PROJECT_SPEC"}}})
        self.assertEqual(design["status"], "PASS", design)
        riser = generate_riser_from_network(design["network"])
        self.assertEqual(riser["status"], "PASS", riser)
        row = next(value for value in riser["riser"]["segments"] if value["role"] == "vertical_riser")
        self.assertEqual(row["shaft_key"], "S-01")
        self.assertEqual(row["downstream_load"], 1.25)
        self.assertEqual(row["from_elevation_m"], 0.0)
        self.assertEqual(row["to_elevation_m"], 3.2)
        self.assertTrue(riser["reconciliation"]["zero_mismatch"])

    def test_mismatched_shaft_correspondence_fails_closed(self):
        architecture, recognition = _inputs("S-OTHER")
        result = build_authoritative_topology_from_evidence(_pmm(), architecture, recognition)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("VERTICAL_SHAFT_ALIGNMENT_KEY_MISMATCH:cold_water", result["missing_inputs"])

    def test_riser_crosses_unoccupied_intermediate_level_and_loads_accumulate_above(self):
        model = _pmm()
        model["levels"].insert(1, {"name": "Mezzanine", "region_bounds": [10, 0, 20, 10], "elevation_m": 1.6})
        architecture, recognition = _inputs()
        architecture["shafts"].insert(1, {"centroid": [18, 8],
            "polygon": [[17, 7], [19, 7], [19, 9], [17, 9]], "vertical_alignment_key": "S-01"})
        topology = build_authoritative_topology_from_evidence(model, architecture, recognition)
        self.assertEqual(topology["status"], "PASS", topology)
        vertical = [row for row in topology["network"]["edges"] if row["role"] == "vertical_riser"]
        self.assertEqual(len(vertical), 2)
        self.assertEqual([row["levels"] for row in vertical], [
            [topology["network"]["levels"][0]["id"], topology["network"]["levels"][1]["id"]],
            [topology["network"]["levels"][1]["id"], topology["network"]["levels"][2]["id"]]])
        self.assertTrue(all(len(row["endpoint_ids"]) == 1 for row in vertical))

    def test_missing_elevation_load_and_undeclared_offset_block_issue(self):
        network = {"graph_id": "G", "levels": [{"id": "L1", "type": "GROUND"}, {"id": "L2", "type": "FIRST"}],
            "nodes": [{"id": "S1", "level": "L1"}, {"id": "S2", "level": "L2"}], "edges": [{
                "id": "E", "calc_id": "C", "plan_id": "C", "riser_id": "C", "schedule_id": "C",
                "from": "S1", "to": "S2", "system": "cold_water", "role": "vertical_riser",
                "levels": ["L1", "L2"], "size": 25, "material": "PPR", "vertical_offset_xy": [1, 0]}]}
        result = generate_riser_from_network(network)
        self.assertEqual(result["status"], "FAIL")
        errors = result["reconciliation"]["vertical_errors"]
        self.assertTrue(any(value.startswith("VERTICAL_LEVEL_ELEVATIONS_REQUIRED") for value in errors))
        self.assertTrue(any(value.startswith("UNDECLARED_VERTICAL_OFFSET") for value in errors))
        self.assertTrue(any(value.startswith("VERTICAL_CUMULATIVE_LOAD_REQUIRED") for value in errors))


if __name__ == "__main__":
    unittest.main()
