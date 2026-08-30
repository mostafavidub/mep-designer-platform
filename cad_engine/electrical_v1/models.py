from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


class EngineeringStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    INPUT_REQUIRED = "INPUT_REQUIRED"
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    NOT_REQUIRED = "NOT_REQUIRED"


FINAL_SOURCES = {
    "architectural_evidence",
    "project_design_basis",
    "engineering_calculation",
    "applicable_rule",
    "manufacturer_data",
    "explicit_user_input",
}


@dataclass
class EvidenceValue:
    value: Any = None
    source: Optional[str] = None
    confidence: float = 0.0
    status: EngineeringStatus = EngineeringStatus.UNKNOWN
    reference: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not 0.0 <= float(self.confidence) <= 1.0:
            errors.append("confidence_out_of_range")
        if self.status == EngineeringStatus.FINAL:
            if self.value is None:
                errors.append("final_value_missing")
            if self.source not in FINAL_SOURCES:
                errors.append("final_source_not_allowed")
        if self.value is None and self.status == EngineeringStatus.FINAL:
            errors.append("fabricated_final_guard")
        return errors

    @classmethod
    def unknown(cls, note: str = "") -> "EvidenceValue":
        return cls(notes=[note] if note else [])

    @classmethod
    def input_required(cls, note: str = "") -> "EvidenceValue":
        return cls(status=EngineeringStatus.INPUT_REQUIRED, notes=[note] if note else [])

    @classmethod
    def preliminary(cls, value: Any, source: str, confidence: float, note: str = "") -> "EvidenceValue":
        return cls(value=value, source=source, confidence=confidence,
                   status=EngineeringStatus.PRELIMINARY, notes=[note] if note else [])

    @classmethod
    def final(cls, value: Any, source: str, confidence: float = 1.0, reference: Optional[str] = None) -> "EvidenceValue":
        obj = cls(value=value, source=source, confidence=confidence,
                  status=EngineeringStatus.FINAL, reference=reference)
        errors = obj.validate()
        if errors:
            raise ValueError(f"invalid FINAL evidence: {errors}")
        return obj


Point = Tuple[float, float]
Polygon = List[Point]


@dataclass
class ArchitecturalEntity:
    id: str
    kind: str
    level_id: Optional[str]
    geometry: Any
    source: str = "architectural_evidence"
    confidence: float = 1.0
    status: EngineeringStatus = EngineeringStatus.FINAL
    frame_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DrawingFrame:
    id: str
    classification: str
    bounds: Tuple[float, float, float, float]
    title: Optional[str] = None
    level_id: Optional[str] = None
    confidence: float = 0.0
    source: str = "architectural_evidence"
    eligible_for_electrical: bool = False


@dataclass
class Room:
    id: str
    level_id: str
    room_type: EvidenceValue
    polygon: Optional[Polygon] = None
    label_point: Optional[Point] = None
    label: Optional[str] = None
    unit_id: Optional[str] = None
    frame_id: Optional[str] = None
    area_m2: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    properties: Dict[str, EvidenceValue] = field(default_factory=dict)


@dataclass
class Level:
    id: str
    name: EvidenceValue
    elevation_m: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    frame_ids: List[str] = field(default_factory=list)
    room_ids: List[str] = field(default_factory=list)
    special_type: Optional[str] = None


@dataclass
class ArchitecturalModel:
    source_path: str
    units: EvidenceValue
    levels: List[Level] = field(default_factory=list)
    rooms: List[Room] = field(default_factory=list)
    frames: List[DrawingFrame] = field(default_factory=list)
    entities: List[ArchitecturalEntity] = field(default_factory=list)
    building_footprint: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    issues: List[str] = field(default_factory=list)

    def validate(self) -> Dict[str, Any]:
        errors: List[str] = []
        if self.units.status in {EngineeringStatus.UNKNOWN, EngineeringStatus.INPUT_REQUIRED}:
            errors.append("architectural_units_unknown")
        if not self.levels:
            errors.append("no_levels")
        if not self.rooms:
            errors.append("no_rooms")
        eligible = [f for f in self.frames if f.eligible_for_electrical]
        if self.frames and not eligible:
            errors.append("no_electrical_eligible_frames")
        level_ids = {x.id for x in self.levels}
        frame_ids = {x.id for x in self.frames}
        for room in self.rooms:
            if room.level_id not in level_ids:
                errors.append(f"room_level_missing:{room.id}")
            if room.frame_id and room.frame_id not in frame_ids:
                errors.append(f"room_frame_missing:{room.id}")
        return {"status": "PASS" if not errors else "FAIL", "errors": errors}


@dataclass
class ElectricalProjectModel:
    project: Dict[str, EvidenceValue]
    levels: List[Level]
    rooms: List[Room]
    units: List[Dict[str, EvidenceValue]] = field(default_factory=list)
    room_types: Dict[str, List[str]] = field(default_factory=dict)
    electrical_zones: List[Dict[str, Any]] = field(default_factory=list)
    service_entry: EvidenceValue = field(default_factory=lambda: EvidenceValue.input_required("service entry not evidenced"))
    possible_meter_location: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    possible_panel_locations: List[EvidenceValue] = field(default_factory=list)
    roof: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    parking: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    common_areas: List[str] = field(default_factory=list)
    special_spaces: List[str] = field(default_factory=list)

    def validate(self) -> Dict[str, Any]:
        errors: List[str] = []
        values: List[EvidenceValue] = list(self.project.values())
        values += [x.name for x in self.levels]
        for room in self.rooms:
            values += [room.room_type, room.area_m2]
            values += list(room.properties.values())
        values += [self.service_entry, self.possible_meter_location, self.roof, self.parking]
        values += list(self.possible_panel_locations)
        for value in values:
            errors.extend(value.validate())
        return {"status": "PASS" if not errors else "FAIL", "errors": errors}


DESIGN_BASIS_FIELDS = (
    "city", "building_type", "number_of_units", "supply_voltage_v",
    "phase_configuration", "utility_service", "earthing_system",
    "lighting_basis", "socket_power_requirements", "dedicated_appliance_requirements",
    "hvac_electrical_loads", "elevator", "pump", "package_boiler", "split_ac",
    "kitchen_appliances", "parking_equipment", "emergency_lighting",
    "fire_alarm_requirement", "low_current_systems", "lightning_protection",
    "generator", "ups", "ev_charging", "solar_pv",
    "ambient_temperature_c", "installation_method", "conductor_material",
    "power_factor", "frequency_hz", "voltage_drop_limits",
)


@dataclass
class ElectricalDesignBasis:
    values: Dict[str, EvidenceValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in DESIGN_BASIS_FIELDS:
            self.values.setdefault(key, EvidenceValue.input_required(f"{key} requires project evidence/input"))

    def get(self, key: str) -> EvidenceValue:
        return self.values.get(key, EvidenceValue.unknown())

    def missing(self) -> List[str]:
        return [k for k, v in self.values.items() if v.status in {EngineeringStatus.UNKNOWN, EngineeringStatus.INPUT_REQUIRED}]

    def validate(self) -> Dict[str, Any]:
        errors = [f"{k}:{e}" for k, v in self.values.items() for e in v.validate()]
        return {"status": "PASS" if not errors else "FAIL", "errors": errors, "missing": self.missing()}


@dataclass
class SystemRequirement:
    system: str
    status: EngineeringStatus
    required: Optional[bool]
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""


@dataclass
class SheetManifestItem:
    sheet_id: str
    family: str
    level_id: Optional[str]
    purpose: str
    required_content: List[str]
    allowed_layers: List[str]
    forbidden_layers: List[str]
    minimum_content_signature: Dict[str, int]
    source_frame_ids: List[str] = field(default_factory=list)
    scale: EvidenceValue = field(default_factory=lambda: EvidenceValue.preliminary(None, "applicable_rule", 0.0, "scale selected at composition from print readability"))


@dataclass
class EquipmentRequirement:
    id: str
    room_id: Optional[str]
    level_id: str
    equipment_type: str
    system: str
    quantity: EvidenceValue
    basis: List[str]
    placement_contract: str
    load_w: EvidenceValue = field(default_factory=EvidenceValue.unknown)


@dataclass
class EquipmentPlacement:
    requirement_id: str
    equipment_id: str
    level_id: str
    frame_id: Optional[str]
    point: Optional[Point]
    rotation_deg: Optional[float]
    host_type: Optional[str]
    host_id: Optional[str]
    room_id: Optional[str]
    status: EngineeringStatus
    qa: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ElectricalLoad:
    id: str
    equipment_id: str
    system: str
    level_id: str
    frame_id: Optional[str]
    load_w: EvidenceValue
    phase_requirement: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    circuit_id: Optional[str] = None


@dataclass
class Circuit:
    id: str
    panel_id: str
    load_ids: List[str]
    system: str
    phase: EvidenceValue
    connected_load_w: EvidenceValue
    demand_load_w: EvidenceValue
    design_current_a: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    breaker: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    cable: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    earth_conductor: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    route_length_m: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    voltage_drop_pct: EvidenceValue = field(default_factory=EvidenceValue.unknown)


@dataclass
class Panel:
    id: str
    level_id: str
    location: EvidenceValue
    incoming_feeder_id: Optional[str]
    main_breaker: EvidenceValue
    bus_rating: EvidenceValue
    phase_configuration: EvidenceValue
    circuit_ids: List[str]
    spare_count: EvidenceValue
    connected_load_w: EvidenceValue
    demand_load_w: EvidenceValue
    phase_loads_w: Dict[str, float] = field(default_factory=dict)


@dataclass
class Feeder:
    id: str
    source_panel_id: Optional[str]
    destination_panel_id: str
    connected_load_w: EvidenceValue
    demand_load_w: EvidenceValue
    design_current_a: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    breaker: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    cable: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    route_length_m: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    voltage_drop_pct: EvidenceValue = field(default_factory=EvidenceValue.unknown)


def serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {k: serialize(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value
