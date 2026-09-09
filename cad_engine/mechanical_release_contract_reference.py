"""Mechanical authority release contract canonical."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_preservation import REQUIRED_CAPABILITIES as V16_CAPABILITIES

RELEASE_VERSION='17.0.0'
REQUIRED_CAPABILITIES={
    **V16_CAPABILITIES,
    'reference_sheet_decomposition':'cad_engine.reference_parity_engine',
    'project_specific_detail_library':'cad_engine.reference_parity_engine',
    'detail_parameter_resolver':'cad_engine.reference_parity_engine',
    'adaptive_detail_sheet_composer':'cad_engine.reference_parity_engine',
    'riser_graph_engine':'cad_engine.reference_parity_engine',
    'floor_to_riser_reconciliation':'cad_engine.reference_parity_engine',
    'riser_geometry_composer':'cad_engine.reference_parity_engine',
    'calculation_dependency_engine':'cad_engine.reference_parity_engine',
    'calculation_traceability':'cad_engine.reference_parity_engine',
    'calculation_sheet_formatter':'cad_engine.reference_parity_engine',
    'general_notes_knowledge_base':'cad_engine.reference_parity_engine',
    'project_specific_note_filter':'cad_engine.reference_parity_engine',
    'standards_provenance_layer':'cad_engine.reference_parity_engine',
    'reference_grammar_inference':'cad_engine.reference_parity_engine',
    'sheet_to_sheet_consistency_gate':'cad_engine.reference_parity_engine',
    'semantic_reference_pairing':'cad_engine.reference_parity_engine',
    'four_component_reference_scoring':'cad_engine.reference_parity_engine',
    'gap_to_fix_loop':'cad_engine.reference_parity_engine',
    'multi_project_regression':'cad_engine.reference_parity_engine',
    'unseen_project_acceptance':'cad_engine.reference_parity_engine',
    'documentation_cad_enhancer':'cad_engine.documentation_enhancer',
    'production_reference_parity_transaction':'cad_engine.mechanical_cad_shell',
}

def release_contract_status()->dict:
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try:
            import_module(module_name); checks[capability]=True
        except Exception:
            checks[capability]=False
    return {'version':RELEASE_VERSION,'status':'PASS' if all(checks.values()) else 'FAIL','required_count':len(REQUIRED_CAPABILITIES),'passed_count':sum(checks.values()),'checks':checks}
