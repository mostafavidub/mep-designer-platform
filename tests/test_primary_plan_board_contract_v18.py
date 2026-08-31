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


def _generated_primary(include=17, duplicate_board=False):
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
        purpose='PLAN'
        rows.append({
            'family':family,'code':code,'level':level,'purpose':purpose,
            'old_sheet':board_id,
        })
        boards[board_id]={'plan_area':[index*20.0,0,index*20.0+18.0,12.0]}
    return {'manifest':rows,'boards':boards}


def test_release_fails_when_17_approved_primary_plans_generate_only_5_boards():
    report={'composition':_generated_primary(include=5)}
    result=validate_approved_manifest(report,{'_approved_drawing_manifest':_approved_17()})
    assert result['status']=='FAIL'
    assert result['expected_primary_plans']==16
    assert result['generated_primary_plans']==5
    assert any(x.startswith('total_primary_plan_count_mismatch:') for x in result['errors'])


def test_release_passes_primary_count_when_all_approved_primary_boards_exist():
    # 15 floor plans + cooling roof equipment is a support role + 1 roof rainwater
    # = 16 approved primary plans. The generated composition mirrors those 16.
    report={'composition':_generated_primary(include=16)}
    result=validate_approved_manifest(report,{'_approved_drawing_manifest':_approved_17()})
    count_errors=[x for x in result['errors'] if 'count_mismatch' in x or 'board_not_found' in x]
    assert not count_errors
    assert result['expected_primary_plans']==16
    assert result['generated_primary_plans']==16
    assert result['real_primary_boards']==16


def test_duplicate_primary_board_id_blocks_release_even_when_count_matches():
    report={'composition':_generated_primary(include=16,duplicate_board=True)}
    result=validate_approved_manifest(report,{'_approved_drawing_manifest':_approved_17()})
    assert result['status']=='FAIL'
    assert any(x.startswith('duplicate_generated_primary_board_ids:') for x in result['errors'])
