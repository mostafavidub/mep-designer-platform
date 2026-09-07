from pathlib import Path


def test_mechanical_runtime_keeps_rendering_dependencies_lazy():
    runtime = Path("cad_engine/runtime_core.py").read_text(encoding="utf-8")
    main = Path("cad_engine/main_v15.py").read_text(encoding="utf-8")

    assert runtime.index("def render_pdf") < runtime.index("    import matplotlib")
    assert runtime.index("def merge_pdfs") < runtime.index("    from pypdf import PdfReader, PdfWriter")
    assert main.index("def render_mechanical_pages") < main.index("    import matplotlib")
