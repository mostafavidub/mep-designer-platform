from pathlib import Path


def test_production_startup_supervises_cobuilt_cad_runtime():
    startup = Path("start_services.sh").read_text(encoding="utf-8")

    assert "run_cad_designer()" in startup
    assert "while :; do" in startup
    assert "uvicorn cad_engine.main:app --host 127.0.0.1 --port 8081" in startup
    assert "CAD_SUPERVISOR_PID=$!" in startup
    assert 'kill "$CAD_SUPERVISOR_PID"' in startup
