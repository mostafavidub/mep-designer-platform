from starlette.middleware.gzip import GZipMiddleware

from . import main_auto
from . import unit_sanity  # patches dimension-based CAD unit sanity before project analysis
from . import dxf_output  # patches design/download flow to deliver DXF artifacts
from .resumable_upload import register_resumable_upload_routes
from .service_art_runtime import register_service_art_routes
from .mechanical_workflow import register_mechanical_workflow

app = main_auto.app
register_resumable_upload_routes(app)
register_service_art_routes(app)
register_mechanical_workflow(app, main_auto.legacy)

# Compress HTML/CSS/JS/SVG/JSON responses without spending excessive CPU.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


@app.middleware('http')
async def performance_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path

    # Static assets with an explicit version query are immutable. Unversioned
    # assets still get a useful cache window while remaining refreshable.
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
