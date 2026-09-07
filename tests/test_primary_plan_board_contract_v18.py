import ezdxf

from cad_engine.mechanical_authority_site_v17 import validate_approved_manifest
from cad_engine.mechanical_authority_site_v15 import qa_semantic_sheet_content
from cad_engine.mechanical_release_hardening_v18 import validate_equipment_linkage
from cad_engine.mechanical_authority_v15 import (
    Board, _append_approved_service_plan_boards, _draw_service_equipment_content,
    _layout_manifest,
)


def _approved_17():
    rows=[]
    families=[
        ('water_supply','M-W'),
        ('sanitary_vent','M-S'),
        ('heating','M-H'),
        ('cooling','M-C'),
        ('gas','M-G'),
    ]
    levels=['GROUND','LEVEL 1','LEVEL 2']
    for family,prefix in families:
        for i,level in enumerate(levels,1):
            rows.append({
                'family':family,
                'code':f'{prefix}-{i:02d}',
                'pattern':level,
                'levels':[level],
                'drawing_type':'floor_plan',
            })
    rows.append({
        'family':'cooling','code':'M-C-EQUIP','pattern':'ROOF','levels':['ROOF'],
        'drawing_type':'equipment_plan','special':True,
    })
    rows.append({
        'family':'roof_rainwater','code':'M-R-01','pattern':'ROOF','levels':['ROOF'],
        'drawing_type':'roof_plan',
    })
    return {'schema_version':'3.0','total_sheets':len(rows),'sheets':rows}


def _generated_plans(include=17, duplicate_board=False):
    rows=[]; boards={}
    mapping=[
        ('WATER','M-W'),('SANITARY_VENT','M-S'),('HEATING','M-H'),
        ('SPLIT_AC','M-C'),('GAS','M-G'),
    ]
    levels=['GROUND','LEVEL 1','LEVEL 2']
    specs=[]
    for family,prefix in mapping:
        for i,level in enumerate(levels,1):
            specs.append((family,f'{prefix}-{i:02d}',level))
    specs.append(('SPLIT_AC','M-C-ROOF','ROOF'))
    specs.append(('ROOF','M-R-01','ROOF'))
    for index,(family,code,level) in enumerate(specs[:include],1):
        board_id='BOARD-01' if duplicate_board and index==2 else f'BOARD-{index:02d}'
        rows.append({
            'family':family,'code':code,'level':level,'purpose':'PLAN',
            'old_sheet':board_id,
        })
        boards[board_id]={'plan_area':[index*20.0,0,index*20.0+18.0,12.0]}
    return {'manifest':rows,'boards':boards}


def test_release_fails_when_17_approved_plans_generate_only_5_boards():
    report={'composition':_generated_plans(include=5)}
    result=validate_approved_manifest(report,{'_approved_drawing_manifest':_approved_17()})
    assert result['status']=='FAIL'
    assert result['expected_plan_count']==17
    assert result['generated_plan_count']==5
    assert any(x.startswith('total_plan_count_mismatch:approved=17:generated=5') for x in result['errors'])


def test_release_has_exact_17_plan_board_parity_when_all_plans_exist():
    report={'composition':_generated_plans(include=17)}
    result=validate_approved_manifest(report,{'_approved_drawing_manifest':_approved_17()})
    count_errors=[x for x in result['errors'] if 'count_mismatch' in x or 'board_not_found' in x or 'missing_board_id' in x]
    assert not count_errors
    assert result['expected_plan_count']==17
    assert result['generated_plan_count']==17
    assert result['real_plan_board_count']==17


def test_duplicate_plan_board_id_blocks_release_even_when_count_matches():
    report={'composition':_generated_plans(include=17,duplicate_board=True)}
    result=validate_approved_manifest(report,{'_approved_drawing_manifest':_approved_17()})
    assert result['status']=='FAIL'
    assert any(x.startswith('duplicate_generated_plan_board_ids:') for x in result['errors'])


def test_approved_equipment_plans_are_materialized_as_distinct_service_boards():
    approved = [
        {'family':'water_supply','code':'M-W-EQUIP','label':'Water equipment','drawing_type':'equipment_plan'},
        {'family':'heating','code':'M-H-EQUIP','label':'Heating equipment','drawing_type':'equipment_plan'},
        {'family':'cooling','code':'M-C-EQUIP','label':'Cooling equipment','drawing_type':'equipment_plan'},
    ]
    manifest = {'sheets':[{'sheet':'M-00','family':'WATER','level':'LEVEL-01','purpose':'PLAN'}]}
    _append_approved_service_plan_boards(manifest, approved)
    rows = _layout_manifest({'manifest':manifest})
    service = [row for row in rows if row['level'] == 'SERVICE']
    assert [row['code'] for row in service] == ['M-W-EQUIP','M-H-EQUIP','M-C-EQUIP']
    assert [row['family'] for row in service] == ['WATER','HEATING','SPLIT_AC']
    assert all(row['purpose'] == 'PLAN' for row in service)


def test_service_equipment_boards_have_family_specific_semantic_content(tmp_path):
    doc=ezdxf.new('R2010');msp=doc.modelspace();boards={};manifest=[]
    for index,family in enumerate(('WATER','HEATING','SPLIT_AC')):
        x1=index*30.0
        board=Board(f'B{index}',f'M-{index}',family,'SERVICE',f'{family} equipment',(x1,0,x1+21,29.7),(x1+1,4,x1+20,28),(x1,0,x1+21,3),(x1,3,x1+21,4))
        boards[board.sheet]=vars(board)
        manifest.append({'old_sheet':board.sheet,'code':board.code,'family':family,'level':'SERVICE','purpose':'PLAN'})
        _draw_service_equipment_content(doc,msp,board,{'hvac':{'equipment':[]}}, {})
    path=tmp_path/'service-plans.dxf';doc.saveas(path)
    result=qa_semantic_sheet_content(path,{'boards':boards,'manifest':manifest})
    assert result['status']=='PASS'
    assert result['missing_family_content']==[]
    linkage=validate_equipment_linkage(path,{'boards':boards,'manifest':manifest})
    assert linkage['status']=='PASS', linkage
