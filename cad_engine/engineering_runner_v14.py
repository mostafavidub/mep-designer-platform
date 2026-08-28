"""End-to-end engineering pipeline v14."""
from __future__ import annotations
from .architecture_reconstruction_v14 import reconstruct_architecture
from .fixture_recognition_v14 import recognize_fixtures_equipment
from .system_requirements_v14 import derive_system_requirements
from .mechanical_calculations_v14 import calculate_mechanical_loads
from .topology_v14 import build_system_topology
from .routing_v14 import route_topology
from .sizing_v14 import size_networks
from .annotation_v14 import build_annotations
from .detail_library_v14 import build_details_schedules


def run_engineering_pipeline(src,design_basis=None,project_overrides=None):
 ov=project_overrides or {}
 arch=reconstruct_architecture(src)
 rec=recognize_fixtures_equipment(arch)
 req=derive_system_requirements(arch,rec,ov.get('system_options'))
 calc=calculate_mechanical_loads(arch,rec,req,design_basis)
 topo=build_system_topology(arch,rec,req,calc)
 routing=route_topology(arch,topo,clearance=ov.get('routing_clearance'))
 sizing=size_networks(topo,routing,rec,calc,tables=ov.get('sizing_tables'),design_basis=ov.get('sizing_design_basis'))
 ann=build_annotations(routing,sizing,rec,calc,topo)
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
 expected_routes={x['id'] for x in routing.get('routes') or []}; labelled={x.get('route_id') for x in ann.get('annotations') or [] if x.get('kind')=='route_label'}
 if expected_routes-labelled: errors.append('unannotated_routes')
 if details.get('quality',{}).get('incomplete'): warnings.append('incomplete_dynamic_details')
 return {'status':'PASS' if not errors else 'FAIL','errors':errors,'warnings':warnings,
         'metrics':{'rooms':len(arch.get('rooms') or []),'installed_objects':len(rec.get('detections') or []),'systems':len(req.get('project_systems') or []),
                    'topology_edges':len(topo.get('edges') or []),'routes':len(expected_routes),'sized_routes':sizing.get('quality',{}).get('segments_sized',0),
                    'route_labels':ann.get('quality',{}).get('route_labels',0),'complete_details':details.get('quality',{}).get('complete',0)}}
