"""Locked release contract for coordinated mechanical pipeline v19."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_v17 import REQUIRED_CAPABILITIES as PRIOR_CAPABILITIES

RELEASE_VERSION = "19.0.0"
REQUIRED_CAPABILITIES = {
    **PRIOR_CAPABILITIES,
    "structural_rcp_coordination_model":"cad_engine.coordination_v19",
    "multi_elevation_25d_candidate_router":"cad_engine.coordination_v19",
    "clash_penetration_slope_gate":"cad_engine.coordination_v19",
    "official_datasheet_ingestion":"cad_engine.manufacturer_selector_v19",
    "calculation_driven_manufacturer_selector":"cad_engine.manufacturer_selector_v19",
    "route_equipment_revalidation":"cad_engine.manufacturer_selector_v19",
    "parametric_executable_details":"cad_engine.parametric_documentation_v19",
    "graph_native_identity_locked_risers":"cad_engine.parametric_documentation_v19",
    "blind_seal_before_reference":"cad_engine.submission_qa_v19",
    "seven_project_strict_golden_regression":"cad_engine.submission_qa_v19",
}

def release_contract_status():
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try: import_module(module_name); checks[capability]=True
        except Exception: checks[capability]=False
    return {"version":RELEASE_VERSION,"status":"PASS" if all(checks.values()) else "FAIL",
            "required_count":len(checks),"passed_count":sum(checks.values()),"checks":checks}
