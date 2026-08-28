from cad_engine.sheet_cleanup_policy_v1 import should_remove_footer_entity


SHEET=(0.0,0.0,21.0,29.7)


def call(**kw):
    base=dict(
        family="GAS",
        layer="MEN",
        entity_type="LINE",
        bbox_center_x=10.0,
        bbox_center_y=6.5,
        bbox_width=5.0,
        bbox_height=0.0,
        sheet_bounds=SHEET,
        text=None,
    )
    base.update(kw)
    return should_remove_footer_entity(**base)


def test_known_stale_separator_line_can_be_removed():
    assert call() is True


def test_wall_is_never_removed_by_footer_region():
    assert call(layer="WALL", entity_type="LINE") is False


def test_door_polyline_is_never_removed_by_footer_region():
    assert call(layer="DOOR", entity_type="LWPOLYLINE", bbox_width=1.0, bbox_height=.1) is False


def test_unknown_geometry_defaults_to_preserve():
    assert call(layer="A-WALL-EXT", entity_type="LINE") is False


def test_dimensions_are_preserved_even_on_legacy_layer():
    assert call(layer="MEN", entity_type="DIMENSION") is False


def test_insert_hatch_and_arc_are_preserved():
    assert call(layer="MEN", entity_type="INSERT") is False
    assert call(layer="MEN", entity_type="HATCH") is False
    assert call(layer="MEN", entity_type="ARC") is False


def test_only_explicit_stale_text_is_removed():
    assert call(layer="MEN", entity_type="TEXT", text="پلان معماری طبقه همکف") is True
    assert call(layer="MEN", entity_type="TEXT", text="کف تمام شده +3.60") is False


def test_entities_outside_footer_band_are_preserved():
    assert call(bbox_center_y=15.0) is False


def test_engitools_entities_are_preserved():
    assert call(layer="ENGITOOLS-M-GAS", entity_type="LINE") is False
