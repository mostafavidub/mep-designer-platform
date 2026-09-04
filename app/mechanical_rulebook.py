"""Machine-readable mechanical Rule Book.

The Rule Book owns engineering rules (materials, slopes, calculation methods),
not project facts. Project facts must come from traceable DXF evidence or an
explicit user answer and unresolved facts must remain unresolved.
"""
import math
import re

from cad_engine.version_manifest import MECHANICAL_RULEBOOK_VERSION

# Active application code must never carry a second, independently maintained
# Rule Book version. Compatibility snapshots keep their historical versions.
RULEBOOK_VERSION = MECHANICAL_RULEBOOK_VERSION

NETWORK_COMPOSITION_STANDARD = {
    'topology': 'shared trunk/branch split at every terminal junction',
    'sizing': 'each segment sized from cumulative downstream load',
    'routing': 'multi-elevation 2.5D candidates with structural/RCP clash, penetration, clearance and slope checks',
    'coordination_input_policy': 'without Structural/RCP issue only PRE_SUBMISSION with NOT_COORDINATED claim',
    'manufacturer_policy': 'official hashed datasheet selection or non-confirmed Design Envelope',
    'documentation_identity': 'Plan ID=Riser ID=Calc ID=Schedule ID',
    'independent_systems': (
        'cold_water', 'hot_water', 'hot_water_return', 'sanitary', 'vent',
        'heating_supply', 'heating_return', 'cooling', 'condensate',
        'gas', 'exhaust_ventilation', 'roof_rainwater',
    ),
    'required_provenance': ('Detected', 'Calculated', 'Rule-based Proposed', 'User-confirmed'),
}

PROJECT_EVIDENCE_STANDARD = (
    'location', 'heights', 'heating', 'cooling', 'water_inlet_pressure',
    'water_source', 'water_service_connection', 'sanitary_outlet',
    'mechanical_shaft_route', 'equipment_schedule', 'gas_pressure',
    'rainfall_intensity', 'ventilation_design_basis', 'hot_water_system',
    'local_mechanical_code',
)

# Kept only for backward imports. These are suggestions, never automatic facts.
DEFAULT_HEIGHTS = None
DEFAULT_GAS_PROPOSAL = None
DEFAULT_WATER_INLET_PRESSURE = None

WATER = {
    'material': 'PPR',
    'hazen_williams_c': 150,
    'target_velocity_mps': 1.5,
    'maximum_friction_loss_kpa_per_100m': 20,
}
SANITARY = {
    'material': 'uPVC', 'branch_slope_pct': 2.0, 'main_slope_pct': 1.0,
    'wc_dn_mm': 110, 'basin_bath_dn_mm': 50, 'vent_dn_mm': 50,
}
VENTILATION = {
    'toilet_m3h_each': 90, 'bath_m3h_each': 90, 'kitchen_m3h_each': 120,
    'parking_ach': 6, 'default_parking_m3h_when_geometry_missing': 500,
}

PLAN_DETAIL_STANDARD = {
    'water_supply': ('fixture_connection', 'shared_trunk', 'cumulative_segment_size', 'branch_diameter', 'isolation_valve', 'junction_tag', 'flow_direction', 'riser_tag', 'decision_provenance'),
    'sanitary_vent': ('fixture_connection', 'shared_trunk', 'cumulative_segment_size', 'branch_diameter', 'slope_tag', 'cleanout', 'junction_tag', 'flow_direction', 'vent_tag', 'riser_tag', 'decision_provenance'),
    'heating': ('terminal_equipment', 'design_capacity', 'supply_return_tag', 'junction_tag', 'flow_direction', 'riser_tag'),
    'cooling': ('terminal_equipment', 'design_capacity', 'junction_tag', 'flow_direction', 'condensate_fall', 'outdoor_unit_location'),
    'ventilation_exhaust': ('exhaust_terminal', 'airflow_tag', 'junction_tag', 'flow_direction', 'discharge_path', 'makeup_air_path'),
    'gas': ('appliance_connection', 'pipe_diameter', 'junction_tag', 'flow_direction', 'meter_regulator', 'riser_tag'),
    'roof_rainwater': ('roof_drain', 'drain_diameter', 'rainfall_basis', 'downpipe_riser'),
}

def plan_detail_requirements(family):
    return PLAN_DETAIL_STANDARD.get(str(family or ''), ())

# Maintained values may be presented as suggestions only. They are not silently
# selected as a project design intensity.
RAIN_MM_H = {
    'تهران': 110, 'tehran': 110, 'مشهد': 90, 'mashhad': 90,
    'اصفهان': 90, 'isfahan': 90, 'شیراز': 100, 'shiraz': 100,
    'تبریز': 100, 'tabriz': 100,
}

def rainfall_mm_h(location):
    value = str(location or '').lower()
    for city, rainfall in RAIN_MM_H.items():
        if city.lower() in value:
            return rainfall
    return None

def is_confirmation(value):
    text = str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').lower()
    return text in ('تأیید', 'تایید', 'پیشنهاد بده', 'پیشنهاد شود', 'قبول', 'yes', 'ok', 'approve')

def water_inlet_pressure_basis(value):
    """Return a real numeric project pressure or None; never fabricate one."""
    text = str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').lower()
    if not text or is_confirmation(text) or any(marker in text for marker in (
        'نمی‌دانم','نمیدانم','نامشخص','اندازه‌گیری نشده','unknown','unresolved','tbd','not measured')):
        return None
    return str(value).strip() if re.search(r'\d+(?:[\.,]\d+)?\s*(?:bar|بار)', text, re.I) else None

def fixture_schedule_proposal(auto_or_levels):
    rooms = {}
    if isinstance(auto_or_levels, dict): rooms = auto_or_levels.get('room_counts') or {}
    else:
        for level in auto_or_levels or []:
            for room in level.get('rooms') or []:
                kind=room.get('room'); rooms[kind]=rooms.get(kind,0)+1
    kitchen=int(rooms.get('kitchen',0));bath=int(rooms.get('bath',0));toilet=int(rooms.get('toilet',0))
    return f'sink {kitchen}; faucet {bath + toilet}; toilet {toilet}; bath {bath}'

def roof_geometry_proposal(auto_or_levels):
    if isinstance(auto_or_levels, dict):
        rooms=auto_or_levels.get('room_counts') or {};level_count=max(1,len([x for x in auto_or_levels.get('levels') or [] if 'بام' not in str(x.get('name') or '') and 'roof' not in str(x.get('name') or '').lower()]));explicit_area=auto_or_levels.get('roof_area_m2')
    else:
        levels=[x for x in (auto_or_levels or []) if 'بام' not in str(x.get('level') or '') and 'roof' not in str(x.get('level') or '').lower()];level_count=max(1,len(levels));rooms={}
        for level in levels:
            for room in level.get('rooms') or []:
                kind=room.get('room');rooms[kind]=rooms.get(kind,0)+1
        explicit_area=None
    room_total=sum(int(x or 0) for x in rooms.values());area=float(explicit_area) if explicit_area else max(60.0,round(room_total*12.0/level_count,1));drains=max(2,int(math.ceil(area/100.0)))
    return f'{area:g} m2 roof; {drains} drains at coordinated architecture low points'

def automatic_answers(auto):
    """Return only non-project-specific technical rules.

    No heating/cooling system, pressure, equipment family, water-source topology,
    height, discharge location, gas load or rainfall intensity may be injected here.
    """
    return {
        'water_design_basis': (
            f"{WATER['material']}; Hazen-Williams C={WATER['hazen_williams_c']}; "
            f"maximum loss {WATER['maximum_friction_loss_kpa_per_100m']} kPa/100 m"
        ),
        'sanitary_design_basis': (
            f"{SANITARY['material']}; {SANITARY['branch_slope_pct']} percent branches; "
            f"{SANITARY['main_slope_pct']} percent mains"
        ),
        'mechanical_rulebook_version': RULEBOOK_VERSION,
        'questionnaire_evidence_version': '2.0',
    }

def roof_basis(location, geometry_text, rainfall_intensity=None):
    """Complete roof basis only with an explicit/evidenced rainfall intensity."""
    geometry=str(geometry_text or '').strip()
    if not geometry: return geometry
    if re.search(r'\d+(?:\.\d+)?\s*(?:mm/h|میلی.?متر)', geometry, re.I): return geometry
    raw=str(rainfall_intensity or '').strip()
    match=re.search(r'(\d+(?:[\.,]\d+)?)\s*(?:mm/h|میلی.?متر)', raw, re.I)
    if not match: return None
    return f"{geometry}; {match.group(1).replace(',', '.')} mm/h user/evidence-confirmed design rainfall"
