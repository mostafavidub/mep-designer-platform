import base64
import re
from functools import lru_cache
from pathlib import Path

from fastapi.responses import Response

_BASE64_CHARS = re.compile(r'[^A-Za-z0-9+/=]')
_APPROVED_JPEG = Path('app/static/mechanical-hero-exact-current.txt')

@lru_cache(maxsize=1)
def _approved_mechanical_art() -> tuple[bytes, str]:
    payload = _APPROVED_JPEG.read_text(encoding='ascii')
    payload = _BASE64_CHARS.sub('', payload)
    payload += '=' * ((4 - len(payload) % 4) % 4)
    data = base64.b64decode(payload, validate=False)
    if not data.startswith(b'\xff\xd8\xff'):
        raise ValueError('Approved mechanical artwork is not a JPEG asset')
    if len(data) < 10_000:
        raise ValueError('Approved mechanical artwork payload is unexpectedly small')
    return data, 'image/jpeg'

def register_service_art_routes(app):
    @app.get('/service-art/mechanical.jpg', include_in_schema=False)
    def mechanical_service_art():
        data, media_type = _approved_mechanical_art()
        return Response(data, media_type=media_type, headers={
            'Cache-Control': 'public, max-age=31536000, immutable',
            'X-Content-Type-Options': 'nosniff',
            'X-EngiTools-Art': 'mechanical-approved-jpeg',
        })
