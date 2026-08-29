#!/bin/sh
# EngiTools production release: mechanical authority pipeline v17 + preservation + project-agnostic reference parity.
set -eu

# CAD_OUTPUT_DIR contains regenerable transaction workspaces only. Final
# deliverables are copied to the project output store before delivery.
# Clear interrupted work before SQLite starts so a full volume cannot prevent
# the queue recovery transaction during application startup.
python -c 'from pathlib import Path; import shutil; root=Path("/data/cad-engine"); root.mkdir(parents=True, exist_ok=True); [shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True) for p in list(root.iterdir())]'

RULEBOOK_TARGET="${RULEBOOK_PATH:-/data/rulebook/MEP_Design_Rulebook.docx}"
mkdir -p "$(dirname "$RULEBOOK_TARGET")"
python data/rulebook/generate_rulebook_v4.py "$RULEBOOK_TARGET"

# CAD designer: mechanical requests use the fail-closed v17 authority pipeline
# with Architecture Preservation Gate plus project-agnostic Detail/Riser/
# Calculation/General-Notes parity. Electrical remains on the existing flow.
uvicorn cad_engine.main_v17:app --host 127.0.0.1 --port 8081 &
CAD_PID=$!
trap 'kill $CAD_PID 2>/dev/null || true' EXIT INT TERM

exec uvicorn app.main_health:app --host 0.0.0.0 --port ${PORT:-8080}
