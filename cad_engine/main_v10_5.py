"""Production wrapper for guarded mechanical v11 upgrades."""
from . import main_v10_3 as v10_3
from . import main_v10_4 as v10_4
from . import main_v3 as engine
from .mechanical_upgrade_v11 import install as install_sheet_composer
from .water_sanitary_v11 import install as install_water_sanitary
from .gas_v11 import install as install_gas
from .hvac_v11 import install as install_hvac
from .rainwater_v11 import install as install_rainwater
from .engineering_qa_v11 import validate_generated_mechanical_output

install_sheet_composer(v10_3, v10_4)
install_water_sanitary(v10_4)
install_gas(v10_4)
install_hvac(v10_4)
install_rainwater(v10_4)
app = v10_4.app


def design_dxf_v10_5(src, dst, discipline, systems, revision, calc):
    meta = v10_4.design_dxf_v10_4(src, dst, discipline, systems, revision, calc)
    if discipline == 'mechanical':
        meta['final_engineering_qa'] = validate_generated_mechanical_output(dst, calc, meta)
        meta['design_standard'] = str(meta.get('design_standard') or '') + ' + final engineering QA v11'
    return meta


# All CAD API routes resolve the engine function at request time, so production
# mechanical issuance passes through the final QA gate without replacing the
# proven v10.4 application or unrelated disciplines.
engine.design_dxf = design_dxf_v10_5


@app.get('/v10-5-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.2.0-mechanical-final-qa',
        'nonduplicating_special_sheets': True,
        'approved_manifest_contract': True,
        'system_specific_typical_floors': True,
        'water_sanitary_connected_networks': True,
        'gas_connected_network': True,
        'hvac_ventilation_completed': True,
        'rainwater_connected_network': True,
        'final_engineering_qa_fail_closed': True,
        'professional_verification_required': True,
    }
