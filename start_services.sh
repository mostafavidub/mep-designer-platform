#!/bin/sh
# EngiTools production release: mechanical authority pipeline v16 + preservation gate.
set -eu

RULEBOOK_TARGET="${RULEBOOK_PATH:-/data/rulebook/MEP_Design_Rulebook.docx}"
mkdir -p "$(dirname "$RULEBOOK_TARGET")"
python data/rulebook/generate_rulebook_v4.py "$RULEBOOK_TARGET"

# CAD designer: mechanical requests use the fail-closed v16 authority pipeline
# with Architecture Preservation Gate. Electrical remains on the existing flow.
uvicorn cad_engine.main_v16:app --host 127.0.0.1 --port 8081 &
CAD_PID=$!
trap 'kill $CAD_PID 2>/dev/null || true' EXIT INT TERM

exec uvicorn app.main_health:app --host 0.0.0.0 --port ${PORT:-8080}
