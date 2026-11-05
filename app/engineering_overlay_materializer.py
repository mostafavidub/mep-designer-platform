"""Validate and materialize source-bound, reversible DRAFT design proposals."""
from copy import deepcopy
from hashlib import sha256
import json
import math


SYSTEM_REQUIREMENTS = {
    "water": {"endpoints", "water_design_basis"},
    "sanitary": {"endpoints", "sanitary_design_basis"},
    "heating": {"rooms", "heating_design_basis"},
    "cooling": {"rooms", "cooling_design_basis", "manufacturer_line_sizing"},
    "gas": {"endpoints", "gas_design_basis", "official_capacity_table"},
    "ventilation": {"rooms", "ventilation_design_basis"},
    "rainwater": {"roof_catchments", "rainfall_basis", "official_capacity_table"},
}

PROPOSAL_SCHEMA = "planha-model-engineering-proposal/1.0"
ALLOWED_ENDPOINT_TYPES = {
    "wc", "toilet", "basin", "sink", "shower", "floor_drain", "bath",
    "stove", "water_heater", "exhaust_fan",
}


def _polygon(row):
    return (row.get("polygon") or row.get("boundary") or row.get("points") or
            ((row.get("geometry") or {}).get("coordinates") if isinstance(row.get("geometry"), dict) else None) or [])


def _area(points):
    if len(points or []) < 3:
        return None
    return abs(sum(float(points[i][0]) * float(points[(i + 1) % len(points)][1]) -
                   float(points[(i + 1) % len(points)][0]) * float(points[i][1])
                   for i in range(len(points))) / 2.0)


def _centroid(points):
    if not points:
        return None
    return [sum(float(row[0]) for row in points) / len(points),
            sum(float(row[1]) for row in points) / len(points)]


def build_engineering_proposal(*, source_sha256, architecture, ambiguity_ids=(), answers=None,
                               model_proposals=()):
    """Build a reversible proposal from canonical geometry and explicit project inputs.

    This function never claims to detect a fixture.  It merely hosts design
    endpoints inside source-bound spaces and records every non-source value as
    a DRAFT design assumption.  Missing project/code/manufacturer inputs stay
    listed in ``missing_verified_data``.
    """
    answers = dict(answers or {})
    spaces = list(architecture.get("physical_spaces") or architecture.get("spaces") or [])
    zone_types = {}
    for zone in architecture.get("functional_zones") or []:
        identity = str(zone.get("physical_space_id") or zone.get("space_id") or "")
        category = zone.get("category") or zone.get("type")
        if identity and category:
            zone_types.setdefault(identity, str(category).lower())
    endpoints = []
    rooms = []
    design_zones=[]
    fixture_by_room_type = {
        "bathroom": ("wc", "basin", "shower", "floor_drain"),
        "toilet": ("wc", "basin", "floor_drain"),
        "wc": ("wc", "basin", "floor_drain"),
        "kitchen": ("sink", "stove", "exhaust_fan"),
        "laundry": ("sink", "floor_drain", "exhaust_fan"),
    }
    model_by_room={str(row.get("room_id")):row for row in model_proposals or []
                   if row.get("authority")=="MODEL_PROPOSED_DESIGN_ASSUMPTION"
                   and row.get("release_allowed") is False}
    for index, space in enumerate(spaces):
        polygon = _polygon(space)
        room_id = str(space.get("physical_space_id") or space.get("space_id") or space.get("id") or f"SPACE-{index+1}")
        room_type = str(space.get("category") or space.get("type") or zone_types.get(room_id) or "room").lower()
        point = space.get("centroid") or space.get("label_point") or _centroid(polygon)
        area = space.get("area_m2")
        if area is None:
            area = _area(polygon)
        rooms.append({"room_id": room_id, "room_type": room_type, "area_m2": area,
                      "point": point, "level_id":space.get("level_id") or space.get("frame_id"),
                      "source_sha256": source_sha256})
        if polygon:
            design_zones.append({"zone_id":"DRAFT-ZONE-"+room_id,"room_id":room_id,
                "room_type":room_type,"polygon":deepcopy(polygon),"centroid":point,
                "source_sha256":source_sha256,"authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION",
                "release_allowed":False})
        if point and _inside(point, polygon):
            model_row=model_by_room.get(room_id)
            selected_types=(model_row.get("endpoint_types") if model_row else
                            fixture_by_room_type.get(room_type, ()))
            for ordinal, fixture_type in enumerate(selected_types):
                endpoints.append({"id": f"DRAFT-{room_id}-{fixture_type}-{ordinal+1}",
                    "type": fixture_type, "room_id": room_id, "room_type": room_type,
                    "point": list(map(float, point)), "source_sha256": source_sha256,
                    "wet_core_id":room_id if fixture_type in {"wc","toilet","basin","sink","shower","floor_drain","bath"} else None,
                    "proposal_kind": "NEW_DESIGN_PROPOSAL", "source_fact": False,
                    "proposal_origin":"LLM_STRUCTURED_RESPONSE" if model_row else "DETERMINISTIC_ROOM_PROGRAM",
                    "ambiguity_id":model_row.get("ambiguity_id") if model_row else None,
                    "dependencies":list(model_row.get("dependencies") or []) if model_row else []})
    basis = {key: deepcopy(value) for key, value in answers.items()
             if key.endswith("_basis") or key in {"official_capacity_table", "manufacturer_line_sizing"}}
    # Normalize explicit owner-provided questionnaire facts into the typed
    # basis contract. This is transport, not inference: absent facts remain
    # absent and no official/manufacturer authority is fabricated.
    if "rainfall_basis" not in basis and (answers.get("rainfall_intensity_mm_h")
                                           or answers.get("rainfall_intensity")):
        basis["rainfall_basis"]={"intensity_mm_h":answers.get("rainfall_intensity_mm_h")
                                 or answers.get("rainfall_intensity"),
                                 "authority":"OWNER_DECLARED_PROJECT_FACT"}
    for system in ("heating","cooling"):
        key=system+"_design_basis"
        values={name:answers.get(name) for name in (system,system+"_system",system+"_load_kw")
                if answers.get(name) not in (None,"")}
        if key not in basis and values:
            basis[key]={**values,"authority":"OWNER_DECLARED_PROJECT_FACT"}
    if "gas_design_basis" not in basis:
        values={name:answers.get(name) for name in ("gas","gas_pressure","gas_relative_density")
                if answers.get(name) not in (None,"")}
        if values: basis["gas_design_basis"]={**values,"authority":"OWNER_DECLARED_PROJECT_FACT"}
    ventilation_usage = {
        "kitchen": "RESIDENTIAL_KITCHEN",
        "bathroom": "RESIDENTIAL_BATHROOM_OR_TOILET",
        "bath": "RESIDENTIAL_BATHROOM_OR_TOILET",
        "toilet": "RESIDENTIAL_BATHROOM_OR_TOILET",
        "wc": "RESIDENTIAL_BATHROOM_OR_TOILET",
    }
    ventilation_spaces = [
        {"space_id": row["room_id"], "usage": ventilation_usage[row["room_type"]],
         "source_sha256": source_sha256, "authority": "SOURCE_ARCHITECTURE_ROOM_TYPE"}
        for row in rooms if row.get("room_type") in ventilation_usage
    ]
    preliminary = dict(basis.get("preliminary_design_basis") or {})
    for key in ("gas_relative_density", "max_duct_velocity_m_s", "candidate_round_duct_diameters_mm"):
        if answers.get(key) not in (None, "", []):
            preliminary[key] = deepcopy(answers[key])
    if ventilation_spaces:
        preliminary["ventilation_spaces"] = ventilation_spaces
    if preliminary:
        basis["preliminary_design_basis"] = preliminary
    missing = []
    for key in ("water_design_basis", "sanitary_design_basis", "heating_design_basis",
                "cooling_design_basis", "gas_design_basis", "ventilation_design_basis",
                "rainfall_basis"):
        if key not in basis:
            missing.append(key)
    return {"schema": PROPOSAL_SCHEMA, "source_sha256": source_sha256,
            "ambiguity_ids": sorted(set(map(str, ambiguity_ids))),
            "source_inferences": [], "new_design_proposals": endpoints,
            "endpoints": endpoints, "rooms": rooms, "design_zones":design_zones, **basis,
            "missing_verified_data": sorted(missing), "release_allowed": False,
            "authority": "MODEL_PROPOSED_DESIGN_ASSUMPTION"}


def _inside(point, polygon):
    if len(point or []) != 2 or len(polygon or []) < 4: return False
    x,y=map(float,point); inside=False
    for index,a in enumerate(polygon):
        b=polygon[index-1]; ax,ay=map(float,a); bx,by=map(float,b)
        if ((ay>y)!=(by>y)) and x < (bx-ax)*(y-ay)/(by-ay)+ax: inside=not inside
    return inside


def materialize_engineering_overlay(*, source_sha256, architecture, proposal):
    """Return a validated overlay; missing/invalid engineering facts stay blocked."""
    if proposal.get("source_sha256") != source_sha256:
        return {"status":"INPUT_REQUIRED","errors":["PROPOSAL_SOURCE_MISMATCH"],"systems":{}}
    if proposal.get("schema") not in {None, PROPOSAL_SCHEMA}:
        return {"status":"INPUT_REQUIRED","errors":["PROPOSAL_SCHEMA_INVALID"],"systems":{}}
    spaces={str(row.get("physical_space_id") or row.get("space_id") or row.get("id")):row
            for row in (architecture.get("physical_spaces") or architecture.get("spaces") or [])}
    errors=[]; endpoints=[]
    for row in proposal.get("endpoints") or []:
        room=spaces.get(str(row.get("room_id"))); point=row.get("point")
        if row.get("type") not in ALLOWED_ENDPOINT_TYPES:
            errors.append("ENDPOINT_TYPE_INVALID:"+str(row.get("id"))); continue
        if not room or not _inside(point,_polygon(room)):
            errors.append("ENDPOINT_NOT_CONTAINED:"+str(row.get("id"))); continue
        if row.get("source_sha256") != source_sha256:
            errors.append("ENDPOINT_SOURCE_MISMATCH:"+str(row.get("id"))); continue
        endpoints.append({**deepcopy(row),"authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION",
                          "release_allowed":False})
    supplied=set(proposal)
    systems={}
    for system,required in SYSTEM_REQUIREMENTS.items():
        missing=sorted(required-supplied)
        if "endpoints" in required and not endpoints: missing.append("validated_endpoints")
        systems[system]={"status":"BLOCKED_INPUT" if missing else "READY_FOR_CALCULATION",
                         "missing":sorted(set(missing))}
    shaft_candidates=list(architecture.get("shafts") or architecture.get("vertical_cores") or [])
    for level in architecture.get("levels") or []:
        shaft_candidates.extend(level.get("shafts") or [])
    shafts=[]
    for row in shaft_candidates:
        polygon=_polygon(row) if row.get("closed",True) else []
        point=row.get("centroid") or row.get("point") or _centroid(polygon)
        if point:
            shafts.append({"shaft_id":str(row.get("shaft_id") or row.get("id")),
                           "shaft_key":str(row.get("shaft_key") or row.get("shaft_id") or row.get("id")),
                           "centroid":list(map(float,point)),"source":"ARCHITECTURAL_SHAFT_GEOMETRY",
                           "topology_role":"VERTICAL_SHAFT",
                           "polygon":[list(map(float,value)) for value in polygon] if len(polygon)>=3 else [],
                           "area_m2":row.get("area_m2") or row.get("area"),
                           "frame_id":row.get("frame_id"),"plan_id":row.get("plan_id"),
                           "source_handles":list(row.get("source_handles") or []),"release_allowed":False})
    room_rows=[]
    for row in proposal.get("rooms") or []:
        if str(row.get("room_id")) in spaces and row.get("source_sha256")==source_sha256:
            room_rows.append(deepcopy(row))
    # Canonical preliminary load engine: explicit DRAFT defaults are carried in
    # the output and remain replaceable; they are never represented as code or
    # manufacturer authority.
    from cad_engine.mechanical_calculations_v14 import calculate_mechanical_loads
    calc_arch={"units":6,"rooms":[{"id":row["room_id"],"type":row.get("room_type"),
                 "area_m2":row.get("area_m2")} for row in room_rows]}
    detections=[{"id":row["id"],"room_id":row["room_id"],
                 "category":"equipment" if row["type"] in {"stove","water_heater","exhaust_fan"} else "fixture",
                 "type":row["type"]} for row in endpoints]
    requirements={"rooms":[{"room_id":row["room_id"],"systems":["cold_water","hot_water","sanitary",
        "heating","cooling","exhaust","gas"]} for row in room_rows]}
    calculation=calculate_mechanical_loads(calc_arch,{"detections":detections},requirements,
                                            design_basis=proposal.get("preliminary_design_basis"))
    payload={"schema":"planha-project-draft-design-overlay/1.0",
             "source_sha256":source_sha256,"authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION",
             "release_allowed":False,"fixture_endpoints":endpoints,
             "shafts":shafts,
             "design_zones":deepcopy(proposal.get("design_zones") or []),
             "design_rooms":room_rows,
             "deterministic_calculation":calculation,
             "missing_verified_data":deepcopy(proposal.get("missing_verified_data") or []),
             "engineering_basis":{key:deepcopy(value) for key,value in proposal.items()
                                  if key.endswith("_basis") or key in {"official_capacity_table","manufacturer_line_sizing"}},
             "proposal_ids":sorted(str(value) for value in proposal.get("ambiguity_ids") or [])}
    payload["overlay_hash"]=sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"status":"INPUT_REQUIRED" if errors else "MATERIALIZED_DRAFT",
            "errors":errors,"systems":systems,"overlay":payload}
