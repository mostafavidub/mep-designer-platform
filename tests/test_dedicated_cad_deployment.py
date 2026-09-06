from pathlib import Path


def test_dedicated_cad_image_uses_canonical_entrypoint_and_ephemeral_storage():
    dockerfile = Path("cad_engine/Dockerfile").read_text(encoding="utf-8")

    assert "uvicorn cad_engine.main:app" in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY cad_engine ./cad_engine" in dockerfile
    assert "COPY standards ./standards" in dockerfile
    assert "CAD_OUTPUT_DIR=/tmp/engitools-cad-output" in dockerfile
    assert "ENV DATA_DIR=/data" not in dockerfile


def test_panel_and_cad_images_include_the_same_governance_inputs():
    panel = Path("Dockerfile").read_text(encoding="utf-8")
    cad = Path("cad_engine/Dockerfile").read_text(encoding="utf-8")

    for copy_line in ("COPY app ./app", "COPY cad_engine ./cad_engine", "COPY data ./data", "COPY standards ./standards"):
        assert copy_line in panel
        assert copy_line in cad


def test_panel_runtime_does_not_mutate_packaged_release_identity_inputs():
    panel = Path("Dockerfile").read_text(encoding="utf-8")
    startup = Path("start_services.sh").read_text(encoding="utf-8")

    assert "ENV RULEBOOK_PATH=/data/rulebook/MEP_Design_Rulebook.docx" in panel
    assert "ENV RULEBOOK_PATH=/app/data/rulebook/MEP_Design_Rulebook.docx" not in panel
    assert 'RULEBOOK_TARGET="${RULEBOOK_PATH:-/data/rulebook/MEP_Design_Rulebook.docx}"' in startup
