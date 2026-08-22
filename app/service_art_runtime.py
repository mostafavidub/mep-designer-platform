import base64
import re
from pathlib import Path

from fastapi.responses import Response


_DATA_RE = re.compile(r'href=["\']data:image/jpeg;base64,([^"\']+)["\']')


def _embedded_jpeg(path: Path) -> bytes:
    text = path.read_text(encoding='utf-8')
    match = _DATA_RE.search(text)
    if not match:
        raise ValueError(f'No embedded JPEG found in {path}')
    return base64.b64decode(match.group(1))


def register_service_art_routes(app):
    @app.get('/service-art/mechanical.jpg', include_in_schema=False)
    def mechanical_service_art():
        data = _embedded_jpeg(Path('app/static/service-art-mechanical.svg'))
        return Response(data, media_type='image/jpeg', headers={
            'Cache-Control': 'public, max-age=31536000, immutable',
            'X-Content-Type-Options': 'nosniff',
        })
