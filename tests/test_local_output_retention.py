from pathlib import Path

import ezdxf

from app.artifact_storage import persist_local_output, validate_output_artifact


def test_valid_output_is_atomically_retained_on_local_volume(tmp_path):
    source = tmp_path / 'generated.dxf'
    doc = ezdxf.new('R2010')
    doc.modelspace().add_line((0, 0), (100, 100))
    doc.saveas(source)
    stored = Path(persist_local_output(7, 2, 'mechanical', source, tmp_path / 'data'))
    assert stored.exists()
    assert stored != source
    assert stored.parts[-5:] == ('7', 'output', 'R002', 'mechanical', 'generated.dxf')
    assert validate_output_artifact(stored)['status'] == 'PASS'
    assert not stored.with_name('.uploading-' + stored.name).exists()
