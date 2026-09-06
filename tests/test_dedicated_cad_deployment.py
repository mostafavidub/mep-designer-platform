from pathlib import Path


def test_dedicated_cad_image_uses_canonical_entrypoint_and_ephemeral_storage():
    dockerfile = Path("cad_engine/Dockerfile").read_text(encoding="utf-8")

    assert "uvicorn cad_engine.main:app" in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY cad_engine ./cad_engine" in dockerfile
    assert "COPY standards ./standards" in dockerfile
    assert "CAD_OUTPUT_DIR=/tmp/engitools-cad-output" in dockerfile
    assert "ENV DATA_DIR=/data" not in dockerfile
