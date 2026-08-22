import base64
import re
from functools import lru_cache
from pathlib import Path

from fastapi.responses import Response


_MARKER = 'data:image/jpeg;base64,'
_BASE64_CHARS = re.compile(r'[^A-Za-z0-9+/=]')
_FALLBACK_JPEG = Path('app/static/hero-integrated-mep-v1.jpg')
_APPROVED_PART_DIR = Path('app/static/service-art-mechanical-1080.b64')


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
    data = base64.b64decode(payload, validate=False)
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError(f'Embedded JPEG is incomplete or invalid in {path}')
    return data


@lru_cache(maxsize=1)
def _approved_mechanical_art() -> tuple[bytes, str]:
    parts = sorted(_APPROVED_PART_DIR.glob('part-*.txt'))
    if len(parts) != 5:
        raise ValueError(f'Expected 5 mechanical artwork chunks, found {len(parts)}')
    payload = ''.join(p.read_text(encoding='ascii').strip() for p in parts)
    data = base64.b64decode(payload, validate=True)
    if len(data) < 50_000:
        raise ValueError('Approved mechanical artwork is unexpectedly small')
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        # VP8 frame header stores exact raster dimensions immediately after 9d012a.
        sync = data.find(b'\x9d\x01\x2a')
        if sync < 0 or len(data) < sync + 7:
            raise ValueError('WEBP frame header is incomplete')
        width = int.from_bytes(data[sync + 3:sync + 5], 'little') & 0x3FFF
        height = int.from_bytes(data[sync + 5:sync + 7], 'little') & 0x3FFF
        if (width, height) != (1920, 1080):
            raise ValueError(f'Expected 1920x1080 approved artwork, got {width}x{height}')
        return data, 'image/webp'
    raise ValueError('Approved mechanical artwork is not the expected WEBP asset')


def _mechanical_art() -> tuple[bytes, str]:
    try:
        return _approved_mechanical_art()
    except Exception as exc:
        try:
            data = _embedded_jpeg(Path('app/static/service-art-mechanical.svg'))
            return data, 'image/jpeg'
        except Exception:
            if _FALLBACK_JPEG.exists():
                print(f'[service-art] approved mechanical artwork unavailable: {exc}; serving fallback', flush=True)
                return _FALLBACK_JPEG.read_bytes(), 'image/jpeg'
            raise


def register_service_art_routes(app):
    @app.get('/service-art/mechanical.jpg', include_in_schema=False)
    def mechanical_service_art():
        data, media_type = _mechanical_art()
        return Response(data, media_type=media_type, headers={
            'Cache-Control': 'public, max-age=31536000, immutable',
            'X-Content-Type-Options': 'nosniff',
            'X-EngiTools-Art': 'mechanical-approved-1920x1080',
        })
