import os
import shutil

from starlette.middleware.gzip import GZipMiddleware

from . import main_auto
from . import unit_sanity  # patches dimension-based CAD unit sanity before project analysis
from . import dxf_output  # patches design/download flow to deliver DXF artifacts
from . import artifact_storage
from . import mechanical_workflow
from . import mechanical_drawing_set
from . import mechanical_review_fix
from .artifact_delivery_fix import install as install_artifact_delivery_fix
from .architecture_reconstruction_v1 import install as install_architecture_reconstruction_v1
from .architecture_topology_v1 import install as install_architecture_topology_v1
from .fixture_detection_v2 import install as install_fixture_detection_v2
from .fixture_context_v1 import install as install_fixture_context_v1
from .fixture_gate_v1 import install as install_fixture_gate_v1
from .level_detection_v3 import install as install_level_detection_v3
from .system_typical_v1 import install as install_system_typical_v1
from .manifest_contract_v2 import install as install_manifest_contract_v2
from .project_mechanical_model import install as install_project_mechanical_model
from .mechanical_site_manifest_v12 import install as install_manifest_site_v12
from .resumable_upload import register_resumable_upload_routes
from .service_art_runtime import register_service_art_routes
from .seo_runtime import register_seo_articles
from .analysis_workspace_guard import install as install_analysis_workspace_guard
from .job_queue import register_job_queue
from .gsc_api import register_gsc_routes

app = main_auto.app
# R2 must serve CAD artifacts as binary DXF/ZIP attachments before any route or
# queue operation uploads or signs an artifact URL.
install_artifact_delivery_fix(artifact_storage)
register_resumable_upload_routes(app)
register_service_art_routes(app)
install_level_detection_v3(main_auto)
# Step 1: reconstruct actual architecture and engineering topology.
install_architecture_reconstruction_v1(main_auto)
install_architecture_topology_v1(main_auto)
# Step 2: detect fixtures/equipment then bind each detection to room/wet-core context.
install_fixture_detection_v2(main_auto)
install_fixture_context_v1(main_auto)
# Existing downstream guards remain after the stronger evidence model.
install_fixture_gate_v1(main_auto, mechanical_workflow)
install_system_typical_v1(mechanical_workflow, mechanical_drawing_set)
install_manifest_contract_v2(mechanical_workflow, mechanical_drawing_set, dxf_output)
install_project_mechanical_model(mechanical_workflow)
mechanical_workflow.register_mechanical_workflow(app, main_auto.legacy)
install_manifest_site_v12(mechanical_review_fix)
mechanical_review_fix.register_mechanical_review_fix(app, main_auto.legacy)
register_seo_articles(app, main_auto.legacy)
# The queue captures analyze_project_job at registration time, so the guard must
# be installed immediately before it to protect the complete production analyzer.
install_analysis_workspace_guard(main_auto.legacy)
register_job_queue(app, main_auto.legacy)
register_gsc_routes(app)

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


# The Railway hostname is a temporary trial URL and must not accumulate search
# signals that cannot be preserved after the trial expires. Keep this scoped by
# hostname so a future custom domain is indexable without a code change.
TEMPORARY_NOINDEX_HOSTS = {
    host.strip().lower().rstrip('.')
    for host in os.getenv(
        'TEMPORARY_NOINDEX_HOSTS',
        'web-app-production-3d3b.up.railway.app',
    ).split(',')
    if host.strip()
}


def _request_hostname(request):
    forwarded_host = request.headers.get('x-forwarded-host', '').split(',')[0].strip()
    host = forwarded_host or request.headers.get('host', '')
    return host.split(':', 1)[0].lower().rstrip('.')


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
    if path.startswith('/projects/') or path in {'/login', '/register'}:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    elif _request_hostname(request) in TEMPORARY_NOINDEX_HOSTS:
        response.headers['X-Robots-Tag'] = 'noindex, follow'
    response.headers.setdefault('Vary', 'Accept-Encoding')
    return response


@app.get('/system_health')
def integrated_system_health():
    status = main_auto.system_health()
    status['object_storage'] = artifact_storage.healthcheck()
    return status


@app.get('/storage_health')
def object_storage_health():
    status = artifact_storage.healthcheck()
    usage = shutil.disk_usage(str(main_auto.legacy.DATA_DIR))
    status['volume'] = {
        'total_bytes': usage.total,
        'used_bytes': usage.used,
        'free_bytes': usage.free,
    }
    return status
