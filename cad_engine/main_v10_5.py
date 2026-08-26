"""Production wrapper for guarded mechanical v11 upgrades."""
from . import main_v10_3 as v10_3
from . import main_v10_4 as v10_4
from . import main_v3 as engine
from .mechanical_upgrade_v11 import install

install(v10_3, v10_4)
app = v10_4.app
# v10.4 remains the calculation/design implementation; its helper globals and
# v10.3 compositor are upgraded in-place above.
engine.design_dxf = v10_4.design_dxf_v10_4


@app.get('/v10-5-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.1.0-mechanical-guarded-upgrades',
        'nonduplicating_special_sheets': True,
        'approved_manifest_contract': True,
        'system_specific_typical_floors': True,
        'professional_verification_required': True,
    }
