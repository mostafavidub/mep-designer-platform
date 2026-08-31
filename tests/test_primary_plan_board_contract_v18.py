from cad_engine.mechanical_authority_site_v17 import validate_approved_manifest


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
