"""Canonical Dimension Engine v2 ontology.

Pure contracts only. No routing, sizing, or CAD mutation authority lives here.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

PURPOSES={
    "PROPERTY","SETBACK","BUILDING_OVERALL","GRID","STRUCTURAL_SETOUT",
    "WALL_SETOUT","ROOM_CLEAR","STAIR","SHAFT","OPENING_SIZE",
    "OPENING_POSITION","EQUIPMENT_SIZE","EQUIPMENT_POSITION","PENETRATION",
    "SLEEVE","RISER","CODE_CLEARANCE","CONSTRUCTION_CLEARANCE","CHECK",
}
ROLES={"SETOUT","CHECK"}
REFERENCE_SUBFEATURES={
    "GRID_AXIS","GRID_INTERSECTION","STRUCTURAL_CENTERLINE","STRUCTURAL_FACE",
    "WALL_CORE_FACE","WALL_INNER_FINISH_FACE","WALL_OUTER_FINISH_FACE",
    "BUILDING_ENVELOPE_FACE","PROPERTY_BOUNDARY","SHAFT_FACE","STAIR_CORE_FACE",
    "OPENING_JAMB","OPENING_CENTERLINE","EQUIPMENT_CENTER","EQUIPMENT_FACE",
    "PIPE_RISER_CENTER","PENETRATION_CENTER","PLAN_EDGE",
}
CRITICAL_PRIORITIES={"P0","P1"}


@dataclass(frozen=True)
class SemanticReference:
    id:str
    element_id:str
    subfeature:str
    geometry:dict[str,Any]
    plan_id:str|None=None
    level:str|None=None
    priority:int=50
    source:str="semantic_geometry"
    confidence:float=1.0
    evidence:tuple[str,...]=()
    datum_class:str|None=None
    local_axis_deg:float|None=None

    def validate(self):
        errors=[]
        if not self.id: errors.append("REFERENCE_ID_REQUIRED")
        if not self.element_id: errors.append("REFERENCE_ELEMENT_ID_REQUIRED")
        if self.subfeature not in REFERENCE_SUBFEATURES:
            errors.append("UNSUPPORTED_REFERENCE_SUBFEATURE")
        if not (0.0<=float(self.confidence)<=1.0):
            errors.append("REFERENCE_CONFIDENCE_OUT_OF_RANGE")
        if not isinstance(self.geometry,dict) or not self.geometry:
            errors.append("REFERENCE_GEOMETRY_REQUIRED")
        return errors

    def to_dict(self): return asdict(self)


@dataclass(frozen=True)
class DimensionIntentV2:
    id:str
    purpose:str
    role:str
    reference_a:dict[str,Any]
    reference_b:dict[str,Any]
    measured_value:float
    engineering_value_m:float|None
    drawing_profile:str
    plan_id:str|None=None
    level:str|None=None
    priority_class:str="P1"
    required:bool=True
    rule_id:str|None=None
    source_kind:str="PLANHA_GENERATED"
    source_dimension_id:str|None=None
    display_value:str|None=None
    orientation:str|None=None
    datum_class:str|None=None
    evidence:tuple[str,...]=()

    def validate(self):
        errors=[]
        if self.purpose not in PURPOSES: errors.append("UNSUPPORTED_DIMENSION_PURPOSE")
        if self.role not in ROLES: errors.append("DIMENSION_ROLE_REQUIRED")
        for label,ref in (("A",self.reference_a),("B",self.reference_b)):
            if not isinstance(ref,dict) or not (ref.get("id") or ref.get("element_id")):
                errors.append(f"REFERENCE_{label}_REQUIRED")
        if self.purpose=="CODE_CLEARANCE" and not self.rule_id:
            errors.append("CODE_CLEARANCE_RULE_ID_REQUIRED")
        if self.priority_class not in {"P0","P1","P2","P3"}:
            errors.append("INVALID_PRIORITY_CLASS")
        return errors

    def to_dict(self): return asdict(self)


def validate_intents(intents):
    errors=[]
    for row in intents or []:
        if isinstance(row,DimensionIntentV2):
            errs=row.validate(); ident=row.id
        else:
            try:
                obj=DimensionIntentV2(**row); errs=obj.validate(); ident=obj.id
            except Exception as exc:
                errors.append({"id":str((row or {}).get("id") if isinstance(row,dict) else "?"),"error":"INVALID_INTENT:"+str(exc)})
                continue
        errors.extend({"id":ident,"error":e} for e in errs)
    return errors
