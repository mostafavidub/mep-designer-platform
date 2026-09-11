from pathlib import Path

import ezdxf

from cad_engine.plan_segmentation import analyze_plan_frames, detect_print_plans


def _drawing(path: Path, frames):
    doc=ezdxf.new("R2013");doc.layers.add("suport");msp=doc.modelspace()
    for i,(x,y,w,h,title) in enumerate(frames):
        msp.add_lwpolyline([(x,y),(x+w,y),(x+w,y+h),(x,y+h)],close=True,dxfattribs={"layer":"suport"})
        msp.add_text(title,dxfattribs={"height":.2}).dxf.insert=(x+1,y+h-2)
        msp.add_text(f"Arc - {i+1:02d}",dxfattribs={"height":.2}).dxf.insert=(x+1,y+1)
        for n in range(30):
            yy=y+3+(n%10)*.5;xx=x+2+(n//10)*2
            msp.add_line((xx,yy),(xx+1,yy),dxfattribs={"layer":"0"})
    doc.saveas(path)


def test_portrait_landscape_and_custom_repeated_frames_are_all_detected(tmp_path):
    path=tmp_path/"mixed.dxf"
    _drawing(path,[(0,0,21,29.7,"پلان معماری طبقه همکف"),
                   (35,0,29.7,21,"پلان معماری طبقه اول"),
                   (0,40,27.47,42.57,"پلان معماری طبقه دوم"),
                   (35,40,27.47,42.57,"پلان معماری طبقه سوم")])
    result=analyze_plan_frames(path);plans=detect_print_plans(path)
    assert result["status"]=="PASS"
    assert result["accepted_count"]==4
    assert len(plans)==4
    assert {p["level"] for p in plans}=={"GROUND","LEVEL-01","LEVEL-02","LEVEL-03"}
    assert all(p["frame_confidence"]>=70 for p in plans)


def test_typical_floor_range_is_preserved_instead_of_collapsed(tmp_path):
    path=tmp_path/"typical.dxf"
    _drawing(path,[(0,0,29.7,21,"پلان معماری طبقات اول تا سوم")])
    plans=detect_print_plans(path)
    assert plans[0]["represented_levels"]==["LEVEL-01","LEVEL-02","LEVEL-03"]
    assert plans[0]["mechanical_role"]=="PRIMARY_FLOOR"


def test_unlabelled_room_rectangle_is_not_a_sheet(tmp_path):
    path=tmp_path/"room.dxf";doc=ezdxf.new("R2013");msp=doc.modelspace()
    for x in (0,20):
        msp.add_lwpolyline([(x,0),(x+10,0),(x+10,7),(x,7)],close=True,dxfattribs={"layer":"WALL"})
    doc.saveas(path)
    result=analyze_plan_frames(path)
    assert result["status"]=="INPUT_REQUIRED"
    assert result["accepted_count"]==0
    assert detect_print_plans(path)==[]


def test_inset_wall_border_does_not_duplicate_print_frame(tmp_path):
    path=tmp_path/"nested.dxf"
    _drawing(path,[(0,0,21,29.7,"پلان معماری طبقه همکف")])
    doc=ezdxf.readfile(path);msp=doc.modelspace()
    msp.add_lwpolyline([(1,1),(20,1),(20,28.7),(1,28.7)],close=True,dxfattribs={"layer":"WALL"})
    doc.saveas(path)
    assert len(detect_print_plans(path))==1
