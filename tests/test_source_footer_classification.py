import ezdxf

from cad_engine.mechanical_design_core import _presentation_artifact_reason


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
