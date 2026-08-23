"""Machine-readable mechanical Rule Book defaults.

These are design rules, not customer facts.  The questionnaire must not ask a
customer to provide values that the Rule Book or Code Designer owns.
"""

import math
import re


RULEBOOK_VERSION = '1.4'

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


def automatic_answers(auto):
    """Return non-customer mechanical decisions owned by Rule Book v1.4."""
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
        'water_source': 'Rulebook automatic selection after inlet pressure and building elevation check',
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

