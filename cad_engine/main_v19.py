"""Active production CAD entrypoint for pre-submission release 19.1.0."""
from . import main_v15 as _v15
from .main_v18 import app
from .mechanical_release_contract_v19 import release_contract_status
from .mechanical_authority_site_v19 import design_mechanical_authority_site

_v15.design_mechanical_authority_site = design_mechanical_authority_site

@app.get("/mechanical-v19/status")
def mechanical_v19_status():
    status=release_contract_status()
    status["production_adapter"]="cad_engine.mechanical_authority_site_v19"
    return status
