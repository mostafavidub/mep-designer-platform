from cad_engine.rainwater_calculations_v19 import design_roof_rainwater


def basis():
    return {'rainfall_intensity_mm_h':100,'runoff_coefficient':1.0,'minimum_slope_percent':2,
            'drain_capacity_table':[{'dn_mm':75,'max_flow_lps':3},{'dn_mm':110,'max_flow_lps':8}],
            'downpipe_capacity_table':[{'dn_mm':90,'max_flow_lps':4},{'dn_mm':110,'max_flow_lps':8}]}


def roof():
    return {'roof_id':'ROOF-1','boundary':[[0,0],[20,0],[20,10],[0,10]],
            'stacks':[{'id':'RW-1','point':[10,5]}],
            'catchments':[{'id':'C1','polygon':[[0,0],[10,0],[10,10],[0,10]],'low_point':[5,5],
              'drain':{'id':'RD-1','point':[5,5]},'stack_id':'RW-1','slope_percent':2,
              'emergency_overflow':{'id':'OF-1','point':[0,5]}}]}


def test_roof_rainwater_materializes_catchment_flow_drain_downpipe_and_identity():
    result=design_roof_rainwater(roof(),basis())
    assert result['status']=='PASS',result
    row=result['catchments'][0]
    assert row['area_m2']==100
    assert row['design_flow_lps']==round(100*100/3600,4)
    assert row['drain_dn_mm']==75
    assert row['downpipe_dn_mm']==90
    assert result['coverage']['all_catchments_drained']
    segment=result['segments'][0]
    assert len({segment['calc_id'],segment['plan_id'],segment['riser_id'],segment['schedule_id']})==1


def test_missing_catchment_plan_or_rainfall_is_input_required_not_a_proposal():
    value=roof(); value['catchments']=[]
    assert design_roof_rainwater(value,basis())['status']=='INPUT_REQUIRED'
    design=basis(); del design['rainfall_intensity_mm_h']
    result=design_roof_rainwater(roof(),design)
    assert result['status']=='INPUT_REQUIRED'
    assert 'design_basis.rainfall_intensity_mm_h' in result['missing_inputs']


def test_low_point_slope_capacity_and_stack_errors_fail_closed():
    value=roof(); value['catchments'][0].update({'low_point':[30,30],'slope_percent':1,'stack_id':'UNKNOWN'})
    value['catchments'][0]['drain']['point']=[30,30]
    result=design_roof_rainwater(value,basis())
    assert result['status']=='FAIL'
    assert any('LOW_POINT_OUTSIDE' in error for error in result['errors'])
    assert 'C1:SLOPE_BELOW_MINIMUM' in result['errors']
    assert 'C1:UNKNOWN_STACK' in result['errors']
