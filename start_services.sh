#!/bin/sh
# EngiTools production release: mechanical authority pipeline v17 + preservation + project-agnostic reference parity.
set -eu

# CAD workspaces are regenerable and must never consume the persistent
# Railway Volume. The Volume is reserved for SQLite metadata only; final
# artifacts are verified in R2 before their local copies are removed.
export CAD_OUTPUT_DIR="${CAD_OUTPUT_DIR:-/tmp/engitools-cad-output}"
export TMPDIR="${TMPDIR:-/tmp/engitools-tmp}"
mkdir -p "$CAD_OUTPUT_DIR" "$TMPDIR"
python -c 'import os, shutil; from pathlib import Path; root=Path(os.environ["CAD_OUTPUT_DIR"]); [shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True) for p in list(root.iterdir())]'

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
