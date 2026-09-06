from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.electrical_v1.models import EngineeringStatus, EvidenceValue
from cad_engine.electrical_v1.strict_pipeline import run_strict_electrical_pipeline


def make_architecture(path: Path):
    doc=ezdxf.new("R2013"); doc.header["$INSUNITS"]=4
    msp=doc.modelspace()
    # One physical drawing frame with a defensible architectural-plan title.
    msp.add_lwpolyline([(0,0),(12000,0),(12000,8000),(0,8000),(0,0)], close=True, dxfattribs={"layer":"SHEET_FRAME"})
    msp.add_text("Architectural Plan Ground",dxfattribs={"height":180,"layer":"TITLE"}).set_placement((400,400))
    # One closed Living room. Its area is 60 m2 in an mm DXF.
    msp.add_lwpolyline([(1000,1000),(11000,1000),(11000,7000),(1000,7000),(1000,1000)], close=True, dxfattribs={"layer":"ROOM"})
    msp.add_text("Living",dxfattribs={"height":180,"layer":"ROOM_NAME"}).set_placement((5500,3800))
    # Real host wall primitive and an entry block for host-aware switch placement.
    msp.add_line((1000,1000),(1000,7000),dxfattribs={"layer":"WALL"})
    if "DOOR" not in doc.blocks:
        b=doc.blocks.new("DOOR"); b.add_line((0,0),(800,0))
    msp.add_blockref("DOOR",(1000,4000),dxfattribs={"layer":"DOOR"})
    doc.saveas(path)


def fully_evidenced_config():
    return {
        "project_inputs":{"project_name":"Synthetic Evidence Project","building_type":"residential"},
        "design_basis":{
            "city":"TEST_CITY","building_type":"residential","number_of_units":1,
            "supply_voltage_v":230.0,"phase_configuration":"single_phase","utility_service":"documented_test_service",
            "earthing_system":"documented_test_earthing","lighting_basis":{"living":100.0},
            "socket_power_requirements":{"living":{"minimum_count":2,"design_load_w_per_outlet":100.0,"reference":"TEST-SOCKET-RULE"}},
            "dedicated_appliance_requirements":{},"hvac_electrical_loads":False,"elevator":False,"pump":False,
            "package_boiler":False,"split_ac":False,"kitchen_appliances":{},"parking_equipment":{},
            "emergency_lighting":False,"fire_alarm_requirement":False,"low_current_systems":[],
            "lightning_protection":False,"generator":False,"ups":False,"ev_charging":False,"solar_pv":False,
            "ambient_temperature_c":30.0,"installation_method":"B1","conductor_material":"Cu","power_factor":1.0,
            "frequency_hz":50.0,"voltage_drop_limits":{"default":3.0},"switch_control_requirements":{"living":1},
        },
        "manufacturer_data":{"luminaires":{"living":{"lumens":1000.0,"utilization_factor":0.8,"maintenance_factor":0.8,"input_power_w":10.0}}},
        "placement_rules":{"opening_clearance_m":0.2,"wall_host_tolerance_m":0.05,"ceiling_layout_basis_confirmed":True,"switch_door_relation_confirmed":True},
        "circuit_rules":{
            "grouping":{"LIGHTING":{"max_points":10},"GENERAL_RECEPTACLES":{"max_points":10}},
            "demand_factors":{"LIGHTING":1.0,"GENERAL_RECEPTACLES":1.0},
            "panel_locations":{"LVL-001":{"point":[10500,4000],"frame_id":"FRAME-001","host":"wall"}},
        },
        "calculation_rules":{"phase_names":["L1","L2","L3"],"max_phase_imbalance_pct":15.0},
        "sizing_tables":{
            "reference":"TEST-AMPACITY-TABLE","breakers_a":[6,10,16,20,25,32],
            "cables":[
                {"installation_method":"B1","material":"Cu","ampacity_a":15.0,"size_mm2":1.5,"conductors":3,"voltage_rating":"450/750V","earth_mm2":1.5},
                {"installation_method":"B1","material":"Cu","ampacity_a":22.0,"size_mm2":2.5,"conductors":3,"voltage_rating":"450/750V","earth_mm2":2.5},
            ],
        },
        "voltage_drop_rules":{"resistivity_ohm_mm2_per_m":0.0175},
        "panel_rules":{"phase_voltage_v":230.0,"main_breakers_a":[10,16,20,25,32,40],"bus_ratings_a":[25,40,63],"spare_count":2,"reference":"TEST-PANEL-RULE"},
        "service_inputs":{
            "service":{"voltage":230.0,"phase":"single_phase"},"meter":{"type":"test_meter"},"main_distribution":{"id":"MAIN"},
            "feeders":{"DB-LVL-001":{"cable":"3x6 Cu","breaker":"32A","route_length_m":8.0,"tag":"F-DB-01"}},
        },
        "optional_system_inputs":{"grounding":{
            "earth_electrode":{"type":"test_electrode","point":[11500,500],"frame_id":"FRAME-001"},
            "main_earth_bar":{"id":"MEB"},"protective_conductors":{"basis":"TEST-GROUND-RULE"},"panel_grounding":{"DB-LVL-001":"PE"},
        }},
        "detail_parameters":{
            "D-EL-CONDUIT-SUPPORT":{"support_spacing":"PROJECT_VALUE","conduit_type":"PROJECT_VALUE"},
            "D-EL-WALL-PEN":{"wall_type":"PROJECT_VALUE","fire_rating":"PROJECT_VALUE","sleeve":"PROJECT_VALUE"},
            "D-EL-EARTHING":{"electrode_type":"PROJECT_VALUE","conductor":"PROJECT_VALUE","inspection_point":"PROJECT_VALUE"},
            "D-EL-LIGHT-MOUNT":{"ceiling_type":"PROJECT_VALUE","fixture_type":"PROJECT_VALUE"},
            "D-EL-SWITCH-OUTLET":{"mounting_height":"PROJECT_VALUE","wall_type":"PROJECT_VALUE"},
            "D-EL-TERMINATION":{"cable":"PROJECT_VALUE","lug":"PROJECT_VALUE","protection":"PROJECT_VALUE"},
        },
        "reference_similarity_threshold":0.60,
    }


class EvidenceModelTests(unittest.TestCase):
    def test_final_value_rejects_unapproved_source(self):
        with self.assertRaises(ValueError):
            EvidenceValue.final(16,"hardcoded_default")

    def test_input_required_is_not_final(self):
        value=EvidenceValue.input_required("utility data missing")
        self.assertEqual(value.status,EngineeringStatus.INPUT_REQUIRED)
        self.assertIsNone(value.value)


class StrictPipelineTests(unittest.TestCase):
    def test_missing_engineering_inputs_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"arch.dxf"; output=Path(td)/"out.dxf"; make_architecture(source)
            report=run_strict_electrical_pipeline(source,output,{"project_inputs":{"project_name":"Incomplete"}})
            self.assertEqual(report["acceptance"]["status"],"NOT_ACCEPTED")
            self.assertFalse(report["acceptance"]["production_release_allowed"])
            self.assertTrue(report["acceptance"]["incomplete_gates"] or report["acceptance"]["hard_fail_gates"])

    def test_fully_evidenced_synthetic_project_runs_to_reopen_gate(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"arch.dxf"; output=Path(td)/"electrical.dxf"; make_architecture(source)
            report=run_strict_electrical_pipeline(source,output,fully_evidenced_config())
            # If this assertion fails, the JSON-like report identifies the exact gate; do not relax the gate.
            self.assertEqual(report["acceptance"]["status"],"PASS",msg=str({k:v for k,v in report["gates"].items() if v["status"] not in {"PASS","NOT_REQUIRED"}}))
            self.assertTrue(output.exists())
            self.assertEqual(report["gates"]["FINAL_FILE_REOPEN"]["status"],"PASS")
            self.assertEqual(report["gates"]["REFERENCE_SIMILARITY"]["status"],"PASS")
            self.assertFalse(report["acceptance"]["production_release_allowed"])
            # Verify traceability and that final breaker/cable values have provenance, not arbitrary defaults.
            topology=report["data"]["topology"]
            self.assertGreater(len(topology["loads"]),0)
            for circuit in topology["circuits"]:
                self.assertEqual(circuit["breaker"]["status"],"FINAL")
                self.assertEqual(circuit["breaker"]["source"],"engineering_calculation")
                self.assertEqual(circuit["cable"]["status"],"FINAL")
                self.assertEqual(circuit["cable"]["source"],"engineering_calculation")


if __name__ == "__main__":
    unittest.main()
