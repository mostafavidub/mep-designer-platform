import ezdxf
from ezdxf import bbox

from cad_engine.engineering_pipeline_v13 import reconstruct_architecture


def test_reconstruction_bounds_are_derived_without_global_bbox_cache(tmp_path, monkeypatch):
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_line((10, 20), (40, 60))
    msp.add_lwpolyline([(15, 25), (30, 25), (30, 45), (15, 45)], close=True)
    source = tmp_path / "architecture.dxf"
    doc.saveas(source)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("global ezdxf bbox cache must not be built")

    monkeypatch.setattr(bbox, "extents", fail_if_called)
    result = reconstruct_architecture(source)

    assert result["bounds"] == [10.0, 20.0, 40.0, 60.0]
    assert result["quality"]["wall_segments"] >= 1
