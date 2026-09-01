import ezdxf
from cad_engine.mechanical_authority_v15 import _boards, _draw_titleblock, _draw_detail_sheet, _ensure_ac_blocks, _entity_should_copy, _north_from_architecture
from cad_engine.mechanical_release_hardening_v18 import validate_layout_geometry, validate_titleblocks, validate_safe_zones, validate_equipment_linkage, validate_detail_library, validate_content_completeness, validate_split_ac_visual_legibility, create_montage_and_validate, validate_architectural_presentation


def _rows(n=8):
    return [{"old_sheet":f"S{i}","code":f"M-{i:03d}","family":"WATER",
             "level":"GROUND","title_fa":f"Sheet {i}"} for i in range(n)]


def test_gate_1_generated_boards_have_clear_safe_geometry():
    boards={key:vars(value) for key,value in _boards(_rows()).items()}
    result=validate_layout_geometry({"boards":boards})
    assert result["status"] == "PASS", result["errors"]
    assert result["minimum_clear_gap"] >= 7.5


def test_gate_1_fails_closed_on_board_overlap():
    boards={key:vars(value) for key,value in _boards(_rows(2)).items()}
    boards["S1"]["bounds"]=boards["S0"]["bounds"]
    result=validate_layout_geometry({"boards":boards})
    assert result["status"] == "FAIL"
    assert any(x.startswith("board_overlap:") for x in result["errors"])


def test_gate_2_titleblock_is_unique_complete_and_reopened(tmp_path):
    board=next(iter(_boards(_rows(1)).values())); doc=ezdxf.new("R2010")
    _draw_titleblock(doc,doc.modelspace(),board,"Project 1")
    path=tmp_path/"issued.dxf"; doc.saveas(path)
    composition={"boards":{board.sheet:vars(board)},"manifest":[{"old_sheet":board.sheet,"code":board.code}]}
    result=validate_titleblocks(path,composition)
    assert result["status"] == "PASS", result["errors"]
    assert result["exact_file_reopened"] is True


def test_gate_2_missing_titleblock_fails_closed(tmp_path):
    board=next(iter(_boards(_rows(1)).values())); doc=ezdxf.new("R2010")
    path=tmp_path/"issued.dxf"; doc.saveas(path)
    composition={"boards":{board.sheet:vars(board)},"manifest":[{"old_sheet":board.sheet,"code":board.code}]}
    assert validate_titleblocks(path,composition)["status"] == "FAIL"


def test_source_presentation_filter_removes_frame_and_footer_but_preserves_architecture():
    doc=ezdxf.new("R2013");msp=doc.modelspace();bounds=(0.0,0.0,21.0,29.7)
    frame=msp.add_lwpolyline([(0,0),(21,0),(21,29.7),(0,29.7)],close=True)
    footer=msp.add_line((2,2),(19,2),dxfattribs={"layer":"MEN"})
    wall=msp.add_line((2,2),(19,2),dxfattribs={"layer":"WALL"})
    title=msp.add_text("پلان معماری طبقه همکف",dxfattribs={"height":.2});title.dxf.insert=(5,1.5)
    assert _entity_should_copy(frame,bounds) is False
    assert _entity_should_copy(footer,bounds) is False
    assert _entity_should_copy(title,bounds) is False
    assert _entity_should_copy(wall,bounds) is True


def test_architectural_presentation_gate_rejects_duplicate_north_frame_and_subtitle(tmp_path):
    rows=[{"old_sheet":"S1","code":"M-101","family":"SANITARY_VENT","level":"GROUND","title_fa":"Plan"}]
    board=_boards(rows)["S1"];composition={"boards":{"S1":vars(board)},"manifest":rows}
    doc=ezdxf.new("R2013");doc.layers.add("ENGITOOLS-SHEET-NORTH");doc.layers.add("ENGITOOLS-SHEET-SUBTITLE");msp=doc.modelspace()
    x1,y1,x2,y2=board.plan_area
    msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)],close=True)
    msp.add_line((x2-1,y2-1),(x2-1,y2-.2),dxfattribs={"layer":"ENGITOOLS-SHEET-NORTH"})
    msp.add_text("SC:1/100",dxfattribs={"layer":"ENGITOOLS-SHEET-SUBTITLE","height":.1}).set_placement((x1+1,y1+.1))
    path=tmp_path/"dirty-presentation.dxf";doc.saveas(path)
    result=validate_architectural_presentation(path,composition)
    assert result["status"]=="FAIL"
    assert any(x.startswith("duplicate_generated_north") for x in result["errors"])
    assert any(x.startswith("forbidden_subtitle_band") for x in result["errors"])
    assert any(x.startswith("source_print_frame_present") for x in result["errors"])


def test_north_vector_is_read_from_owning_architectural_compass_without_redraw():
    doc=ezdxf.new("R2013");msp=doc.modelspace()
    msp.add_text("N",dxfattribs={"height":.2}).set_placement((10,10))
    msp.add_line((9.7,9),(10.3,9));msp.add_line((10,8.7),(10,9.3))
    north=_north_from_architecture(doc,{"bounds":(0,0,21,29.7)})
    assert north is not None
    assert abs(north["angle_deg"]-90.0)<1e-6
    rows=[{"old_sheet":"S1","code":"M-101","family":"SANITARY_VENT","level":"GROUND","title_fa":"Plan"}]
    _draw_titleblock(doc,msp,_boards(rows)["S1"])
    assert not [e for e in msp if str(getattr(e.dxf,"layer","")).upper()=="ENGITOOLS-SHEET-NORTH"]
    assert not [e for e in msp if str(getattr(e.dxf,"layer","")).upper()=="ENGITOOLS-SHEET-SUBTITLE"]


def test_gate_3_reserved_zones_are_enforced_on_exact_file(tmp_path):
    board=next(iter(_boards(_rows(1)).values())); composition={"boards":{board.sheet:vars(board)}}
    doc=ezdxf.new("R2010"); doc.layers.add("ENGITOOLS-M-WATER")
    doc.modelspace().add_line((board.plan_area[0],board.plan_area[1]),(board.plan_area[2],board.plan_area[2]),dxfattribs={"layer":"ENGITOOLS-M-WATER"})
    path=tmp_path/"safe.dxf"; doc.saveas(path)
    assert validate_safe_zones(path,composition)["status"] == "PASS"
    doc=ezdxf.readfile(path); y=(board.title_area[1]+board.title_area[3])/2
    doc.modelspace().add_line((board.title_area[0],y),(board.title_area[2],y),dxfattribs={"layer":"ENGITOOLS-M-WATER"}); doc.saveas(path)
    result=validate_safe_zones(path,composition)
    assert result["status"] == "FAIL"
    assert result["boards"][0]["intrusion_count"] == 1


def test_gate_4_equipment_requires_all_linked_routes(tmp_path):
    row=_rows(1)[0];row["family"]="HEATING";board=next(iter(_boards([row]).values())); composition={"boards":{board.sheet:vars(board)}}
    required=["ENGITOOLS-M-PACKAGE","ENGITOOLS-M-RADIATOR","ENGITOOLS-M-HEAT-FLOW","ENGITOOLS-M-HEAT-RETURN"]
    doc=ezdxf.new("R2010");p=(board.plan_area[0]+1,board.plan_area[1]+1)
    for i,layer in enumerate(required):doc.layers.add(layer);doc.modelspace().add_circle((p[0]+i,p[1]),.1,dxfattribs={"layer":layer})
    path=tmp_path/"equipment.dxf";doc.saveas(path)
    assert validate_equipment_linkage(path,composition)["status"] == "PASS"
    doc=ezdxf.readfile(path)
    for e in list(doc.modelspace()):
        if e.dxf.layer=="ENGITOOLS-M-HEAT-RETURN":doc.modelspace().delete_entity(e)
    doc.saveas(path)
    result=validate_equipment_linkage(path,composition)
    assert result["status"] == "FAIL"
    assert "ENGITOOLS-M-HEAT-RETURN" in result["errors"][0]


def _split_document(board, tiny=False):
    doc=ezdxf.new("R2010");msp=doc.modelspace()
    for i,layer in enumerate(("ENGITOOLS-M-HVAC-EQUIP","ENGITOOLS-M-HVAC-REFRIG","ENGITOOLS-M-HVAC-COND","ENGITOOLS-M-HVAC-CALLOUT","ENGITOOLS-M-HVAC-AIRFLOW"),start=1):doc.layers.add(layer,color=(i%6)+1)
    if tiny:
        b=doc.blocks.new("ENGI_AC_INDOOR");b.add_lwpolyline([(-.05,-.02),(.05,-.02),(.05,.02),(-.05,.02)],close=True);b.add_text("IDU",dxfattribs={"height":.01})
    else:_ensure_ac_blocks(doc)
    p=(board.plan_area[0]+3,board.plan_area[1]+5);msp.add_blockref("ENGI_AC_INDOOR",p,dxfattribs={"layer":"ENGITOOLS-M-HVAC-EQUIP"})
    msp.add_line(p,(p[0]+1,p[1]),dxfattribs={"layer":"ENGITOOLS-M-HVAC-REFRIG"});msp.add_line(p,(p[0],p[1]+1),dxfattribs={"layer":"ENGITOOLS-M-HVAC-COND"});msp.add_line(p,(p[0]+.8,p[1]+.8),dxfattribs={"layer":"ENGITOOLS-M-HVAC-CALLOUT"});msp.add_line(p,(p[0]-.8,p[1]),dxfattribs={"layer":"ENGITOOLS-M-HVAC-AIRFLOW"});msp.add_mtext("IDU | AC-01 | 12000 BTU/h",dxfattribs={"layer":"ENGITOOLS-M-HVAC-CALLOUT","char_height":.11}).set_location((p[0]+.9,p[1]+.9))
    return doc


def test_split_gate_requires_standard_blocks_labels_callouts_and_leaders(tmp_path):
    row=_rows(1)[0];row["family"]="SPLIT_AC";board=next(iter(_boards([row]).values()));composition={"boards":{board.sheet:vars(board)}};path=tmp_path/"split.dxf";_split_document(board).saveas(path)
    result=validate_equipment_linkage(path,composition)
    assert result["status"]=="PASS",result
    doc=ezdxf.readfile(path)
    for e in list(doc.modelspace()):
        if e.dxftype()=="INSERT":doc.modelspace().delete_entity(e)
    doc.modelspace().add_circle((board.plan_area[0]+3,board.plan_area[1]+5),.2,dxfattribs={"layer":"ENGITOOLS-M-HVAC-EQUIP"});doc.saveas(path)
    assert validate_equipment_linkage(path,composition)["status"]=="FAIL"


def test_split_visual_gate_rejects_tiny_symbol_and_writes_per_sheet_preview(tmp_path):
    row=_rows(1)[0];row["family"]="SPLIT_AC";board=next(iter(_boards([row]).values()));composition={"boards":{board.sheet:vars(board)}};path=tmp_path/"split.dxf";previews=tmp_path/"previews";_split_document(board,tiny=True).saveas(path)
    assert validate_split_ac_visual_legibility(path,composition,previews)["status"]=="FAIL"
    _split_document(board).saveas(path);result=validate_split_ac_visual_legibility(path,composition,previews)
    assert result["status"]=="PASS",result
    assert list(previews.glob("*.png"))


def test_gate_5_detail_sheet_requires_real_geometry_and_tags(tmp_path):
    row=_rows(1)[0];row["family"]="GENERAL_DETAIL";board=next(iter(_boards([row]).values()));composition={"boards":{board.sheet:vars(board)}}
    doc=ezdxf.new("R2010");_draw_detail_sheet(doc,doc.modelspace(),board,1);path=tmp_path/"details.dxf";doc.saveas(path)
    result=validate_detail_library(path,composition)
    assert result["status"] == "PASS", result["errors"]
    blank=ezdxf.new("R2010");blank.layers.add("ENGITOOLS-M-DETAIL");blank.modelspace().add_mtext("DETAIL REGISTER",dxfattribs={"layer":"ENGITOOLS-M-DETAIL"});blank.saveas(path)
    assert validate_detail_library(path,composition)["status"] == "FAIL"


def test_gate_6_each_plan_requires_content_and_annotation(tmp_path):
    board=next(iter(_boards(_rows(1)).values()));composition={"boards":{board.sheet:vars(board)}};doc=ezdxf.new("R2010");doc.layers.add("ENGITOOLS-M-WATER")
    p=(board.plan_area[0]+1,board.plan_area[1]+1);doc.modelspace().add_line(p,(p[0]+1,p[1]),dxfattribs={"layer":"ENGITOOLS-M-WATER"});doc.modelspace().add_text("CW DN25",dxfattribs={"layer":"ENGITOOLS-M-WATER","height":.1}).set_placement(p)
    path=tmp_path/"content.dxf";doc.saveas(path)
    assert validate_content_completeness(path,composition)["status"] == "PASS"
    blank=ezdxf.new("R2010");blank.saveas(path)
    assert validate_content_completeness(path,composition)["status"] == "FAIL"


def test_gate_7_exact_reopen_and_montage_are_verified(tmp_path):
    doc=ezdxf.new("R2010");doc.modelspace().add_circle((0,0),10);doc.modelspace().add_text("M-001",dxfattribs={"height":1}).set_placement((0,0))
    path=tmp_path/"issued.dxf";png=tmp_path/"montage.png";doc.saveas(path);before=path.read_bytes()
    result=create_montage_and_validate(path,png)
    assert result["status"] == "PASS", result
    assert path.read_bytes() == before
    assert png.exists() and result["montage_size_bytes"] >= 1500
