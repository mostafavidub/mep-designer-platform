from cad_engine.hvac_calculations_v19 import calculate_cooling_design, calculate_exhaust_design


def cooling_basis():
    return {'indoor_design_c':24,'outdoor_design_c':38,'wall_u_w_m2k':0.5,'glazing_u_w_m2k':2.4,
            'solar_gain_w_m2_by_orientation':{'S':180},'people_sensible_w':75,
            'air_density_kg_m3':1.2,'air_specific_heat_j_kgk':1006,'zone_diversity':{'Z1':0.9}}


def cooling_room():
    return {'id':'R1','zone_id':'Z1','area_m2':25,'orientation':'S','glazing_area_m2':4,
            'external_wall_area_m2':18,'occupancy':3,'lighting_w':250,'equipment_w':400,
            'infiltration_m3h':40,'ventilation_m3h':60}


def test_cooling_design_exposes_every_component_and_zone_diversity():
    result=calculate_cooling_design([cooling_room()],cooling_basis())
    assert result['status']=='PASS'
    assert set(result['rooms'][0]['components_w'])=={'wall_w','glazing_conduction_w','glazing_solar_w','people_w','lighting_w','equipment_w','outdoor_air_w'}
    assert result['zones'][0]['design_load_w']==round(result['zones'][0]['connected_load_w']*.9,2)
    assert result['rooms'][0]['calc_id'].startswith('CALC-COOL-')


def test_cooling_design_never_invents_missing_orientation_or_ventilation():
    room=cooling_room(); del room['ventilation_m3h']
    result=calculate_cooling_design([room],cooling_basis())
    assert result['status']=='INPUT_REQUIRED'
    assert 'R1:ventilation_m3h' in result['missing_inputs']


def test_exhaust_duty_uses_ach_or_minimum_and_full_duct_esp():
    rooms=[{'id':'WC-1','room_type':'toilet','volume_m3':24,
            'duct_path':{'duct_friction_pa':35,'fitting_loss_pa':20,'terminal_loss_pa':15}}]
    result=calculate_exhaust_design(rooms,{'toilet':{'ach':10,'minimum_cfm':70}})
    assert result['status']=='PASS'
    assert result['rooms'][0]['required_cfm']==round(10*24*35.314667/60,2)
    assert result['rooms'][0]['required_esp_pa']==70


def test_exhaust_missing_room_criterion_is_input_required():
    rooms=[{'id':'U1','room_type':'utility','volume_m3':20,
            'duct_path':{'duct_friction_pa':1,'fitting_loss_pa':1,'terminal_loss_pa':1}}]
    result=calculate_exhaust_design(rooms,{})
    assert result['status']=='INPUT_REQUIRED'
    assert 'criteria:utility' in result['missing_inputs']
