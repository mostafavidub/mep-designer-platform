from starlette.responses import Response

from . import main_auto

app = main_auto.app


@app.middleware('http')
async def landing_html_accessibility(request, call_next):
    response = await call_next(request)
    if request.url.path not in {'/', '/electrical', '/mechanical'}:
        return response
    if 'text/html' not in response.headers.get('content-type', ''):
        return response

    body = b''
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode('utf-8')
    text = text.replace(
        '<div class="lightbox-content"><img alt="">',
        '<div class="lightbox-content"><img alt="نمایش بزرگ نمونه نقشه پروژه EngiTools">',
    )
    headers = dict(response.headers)
    headers.pop('content-length', None)
    return Response(
        content=text,
        status_code=response.status_code,
        headers=headers,
        media_type='text/html',
    )


@app.get('/system_health')
def integrated_system_health():
    return main_auto.system_health()
