"""Mechanical authority release contract v17."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_v16 import REQUIRED_CAPABILITIES as V16_CAPABILITIES

RELEASE_VERSION='17.0.0'
REQUIRED_CAPABILITIES={
    **V16_CAPABILITIES,
    'reference_sheet_decomposition':'cad_engine.reference_parity_engine_v17',
    'project_specific_detail_library':'cad_engine.reference_parity_engine_v17',
    'detail_parameter_resolver':'cad_engine.reference_parity_engine_v17',
    'adaptive_detail_sheet_composer':'cad_engine.reference_parity_engine_v17',
    'riser_graph_engine':'cad_engine.reference_parity_engine_v17',
    'floor_to_riser_reconciliation':'cad_engine.reference_parity_engine_v17',
    'riser_geometry_composer':'cad_engine.reference_parity_engine_v17',
    'calculation_dependency_engine':'cad_engine.reference_parity_engine_v17',
    'calculation_traceability':'cad_engine.reference_parity_engine_v17',
    'calculation_sheet_formatter':'cad_engine.reference_parity_engine_v17',
    'general_notes_knowledge_base':'cad_engine.reference_parity_engine_v17',
    'project_specific_note_filter':'cad_engine.reference_parity_engine_v17',
    'standards_provenance_layer':'cad_engine.reference_parity_engine_v17',
    'reference_grammar_inference':'cad_engine.reference_parity_engine_v17',
    'sheet_to_sheet_consistency_gate':'cad_engine.reference_parity_engine_v17',
    'semantic_reference_pairing':'cad_engine.reference_parity_engine_v17',
    'four_component_reference_scoring':'cad_engine.reference_parity_engine_v17',
    'gap_to_fix_loop':'cad_engine.reference_parity_engine_v17',
    'multi_project_regression':'cad_engine.reference_parity_engine_v17',
    'unseen_project_acceptance':'cad_engine.reference_parity_engine_v17',
    'documentation_cad_enhancer':'cad_engine.documentation_enhancer_v17',
    'production_reference_parity_transaction':'cad_engine.mechanical_authority_site_v17',
}

def release_contract_status()->dict:
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try:
            import_module(module_name); checks[capability]=True
        except Exception:
            checks[capability]=False
    return {'version':RELEASE_VERSION,'status':'PASS' if all(checks.values()) else 'FAIL','required_count':len(REQUIRED_CAPABILITIES),'passed_count':sum(checks.values()),'checks':checks}
