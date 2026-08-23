# Compatibility loader: execute the last known-good main.py while preserving module globals.
# This is intentionally pinned to the pre-SEO-change commit to restore production safely.
from urllib.request import urlopen

_SOURCE = 'https://raw.githubusercontent.com/mostafavidub/mep-designer-platform/d036584aa04e655f2977e68d0338cde43bae07d3/app/main.py'
with urlopen(_SOURCE, timeout=15) as _response:
    _code = _response.read().decode('utf-8')
exec(compile(_code, __file__, 'exec'), globals(), globals())
