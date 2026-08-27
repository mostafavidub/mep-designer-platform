"""Production wrapper for guarded mechanical v12 upgrades."""
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
        meta['issued_documentation'] = annotate_issued_sheets(dst, calc)
        if meta['issued_documentation'].get('status') != 'PASS':
            raise RuntimeError('Mechanical issued-sheet annotation QA failed.')
        meta['final_engineering_qa'] = validate_generated_mechanical_output(dst, calc, meta)
        meta['design_standard'] = str(meta.get('design_standard') or '') + ' + issued documentation v12 + final engineering QA v11'
    return meta


engine.design_dxf = design_dxf_v10_5


@app.get('/v10-5-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.3.0-mechanical-issued-documentation',
        'nonduplicating_special_sheets': True,
        'approved_manifest_contract': True,
        'system_specific_typical_floors': True,
        'analyzer_to_cad_level_geometry_bridge': True,
        'water_sanitary_connected_networks': True,
        'gas_connected_network': True,
        'hvac_ventilation_completed': True,
        'rainwater_connected_network': True,
        'issued_sheet_dimensions_leaders_callouts': True,
        'final_engineering_qa_fail_closed': True,
        'professional_verification_required': True,
    }
