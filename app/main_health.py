import os
import shutil
from urllib.parse import urlsplit

from cad_engine.build_identity import build_identity
from cad_engine.mechanical_release_contract import release_contract_status

from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import RedirectResponse, Response

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
from .mechanical_site_manifest import install as install_mechanical_site_manifest
from .resumable_upload import register_resumable_upload_routes
from .service_art_runtime import register_service_art_routes
from .seo_runtime import register_seo_articles
from .analysis_workspace_guard import install as install_analysis_workspace_guard
from .job_queue import queue_health, register_job_queue
from .gsc_api import register_gsc_routes
from .commercial_flow import register_commercial_flow
from .panel_bridge import register_panel_bridge

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
install_mechanical_site_manifest(mechanical_review_fix)
mechanical_review_fix.register_mechanical_review_fix(app, main_auto.legacy)
register_seo_articles(app, main_auto.legacy)
# The queue captures analyze_project_job at registration time, so the guard must
# be installed immediately before it to protect the complete production analyzer.
install_analysis_workspace_guard(main_auto.legacy)
DesignJob = register_job_queue(app, main_auto.legacy)
register_gsc_routes(app)
register_commercial_flow(app, main_auto.legacy)
register_panel_bridge(app, main_auto.legacy, DesignJob)

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


PUBLIC_SITE_URL = os.getenv('PUBLIC_SITE_URL', 'https://planha.com').strip().rstrip('/') or 'https://planha.com'
PUBLIC_SITE = urlsplit(PUBLIC_SITE_URL)
CANONICAL_HOST = (PUBLIC_SITE.hostname or 'planha.com').lower().rstrip('.')
CANONICAL_SCHEME = PUBLIC_SITE.scheme or 'https'
CANONICAL_REDIRECT_HOSTS = {
    host.strip().lower().rstrip('.')
    for host in os.getenv(
        'CANONICAL_REDIRECT_HOSTS',
        'www.planha.com',
    ).split(',')
    if host.strip()
}

# Keep any non-canonical technical host out of search even if redirect behavior
# is temporarily bypassed by an internal health request.
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


def _canonical_redirect_url(request):
    path = request.url.path or '/'
    query = request.url.query
    suffix = f'?{query}' if query else ''
    return f'{CANONICAL_SCHEME}://{CANONICAL_HOST}{path}{suffix}'


@app.middleware('http')
async def performance_headers(request, call_next):
    path = request.url.path
    host = _request_hostname(request)
    # Do not interfere with Railway/internal probes, but consolidate all public
    # duplicate hosts to the single SEO host while preserving path and query.
    is_probe = path in {'/system_health', '/storage_health'} or path.startswith('/internal/')
    if not is_probe and host in CANONICAL_REDIRECT_HOSTS and host != CANONICAL_HOST:
        return RedirectResponse(url=_canonical_redirect_url(request), status_code=301)

    response = await call_next(request)
    if path.startswith('/static/'):
        if request.query_params.get('v'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = 'public, max-age=604800, stale-while-revalidate=86400'
    elif 'text/html' in response.headers.get('content-type', ''):
        response.headers['Cache-Control'] = 'no-cache'
    if path.startswith('/projects/') or path in {'/login', '/register'}:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    elif host in TEMPORARY_NOINDEX_HOSTS:
        response.headers['X-Robots-Tag'] = 'noindex, follow'
    response.headers.setdefault('Vary', 'Accept-Encoding')
    return response


# Replace inherited host-derived SEO endpoints with canonical-domain versions.
for route in list(app.router.routes):
    if getattr(route, 'path', None) in {'/sitemap.xml', '/robots.txt'} and 'GET' in (getattr(route, 'methods', None) or set()):
        app.router.routes.remove(route)


@app.get('/sitemap.xml', include_in_schema=False)
def canonical_sitemap():
    paths = ['/', '/electrical', '/mechanical', '/blog'] + [
        f"/blog/{post['slug']}" for post in main_auto.legacy.BLOG
    ]
    rows = ''.join(
        f'<url><loc>{PUBLIC_SITE_URL}{path}</loc>'
        f'<changefreq>{"weekly" if path.startswith("/blog/") else "daily"}</changefreq>'
        f'<priority>{"0.8" if path.startswith("/blog/") else "0.9"}</priority></url>'
        for path in paths
    )
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + rows + '</urlset>'
    )
    return Response(content=xml, media_type='application/xml')


@app.get('/robots.txt', include_in_schema=False)
def canonical_robots():
    return Response(
        content=f'User-agent: *\nAllow: /\nSitemap: {PUBLIC_SITE_URL}/sitemap.xml\n',
        media_type='text/plain',
    )


def integrated_system_health():
    status = main_auto.legacy.system_health()
    status['object_storage'] = artifact_storage.healthcheck()
    status['job_queue'] = queue_health()
    if status['job_queue']['status'] == 'error':
        status['status'] = 'error'
    status['build_identity'] = build_identity()
    status['mechanical'] = release_contract_status()
    return status


# ``main_auto`` inherits the legacy /system_health route. Replace it instead of
# registering a duplicate because Starlette dispatches the first matching route.
for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/system_health' and 'GET' in (getattr(route, 'methods', None) or set()):
        app.router.routes.remove(route)
app.add_api_route('/system_health', integrated_system_health, methods=['GET'])


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
