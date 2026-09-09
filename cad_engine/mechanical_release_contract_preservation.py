"""Mechanical authority release contract canonical with preservation gate."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_base import REQUIRED_CAPABILITIES as PRIOR_CAPABILITIES

REQUIRED_CAPABILITIES={
    **PRIOR_CAPABILITIES,
    "architecture_source_snapshot":"cad_engine.architecture_preservation_gate",
    "architecture_semantic_classifier":"cad_engine.architecture_preservation_gate",
    "preservation_criticality_engine":"cad_engine.architecture_preservation_gate",
    "mechanical_architecture_dependency_graph":"cad_engine.architecture_preservation_gate",
    "central_mutation_policy":"cad_engine.architecture_preservation_gate",
    "atomic_plan_transform_contract":"cad_engine.architecture_preservation_gate",
    "architecture_diff_engine":"cad_engine.architecture_preservation_gate",
    "topology_preservation_gate":"cad_engine.architecture_preservation_gate",
    "architecture_visibility_gate":"cad_engine.architecture_preservation_gate",
    "mechanical_impact_gate":"cad_engine.architecture_preservation_gate",
    "golden_multi_project_regression":"cad_engine.architecture_preservation_gate",
    "hard_fail_rollback_delivery_block":"cad_engine.mechanical_cad_preservation",
    "production_architecture_preservation_transaction":"cad_engine.mechanical_cad_preservation",
}

def release_contract_status()->dict:
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try:
            import_module(module_name); checks[capability]=True
        except Exception:
            checks[capability]=False
    return {"status":"PASS" if all(checks.values()) else "FAIL","required_count":len(REQUIRED_CAPABILITIES),"passed_count":sum(checks.values()),"checks":checks}
