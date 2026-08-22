import base64
import re
from pathlib import Path

from fastapi.responses import Response


_MARKER = 'data:image/jpeg;base64,'
_BASE64_CHARS = re.compile(r'[^A-Za-z0-9+/=]')
_FALLBACK_JPEG = Path('app/static/hero-integrated-mep-v1.jpg')


def _embedded_jpeg(path: Path) -> bytes:
    text = path.read_text(encoding='utf-8')
    start = text.find(_MARKER)
    if start < 0:
        raise ValueError(f'No embedded JPEG marker found in {path}')

    payload = text[start + len(_MARKER):]
    quote_positions = [p for p in (payload.find('"'), payload.find("'")) if p >= 0]
    if quote_positions:
        payload = payload[:min(quote_positions)]

    payload = _BASE64_CHARS.sub('', payload)
    if not payload:
        raise ValueError(f'Embedded JPEG payload is empty in {path}')

    payload += '=' * ((4 - len(payload) % 4) % 4)
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise ValueError(f'Embedded JPEG payload is not decodable in {path}: {exc}') from exc
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError(f'Embedded JPEG is incomplete or invalid in {path}')
    return data


def _mechanical_jpeg() -> bytes:
    try:
        return _embedded_jpeg(Path('app/static/service-art-mechanical.svg'))
    except Exception as exc:
        # Keep the site usable while an embedded artwork asset is being replaced.
        # This is deliberately a valid existing high-resolution image, never a
        # generated blank/placeholder response.
        if _FALLBACK_JPEG.exists():
            print(f'[service-art] embedded mechanical JPEG unavailable: {exc}; serving safe fallback', flush=True)
            return _FALLBACK_JPEG.read_bytes()
        raise


def register_service_art_routes(app):
    @app.get('/service-art/mechanical.jpg', include_in_schema=False)
    def mechanical_service_art():
        data = _mechanical_jpeg()
        return Response(data, media_type='image/jpeg', headers={
            'Cache-Control': 'public, max-age=31536000, immutable',
            'X-Content-Type-Options': 'nosniff',
        })
