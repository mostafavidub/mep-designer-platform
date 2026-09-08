from cad_engine.equipment_representation_v14 import validate_equipment_integrity
from cad_engine.project_hvac_v13 import design_project_hvac


def _architecture():
    rooms=[]
    for index,x in enumerate((2.0,3.0,4.0,5.0),1):
        rooms.append({'id':f'B{index}','type':'bedroom','plan_id':'P1','label_point':(x,2.0)})
    rooms.append({'id':'T1','type':'terrace','plan_id':'P1','label_point':(9.0,9.0)})
    return {'plans':[{'plan_id':'P1','mechanical_role':'PRIMARY_FLOOR','bounds':[0,0,10,10]}],'rooms':rooms}


def _overrides():
    return {'hvac':{'cooling':'split_ac','heating':'package_radiator','city':'TEST'}}


def test_multiple_split_units_get_distinct_outdoor_geometry_and_explicit_pairs():
    result=design_project_hvac(_architecture(),_overrides())
    assert result['status']=='PASS',result
    outdoors=[row for row in result['equipment'] if row.get('kind')=='split_outdoor']
    assert len(outdoors)==4
    assert len({tuple(row['point']) for row in outdoors})==4
    assert all(row.get('serves') for row in outdoors)
    assert result['equipment_integrity']['status']=='PASS'
    assert result['equipment_integrity']['metrics']['paired_split_units']==4


def test_coincident_generated_indoor_outdoor_pair_is_hard_failure():
    rows=[{'id':'AC-I-1','kind':'split_indoor','plan_id':'P1','point':(2,2),'odu_id':'AC-O-1'},
          {'id':'AC-O-1','kind':'split_outdoor','plan_id':'P1','point':(2,2),'serves':'AC-I-1'}]
    result=validate_equipment_integrity(rows,scope_bounds={'P1':[0,0,10,10]},require_split_pairs=True)
    assert result['status']=='FAIL'
    assert 'split_pair_coincident:AC-I-1:AC-O-1' in result['errors']
