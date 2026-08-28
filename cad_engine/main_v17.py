"""Production CAD entrypoint v17: preservation + project-agnostic reference parity documentation."""
from . import main_v16 as _base
from .mechanical_authority_site_v17 import design_mechanical_authority_site
from .mechanical_release_contract_v17 import release_contract_status, RELEASE_VERSION

try:
    _base._base.design_mechanical_authority_site = design_mechanical_authority_site
except Exception:
    pass
app=_base.app

@app.get('/mechanical_release/v17')
def mechanical_release_v17():
    return release_contract_status()

@app.get('/reference_parity')
def reference_parity_status():
    s=release_contract_status()
    names=[k for k in s['checks'] if any(x in k for x in ('detail','riser','calculation','notes','reference','regression','unseen'))]
    return {'version':RELEASE_VERSION,'status':'PASS' if all(s['checks'][k] for k in names) else 'FAIL','checks':{k:s['checks'][k] for k in names},'production_mode':'PROJECT_AGNOSTIC'}
