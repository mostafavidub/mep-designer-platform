import os
import shutil
from cad_engine.build_identity import build_identity
from cad_engine.mechanical_release_contract_v19 import release_contract_status

from starlette.middleware.gzip import GZipMiddleware

from . import main_auto
from . import unit_sanity
from . import dxf_output
from . import artifact_storage
from . import mechanical_workflow
from . import mechanical_drawing_set
from . import mechanical_review_fix
from . import electrical_workflow
from . import electrical_drawing_set
from . import electrical_runtime_patch
from . import electrical_design_integration
from . import electrical_review_fix
from . import discipline_workflow_dispatcher
from . import panel_bridge as panel_bridge_module
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
from .commercial_flow import register_commercial_flow
from .panel_bridge import register_panel_bridge

app = main_auto.app
install_artifact_delivery_fix(artifact_storage)
register_resumable_upload_routes(app)
register_service_art_routes(app)
install_level_detection_v3(main_auto)
install_architecture_reconstruction_v1(main_auto)
install_architecture_topology_v1(main_auto)
install_fixture_detection_v2(main_auto)
install_fixture_context_v1(main_auto)
install_fixture_gate_v1(main_auto, mechanical_workflow)
install_system_typical_v1(mechanical_workflow, mechanical_drawing_set)
install_manifest_contract_v2(mechanical_workflow, mechanical_drawing_set, dxf_output)
install_project_mechanical_model(mechanical_workflow)
mechanical_workflow.register_mechanical_workflow(app, main_auto.legacy)
install_manifest_site_v12(mechanical_review_fix)
mechanical_review_fix.register_mechanical_review_fix(app, main_auto.legacy)

electrical_runtime_patch.install(main_auto)
electrical_design_integration.install(dxf_output, main_auto.legacy)
electrical_review_fix.register_electrical_review_fix(app, main_auto.legacy)

register_seo_articles(app, main_auto.legacy)
install_analysis_workspace_guard(main_auto.legacy)
DesignJob = register_job_queue(app, main_auto.legacy)
register_gsc_routes(app)
register_commercial_flow(app, main_auto.legacy)
panel_bridge_module.mechanical_workflow = discipline_workflow_dispatcher
register_panel_bridge(app, main_auto.legacy, DesignJob)

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

TEMPORARY_NOINDEX_HOSTS = {
    host.strip().lower().rstrip('.')
    for host in os.getenv('TEMPORARY_NOINDEX_HOSTS', 'web-app-production-3d3b.up.railway.app').split(',')
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
    status['build_identity'] = build_identity()
    status['mechanical_v19'] = release_contract_status()
    try:
        from cad_engine.electrical_v1.release_contract_v19 import release_contract_status as electrical_cad_status
        status['electrical_v19_cad_contract'] = electrical_cad_status()
    except Exception as exc:
        status['electrical_v19_cad_contract'] = {'status': 'FAIL', 'error': type(exc).__name__}
    try:
        from .electrical_site_release_contract import release_contract_status as electrical_site_status
        status['electrical_v19_site_contract'] = electrical_site_status()
    except Exception as exc:
        status['electrical_v19_site_contract'] = {'status': 'FAIL', 'error': type(exc).__name__}
    cad_ok = status['electrical_v19_cad_contract'].get('status') == 'PASS'
    site_ok = status['electrical_v19_site_contract'].get('status') == 'PASS'
    status['electrical_v19'] = {
        'version': '19.0.0',
        'status': 'PASS' if cad_ok and site_ok else 'FAIL',
        'cad_runtime': status['electrical_v19_cad_contract'].get('status'),
        'site_runtime': status['electrical_v19_site_contract'].get('status'),
    }
    return status


@app.get('/storage_health')
def object_storage_health():
    status = artifact_storage.healthcheck()
    usage = shutil.disk_usage(str(main_auto.legacy.DATA_DIR))
    status['volume'] = {'total_bytes': usage.total, 'used_bytes': usage.used, 'free_bytes': usage.free}
    return status
