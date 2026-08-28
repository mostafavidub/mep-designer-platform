"""Mechanical authority release contract v16 with preservation gate."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_v15 import REQUIRED_CAPABILITIES as V15_CAPABILITIES

RELEASE_VERSION="16.0.0"
REQUIRED_CAPABILITIES={
    **V15_CAPABILITIES,
    "architecture_source_snapshot":"cad_engine.architecture_preservation_gate_v16",
    "architecture_semantic_classifier":"cad_engine.architecture_preservation_gate_v16",
    "preservation_criticality_engine":"cad_engine.architecture_preservation_gate_v16",
    "mechanical_architecture_dependency_graph":"cad_engine.architecture_preservation_gate_v16",
    "central_mutation_policy":"cad_engine.architecture_preservation_gate_v16",
    "atomic_plan_transform_contract":"cad_engine.architecture_preservation_gate_v16",
    "architecture_diff_engine":"cad_engine.architecture_preservation_gate_v16",
    "topology_preservation_gate":"cad_engine.architecture_preservation_gate_v16",
    "architecture_visibility_gate":"cad_engine.architecture_preservation_gate_v16",
    "mechanical_impact_gate":"cad_engine.architecture_preservation_gate_v16",
    "golden_multi_project_regression":"cad_engine.architecture_preservation_gate_v16",
    "hard_fail_rollback_delivery_block":"cad_engine.mechanical_authority_site_v16",
    "production_architecture_preservation_transaction":"cad_engine.mechanical_authority_site_v16",
}

def release_contract_status()->dict:
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try:
            import_module(module_name); checks[capability]=True
        except Exception:
            checks[capability]=False
    return {"version":RELEASE_VERSION,"status":"PASS" if all(checks.values()) else "FAIL","required_count":len(REQUIRED_CAPABILITIES),"passed_count":sum(checks.values()),"checks":checks}
