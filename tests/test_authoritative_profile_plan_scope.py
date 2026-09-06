from pathlib import Path

import ezdxf

from cad_engine.engineering_pipeline_v13 import reconstruct_architecture, recognize_fixtures_equipment
from cad_engine.plan_segmentation_v13 import apply_plan_scopes


def _duplicate_title_file(path: Path):
    doc = ezdxf.new("R2013")
    msp = doc.modelspace()
    for offset in (0.0, 40.0):
        msp.add_lwpolyline(
            [(offset, 0), (offset + 21, 0), (offset + 21, 29), (offset, 29)],
            close=True,
            dxfattribs={"layer": "suport"},
        )
        msp.add_text("طبقه اول پلان معماری").set_placement((offset + 2, 2))
        msp.add_text("آشپزخانه").set_placement((offset + 7, 10))
        msp.add_text("حمام").set_placement((offset + 13, 10))
    doc.saveas(path)


def test_sealed_profiles_preserve_distinct_plans_with_duplicate_local_titles(tmp_path):
    src = tmp_path / "duplicate-titles.dxf"
    _duplicate_title_file(src)
    architecture = reconstruct_architecture(src)
    recognition = recognize_fixtures_equipment(architecture)
    profiles = [
        {
            "name": "طبقه اول - بلوک الف",
            "region_bounds": [0, 0, 21, 29],
            "level_detection_status": "confirmed",
        },
        {
            "name": "طبقه اول - بلوک ب",
            "region_bounds": [40, 0, 61, 29],
            "level_detection_status": "confirmed",
        },
    ]

    architecture, recognition = apply_plan_scopes(src, architecture, recognition, profiles)

    primary = [p for p in architecture["plans"] if p["mechanical_role"] == "PRIMARY_FLOOR"]
    assert [p["level"] for p in primary] == ["طبقه اول - بلوک الف", "طبقه اول - بلوک ب"]
    assert architecture["primary_floor_plan_ids"] == ["PLAN-AUTH-01", "PLAN-AUTH-02"]
    assert {r["plan_id"] for r in architecture["rooms"]} == {"PLAN-AUTH-01", "PLAN-AUTH-02"}


def test_unconfirmed_profile_cannot_override_detected_architecture(tmp_path):
    src = tmp_path / "detected-floor.dxf"
    _duplicate_title_file(src)
    architecture = reconstruct_architecture(src)
    recognition = recognize_fixtures_equipment(architecture)
    profiles = [{
        "name": "untrusted",
        "region_bounds": [0, 0, 21, 29],
        "level_detection_status": "candidate",
    }]

    architecture, _ = apply_plan_scopes(src, architecture, recognition, profiles)

    assert architecture["primary_floor_plan_ids"] == ["PLAN-01"]
