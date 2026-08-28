"""System Requirement Engine v14.

Separates code/room-driven base services from equipment-dependent conditional
services.  This avoids inventing gas/HVAC merely because a room is named kitchen
or bedroom, while still making every requirement traceable.
"""
from __future__ import annotations

BASE_BY_ROOM={
 'bathroom':{'cold_water','hot_water','sanitary','vent','exhaust'},
 'toilet':{'cold_water','sanitary','vent','exhaust'},
 'kitchen':{'cold_water','hot_water','sanitary','vent','exhaust'},
 'living':set(),'bedroom':set(),'parking':set(),'mechanical':set(),
}
CONDITIONAL_BY_ROOM={
 'bathroom':{'heating'},'toilet':{'heating'},'kitchen':{'gas','heating','cooling'},
 'living':{'heating','cooling'},'bedroom':{'heating','cooling'},'parking':{'ventilation'},
 'mechanical':{'cold_water','sanitary','vent','heating'},
}
EQUIPMENT_SYSTEMS={
 'radiator':{'heating'},'fan_coil':{'heating','cooling','condensate'},
 'split_indoor':{'cooling','condensate'},'split_outdoor':{'cooling'},
 'exhaust_fan':{'exhaust'},'hood':{'exhaust'},'pump':{'cold_water'},'tank':{'cold_water'},
 'water_heater':{'cold_water','hot_water'},'stove':{'gas'},
}
FIXTURE_SYSTEMS={
 'wc':{'cold_water','sanitary','vent'},'basin':{'cold_water','hot_water','sanitary','vent'},
 'sink':{'cold_water','hot_water','sanitary','vent'},'shower':{'cold_water','hot_water','sanitary','vent'},
 'floor_drain':{'sanitary'},
}

def derive_system_requirements(architecture,recognition,project_options=None):
 options=project_options or {}; rooms={r['id']:r for r in architecture.get('rooms') or []}
 installed_by_room={rid:[] for rid in rooms}
 for item in recognition.get('detections') or []:
  if item.get('room_id') in installed_by_room: installed_by_room[item['room_id']].append(item)
 rows=[]; project=set(); unresolved=[]
 for rid,room in rooms.items():
  base=set(BASE_BY_ROOM.get(room.get('type'),set())); conditional=set(CONDITIONAL_BY_ROOM.get(room.get('type'),set()))
  evidence=[{'system':s,'source':'room_base','value':room.get('type')} for s in sorted(base)]
  required=set(base)
  for item in installed_by_room[rid]:
   mapping=FIXTURE_SYSTEMS if item.get('category')=='fixture' else EQUIPMENT_SYSTEMS
   for system in mapping.get(item.get('type'),set()):
    required.add(system); conditional.discard(system)
    evidence.append({'system':system,'source':item.get('category'),'value':item.get('type'),'object_id':item.get('id')})
  forced=set(options.get('required_systems') or [])
  for system in forced:
   required.add(system); conditional.discard(system); evidence.append({'system':system,'source':'project_option','value':'required_systems'})
  disabled=set(options.get('disabled_systems') or [])
  required-=disabled; conditional-=disabled
  for system in sorted(conditional): unresolved.append({'room_id':rid,'system':system,'reason':'equipment_or_design_basis_not_confirmed'})
  project.update(required)
  rows.append({'room_id':rid,'room_type':room.get('type'),'required':sorted(required),'conditional':sorted(conditional),'evidence':evidence})
 return {'version':'system-requirements-v14.3','rooms':rows,'project_systems':sorted(project),'unresolved_conditionals':unresolved,
         'quality':{'rooms_evaluated':len(rows),'rooms_with_required_systems':sum(bool(x['required']) for x in rows),
                    'required_system_count':len(project),'unresolved_conditionals':len(unresolved)}}
