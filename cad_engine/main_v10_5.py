"""Production wrapper for guarded mechanical v11 upgrades."""
from . import main_v10_3 as v10_3
from . import main_v10_4 as v10_4
from . import main_v3 as engine
from .mechanical_upgrade_v11 import install as install_sheet_composer
from .water_sanitary_v11 import install as install_water_sanitary
from .gas_v11 import install as install_gas
from .hvac_v11 import install as install_hvac
from .rainwater_v11 import install as install_rainwater

install_sheet_composer(v10_3, v10_4)
install_water_sanitary(v10_4)
install_gas(v10_4)
install_hvac(v10_4)
install_rainwater(v10_4)
app = v10_4.app
# v10.4 remains the calculation/design implementation; narrow helper layers are
# upgraded in-place above without replacing unrelated CAD disciplines.
engine.design_dxf = v10_4.design_dxf_v10_4


@app.get('/v10-5-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.1.4-mechanical-guarded-upgrades',
        'nonduplicating_special_sheets': True,
        'approved_manifest_contract': True,
        'system_specific_typical_floors': True,
        'water_sanitary_connected_networks': True,
        'gas_connected_network': True,
        'hvac_ventilation_completed': True,
        'rainwater_connected_network': True,
        'professional_verification_required': True,
    }
