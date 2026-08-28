"""Production CAD entrypoint v16 with fail-closed Architecture Preservation Gate."""
from . import main_v15 as _base
from .mechanical_authority_site_v16 import design_mechanical_authority_site
from .mechanical_release_contract_v16 import release_contract_status, RELEASE_VERSION

# main_v15.design() resolves this module global at request time; replacing it here
# upgrades only the mechanical path while preserving the existing electrical path.
_base.design_mechanical_authority_site = design_mechanical_authority_site
app = _base.app

@app.get("/mechanical_release")
def mechanical_release_v16():
    return release_contract_status()

@app.get("/mechanical_release/version")
def mechanical_release_version_v16():
    return {"version":RELEASE_VERSION,"architecture_preservation_gate":"v16.0","fail_closed":True}

@app.get("/architecture_preservation")
def architecture_preservation_status():
    status=release_contract_status()
    required=[k for k in status["checks"] if "architecture" in k or "preservation" in k or "mutation" in k or "rollback" in k]
    return {"version":"16.0","status":"PASS" if all(status["checks"][k] for k in required) else "FAIL","fail_closed":True,"critical_loss_tolerance":0,"checks":{k:status["checks"][k] for k in required}}
