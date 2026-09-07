from pathlib import Path

from cad_engine.engineering_runner_v13 import _add_locked_design_endpoints


def test_mechanical_request_passes_plan_analysis_into_authority_answers():
    source=Path("cad_engine/main_v15.py").read_text(encoding="utf-8")
    assert 'design_answers["_plan_analysis"]=dict(req.plan_analysis or {})' in source
    assert "answers=design_answers" in source


def test_isolated_version_keeps_manifest_wrapper_for_panel_identity():
    source=Path("cad_engine/isolated_service.py").read_text(encoding="utf-8")
    assert "def version(): return active_version_manifest()" in source


def test_package_radiator_creates_one_gas_endpoint_on_every_plan():
    architecture={
        "plans":[{"plan_id":"P1"},{"plan_id":"P2"}],
        "rooms":[
            {"id":"R1","plan_id":"P1","type":"living","label_point":[1,1]},
            {"id":"R2","plan_id":"P2","type":"living","label_point":[11,1]},
            {"id":"R3","plan_id":"P2","type":"kitchen","label_point":[12,1]},
        ],
    }
    result=_add_locked_design_endpoints(
        architecture,{"detections":[]},{"gas_service":True,"heating_system":"package_radiator"}
    )
    heaters=[row for row in result["detections"] if row.get("type")=="water_heater"]
    assert {row["plan_id"] for row in heaters}=={"P1","P2"}
    assert len(heaters)==2
