from cad_engine.mechanical_authority_site_v15 import (
    _critical_water_path, _served_floor_count, _water_service_mode,
)
from cad_engine.mechanical_design_core import canonical_water_service_mode


def test_typical_floor_range_expands_static_head_basis():
    authority={"project":{"levels":{"تیپ طبقات اول تا پنجم":{},"بام":{}}}}
    assert _served_floor_count(authority,{}) == 5
    assert _served_floor_count(authority,{"floor_count":7}) == 7


def test_break_tank_and_inline_modes_are_not_conflated():
    assert _water_service_mode({"water_service_mode":"break_tank_pump"}) == "break_tank_pump"
    assert _water_service_mode({"water_service_mode":"inline_booster"}) == "inline_booster"
    assert _water_service_mode({}) == ""


def test_questionnaire_water_source_maps_to_calculation_service_mode():
    assert canonical_water_service_mode({"water_source":"تأیید: کنتور شهری + مخزن + بوسترپمپ"}) == "break_tank_pump"
    assert canonical_water_service_mode({"water_source":"کنتور شهری و پمپ، بدون مخزن"}) == "inline_booster"
    assert canonical_water_service_mode({"water_source":"تغذیه مستقیم آب شهری"}) == "direct_city"
    assert canonical_water_service_mode({"water_source":"مخزن و پمپ موجود با مشخصات پروژه"}) == "break_tank_pump"


def test_explicit_service_mode_has_priority_and_ambiguous_source_stays_unresolved():
    assert canonical_water_service_mode({"water_service_mode":"direct_city","water_source":"مخزن و پمپ"}) == "direct_city"
    assert canonical_water_service_mode({"water_source":"کنتور شهری"}) is None


def test_critical_path_uses_longest_actual_cold_water_route():
    pipeline={"routing":{"routes":[
        {"id":"A","system":"cold_water","length":12},
        {"id":"B","system":"cold_water","length":40},
        {"id":"X","system":"gas","length":100},
    ]}}
    result=_critical_water_path(pipeline)
    assert result["route_id"] == "B"
    assert result["friction_head_m"] == 1.92
