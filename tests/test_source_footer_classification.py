import ezdxf

from cad_engine.mechanical_design_core import _presentation_artifact_reason, _entities_in_bounds


BOUNDS=(0.0,0.0,30.0,20.0)


def _mtext(value,insert,width,layer):
    doc=ezdxf.new("R2010");doc.layers.add(layer);entity=doc.modelspace().add_mtext(
        value,dxfattribs={"layer":layer,"char_height":.3})
    entity.dxf.insert=insert;entity.dxf.width=width
    return entity


def test_long_repeated_footer_note_is_source_furniture():
    note=_mtext(
        "ارتفاع نرده های حفاظتی و جان پناه ها حداقل متر است " * 4,
        (1,.8),
        20,
        "construction",
    )
    assert _presentation_artifact_reason(note,BOUNDS)=="SOURCE_FOOTER_BAND"


def test_arc_code_and_scale_fraction_are_source_footer_furniture():
    assert _presentation_artifact_reason(_mtext("ARC 03",(1,.8),3,"Dime-Arch"),BOUNDS)=="SOURCE_FOOTER_BAND"
    assert _presentation_artifact_reason(_mtext("1/10",(10,.8),3,"DATABASEP7"),BOUNDS)=="SOURCE_FOOTER_BAND"


def test_in_plan_room_note_is_never_removed_by_text_shape_alone():
    note=_mtext("آشپزخانه",(10,10),5,"construction")
    assert _presentation_artifact_reason(note,BOUNDS) is None


def test_nonsemantic_text_spanning_neighbouring_print_frames_is_removed():
    note=_mtext("LONG SOURCE SHEET NOTE "*30,(10,10),60,"construction")
    assert _presentation_artifact_reason(note,BOUNDS)=="SOURCE_CROSS_FRAME_TEXT"


def test_cross_frame_architectural_text_on_semantic_layer_is_preserved():
    note=_mtext("ARCHITECTURAL GRID NOTE "*30,(10,10),60,"wall-note")
    assert _presentation_artifact_reason(note,BOUNDS) is None


def test_a4_border_inset_five_percent_is_removed_even_when_mislabeled_wall():
    doc=ezdxf.new("R2010");doc.layers.add("WALL")
    frame=doc.modelspace().add_lwpolyline(
        [(1,1),(29,1),(29,19),(1,19)],close=True,dxfattribs={"layer":"WALL"})
    assert _presentation_artifact_reason(frame,BOUNDS)=="SOURCE_PRINT_FRAME"


def test_smaller_closed_wall_outline_is_not_classified_as_sheet_border():
    doc=ezdxf.new("R2010");doc.layers.add("WALL")
    building=doc.modelspace().add_lwpolyline(
        [(3,3),(27,3),(27,17),(3,17)],close=True,dxfattribs={"layer":"WALL"})
    assert _presentation_artifact_reason(building,BOUNDS) is None


def test_fragmented_bottom_frame_on_wall_layer_is_removed_only_when_connected():
    doc=ezdxf.new("R2010");doc.layers.add("WALL");msp=doc.modelspace()
    frame_bottom=msp.add_line((4.6,1.5),(29.4,1.5),dxfattribs={"layer":"WALL"})
    frame_stub=msp.add_line((4.6,.4),(4.6,1.5),dxfattribs={"layer":"WALL"})
    real_wall=msp.add_line((8,5),(24,5),dxfattribs={"layer":"WALL"})
    selected=_entities_in_bounds(msp,BOUNDS)
    assert frame_bottom not in selected
    assert frame_stub not in selected
    assert real_wall in selected


def test_isolated_long_lower_wall_is_preserved_without_frame_topology():
    doc=ezdxf.new("R2010");doc.layers.add("WALL");msp=doc.modelspace()
    wall=msp.add_line((4.6,1.5),(29.4,1.5),dxfattribs={"layer":"WALL"})
    assert wall in _entities_in_bounds(msp,BOUNDS)
