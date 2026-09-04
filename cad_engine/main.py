"""The only production CAD entrypoint.

History lives in Git. Transitional implementation modules remain internal until
their compatibility migration is complete; launchers must import only this path.
"""
from . import main_v15 as _base
from .main_v18 import app
from .build_identity import build_identity
from .mechanical_release_contract_v19 import release_contract_status
from .mechanical_authority_site_v19 import design_mechanical_authority_site
from .runtime_core import design_dxf

_base.design_mechanical_authority_site = design_mechanical_authority_site


@app.get("/version")
def version():
    return build_identity()


@app.get("/mechanical/status")
def mechanical_status():
    status = release_contract_status()
    status["production_entrypoint"] = "cad_engine.main:app"
    status["build"] = build_identity()
    return status
