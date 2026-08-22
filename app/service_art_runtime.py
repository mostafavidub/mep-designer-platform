import base64
import re
from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

from fastapi.responses import Response


_MARKER = 'data:image/jpeg;base64,'
_BASE64_CHARS = re.compile(r'[^A-Za-z0-9+/=]')
_FALLBACK_JPEG = Path('app/static/hero-integrated-mep-v1.jpg')

# The approved 1920x1080 mechanical artwork is stored as five base64 text
# chunks on a dedicated immutable Git branch. Keeping the binary out of the
# normal source tree avoids GitHub connector binary-write limitations while
# still giving production a deterministic, browser-safe asset.
_APPROVED_BRANCH = 'service-mech-art-1080-v2'
_APPROVED_PART_URLS = [
    f'https://raw.githubusercontent.com/mostafavidub/mep-designer-platform/{_APPROVED_BRANCH}/app/static/service-art-mechanical-1080.b64/part-{i:02d}.txt'
    for i in range(5)
]


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
    chunks = []
    for url in _APPROVED_PART_URLS:
        req = Request(url, headers={'User-Agent': 'EngiTools/1.0'})
        with urlopen(req, timeout=12) as res:
            chunks.append(res.read().decode('ascii').strip())
    payload = ''.join(chunks)
    data = base64.b64decode(payload, validate=True)
    if len(data) < 150_000:
        raise ValueError('Approved mechanical artwork is unexpectedly small')
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return data, 'image/webp'
    if data.startswith(b'\xff\xd8'):
        return data, 'image/jpeg'
    raise ValueError('Approved mechanical artwork has an unsupported format')


def _mechanical_art() -> tuple[bytes, str]:
    try:
        return _approved_mechanical_art()
    except Exception as exc:
        # Last-resort compatibility path. Production should normally never hit
        # this because the approved artwork branch is public and immutable.
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
