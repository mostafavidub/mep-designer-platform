"""Production CAD entrypoint for the complete mechanical authority release."""
from .main_v15 import app
from .mechanical_release_contract_v15 import release_contract_status, RELEASE_VERSION


@app.get("/mechanical_release")
def mechanical_release():
    """Expose the exact capability contract deployed by the CAD service."""
    return release_contract_status()


@app.get("/mechanical_release/version")
def mechanical_release_version():
    return {"version": RELEASE_VERSION}
