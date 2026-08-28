"""Production wrapper for guarded mechanical engineering upgrades."""
from . import main_v10_3 as v10_3
from . import main_v10_4 as v10_4
from . import main_v8 as v8
from . import main_v3 as engine
from .mechanical_upgrade_v11 import install as install_sheet_composer
from .water_sanitary_v11 import install as install_water_sanitary
from .gas_v11 import install as install_gas
from .hvac_v11 import install as install_hvac
from .rainwater_v11 import install as install_rainwater
from .level_geometry_v11 import install as install_level_geometry
from .engineering_qa_v11 import validate_generated_mechanical_output
from .documentation_v12 import annotate_issued_sheets
from .drawing_content_qa_v12 import validate_independent_drawing_content
from .production_engineering_v14 import apply_engineering_pipeline_v14

install_sheet_composer(v10_3, v10_4)
install_water_sanitary(v10_4)
install_gas(v10_4)
install_hvac(v10_4)
install_rainwater(v10_4)
install_level_geometry(v10_3, v10_4, v8)
app = v10_4.app


def design_dxf_v10_5(src, dst, discipline, systems, revision, calc):
    meta = v10_4.design_dxf_v10_4(src, dst, discipline, systems, revision, calc)
    if discipline == 'mechanical':
        # v14 uses the original architectural coordinate system and overlays real
        # routed/sized/annotated mechanical content on a visible architectural
        # underlay. Insufficient evidence is guarded instead of being fabricated.
        meta['engineering_pipeline_v14'] = apply_engineering_pipeline_v14(src, dst, calc)
        meta['issued_documentation'] = annotate_issued_sheets(dst, calc)
        if meta['issued_documentation'].get('status') != 'PASS':
            raise RuntimeError('Mechanical issued-sheet annotation QA failed.')
        meta['drawing_content_qa'] = validate_independent_drawing_content(dst, calc)
        meta['final_engineering_qa'] = validate_generated_mechanical_output(dst, calc, meta)
        meta['design_standard'] = str(meta.get('design_standard') or '') + ' + plan-grade engineering pipeline v14 + issued documentation v12 + independent drawing-content QA v12 + final engineering QA v11'
    return meta


engine.design_dxf = design_dxf_v10_5


@app.get('/v10-5-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.6.0-mechanical-plan-grade-v14',
        'nonduplicating_special_sheets': True,
        'approved_manifest_contract': True,
        'system_specific_typical_floors': True,
        'analyzer_to_cad_level_geometry_bridge': True,
        'architecture_reconstruction_v14': True,
        'architectural_underlay_preserved_v14': True,
        'fixture_equipment_recognition_v14': True,
        'system_requirement_engine_v14': True,
        'traceable_calculation_engine_v14': True,
        'trunk_branch_riser_topology_v14': True,
        'obstacle_aware_orthogonal_routing_v14': True,
        'downstream_load_sizing_v14': True,
        'engineering_annotations_v14': True,
        'dynamic_detail_schedule_library_v14': True,
        'plan_grade_sheet_composer_v14': True,
        'water_sanitary_connected_networks': True,
        'gas_connected_network': True,
        'hvac_ventilation_completed': True,
        'rainwater_connected_network': True,
        'issued_sheet_dimensions_leaders_callouts': True,
        'independent_issued_drawing_content_parity': True,
        'layout_count_alone_is_not_deliverable_proof': True,
        'final_engineering_qa_fail_closed': True,
        'professional_verification_required': True,
    }
