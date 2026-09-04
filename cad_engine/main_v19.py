"""Active production CAD entrypoint for coordinated release 19.0.0."""
from .main_v18 import app
from .mechanical_release_contract_v19 import release_contract_status

@app.get("/mechanical-v19/status")
def mechanical_v19_status():
    return release_contract_status()
