from app.mechanical_drawing_set import predict_drawing_set


def test_multilevel_direct_municipal_water_does_not_create_pump_or_tank_plan():
    scope={
        'all_levels':['GROUND','LEVEL 1','LEVEL 2'],
        'wet_fixture_levels':['GROUND','LEVEL 1','LEVEL 2'],
        'sanitary_fixture_levels':['GROUND','LEVEL 1','LEVEL 2'],
        'heated_levels':['GROUND','LEVEL 1','LEVEL 2'],
        'conditioned_levels':['GROUND','LEVEL 1','LEVEL 2'],
        'gas_consumer_levels':['GROUND','LEVEL 1','LEVEL 2'],
        'ventilation_required_levels':[],
        'roof_exists':True,
        'roof_level_name':'ROOF',
        'vertical_systems':True,
        'central_water_equipment':False,
        'hot_water_return_required':False,
        'enclosed_parking':False,
    }
    proposal=predict_drawing_set(scope)
    water=proposal['sheet_families']['water_supply']['sheets']
    assert not any(s.get('drawing_type')=='equipment_plan' for s in water)
    assert not any(s.get('drawing_type')=='calculation_sheet' for s in water)
    plan_types={'floor_plan','roof_plan','equipment_plan','ventilation_plan'}
    plans=[s for s in proposal['deliverable_sheets'] if s.get('drawing_type') in plan_types]
    assert len(plans)==17
    assert proposal['drawing_manifest']['schema_version']=='3.1'
