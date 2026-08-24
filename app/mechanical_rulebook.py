"""Machine-readable mechanical Rule Book defaults.

These are design rules, not customer facts.  The questionnaire must not ask a
customer to provide values that the Rule Book or Code Designer owns.
"""

import math
import re


RULEBOOK_VERSION = '1.7'

DEFAULT_HEIGHTS = '3.20 m floor-to-floor; 0.40 m false ceiling in wet/service zones'
DEFAULT_GAS_PROPOSAL = 'boiler 24 kW and cooker 10 kW; 21 mbar; meter/regulator at entrance'
DEFAULT_WATER_INLET_PRESSURE = (
    '2.5 bar conservative design basis at property inlet; storage tank and booster pump '
    'maintain calculated residual pressure'
)

WATER = {
    'material': 'PPR',
    'hazen_williams_c': 150,
    'target_velocity_mps': 1.5,
    'maximum_friction_loss_kpa_per_100m': 20,
}

SANITARY = {
    'material': 'uPVC',
    'branch_slope_pct': 2.0,
    'main_slope_pct': 1.0,
    'wc_dn_mm': 110,
    'basin_bath_dn_mm': 50,
    'vent_dn_mm': 50,
}

VENTILATION = {
    'toilet_m3h_each': 90,
    'bath_m3h_each': 90,
    'kitchen_m3h_each': 120,
    'parking_ach': 6,
    'default_parking_m3h_when_geometry_missing': 500,
}

# Minimum *plan-visible* technical content.  This is deliberately separate
# from a sheet-count rule: a drawing family is not complete merely because a
# layout exists.  The Code Designer turns the applicable items into tagged
# plan symbols and schedule entries, using calculated values rather than a
# project-specific canned drawing.
PLAN_DETAIL_STANDARD = {
    'water_supply': ('fixture_connection', 'branch_diameter', 'isolation_valve', 'riser_tag'),
    'sanitary_vent': ('fixture_connection', 'branch_diameter', 'slope_tag', 'cleanout', 'vent_tag', 'riser_tag'),
    'heating': ('terminal_equipment', 'design_capacity', 'supply_return_tag', 'riser_tag'),
    'cooling': ('terminal_equipment', 'design_capacity', 'condensate_fall', 'outdoor_unit_location'),
    'ventilation_exhaust': ('exhaust_terminal', 'airflow_tag', 'discharge_path', 'makeup_air_path'),
    'gas': ('appliance_connection', 'pipe_diameter', 'meter_regulator', 'riser_tag'),
    'roof_rainwater': ('roof_drain', 'drain_diameter', 'rainfall_basis', 'downpipe_riser'),
}


def plan_detail_requirements(family):
    """Return the non-negotiable plan-visible details for a sheet family."""
    return PLAN_DETAIL_STANDARD.get(str(family or ''), ())

RAIN_MM_H = {
    'تهران': 110, 'tehran': 110,
    'مشهد': 90, 'mashhad': 90,
    'اصفهان': 90, 'isfahan': 90,
    'شیراز': 100, 'shiraz': 100,
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
    """Resolve missing/unknown pressure without blocking the design workflow.

    Utility pressure is an external fact, but an unknown reading does not have
    to make the drawing engine fail.  The Rule Book uses a conservative inlet
    basis and explicitly includes storage/booster protection in that case.
    A real numeric project value always wins.
    """
    text = str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').lower()
    unresolved = (
        not text
        or is_confirmation(text)
        or any(marker in text for marker in (
            'نمی‌دانم', 'نمیدانم', 'نامشخص', 'اندازه‌گیری نشده',
            'unknown', 'unresolved', 'tbd', 'not measured',
        ))
    )
    return DEFAULT_WATER_INLET_PRESSURE if unresolved else str(value).strip()


def fixture_schedule_proposal(auto_or_levels):
    rooms = {}
    if isinstance(auto_or_levels, dict):
        rooms = auto_or_levels.get('room_counts') or {}
    else:
        for level in auto_or_levels or []:
            for room in level.get('rooms') or []:
                kind = room.get('room')
                rooms[kind] = rooms.get(kind, 0) + 1
    kitchen = int(rooms.get('kitchen', 0))
    bath = int(rooms.get('bath', 0))
    toilet = int(rooms.get('toilet', 0))
    return f'sink {kitchen}; faucet {bath + toilet}; toilet {toilet}; bath {bath}'


def roof_geometry_proposal(auto_or_levels):
    if isinstance(auto_or_levels, dict):
        rooms = auto_or_levels.get('room_counts') or {}
        level_count = max(1, len([x for x in auto_or_levels.get('levels') or [] if 'بام' not in str(x.get('name') or '') and 'roof' not in str(x.get('name') or '').lower()]))
        explicit_area = auto_or_levels.get('roof_area_m2')
    else:
        levels = [x for x in (auto_or_levels or []) if 'بام' not in str(x.get('level') or '') and 'roof' not in str(x.get('level') or '').lower()]
        level_count = max(1, len(levels))
        rooms = {}
        for level in levels:
            for room in level.get('rooms') or []:
                kind = room.get('room')
                rooms[kind] = rooms.get(kind, 0) + 1
        explicit_area = None
    room_total = sum(int(x or 0) for x in rooms.values())
    area = float(explicit_area) if explicit_area else max(60.0, round(room_total * 12.0 / level_count, 1))
    drains = max(2, int(math.ceil(area / 100.0)))
    return f'{area:g} m2 roof; {drains} drains at coordinated architecture low points'


def automatic_answers(auto):
    """Return non-customer mechanical decisions owned by Rule Book v1.6."""
    rooms = auto.get('room_counts') or {}
    cooling = float(auto.get('estimated_cooling_load_kw') or 0)
    heating = float(auto.get('estimated_heating_load_kw') or 0)
    conditioned = max(1, rooms.get('bedroom', 0) + rooms.get('living', 0) + rooms.get('office', 0) + rooms.get('shop', 0))
    cooling_each = round(cooling / conditioned, 2) if cooling else None
    heating_each = round(heating / conditioned, 2) if heating else None

    airflow = (
        rooms.get('toilet', 0) * VENTILATION['toilet_m3h_each']
        + rooms.get('bath', 0) * VENTILATION['bath_m3h_each']
        + rooms.get('kitchen', 0) * VENTILATION['kitchen_m3h_each']
    )
    if rooms.get('parking', 0):
        airflow += VENTILATION['default_parking_m3h_when_geometry_missing']
    airflow = max(airflow, 90)

    equipment = (
        f"Rulebook automatic selection; per room load: cooling {cooling_each or 'calculated'} kW, "
        f"heating {heating_each or 'calculated'} kW; split cooling units and hydronic radiators; "
        "outdoor units on coordinated roof/service location"
    )
    return {
        'heights': DEFAULT_HEIGHTS,
        'water_inlet_pressure': DEFAULT_WATER_INLET_PRESSURE,
        'heating': 'Rulebook automatic: condensing combi boiler + hydronic radiators',
        'cooling': 'Rulebook automatic: split units sized from calculated room loads',
        'water_design_basis': (
            f"{WATER['material']}; Hazen-Williams C={WATER['hazen_williams_c']}; "
            f"maximum loss {WATER['maximum_friction_loss_kpa_per_100m']} kPa/100 m"
        ),
        'sanitary_design_basis': (
            f"{SANITARY['material']}; {SANITARY['branch_slope_pct']} percent branches; "
            f"{SANITARY['main_slope_pct']} percent mains"
        ),
        'equipment_schedule': equipment,
        'ventilation_design_basis': (
            f"Rulebook calculated airflow {airflow} m3/h; discharge above roof/exterior; "
            "make-up air from facade/openings"
        ),
        'water_source': 'Rulebook automatic: municipal meter + storage tank + booster pump sized from calculated demand',
        'mechanical_rulebook_version': RULEBOOK_VERSION,
    }


def roof_basis(location, geometry_text):
    """Complete roof rainfall from location while preserving project geometry."""
    geometry = str(geometry_text or '').strip()
    rainfall = rainfall_mm_h(location)
    if not geometry or rainfall is None:
        return geometry
    if re.search(r'\d+(?:\.\d+)?\s*(?:mm/h|میلی.?متر)', geometry, re.I):
        return geometry
    return f'{geometry}; {rainfall} mm/h Rulebook design rainfall'
