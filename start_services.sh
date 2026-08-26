#!/bin/sh
# EngiTools mechanical v11 final production release.
set -eu

RULEBOOK_TARGET="${RULEBOOK_PATH:-/data/rulebook/MEP_Design_Rulebook.docx}"
RULEBOOK_PAYLOAD="data/rulebook/MEP_Design_Rulebook_v3.docx.b64"
if [ -f "$RULEBOOK_PAYLOAD" ]; then
  mkdir -p "$(dirname "$RULEBOOK_TARGET")"
  python - "$RULEBOOK_PAYLOAD" "$RULEBOOK_TARGET" <<'PY'
import base64, pathlib, sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
dst.write_bytes(base64.b64decode(src.read_text(encoding='ascii')))
print(f'installed Rule Book v3: {dst} ({dst.stat().st_size} bytes)')
PY
fi

uvicorn cad_engine.main_v10_5:app --host 127.0.0.1 --port 8081 &
CAD_PID=$!
trap 'kill $CAD_PID 2>/dev/null || true' EXIT INT TERM
exec uvicorn app.main_health:app --host 0.0.0.0 --port ${PORT:-8080}
