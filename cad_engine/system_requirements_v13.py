"""Stage 3 — infer required mechanical systems from rooms and installed evidence."""
from __future__ import annotations

ROOM_SYSTEMS = {
    'bathroom': {'cold_water','hot_water','sanitary','vent','exhaust','heating'},
    'toilet': {'cold_water','sanitary','vent','exhaust'},
    'kitchen': {'cold_water','hot_water','sanitary','vent','exhaust','gas','heating','cooling'},
    'living': {'heating','cooling'},
    'bedroom': {'heating','cooling'},
    'parking': {'ventilation'},
    'mechanical': {'cold_water','sanitary','vent','heating'},
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


def derive_system_requirements(architecture, recognition):
    rooms = {r['id']: r for r in architecture.get('rooms') or []}
    required = {rid: set(ROOM_SYSTEMS.get(room.get('type'), set())) for rid, room in rooms.items()}
    evidence = {rid: [] for rid in rooms}
    for rid, room in rooms.items():
        for system in sorted(required[rid]):
            evidence[rid].append({'source':'room_type','value':room.get('type'),'system':system})

    for item in recognition.get('detections') or []:
        rid = item.get('room_id')
        if rid not in required:
            continue
        mapping = FIXTURE_SYSTEMS if item.get('category') == 'fixture' else EQUIPMENT_SYSTEMS
        for system in mapping.get(item.get('type'), set()):
            required[rid].add(system)
            evidence[rid].append({'source':item.get('category'),'value':item.get('type'),'system':system})

    room_rows = []
    all_systems = set()
    for rid, systems in required.items():
        all_systems.update(systems)
        room_rows.append({'room_id':rid,'room_type':rooms[rid].get('type'),'systems':sorted(systems),'evidence':evidence[rid]})
    return {
        'version':'system-requirements-v13.3',
        'rooms':room_rows,
        'project_systems':sorted(all_systems),
        'quality':{'rooms_evaluated':len(room_rows),'rooms_with_requirements':sum(1 for r in room_rows if r['systems'])},
    }
