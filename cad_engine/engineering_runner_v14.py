"""End-to-end engineering pipeline v14."""
from __future__ import annotations
from .architecture_reconstruction_v14 import reconstruct_architecture
from .fixture_recognition_v14 import recognize_fixtures_equipment
from .system_requirements_v14 import derive_system_requirements
from .mechanical_calculations_v14 import calculate_mechanical_loads, calculate_water_service
from .hvac_calculations import calculate_cooling_design, calculate_exhaust_design
from .rainwater_calculations import design_roof_rainwater
from .calculation_book import build_calculation_book
from .annotation_solver import solve_annotations
from .manufacturer_selector_v19 import (
 select_radiators, select_package, select_split_system, select_exhaust_fans,
)
from .topology_v14 import build_system_topology
from .routing_v14 import route_topology
from .sizing_v14 import (
 size_networks, design_water_network, validate_water_drawing_sizes,
 design_heating_network, design_gas_network,
)
from .annotation_v14 import build_annotations
from .detail_library_v14 import build_details_schedules


def run_engineering_pipeline(src,design_basis=None,project_overrides=None):
 ov=project_overrides or {}
 arch=reconstruct_architecture(src)
 rec=recognize_fixtures_equipment(arch)
 req=derive_system_requirements(arch,rec,ov.get('system_options'))
 calc=calculate_mechanical_loads(arch,rec,req,design_basis)
 if ov.get('radiator_catalogue') is not None:
  room_loads=[{'room_id':row['room_id'],'heating_w':row['heating_w'],
               'radiator_id':f"RAD-{row['room_id']}"} for row in calc.get('rooms') or [] if row.get('heating_w')]
  calc['radiator_selection']=select_radiators(room_loads,ov.get('radiator_catalogue') or [],
                                               ov.get('heating_design_temperatures') or {})
  selected={row['room_id']:row for row in calc['radiator_selection'].get('radiators') or []}
  for row in calc.get('rooms') or []:
   if row['room_id'] in selected: row['radiator_candidate']=selected[row['room_id']]
 if ov.get('package_catalogue') is not None:
  calc['package_selection']=select_package(ov.get('package_requirements') or {},ov.get('package_catalogue') or [])
 if ov.get('cooling_rooms') is not None:
  calc['cooling_design']=calculate_cooling_design(ov.get('cooling_rooms') or [],ov.get('cooling_design_basis') or {})
  calc['split_selection']=select_split_system(calc['cooling_design'],ov.get('idu_catalogue') or [],
                                               ov.get('odu_catalogue') or [],ov.get('split_routes') or [],
                                               ov.get('odu_site') or {})
 if ov.get('exhaust_rooms') is not None:
  calc['exhaust_design']=calculate_exhaust_design(ov.get('exhaust_rooms') or [],ov.get('exhaust_criteria') or {})
  calc['exhaust_selection']=select_exhaust_fans(calc['exhaust_design'],ov.get('exhaust_fan_catalogue') or [])
 if ov.get('roof_rainwater') is not None:
  calc['rainwater_design']=design_roof_rainwater(ov.get('roof_rainwater') or {},
                                                 ov.get('rainwater_design_basis') or {})
 if ov.get('equipment_selection_checks') is not None:
  calc['calculation_book']=build_calculation_book(ov.get('calculation_rows') or calc.get('rooms') or [],
                                                  ov.get('equipment_selection_checks') or [],
                                                  ov.get('declared_equipment_ids') or [])
 topo=build_system_topology(arch,rec,req,calc)
 routing=route_topology(arch,topo,clearance=ov.get('routing_clearance'))
 sizing=size_networks(topo,routing,rec,calc,tables=ov.get('sizing_tables'),design_basis=ov.get('sizing_design_basis'))
 if ov.get('water_hydraulic_design') is not None:
  water=design_water_network(ov.get('water_network_segments') or [],ov.get('water_fixtures') or [],
                             ov.get('water_hydraulic_design') or {})
  drawing=[{'segment_id':row['segment_id'],'dn_mm':row['selected_dn_mm'],'size_source':row['calc_id']}
           for row in water.get('segments') or []]
  drawing_qa=validate_water_drawing_sizes(water.get('segments') or [],drawing)
  sizing.update({'water_hydraulics':water,'water_drawing_entities':drawing,
                 'water_reducers':water.get('reducers') or [],'water_drawing_validation':drawing_qa})
  if ov.get('water_service_basis') is not None:
   calc['water_service']=calculate_water_service(ov.get('water_service_basis') or {},water.get('segments') or [])
 if ov.get('heating_network_design') is not None:
  heating=design_heating_network(ov.get('heating_network_segments') or [],
                                 (calc.get('radiator_selection') or {}).get('radiators') or [],
                                 ov.get('heating_network_design') or {})
  sizing['heating_hydraulics']=heating
 if ov.get('gas_network_design') is not None:
  gas=design_gas_network(ov.get('gas_network_segments') or [],ov.get('gas_appliances') or [],
                         ov.get('gas_network_design') or {})
  sizing['gas_design']=gas
 ann=build_annotations(routing,sizing,rec,calc,topo)
 if ov.get('annotation_solver') is not None:
  request=ov.get('annotation_solver') or {}
  ann['optimized_layout']=solve_annotations(request.get('plan') or {},request.get('requests') or [],
                                             request.get('config') or {})
 details=build_details_schedules(req,rec,calc,sizing,topo,project_overrides=ov)
 return {'version':'engineering-pipeline-v14.10','architecture':arch,'recognition':rec,'requirements':req,'calculations':calc,
         'topology':topo,'routing':routing,'sizing':sizing,'annotations':ann,'details':details}


def validate_pipeline(pipeline):
 errors=[]; warnings=[]
 arch=pipeline['architecture']; rec=pipeline['recognition']; req=pipeline['requirements']; topo=pipeline['topology']; routing=pipeline['routing']; sizing=pipeline['sizing']; ann=pipeline['annotations']; details=pipeline['details']
 if not arch.get('rooms'): errors.append('no_reconstructed_rooms')
 if not arch.get('underlay_entities'): errors.append('no_architectural_underlay')
 if not rec.get('detections'): errors.append('no_installed_fixture_or_equipment_evidence')
 if not req.get('project_systems'): errors.append('no_required_mechanical_systems')
 if topo.get('quality',{}).get('provisional_shaft'): warnings.append('vertical_core_is_provisional')
 if routing.get('quality',{}).get('unrouted_edges'): errors.append('unrouted_topology_edges')
 if routing.get('quality',{}).get('obstacle_hits'): errors.append('routes_hit_structural_obstacles')
 if sizing.get('quality',{}).get('unsized_routes'): errors.append('unsized_routes')
 water=sizing.get('water_hydraulics')
 if water is not None and water.get('status')!='PASS': errors.append('water_hydraulic_design:'+water.get('status','MISSING'))
 drawing_qa=sizing.get('water_drawing_validation')
 if drawing_qa is not None and drawing_qa.get('status')!='PASS': errors.append('water_drawing_reconciliation:'+drawing_qa.get('status','MISSING'))
 water_service=pipeline.get('calculations',{}).get('water_service')
 if water_service is not None and water_service.get('status')!='PASS': errors.append('water_service_design:'+water_service.get('status','MISSING'))
 for key in ('heating_hydraulics','gas_design'):
  result=sizing.get(key)
  if result is not None and result.get('status')!='PASS': errors.append(key+':'+result.get('status','MISSING'))
 for key in ('radiator_selection','package_selection','cooling_design','split_selection','exhaust_design','exhaust_selection','rainwater_design','calculation_book'):
  result=pipeline.get('calculations',{}).get(key)
  if result is not None and result.get('status')!='PASS': errors.append(key+':'+result.get('status','MISSING'))
 expected_routes={x['id'] for x in routing.get('routes') or []}; labelled={x.get('route_id') for x in ann.get('annotations') or [] if x.get('kind')=='route_label'}
 optimized=ann.get('optimized_layout')
 if optimized is not None and optimized.get('status')!='PASS': errors.append('annotation_solver:'+optimized.get('status','MISSING'))
 if expected_routes-labelled: errors.append('unannotated_routes')
 if details.get('quality',{}).get('incomplete'): warnings.append('incomplete_dynamic_details')
 return {'status':'PASS' if not errors else 'FAIL','errors':errors,'warnings':warnings,
         'metrics':{'rooms':len(arch.get('rooms') or []),'installed_objects':len(rec.get('detections') or []),'systems':len(req.get('project_systems') or []),
                    'topology_edges':len(topo.get('edges') or []),'routes':len(expected_routes),'sized_routes':sizing.get('quality',{}).get('segments_sized',0),
                    'route_labels':ann.get('quality',{}).get('route_labels',0),'complete_details':details.get('quality',{}).get('complete',0)}}
