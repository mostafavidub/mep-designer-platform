from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    ArchitecturalModel,
    ElectricalDesignBasis,
    ElectricalProjectModel,
    EngineeringStatus,
    EquipmentRequirement,
    EvidenceValue,
    SheetManifestItem,
    SystemRequirement,
)


SYSTEMS = (
    "LIGHTING", "EMERGENCY_LIGHTING", "GENERAL_RECEPTACLES", "DEDICATED_POWER",
    "HVAC_POWER", "KITCHEN_POWER", "PANEL_DISTRIBUTION", "FEEDERS", "MAIN_SERVICE",
    "GROUNDING", "BONDING", "FIRE_ALARM", "TELECOM", "DATA", "TV", "INTERCOM",
    "CCTV", "ACCESS_CONTROL", "LIGHTNING_PROTECTION", "GENERATOR", "UPS",
    "EV_CHARGING", "SOLAR_PV", "ELEVATOR_POWER", "PUMP_POWER",
)

# Reference taxonomy encodes observed drawing behavior only. It is not a source
# of universal cable sizes, breaker ratings, spacings, quantities or legal rules.
REFERENCE_TAXONOMY = {
    "source": "approved_project01_electrical_dxf_analyzed_in_mep_rulebook",
    "observed": {
        "modelspace_entity_count": 19460,
        "layer_count": 59,
        "families": {
            "LIGHTING": {"layers": ["LIGHT"], "behavior": ["symbols", "control_routes", "circuit_graphics", "annotations"]},
            "POWER": {"layers": ["EL", "EL2", "E-WIRE"], "behavior": ["receptacles", "dedicated_points", "routes", "annotations"]},
            "FIRE_ALARM": {"layers": ["E-FIRE", "E-FIRE ALARM"], "behavior": ["panel", "devices", "traceable_routes", "cable_or_destination_annotation"]},
            "GROUNDING_BONDING": {"layers": ["E-bonding", "Hambandi"], "behavior": ["bonding_graphics"]},
            "LOW_CURRENT": {"layers": ["E-INSTRU", "E-SOUND"], "behavior": ["independent_system_graphics"]},
        },
    },
    "not_proven_as_universal": [
        "cable_sizes", "breaker_ratings", "mounting_heights", "device_spacing",
        "fire_alarm_code_criteria", "panel_capacity", "service_capacity",
    ],
}


def build_project_model(architecture: ArchitecturalModel, project_inputs: Optional[Dict[str, Any]] = None) -> ElectricalProjectModel:
    project_inputs = project_inputs or {}
    project: Dict[str, EvidenceValue] = {
        "project_name": EvidenceValue.input_required("project_name not supplied"),
        "building_type": EvidenceValue.input_required("building type not conclusively evidenced"),
    }
    for key, value in project_inputs.items():
        if isinstance(value, EvidenceValue):
            project[key] = value
        elif value is not None:
            project[key] = EvidenceValue.final(value, "explicit_user_input", 1.0)

    types: Dict[str, List[str]] = defaultdict(list)
    common, special = [], []
    for room in architecture.rooms:
        kind = room.room_type.value if room.room_type.value else "unknown"
        types[str(kind)].append(room.id)
        if kind in {"corridor", "stair", "common", "entrance"}:
            common.append(room.id)
        if kind in {"service", "parking", "roof", "shaft", "commercial"}:
            special.append(room.id)

    roof_rooms = [r.id for r in architecture.rooms if r.room_type.value == "roof"]
    parking_rooms = [r.id for r in architecture.rooms if r.room_type.value == "parking"]
    roof = (EvidenceValue.final(True, "architectural_evidence", .9) if roof_rooms or any(l.special_type == "roof" for l in architecture.levels)
            else EvidenceValue.unknown("roof not detected"))
    parking = (EvidenceValue.final(True, "architectural_evidence", .9) if parking_rooms
               else EvidenceValue.unknown("parking not detected"))

    possible_panels = []
    # A shaft/common circulation adjacency is a candidate only, never a final panel location.
    for room in architecture.rooms:
        if room.room_type.value in {"corridor", "entrance", "common", "service"} and room.label_point:
            possible_panels.append(EvidenceValue.preliminary(
                {"room_id": room.id, "point": room.label_point}, "architectural_evidence", .45,
                "candidate accessible zone only; wall/access/clearance must pass placement contract",
            ))

    return ElectricalProjectModel(
        project=project, levels=architecture.levels, rooms=architecture.rooms,
        room_types=dict(types), possible_panel_locations=possible_panels,
        roof=roof, parking=parking, common_areas=common, special_spaces=special,
    )


def build_design_basis(explicit_inputs: Optional[Dict[str, Any]] = None,
                       rule_inputs: Optional[Dict[str, Any]] = None,
                       manufacturer_inputs: Optional[Dict[str, Any]] = None) -> ElectricalDesignBasis:
    basis = ElectricalDesignBasis()
    for source_name, values in (
        ("explicit_user_input", explicit_inputs or {}),
        ("applicable_rule", rule_inputs or {}),
        ("manufacturer_data", manufacturer_inputs or {}),
    ):
        for key, raw in values.items():
            if isinstance(raw, EvidenceValue):
                basis.values[key] = raw
            elif raw is not None:
                basis.values[key] = EvidenceValue.final(raw, source_name, 1.0)
    return basis


def _basis_bool(basis: ElectricalDesignBasis, key: str) -> Optional[bool]:
    value = basis.get(key)
    if value.status in {EngineeringStatus.UNKNOWN, EngineeringStatus.INPUT_REQUIRED}:
        return None
    if isinstance(value.value, bool):
        return value.value
    text = str(value.value).strip().lower()
    if text in {"yes", "true", "required", "1", "بله"}: return True
    if text in {"no", "false", "not_required", "0", "خیر"}: return False
    return None


def resolve_system_requirements(project: ElectricalProjectModel, basis: ElectricalDesignBasis) -> Dict[str, SystemRequirement]:
    room_types = set(project.room_types)
    results: Dict[str, SystemRequirement] = {}

    def required(system, evidence, confidence=.9, reason=""):
        results[system] = SystemRequirement(system, EngineeringStatus.FINAL, True, evidence, confidence, reason)

    def not_required(system, evidence, confidence=.9, reason=""):
        results[system] = SystemRequirement(system, EngineeringStatus.NOT_REQUIRED, False, evidence, confidence, reason)

    def needs_input(system, evidence, reason=""):
        results[system] = SystemRequirement(system, EngineeringStatus.INPUT_REQUIRED, None, evidence, 0.0, reason)

    # Base building electrical systems are required when habitable/service rooms exist.
    if room_types:
        required("LIGHTING", ["architectural rooms detected"], reason="rooms require a lighting design family")
        required("PANEL_DISTRIBUTION", ["electrical loads require distribution"])
        required("FEEDERS", ["panel distribution required"])
        required("MAIN_SERVICE", ["building electrical service required"])
        required("GROUNDING", ["main service/distribution present"])
        required("BONDING", ["electrical distribution present"])
    else:
        for s in ("LIGHTING", "PANEL_DISTRIBUTION", "FEEDERS", "MAIN_SERVICE", "GROUNDING", "BONDING"):
            needs_input(s, [], "architectural room model absent")

    if room_types & {"bedroom", "living", "kitchen", "office", "commercial"}:
        required("GENERAL_RECEPTACLES", ["receptacle-serving room types detected"], .85)
    else:
        needs_input("GENERAL_RECEPTACLES", [], "no room-use evidence sufficient to finalize receptacle scope")

    if "kitchen" in room_types:
        required("KITCHEN_POWER", ["kitchen detected"], .95)
        required("DEDICATED_POWER", ["kitchen fixed/appliance loads require dedicated-load assessment"], .75,
                 "specific appliances and loads remain project inputs")
    else:
        not_required("KITCHEN_POWER", ["no kitchen detected"], .75)

    hvac = basis.get("hvac_electrical_loads")
    if hvac.status not in {EngineeringStatus.UNKNOWN, EngineeringStatus.INPUT_REQUIRED} and hvac.value:
        required("HVAC_POWER", ["design_basis.hvac_electrical_loads"], .95)
    else:
        needs_input("HVAC_POWER", ["mechanical/electrical cross-check required"], "HVAC equipment/load schedule not supplied")

    for system, key in (
        ("EMERGENCY_LIGHTING", "emergency_lighting"),
        ("FIRE_ALARM", "fire_alarm_requirement"),
        ("LIGHTNING_PROTECTION", "lightning_protection"),
        ("GENERATOR", "generator"), ("UPS", "ups"), ("EV_CHARGING", "ev_charging"), ("SOLAR_PV", "solar_pv"),
    ):
        flag = _basis_bool(basis, key)
        if flag is True: required(system, [f"design_basis.{key}"], 1.0)
        elif flag is False: not_required(system, [f"design_basis.{key}"], 1.0)
        else: needs_input(system, [], f"{key} applicability not established")

    elevator_evidence = any("elevator" in str(r.label or "").lower() or "آسانسور" in str(r.label or "") for r in project.rooms)
    elevator_flag = _basis_bool(basis, "elevator")
    if elevator_flag is True or elevator_evidence:
        required("ELEVATOR_POWER", ["design basis elevator" if elevator_flag else "architectural elevator evidence"], .95 if elevator_flag else .75)
    elif elevator_flag is False:
        not_required("ELEVATOR_POWER", ["design_basis.elevator"], 1.0)
    else:
        needs_input("ELEVATOR_POWER", [], "elevator applicability not established")

    pump_flag = _basis_bool(basis, "pump")
    if pump_flag is True: required("PUMP_POWER", ["design_basis.pump"], 1.0)
    elif pump_flag is False: not_required("PUMP_POWER", ["design_basis.pump"], 1.0)
    else: needs_input("PUMP_POWER", ["mechanical cross-check required"], "pump schedule not established")

    low = basis.get("low_current_systems")
    if low.status not in {EngineeringStatus.UNKNOWN, EngineeringStatus.INPUT_REQUIRED}:
        values = {str(x).upper() for x in (low.value if isinstance(low.value, (list, tuple, set)) else [low.value])}
        aliases = {"TELECOM", "DATA", "TV", "INTERCOM", "CCTV", "ACCESS_CONTROL"}
        for system in aliases:
            if system in values: required(system, ["design_basis.low_current_systems"], 1.0)
            else: not_required(system, ["explicit low_current_systems list"], 1.0)
    else:
        for system in ("TELECOM", "DATA", "TV", "INTERCOM", "CCTV", "ACCESS_CONTROL"):
            needs_input(system, [], "low-current scope not supplied")

    for system in SYSTEMS:
        results.setdefault(system, SystemRequirement(system, EngineeringStatus.UNKNOWN, None, [], 0.0, "resolver has no evidence"))
    return results


FAMILY_RULES = {
    "LIGHTING": {
        "systems": {"LIGHTING", "EMERGENCY_LIGHTING"},
        "required": ["lighting_fixtures", "switches", "lighting_circuits", "annotations"],
        "layers": ["ENGITOOLS-E-LIGHTING", "ENGITOOLS-E-LIGHTING-CONTROL", "ENGITOOLS-E-WIRE", "ENGITOOLS-E-ANNOTATION"],
        "forbidden": ["ENGITOOLS-E-POWER-DEVICE"],
        "signature": {"lighting_fixtures": 1, "lighting_circuits": 1},
    },
    "POWER": {
        "systems": {"GENERAL_RECEPTACLES", "DEDICATED_POWER", "KITCHEN_POWER", "HVAC_POWER", "ELEVATOR_POWER", "PUMP_POWER"},
        "required": ["receptacles_or_dedicated_loads", "power_circuits", "panel_references", "annotations"],
        "layers": ["ENGITOOLS-E-POWER", "ENGITOOLS-E-DEDICATED", "ENGITOOLS-E-WIRE", "ENGITOOLS-E-ANNOTATION"],
        "forbidden": ["ENGITOOLS-E-LIGHTING-FIXTURE"],
        "signature": {"power_loads": 1, "power_circuits": 1},
    },
    "FIRE_ALARM": {
        "systems": {"FIRE_ALARM"},
        "required": ["fire_devices", "fire_routes", "annotations"],
        "layers": ["ENGITOOLS-E-FIRE-ALARM", "ENGITOOLS-E-ANNOTATION"],
        "forbidden": [], "signature": {"fire_devices": 1},
    },
    "LOW_CURRENT": {
        "systems": {"TELECOM", "DATA", "TV", "INTERCOM", "CCTV", "ACCESS_CONTROL"},
        "required": ["low_current_devices", "routes_or_references", "annotations"],
        "layers": ["ENGITOOLS-E-LOW-CURRENT", "ENGITOOLS-E-ANNOTATION"],
        "forbidden": [], "signature": {"low_current_devices": 1},
    },
    "GROUNDING": {
        "systems": {"GROUNDING", "BONDING", "LIGHTNING_PROTECTION"},
        "required": ["grounding_or_bonding_elements", "annotations"],
        "layers": ["ENGITOOLS-E-GROUNDING", "ENGITOOLS-E-BONDING", "ENGITOOLS-E-ANNOTATION"],
        "forbidden": [], "signature": {"grounding_elements": 1},
    },
}


def _active(requirements: Dict[str, SystemRequirement], systems) -> bool:
    return any(requirements[s].required is True for s in systems if s in requirements)


def plan_sheets(project: ElectricalProjectModel, requirements: Dict[str, SystemRequirement],
                density: Optional[Dict[str, Dict[str, int]]] = None) -> List[SheetManifestItem]:
    density = density or {}
    sheets: List[SheetManifestItem] = []
    seq = 0
    # Cover/index is generated because it is documentation, not an engineering assumption.
    seq += 1
    sheets.append(SheetManifestItem(
        f"E-{seq:02d}", "COVER", None, "Electrical index, project design status, legend/notes references",
        ["sheet_index", "design_status"], ["ENGITOOLS-E-DOC"], [], {"sheet_index": 1}, []))

    eligible_by_level = {l.id: list(l.frame_ids) for l in project.levels if l.frame_ids}
    for family, rule in FAMILY_RULES.items():
        if not _active(requirements, rule["systems"]):
            continue
        for level in project.levels:
            frame_ids = eligible_by_level.get(level.id) or []
            if not frame_ids:
                continue
            family_density = density.get(family, {}).get(level.id, 0)
            # Split threshold is a presentation decision only; it does not create engineering quantity.
            split = family_density > 80
            parts = 2 if split else 1
            for part in range(parts):
                seq += 1
                purpose = f"{family} plan for {level.name.value or level.id}"
                if split: purpose += f" part {part+1} of {parts}"
                sheets.append(SheetManifestItem(
                    f"E-{seq:02d}", family, level.id, purpose,
                    list(rule["required"]), list(rule["layers"]), list(rule["forbidden"]), dict(rule["signature"]), frame_ids))

    if _active(requirements, {"PANEL_DISTRIBUTION", "FEEDERS", "MAIN_SERVICE"}):
        for family, purpose, signature in (
            ("PANEL_SCHEDULE", "Project panel schedules", {"panel_schedules": 1}),
            ("SINGLE_LINE", "Main electrical single-line diagram", {"single_line_nodes": 2}),
            ("RISER", "Electrical vertical distribution riser", {"riser_transitions": 1 if len(project.levels) > 1 else 0}),
            ("CALCULATIONS", "Load, demand, voltage-drop and phase-balance results", {"calculation_tables": 1}),
        ):
            if family == "RISER" and len(project.levels) <= 1:
                continue
            seq += 1
            sheets.append(SheetManifestItem(f"E-{seq:02d}", family, None, purpose,
                                             list(signature), [f"ENGITOOLS-E-{family}"], [], signature, []))
    return sheets


ROOM_EQUIPMENT_RULES = {
    # These are requirement categories, not fixed quantities. Quantity defaults to INPUT_REQUIRED
    # unless geometry/rule/manufacturer evidence later resolves it.
    "bedroom": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wall_near_entry"), ("GENERAL_SOCKET", "GENERAL_RECEPTACLES", "wall_room_aware")],
    "living": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wall_near_entry"), ("GENERAL_SOCKET", "GENERAL_RECEPTACLES", "wall_room_aware")],
    "kitchen": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wall_near_entry"), ("GENERAL_SOCKET", "GENERAL_RECEPTACLES", "wall_room_aware"), ("DEDICATED_APPLIANCE_OUTLET", "KITCHEN_POWER", "wall_equipment_coordinated")],
    "bathroom": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wet_area_entry_control")],
    "toilet": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wet_area_entry_control")],
    "corridor": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room")],
    "stair": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "stair_control")],
    "parking": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room")],
    "office": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wall_near_entry"), ("GENERAL_SOCKET", "GENERAL_RECEPTACLES", "wall_room_aware")],
    "commercial": [("LIGHT_FIXTURE", "LIGHTING", "ceiling_inside_room"), ("LIGHT_SWITCH", "LIGHTING", "wall_near_entry"), ("GENERAL_SOCKET", "GENERAL_RECEPTACLES", "wall_room_aware")],
}


def resolve_equipment_requirements(project: ElectricalProjectModel,
                                   requirements: Dict[str, SystemRequirement]) -> List[EquipmentRequirement]:
    rows: List[EquipmentRequirement] = []
    for room in project.rooms:
        room_type = str(room.room_type.value or "unknown")
        for eq_type, system, placement_contract in ROOM_EQUIPMENT_RULES.get(room_type, []):
            if requirements.get(system) and requirements[system].required is not True:
                continue
            quantity = EvidenceValue.input_required(
                f"{eq_type} quantity requires room geometry + applicable rule/design basis/manufacturer data"
            )
            if eq_type == "LIGHT_SWITCH":
                # One control location may be a defensible preliminary need from a single detected room entry,
                # but it is not FINAL without door/control design evidence.
                quantity = EvidenceValue.preliminary(1, "architectural_evidence", .45, "control-point requirement only; switch count/type requires door/control analysis")
            rows.append(EquipmentRequirement(
                id=f"REQ-{len(rows)+1:04d}", room_id=room.id, level_id=room.level_id,
                equipment_type=eq_type, system=system, quantity=quantity,
                basis=[f"room_type:{room_type}"], placement_contract=placement_contract,
            ))
    return rows
