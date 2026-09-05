from cad_engine.mechanical_authority_v15 import build_design_overrides
from cad_engine.plan_segmentation_v13 import _plans_from_authoritative_profiles


def test_confirmed_browser_regions_bridge_into_cad_plan_scope():
    analysis={"architectural_auto":{"level_profiles":[{
        "name":"طبقه همکف", "region_bounds":[10,20,110,90],
        "level_detection_status":"confirmed", "roof":False,
    }]}}
    overrides=build_design_overrides({"_plan_analysis":analysis})
    plans=_plans_from_authoritative_profiles(overrides["authoritative_level_profiles"])
    assert len(plans)==1
    assert plans[0]["mechanical_role"]=="PRIMARY_FLOOR"
    assert plans[0]["level"]=="طبقه همکف"
    assert plans[0]["bounds"]==[10.0,20.0,110.0,90.0]


def test_candidate_browser_regions_never_become_cad_authority():
    plans=_plans_from_authoritative_profiles([{
        "name":"عنوان ضعیف", "region_bounds":[0,0,10,10],
        "level_detection_status":"candidate",
    }])
    assert plans==[]


def test_panel_transaction_carries_same_analysis_into_cad():
    from pathlib import Path
    source=(Path(__file__).parents[1]/"app/dxf_output.py").read_text()
    assert "design_answers['_plan_analysis'] = p.analysis" in source
