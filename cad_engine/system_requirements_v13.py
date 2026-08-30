"""Stage 3 — derive required mechanical systems from architecture and locked project basis.

Optional plant systems (heating, cooling and gas) must never be inferred merely
from room type. They are activated only by an explicit, supported design basis.
Architectural room/fixture evidence may still establish plumbing/vent/exhaust
needs because those systems are intrinsic to the detected use of the room.
"""
from __future__ import annotations

ROOM_SYSTEMS = {
    'bathroom': {'cold_water','hot_water','sanitary','vent','exhaust'},
    'toilet': {'cold_water','sanitary','vent','exhaust'},
    'kitchen': {'cold_water','hot_water','sanitary','vent','exhaust'},
    'living': set(),
    'bedroom': set(),
    'parking': {'ventilation'},
    'mechanical': {'cold_water','sanitary','vent'},
}

FIXTURE_SYSTEMS = {
    'wc': {'cold_water','sanitary','vent'},
    'basin': {'cold_water','hot_water','sanitary','vent'},
    'sink': {'cold_water','hot_water','sanitary','vent'},
    'shower': {'cold_water','hot_water','sanitary','vent'},
    'floor_drain': {'sanitary','vent'},
}

EQUIPMENT_SYSTEMS = {
    'radiator': {'heating'}, 'fan_coil': {'heating','cooling','condensate'},
    'split_indoor': {'cooling','condensate'}, 'exhaust_fan': {'exhaust'},
    'hood': {'exhaust'}, 'pump': {'cold_water'}, 'tank': {'cold_water'},
    'water_heater': {'hot_water'}, 'stove': {'gas'},
}

OPTIONAL_SYSTEMS={'heating','cooling','gas','condensate'}


def _allowed_optional_systems(design_basis):
    basis=dict(design_basis or {})
    allowed=set()
    if basis.get('heating_system'):
        allowed.add('heating')
    if basis.get('cooling_system'):
        allowed.update({'cooling','condensate'})
    if basis.get('gas_service') is True:
        allowed.add('gas')
    return allowed


def derive_system_requirements(architecture, recognition, design_basis=None):
    rooms = {r['id']: r for r in architecture.get('rooms') or []}
    allowed_optional=_allowed_optional_systems(design_basis)
    required = {rid: set(ROOM_SYSTEMS.get(room.get('type'), set())) for rid, room in rooms.items()}
    evidence = {rid: [] for rid in rooms}
    for rid, room in rooms.items():
        room_type=room.get('type')
        # User-locked optional systems are applied only to rooms they can serve.
        if 'heating' in allowed_optional and room_type in {'bathroom','kitchen','living','bedroom'}:
            required[rid].add('heating')
            evidence[rid].append({'source':'design_basis','value':design_basis.get('heating_system'),'system':'heating'})
        if 'cooling' in allowed_optional and room_type in {'kitchen','living','bedroom'}:
            required[rid].add('cooling')
            evidence[rid].append({'source':'design_basis','value':design_basis.get('cooling_system'),'system':'cooling'})
        if 'gas' in allowed_optional and room_type=='kitchen':
            required[rid].add('gas')
            evidence[rid].append({'source':'design_basis','value':'gas_service','system':'gas'})
        for system in sorted(required[rid]):
            if not any(x.get('system')==system for x in evidence[rid]):
                evidence[rid].append({'source':'room_type','value':room_type,'system':system})

    for item in recognition.get('detections') or []:
        rid = item.get('room_id')
        if rid not in required:
            continue
        mapping = FIXTURE_SYSTEMS if item.get('category') == 'fixture' else EQUIPMENT_SYSTEMS
        for system in mapping.get(item.get('type'), set()):
            if system in OPTIONAL_SYSTEMS and system not in allowed_optional:
                # Existing/source symbols are evidence, not authority to silently
                # change the user's selected plant system.
                continue
            required[rid].add(system)
            evidence[rid].append({'source':item.get('category'),'value':item.get('type'),'system':system})

    room_rows = []
    all_systems = set()
    for rid, systems in required.items():
        all_systems.update(systems)
        room_rows.append({'room_id':rid,'room_type':rooms[rid].get('type'),'systems':sorted(systems),'evidence':evidence[rid]})
    return {
        'version':'system-requirements-v13.4',
        'rooms':room_rows,
        'project_systems':sorted(all_systems),
        'design_basis':dict(design_basis or {}),
        'quality':{'rooms_evaluated':len(room_rows),'rooms_with_requirements':sum(1 for r in room_rows if r['systems'])},
    }
