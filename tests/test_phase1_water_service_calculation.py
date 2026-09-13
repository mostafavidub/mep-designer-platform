from cad_engine.mechanical_authority_site_v15 import (
    _critical_water_path, _served_floor_count, _water_service_mode,
)


def test_typical_floor_range_expands_static_head_basis():
    authority={"project":{"levels":{"تیپ طبقات اول تا پنجم":{},"بام":{}}}}
    assert _served_floor_count(authority,{}) == 5
    assert _served_floor_count(authority,{"floor_count":7}) == 7


def test_break_tank_and_inline_modes_are_not_conflated():
    assert _water_service_mode({"water_service_mode":"break_tank_pump"}) == "break_tank_pump"
    assert _water_service_mode({"water_service_mode":"inline_booster"}) == "inline_booster"
    assert _water_service_mode({}) == ""


def test_critical_path_uses_longest_actual_cold_water_route():
    pipeline={"routing":{"routes":[
        {"id":"A","system":"cold_water","length":12},
        {"id":"B","system":"cold_water","length":40},
        {"id":"X","system":"gas","length":100},
    ]}}
    result=_critical_water_path(pipeline)
    assert result["route_id"] == "B"
    assert result["friction_head_m"] == 1.92
