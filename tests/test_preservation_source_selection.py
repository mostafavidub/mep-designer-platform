from pathlib import Path


def test_preservation_selects_source_by_ownership_and_transforms_by_render_fit():
    source=Path("cad_engine/mechanical_cad_preservation.py").read_text(encoding="utf-8")
    block=source[source.index('fit_bounds=tuple(row.get("source_bounds")'):source.index('before=_snapshot_selected')]
    assert 'ownership_bounds=tuple(plan.get("content_bounds") or plan["bounds"])' in block
    assert '_entities_in_bounds(src_doc.modelspace(),ownership_bounds)' in block
    assert '_entities_in_bounds(src_doc.modelspace(),fit_bounds)' not in block
