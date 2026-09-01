"""Active production CAD entrypoint for platform release 18.2."""

from .main_v17 import app
from .version_manifest import active_version_manifest


@app.get("/version")
def version():
    return active_version_manifest()
