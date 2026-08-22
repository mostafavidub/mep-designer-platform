import base64
import re
from functools import lru_cache
from pathlib import Path

from fastapi.responses import Response


_BASE64_CHARS = re.compile(r'[^A-Za-z0-9+/=]')
_APPROVED_PART_DIR = Path('app/static/service-art-mechanical-1080.b64')


@lru_cache(maxsize=1)
def _approved_mechanical_art() -> tuple[bytes, str]:
    parts = sorted(_APPROVED_PART_DIR.glob('part-*.txt'))
    if len(parts) != 5:
        raise ValueError(f'Expected 5 mechanical artwork chunks, found {len(parts)}')
    payload = ''.join(p.read_text(encoding='ascii') for p in parts)
    payload = _BASE64_CHARS.sub('', payload)
    payload += '=' * ((4 - len(payload) % 4) % 4)
    data = base64.b64decode(payload, validate=False)
    if not data.startswith(b'RIFF') or data[8:12] != b'WEBP':
        raise ValueError('Approved mechanical artwork is not the expected WEBP asset')
    sync = data.find(b'\x9d\x01\x2a')
    if sync < 0 or len(data) < sync + 7:
        raise ValueError('WEBP frame header is incomplete')
    width = int.from_bytes(data[sync + 3:sync + 5], 'little') & 0x3FFF
    height = int.from_bytes(data[sync + 5:sync + 7], 'little') & 0x3FFF
    if (width, height) != (1920, 1080):
        raise ValueError(f'Expected 1920x1080 approved artwork, got {width}x{height}')
    return data, 'image/webp'


def register_service_art_routes(app):
    @app.get('/service-art/mechanical.jpg', include_in_schema=False)
    def mechanical_service_art():
        data, media_type = _approved_mechanical_art()
        return Response(data, media_type=media_type, headers={
            'Cache-Control': 'public, max-age=31536000, immutable',
            'X-Content-Type-Options': 'nosniff',
            'X-EngiTools-Art': 'mechanical-approved-1920x1080',
        })
