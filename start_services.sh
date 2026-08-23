#!/bin/sh
set -eu
uvicorn cad_engine.main_v10_4:app --host 127.0.0.1 --port 8081 &
CAD_PID=$!
trap 'kill $CAD_PID 2>/dev/null || true' EXIT INT TERM
exec uvicorn app.main_health:app --host 0.0.0.0 --port ${PORT:-8080}
