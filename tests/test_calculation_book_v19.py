from cad_engine.calculation_book import build_calculation_book


def check(equipment_id='IDU-1'):
    return {'equipment_id':equipment_id,'equipment_type':'split','calc_id':'CALC-1','source_pmm_ids':['PMM-1'],
            'calculated_load':10000,'selected_capacity':12000,'selection_margin_percent':20,
            'manufacturer':'Official','model':'X12','manufacturer_limits':{'max_route_length_m':25,'max_elevation_m':10},
            'route_length_m':18,'elevation_m':6,'status':'PASS'}


def test_equipment_selection_book_contains_full_manufacturer_check_and_identity():
    result=build_calculation_book([{'calc_id':'CALC-1'}],[check()],['IDU-1'])
    assert result['status']=='PASS',result
    assert result['coverage']['complete']
    row=result['sections'][0]
    assert (row['calculated_load'],row['selected_capacity'],row['selection_margin_percent'])==(10000,12000,20)
    assert row['source_pmm_ids']==['PMM-1']


def test_missing_equipment_check_and_manufacturer_limit_violation_block():
    missing=build_calculation_book([{'calc_id':'CALC-1'}],[],['IDU-1'])
    assert missing['status']=='INPUT_REQUIRED'
    bad=check(); bad['route_length_m']=30
    result=build_calculation_book([{'calc_id':'CALC-1'}],[bad],['IDU-1'])
    assert result['status']=='FAIL'
    assert 'IDU-1:ROUTE_LIMIT_EXCEEDED' in result['errors']


def test_pump_operating_point_and_fan_cfm_esp_must_lie_on_curves():
    pump={**check('P-1'),'equipment_type':'pump','operating_point':{'flow_lps':1,'head_m':20},
          'pump_curve':[[0,30],[2,10]]}
    fan={**check('EF-1'),'equipment_type':'fan','calc_id':'CALC-2','fan_duty':{'cfm':200,'esp_pa':100},
         'fan_curve':[[0,180],[300,60]]}
    result=build_calculation_book([{'calc_id':'CALC-1'},{'calc_id':'CALC-2'}],[pump,fan],['P-1','EF-1'])
    assert result['status']=='PASS',result
    fan['fan_duty']['esp_pa']=150
    result=build_calculation_book([{'calc_id':'CALC-1'},{'calc_id':'CALC-2'}],[pump,fan],['P-1','EF-1'])
    assert result['status']=='FAIL'
    assert 'EF-1:FAN_DUTY_OFF_CURVE' in result['errors']
