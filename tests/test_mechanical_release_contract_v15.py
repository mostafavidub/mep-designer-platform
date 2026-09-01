from pathlib import Path

from cad_engine.mechanical_release_contract_v15 import (
    RELEASE_VERSION,
    REQUIRED_CAPABILITIES,
    release_contract_status,
)


def test_release_contract_imports_every_required_capability():
    status = release_contract_status()
    assert RELEASE_VERSION == "15.2.0"
    assert status["required_count"] >= 30
    assert status["status"] == "PASS", status
    assert status["passed_count"] == status["required_count"]


def test_release_contract_contains_real_project_acceptance_features():
    required = {
        "architecture_reconstruction",
        "drawing_type_classification",
        "primary_plan_and_roof_isolation",
        "fixture_equipment_recognition",
        "plan_aware_topology",
        "plan_aware_routing",
        "pipe_sizing",
        "split_wall_hosting",
        "roof_rainwater_calculation",
        "water_service_tank_pump_topology",
        "gas_table_p22_sizing",
        "exhaust_cfm",
        "plumbing_riser",
        "authority_style_sheet_naming",
        "integrated_a4_frame_and_compact_titleblock",
        "drawing_safe_area_zero_title_overlap",
        "north_inherited_from_architecture",
        "preservation_first_footer_cleanup",
        "exact_final_file_reopen_qa",
    }
    assert required.issubset(REQUIRED_CAPABILITIES)


def test_start_services_routes_cad_to_complete_release():
    text = Path("start_services.sh").read_text(encoding="utf-8")
    assert "cad_engine.main_v18:app" in text
    assert "cad_engine.main_v15_2:app" not in text
    assert "cad_engine.main_v10_5:app" not in text
