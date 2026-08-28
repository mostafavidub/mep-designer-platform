from starlette.middleware.gzip import GZipMiddleware

from . import main_auto
from . import unit_sanity  # patches dimension-based CAD unit sanity before project analysis
from . import dxf_output  # patches design/download flow to deliver DXF artifacts
from . import mechanical_workflow
from . import mechanical_drawing_set
from . import mechanical_review_fix
from .architecture_reconstruction_v1 import install as install_architecture_reconstruction_v1
from .architecture_topology_v1 import install as install_architecture_topology_v1
from .fixture_detection_v2 import install as install_fixture_detection_v2
from .fixture_gate_v1 import install as install_fixture_gate_v1
from .level_detection_v3 import install as install_level_detection_v3
from .system_typical_v1 import install as install_system_typical_v1
from .manifest_contract_v2 import install as install_manifest_contract_v2
from .project_mechanical_model import install as install_project_mechanical_model
from .mechanical_site_manifest_v12 import install as install_manifest_site_v12
from .resumable_upload import register_resumable_upload_routes
from .service_art_runtime import register_service_art_routes
from .seo_runtime import register_seo_articles

app = main_auto.app
register_resumable_upload_routes(app)
register_service_art_routes(app)
# Level Detection v3 wraps the proven v2 inference. Explicit architectural
# levels such as mezzanines can no longer disappear merely because their room
# labels are missing, while weak orphan block titles remain non-active candidates.
install_level_detection_v3(main_auto)
# Architecture Reconstruction v1 preserves walls, room polygons, doors,
# windows, columns, stairs, shafts and fixed furniture in a per-level model.
install_architecture_reconstruction_v1(main_auto)
# Architecture Topology v1 turns that geometry into engineering relationships:
# room IDs, door/window adjacency, nearest shafts, wet cores and service zones.
install_architecture_topology_v1(main_auto)
# Fixture & Equipment Detection v2 wraps the upgraded analyzer/inference after
# architecture topology so detections can be attached to canonical geometry.
install_fixture_detection_v2(main_auto)
# Unresolved wet-level evidence becomes an explicit questionnaire requirement;
# mechanical design approval is not considered ready until high-confidence CAD
# evidence or a quantified user-confirmed fixture schedule resolves it.
install_fixture_gate_v1(main_auto, mechanical_workflow)
# Typical Floor equivalence is now evaluated per mechanical system family.
install_system_typical_v1(mechanical_workflow, mechanical_drawing_set)
# Approval freezes an exact content-hashed drawing manifest. Any post-approval
# change or Proposal/CAD mismatch fails closed at the generation boundary.
install_manifest_contract_v2(mechanical_workflow, mechanical_drawing_set, dxf_output)
# PMM v1 remains the canonical shadow snapshot and now records per-detection
# confidence/evidence plus the planner's system-specific Typical decisions.
install_project_mechanical_model(mechanical_workflow)
mechanical_workflow.register_mechanical_workflow(app, main_auto.legacy)
install_manifest_site_v12(mechanical_review_fix)
mechanical_review_fix.register_mechanical_review_fix(app, main_auto.legacy)
register_seo_articles(app, main_auto.legacy)

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


@app.middleware('http')
async def performance_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith('/static/'):
        if request.query_params.get('v'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = 'public, max-age=604800, stale-while-revalidate=86400'
    elif 'text/html' in response.headers.get('content-type', ''):
        response.headers['Cache-Control'] = 'no-cache'
    response.headers.setdefault('Vary', 'Accept-Encoding')
    return response


@app.get('/system_health')
def integrated_system_health():
    return main_auto.system_health()
