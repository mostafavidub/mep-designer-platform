"""Fail-closed, generator-backed independent engineering deliverables."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import base64
import binascii
import io
import json
import math
import re
import tempfile
import zipfile
from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Polygon

from cad_engine.rainwater_calculations import design_roof_rainwater
from cad_engine.semantic_dimension_engine import source_numeric_dimension_policy

CONTRACT_VERSION = "planha-independent-engineering-deliverables/1.0"
SIMULATION_CONTRACT_VERSION = "planha-rainwater-simulation-preview/1.0"
SIMULATION_DISCLAIMER_FA = "آزمایشی — شدت بارندگی فرضی — غیرقابل استناد برای طراحی اجرایی و تأیید مهندسی"
READINESS_GATES = ("CALCULATION", "DRAWING", "DELIVERABLE_QA", "COORDINATION")
PROCESSING_STATES = {"BLOCKED_INPUT", "READY", "QUEUED", "RUNNING", "GENERATED",
                     "QA_PENDING", "QA_FAILED", "AVAILABLE", "FAILED", "STALE"}
RELEASE_LEVELS = {"DRAFT", "PRE_SUBMISSION", "ENGINEER_REVIEWED"}
GENERATOR_VERSIONS = {
    "MECH_ROOF_RAINWATER_SOURCE_PREVIEW": "rainwater-source-diagnostic-preview/1",
    "MECH_HEATING_SOURCE_DIAGNOSTIC_PREVIEW": "mechanical-source-diagnostic-preview/1",
    "MECH_COOLING_SOURCE_DIAGNOSTIC_PREVIEW": "mechanical-source-diagnostic-preview/1",
    "MECH_ROOF_RAINWATER_CALC": "rainwater-calculation/4",
    "MECH_ROOF_RAINWATER_PLAN": "rainwater-roof-plan/6",
    "MECH_WATER_SUPPLY_PACKAGE": "mechanical-system-package/47",
    "MECH_SANITARY_VENT_PACKAGE": "mechanical-system-package/49",
    "MECH_HEATING_PACKAGE": "mechanical-system-package/57",
    "MECH_COOLING_PACKAGE": "mechanical-system-package/49",
    "MECH_GAS_PACKAGE": "mechanical-system-package/49",
    "MECH_VENTILATION_PACKAGE": "mechanical-system-package/49",
}
QA_VERSIONS = {
    "MECH_ROOF_RAINWATER_SOURCE_PREVIEW": "rainwater-source-diagnostic-preview-qa/1",
    "MECH_HEATING_SOURCE_DIAGNOSTIC_PREVIEW": "mechanical-source-diagnostic-preview-qa/1",
    "MECH_COOLING_SOURCE_DIAGNOSTIC_PREVIEW": "mechanical-source-diagnostic-preview-qa/1",
    "MECH_ROOF_RAINWATER_CALC": "rainwater-calculation-qa/1",
    "MECH_ROOF_RAINWATER_PLAN": "rainwater-roof-plan-qa/2",
    "MECH_WATER_SUPPLY_PACKAGE": "mechanical-system-package-qa/2",
    "MECH_SANITARY_VENT_PACKAGE": "mechanical-system-package-qa/2",
    "MECH_HEATING_PACKAGE": "mechanical-system-package-qa/2",
    "MECH_COOLING_PACKAGE": "mechanical-system-package-qa/2",
    "MECH_GAS_PACKAGE": "mechanical-system-package-qa/2",
    "MECH_VENTILATION_PACKAGE": "mechanical-system-package-qa/2",
}

SYSTEM_PACKAGES = {
    "MECH_WATER_SUPPLY_PACKAGE": {"system":"WATER_SUPPLY", "family":"water_supply",
        "runtime_systems":["cold_water","hot_water"], "requirements":["water_pressure_basis","fixture_schedule"]},
    "MECH_SANITARY_VENT_PACKAGE": {"system":"SANITARY_VENT", "family":"sanitary_vent",
        "runtime_systems":["sanitary","vent"], "requirements":["fixture_schedule","shaft_coordination"]},
    "MECH_HEATING_PACKAGE": {"system":"HEATING", "family":"heating",
        "runtime_systems":["heating_supply","heating_return"], "requirements":["heating_basis","heating_loads"]},
    "MECH_COOLING_PACKAGE": {"system":"COOLING", "family":"cooling",
        "runtime_systems":["cooling","condensate"], "requirements":["cooling_basis","cooling_loads"]},
    "MECH_GAS_PACKAGE": {"system":"GAS", "family":"gas", "runtime_systems":["gas"],
        "requirements":["gas_pressure_basis","gas_appliance_loads"]},
    "MECH_VENTILATION_PACKAGE": {"system":"VENTILATION", "family":"ventilation_exhaust",
        "runtime_systems":["exhaust_ventilation"], "requirements":["ventilation_basis","airflow_loads"]},
}

SYSTEM_CALCULATION_CONTRACTS = {
    "MECH_WATER_SUPPLY_PACKAGE": {
        "systems": {"cold_water", "hot_water"},
        "edge_fields": ("flow_lps", "pressure_drop_pa"),
        "materials": {"PPR", "PEX", "COPPER", "CPVC"},
        "calculation_engines": {"design_water_network"},
    },
    "MECH_SANITARY_VENT_PACKAGE": {
        "systems": {"sanitary", "vent"},
        "edge_fields": ("fixture_units", "slope_percent"),
        "materials": {"PVC", "UPVC", "CAST_IRON"},
        "calculation_engines": {"calculate_mechanical_loads", "size_networks"},
    },
    "MECH_HEATING_PACKAGE": {
        "systems": {"heating_supply", "heating_return"},
        "edge_fields": ("load_kw", "delta_t_c"),
        "materials": {"STEEL", "PEX", "COPPER", "PPR"},
        "calculation_engines": {"calculate_heating_design", "design_heating_network"},
    },
    "MECH_COOLING_PACKAGE": {
        "systems": {"cooling", "refrigerant_liquid", "refrigerant_gas", "condensate"},
        "edge_fields": ("load_btu_h", "line_type"),
        "materials": {"COPPER", "PVC", "UPVC"},
        "calculation_engines": {"calculate_cooling_design", "size_networks"},
    },
    "MECH_GAS_PACKAGE": {
        "systems": {"gas"},
        "edge_fields": ("flow_m3_h", "inlet_pressure_mbar"),
        "materials": {"STEEL", "BLACK_STEEL", "COPPER"},
        "calculation_engines": {"design_gas_network"},
    },
    "MECH_VENTILATION_PACKAGE": {
        "systems": {"exhaust", "exhaust_ventilation"},
        "edge_fields": ("airflow_lps", "velocity_m_s"),
        "materials": {"GI", "GALVANIZED_STEEL", "ALUMINUM"},
        "calculation_engines": {"calculate_exhaust_design", "duct_velocity_sizing"},
    },
}

# Official Daikin Europe product/installation evidence for reversible DRAFT
# wall-split proposals.  These are immutable manufacturer values,
# not a generic sizing table: each selected pair must match one listed model,
# route length and connection set.  The drawings remain DRAFT because final
# room placement, dealer availability and design-condition correction are not
# owner/engineer approved.
DAIKIN_SENSIRA_FTXF_D = {
    "manufacturer": "Daikin Europe N.V.",
    "product_family": "Sensira FTXF-D / RXF-D",
    "catalogue_revision": "ECPEN22-050 01/2022",
    "catalogue_url": ("https://www.daikin.eu/content/dam/document-library/catalogues/ac/split/"
                      "ftxf-d/FTXF-D%2C%20RXF-D_Product%20flyer_ECPEN22-050_English.pdf"),
    "installation_revision": "3P512025-11Z 2021.10",
    "installation_url": ("https://www.daikin.eu/content/dam/document-library/installation-manuals/"
                         "ac/split/ftxf-d/FTXF-D_Installation%20manual_3PEN512025-11Z_English.pdf"),
    "models": {
        # ECPEN22-050 publishes the complete 20D--71D capacity series.  The
        # 20D--42D pipe diameters are independently fixed by installer guide
        # 4P519439-16R p.33.  Keeping diameters on each model prevents the
        # earlier 12.7 mm large-unit value from being silently applied to a
        # small unit.
        "FTXF20D5V1B+RXF20D": {"nominal_cooling_kw": 2.0, "max_cooling_kw": 2.4,
                                "liquid_od_mm": 6.4, "gas_od_mm": 9.5},
        "FTXF25D5V1B+RXF25D": {"nominal_cooling_kw": 2.5, "max_cooling_kw": 2.8,
                                "liquid_od_mm": 6.4, "gas_od_mm": 9.5},
        "FTXF35D5V1B+RXF35D": {"nominal_cooling_kw": 3.3, "max_cooling_kw": 3.8,
                                "liquid_od_mm": 6.4, "gas_od_mm": 9.5},
        "FTXF42D5V1B+RXF42D": {"nominal_cooling_kw": 4.2, "max_cooling_kw": 4.3,
                                "liquid_od_mm": 6.4, "gas_od_mm": 9.5},
        "FTXF60D5V1B6+RXF60D": {"nominal_cooling_kw": 6.0, "max_cooling_kw": 7.0,
                                 "liquid_od_mm": 6.4, "gas_od_mm": 12.7},
        "FTXF71D5V1B6+RXF71D": {"nominal_cooling_kw": 7.1, "max_cooling_kw": 7.3,
                                 "liquid_od_mm": 6.4, "gas_od_mm": 12.7},
    },
    "max_pipe_length_m": 30.0,
    "capacity_test_basis": {"indoor_db_c": 27, "indoor_wb_c": 19,
                            "outdoor_db_c": 35, "equivalent_pipe_m": 5,
                            "level_difference_m": 0},
}

# Iran National Building Regulations, Topic 17, fifth edition (1403),
# table 17-4-10.  Capacities are m3/h for welded steel pipe at 176 mmH2O
# inlet pressure, 12.7 mmH2O maximum pressure drop and natural-gas density
# 0.65.  Values are transcribed from the official INBR PDF and kept with its
# immutable SHA-256; they are not manufacturer data or an invented curve.
IRAN_MABHAS17_1403_GAS_TABLE = {
    "authority": "OFFICIAL_STANDARD",
    "standard": "Iran National Building Regulations Topic 17",
    "edition": "fifth edition 1403",
    "table": "17-4-10",
    "printed_page": 84,
    "official_url": "https://inbr.s3.ir-thr-at1.arvanstorage.ir/mabahse%2Fmabahse17%2Fmabhas17-watermark-1403-02.pdf?versionId=",
    "pdf_sha256": "eb575703d82dfe524ea227c1115c487f0d8c65aebb96442859ff68795fa70cc8",
    "inlet_pressure_mmh2o": 176.0,
    "inlet_pressure_mbar": 17.259,
    "allowable_pressure_drop_mmh2o": 12.7,
    "allowable_pressure_drop_mbar": 1.245,
    "relative_density": 0.65,
    "relative_density_correction_factors": {
        0.50: 1.15, 0.55: 1.08, 0.60: 1.04, 0.65: 1.00, 0.70: 0.96,
        0.75: 0.93, 0.80: 0.90, 0.85: 0.87, 0.90: 0.85, 1.00: 0.80,
    },
    "material": "WELDED_STEEL",
    "applicability_limitations": (
        "Applies only to the table conditions: welded steel natural-gas pipe, "
        "176 mmH2O inlet pressure, maximum 12.7 mmH2O pressure drop and relative "
        "density 0.65. Project-reported 20 mbar is not a regulator selection or "
        "utility guarantee; verify actual downstream regulated pressure, appliance "
        "data, meter/regulator, combustion air, flues and local authority requirements."
    ),
    "rows": {
        2:  {15:5.9,20:12.3,25:23.3,32:47.9,40:72.0,50:138.3,65:220.0,80:390.7,100:801.6},
        4:  {15:4.0,20:8.5,25:16.0,32:32.9,40:49.4,50:95.1,65:151.2,80:268.5,100:551.1},
        6:  {15:3.2,20:6.8,25:12.9,32:26.4,40:39.7,50:76.4,65:121.5,80:215.7,100:442.8},
        8:  {15:2.8,20:5.8,25:11.0,32:22.6,40:34.0,50:65.4,65:104.0,80:184.7,100:379.1},
        10: {15:2.4,20:5.0,25:9.6,32:19.7,40:29.6,50:56.9,65:90.4,80:160.6,100:329.7},
        12: {15:2.2,20:4.7,25:8.8,32:18.1,40:27.3,50:52.5,65:83.4,80:148.2,100:304.3},
        14: {15:2.0,20:4.3,25:8.1,32:16.7,40:25.0,50:48.2,65:76.6,80:136.1,100:279.4},
        16: {15:1.9,20:4.0,25:7.5,32:15.5,40:23.3,50:44.8,65:71.3,80:126.2,100:260.0},
        18: {15:1.8,20:3.7,25:7.1,32:14.6,40:21.9,50:42.2,65:67.1,80:119.3,100:244.8},
        20: {15:1.7,20:3.5,25:6.7,32:13.8,40:20.7,50:39.8,65:63.3,80:112.5,100:231.0},
        22: {15:1.6,20:3.3,25:6.3,32:13.1,40:19.6,50:37.8,65:60.1,80:106.8,100:219.4},
        24: {15:1.5,20:3.2,25:6.1,32:12.5,40:18.7,50:36.1,65:57.4,80:101.9,100:209.2},
        26: {15:1.4,20:3.1,25:5.8,32:12.0,40:18.0,50:34.6,65:55.1,80:97.9,100:200.9},
        28: {15:1.4,20:2.9,25:5.5,32:11.4,40:17.2,50:33.1,65:52.6,80:93.6,100:191.0},
        30: {15:1.3,20:2.8,25:5.3,32:11.0,40:16.6,50:31.9,65:50.8,80:90.3,100:185.1},
        35: {15:1.2,20:2.6,25:4.9,32:10.2,40:15.3,50:29.4,65:46.8,80:83.1,100:170.6},
        40: {15:1.1,20:2.4,25:4.6,32:9.4,40:14.1,50:27.1,65:43.3,80:76.9,100:157.9},
        45: {15:1.1,20:2.2,25:4.3,32:8.8,40:13.3,50:25.5,65:40.6,80:72.2,100:148.1},
        50: {15:1.0,20:2.1,25:4.1,32:8.4,40:12.6,50:24.3,65:38.6,80:68.7,100:141.0},
        55: {15:.99,20:2.0,25:3.9,32:8.0,40:12.0,50:23.1,65:36.7,80:65.2,100:133.9},
        60: {15:.94,20:1.9,25:3.7,32:7.6,40:11.5,50:22.1,65:35.1,80:62.4,100:127.1},
        70: {15:.85,20:1.8,25:3.3,32:6.9,40:10.4,50:20.0,65:31.8,80:56.5,100:116.1},
        80: {15:.80,20:1.6,25:3.1,32:6.5,40:9.7,50:18.8,65:29.8,80:53.1,100:108.9},
        90: {15:.75,20:1.5,25:2.9,32:6.1,40:9.1,50:17.6,65:28.0,80:49.7,100:102.0},
        100:{15:.71,20:1.4,25:2.8,32:5.7,40:8.6,50:16.6,65:26.4,80:47.0,100:96.5},
        120:{15:.64,20:1.3,25:2.5,32:5.2,40:7.8,50:15.0,65:23.9,80:42.5,100:87.3},
        150:{15:.57,20:1.2,25:2.2,32:4.6,40:6.9,50:13.3,65:21.2,80:37.7,100:77.5},
        200:{15:.49,20:1.0,25:1.9,32:3.9,40:5.9,50:11.4,65:18.1,80:32.2,100:66.2},
        250:{15:.43,20:.91,25:1.7,32:3.5,40:5.2,50:10.1,65:16.1,80:28.6,100:58.8},
        300:{15:.39,20:.82,25:1.5,32:3.1,40:4.7,50:9.2,65:14.6,80:25.9,100:53.2},
    },
}


def _official_iran_gas_capacity_rows(relative_density=0.65):
    factors=IRAN_MABHAS17_1403_GAS_TABLE["relative_density_correction_factors"]
    try: density=float(relative_density)
    except (TypeError,ValueError): raise ValueError("unsupported M17 Table 17-4-11 relative density")
    if density not in factors:
        raise ValueError("unsupported M17 Table 17-4-11 relative density")
    factor=factors[density]
    return [{"max_equivalent_length_m": length, "dn_mm": dn,
             "max_flow_m3h": round(flow*factor,4),
             "relative_density":density,"density_correction_factor":factor}
            for length, capacities in IRAN_MABHAS17_1403_GAS_TABLE["rows"].items()
            for dn, flow in capacities.items()]


def _validate_system_calculation_contract(deliverable_type, plan_analysis):
    """Reject a generic pipe graph relabelled as another engineering system."""
    contract = SYSTEM_CALCULATION_CONTRACTS[deliverable_type]
    graph = dict(plan_analysis.get("network_graph_canonical") or {})
    edges = list(graph.get("edges") or [])
    rows = list(plan_analysis.get("calculation_rows_canonical") or [])
    errors = []
    if not edges:
        return ["DOMAIN_NETWORK_GRAPH_MISSING"]
    by_calc = {str(row.get("calc_id")): row for row in rows if row.get("calc_id")}
    if len(by_calc) != len(rows):
        errors.append("DOMAIN_CALCULATION_ID_MISSING_OR_DUPLICATE")
    for edge in edges:
        edge_id = str(edge.get("id") or "UNKNOWN")
        system = str(edge.get("system") or "")
        calc_id = str(edge.get("calc_id") or "")
        material = str(edge.get("material") or "").upper()
        if system not in contract["systems"]:
            errors.append(f"DOMAIN_SYSTEM_MISMATCH:{edge_id}:{system}")
        if material not in contract["materials"]:
            errors.append(f"DOMAIN_MATERIAL_MISMATCH:{edge_id}:{material}")
        row = by_calc.get(calc_id)
        if not row or str(row.get("system") or "") != system:
            errors.append(f"DOMAIN_CALCULATION_LINK_MISMATCH:{edge_id}:{calc_id}")
            continue
        engine = str(row.get("calculation_engine") or "")
        if engine not in contract["calculation_engines"]:
            errors.append(f"DOMAIN_CALCULATION_ENGINE_INVALID:{edge_id}:{engine}")
        if not row.get("source_input_ids") or not isinstance(row.get("formula_inputs"), dict):
            errors.append(f"DOMAIN_CALCULATION_LINEAGE_MISSING:{edge_id}:{calc_id}")
        for field in contract["edge_fields"]:
            value = edge.get(field, row.get(field))
            if value in (None, "", []):
                errors.append(f"DOMAIN_CALCULATION_FIELD_MISSING:{edge_id}:{field}")
                continue
            if field not in {"line_type"}:
                try:
                    if not math.isfinite(float(value)) or float(value) <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"DOMAIN_CALCULATION_FIELD_INVALID:{edge_id}:{field}")
    return sorted(set(errors))


def _level_bounds_area(level):
    bounds = level.get("region_bounds") or []
    if len(bounds) != 4:
        return math.inf
    width = float(bounds[2]) - float(bounds[0])
    height = float(bounds[3]) - float(bounds[1])
    area = width * height
    return area if math.isfinite(area) and area > 0 else math.inf


def _level_contains_points(level, points):
    bounds = level.get("region_bounds") or []
    if len(bounds) != 4 or not points or not math.isfinite(_level_bounds_area(level)):
        return False
    try:
        return all(
            math.isfinite(float(point[0])) and math.isfinite(float(point[1]))
            and float(bounds[0]) <= float(point[0]) <= float(bounds[2])
            and float(bounds[1]) <= float(point[1]) <= float(bounds[3])
            for point in points
        )
    except (TypeError, ValueError, IndexError):
        return False


def _draft_domain_routed_graph_single(deliverable_type, pmm, architecture, overlay, answers=None):
    """Route and size real per-room DRAFT branches for dry Mechanical domains.

    The overlay supplies reversible endpoint/shaft geometry and per-room design
    loads.  Canonical calculators still own every size; this adapter only binds
    their results to collision-checked, source-frame plan paths.  Cooling line
    pairs additionally require an exact official manufacturer model contract.
    """
    supported = {"MECH_HEATING_PACKAGE", "MECH_COOLING_PACKAGE", "MECH_GAS_PACKAGE", "MECH_VENTILATION_PACKAGE"}
    if deliverable_type not in supported:
        return None

    def _numeric_value(value):
        if isinstance(value, str):
            match = re.search(r"[-+]?\d+(?:[.,]\d+)?", value.translate(
                str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
            value = match.group(0).replace(",", ".") if match else None
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except (TypeError, ValueError):
            return None
    levels = list(pmm.get("levels") or [])
    design_rooms = {str(row.get("room_id")): row
                    for row in overlay.get("design_rooms") or [] if row.get("room_id")}
    rooms = []
    for raw in (overlay.get("deterministic_calculation") or {}).get("rooms") or []:
        room = deepcopy(raw)
        design_room = design_rooms.get(str(room.get("room_id"))) or {}
        room.setdefault("point", design_room.get("point"))
        room.setdefault("level_id", design_room.get("level_id"))
        rooms.append(room)
    endpoints = list(overlay.get("fixture_endpoints") or [])
    shafts = list(overlay.get("shafts") or [])
    endpoints_required = deliverable_type in {"MECH_GAS_PACKAGE", "MECH_VENTILATION_PACKAGE"}
    if not levels or not rooms or (endpoints_required and not endpoints):
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ROUTE_EVIDENCE"]}
    if len(levels) == 1:
        level = dict(levels[0])
    else:
        from .mechanical_network_topology import _typed_level
        room_points = [row.get("point") for row in rooms
                       if isinstance(row.get("point"), (list, tuple)) and len(row["point"]) == 2]
        containing = []
        for row in levels:
            bounds = row.get("region_bounds")
            if (len(bounds or []) == 4 and room_points
                    and all(float(bounds[0]) <= float(point[0]) <= float(bounds[2])
                            and float(bounds[1]) <= float(point[1]) <= float(bounds[3])
                            for point in room_points)):
                area = (float(bounds[2]) - float(bounds[0])) * (float(bounds[3]) - float(bounds[1]))
                if area > 0 and math.isfinite(area):
                    containing.append((area, row))
        containing.sort(key=lambda item: item[0])
        if containing and (len(containing) == 1 or containing[0][0] < containing[1][0]):
            level = dict(containing[0][1])
            level["type"] = _typed_level(level.get("name"))
        else:
            applicable = [(row, _typed_level(row.get("name"))) for row in levels]
            applicable = [(row, level_type) for row, level_type in applicable
                          if str(level_type or "").startswith("TYPICAL_")]
            if len(applicable) != 1:
                return {"status": "INPUT_REQUIRED", "missing_inputs": [
                    "DRAFT_DOMAIN_LEVEL_FROM_SOURCE_ROOM_GEOMETRY_REQUIRED"]}
            level = dict(applicable[0][0])
            level["type"] = applicable[0][1]
    level["id"] = level.get("id") or "DRAFT-" + stable_hash({
        "name": level.get("name"), "type": level.get("type")})[:16].upper()
    source_levels = list(architecture.get("levels") or [])
    room_points = [row.get("point") for row in rooms
                   if isinstance(row.get("point"), (list, tuple)) and len(row["point"]) == 2]
    binding_points = [*room_points,
                      *(row.get("point") for row in endpoints
                        if isinstance(row.get("point"), (list, tuple)) and len(row["point"]) == 2),
                      *((row.get("centroid") or row.get("point")) for row in shafts
                        if isinstance(row.get("centroid") or row.get("point"), (list, tuple))
                        and len(row.get("centroid") or row.get("point")) == 2)]
    # PMM level labels are normalized (for example ``Typical`` becomes a
    # typed level) while the source Architecture model retains its printed
    # title.  A name-only join therefore selected a broad drawing frame in
    # multi-frame files and silently extrapolated room/shaft coordinates into
    # the target board.  Bind the source level by exact containment of every
    # source-backed room point and choose it only when the smallest containing
    # frame is unique.  Name remains useful evidence, but can never override
    # incompatible geometry.
    named_levels = [row for row in source_levels
                    if str(row.get("name") or "") == str(level.get("name") or "")]
    named_levels = [row for row in named_levels if _level_contains_points(row, binding_points)]
    if len(named_levels) == 1:
        source_level = named_levels[0]
    else:
        containing_source_levels = [row for row in source_levels
                                    if _level_contains_points(row, binding_points)]
        containing_source_levels.sort(key=_level_bounds_area)
        source_level = (containing_source_levels[0]
                        if containing_source_levels and (
                            len(containing_source_levels) == 1
                            or _level_bounds_area(containing_source_levels[0])
                            < _level_bounds_area(containing_source_levels[1]))
                        else {})
    if not source_level and len(source_levels) == 1:
        source_level = source_levels[0]
    if not source_level and len(source_levels) > 1:
        return {"status": "INPUT_REQUIRED", "missing_inputs": [
            "DRAFT_DOMAIN_SOURCE_LEVEL_FRAME_BINDING_REQUIRED"]}
    bounds = source_level.get("region_bounds") or (architecture.get("draft_routing_scope") or {}).get("bounds")
    walls = [row for row in source_level.get("walls") or []
             if isinstance(row.get("start"), (list, tuple)) and isinstance(row.get("end"), (list, tuple))]
    if not bounds:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ROUTE_BOUNDS"]}

    room_by_id = {str(row.get("room_id")): row for row in rooms}
    if not room_by_id:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ROOM_LOAD_BREAKDOWN"]}
    valid_sha = str(overlay.get("source_sha256") or "")
    provenance = dict((answers or {}).get("_engineering_input_provenance") or {})
    engineering_basis = dict(overlay.get("engineering_basis") or {})

    def answer_number(key):
        record = dict(provenance.get(key) or {})
        basis_name = {
            "heating_load_kw": "heating_design_basis",
            "cooling_load_kw": "cooling_design_basis",
        }.get(key)
        basis = dict(engineering_basis.get(basis_name) or {}) if basis_name else {}
        if (not record and basis.get("authority") == "OWNER_DECLARED_PROJECT_FACT"
                and basis.get(key) not in (None, "")
                and _numeric_value(basis.get(key)) == _numeric_value((answers or {}).get(key))):
            record = {"authority": "OWNER_DECLARED_PROJECT_FACT",
                      "source_sha256": valid_sha,
                      "transport": basis_name}
            provenance[key] = record
        if not record and key in {"ventilation_airflow_lps", "gas_appliance_load_kw"}:
            record = {"authority": "USER_CONFIRMED", "source_sha256": valid_sha}
            provenance[key] = record
        if record.get("authority") not in {"USER_CONFIRMED", "ENGINEERING_CALCULATION",
                                             "SOURCE_DOCUMENT", "MODEL_PROPOSED_DRAFT_CALCULATION",
                                             "OWNER_DECLARED_PROJECT_FACT"}:
            return None
        if record.get("source_sha256") and str(record["source_sha256"]) != valid_sha:
            return None
        value = (answers or {}).get(key)
        if isinstance(value, str):
            match = re.search(r"[-+]?\d+(?:[.,]\d+)?", value.translate(
                str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
            value = match.group(0).replace(",", ".") if match else None
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) and parsed > 0 else None
        except (TypeError, ValueError):
            return None

    # Explicit project totals are reversible design inputs. Allocate them to
    # source-bound rooms by area; the room identity and scalar provenance are
    # retained in every calculation row. Existing positive deterministic
    # room loads take precedence and are never overwritten.
    scalar_specs = {
        "MECH_HEATING_PACKAGE": ("heating_load_kw", "heating_w", 1000.0),
        "MECH_COOLING_PACKAGE": ("cooling_load_kw", "cooling_w", 1000.0),
        "MECH_VENTILATION_PACKAGE": ("ventilation_airflow_lps", "exhaust_cfm", 1 / 0.47194745),
    }
    if deliverable_type in scalar_specs:
        answer_key, room_key, multiplier = scalar_specs[deliverable_type]
        load_rooms = [row for row in rooms if str(row.get("room_type") or "").lower()
                      not in {"shaft", "vertical_core", "stair", "elevator"}]
        if deliverable_type == "MECH_VENTILATION_PACKAGE":
            hosted = {str(row.get("room_id")) for row in endpoints
                      if str(row.get("type") or "").lower() == "exhaust_fan"}
            load_rooms = [row for row in load_rooms if str(row.get("room_id")) in hosted]
        if not load_rooms:
            return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ROOM_LOAD_BREAKDOWN"]}
        if not any(float(row.get(room_key) or 0) > 0 for row in load_rooms):
            total = answer_number(answer_key)
            if total is None:
                return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ROOM_LOAD_BREAKDOWN"]}
            weights = [max(float(row.get("area_m2") or 0), 0.0) for row in load_rooms]
            if sum(weights) <= 0:
                weights = [1.0] * len(load_rooms)
            for row, weight in zip(load_rooms, weights):
                row[room_key] = total * multiplier * weight / sum(weights)
                row[room_key + "_lineage"] = {"input_id": answer_key,
                    "authority": provenance[answer_key]["authority"],
                    "allocation": "SOURCE_ROOM_AREA_PROPORTION", "release_allowed": False}

    for source_room in source_level.get("rooms") or []:
        if str(source_room.get("type") or "").lower() != "shaft":
            continue
        point = source_room.get("center") or source_room.get("centroid")
        if isinstance(point, (list, tuple)) and len(point) == 2:
            shafts.append({
                "shaft_id": source_room.get("id"), "shaft_key": source_room.get("id"),
                "centroid": list(point), "polygon": deepcopy(source_room.get("polygon") or []),
                "source": "ARCHITECTURAL_SHAFT_ROOM",
                "source_handles": list(source_room.get("source_handles") or []),
            })
    shaft_rows = []
    for shaft in shafts:
        point = shaft.get("centroid") or shaft.get("point")
        if isinstance(point, (list, tuple)) and len(point) == 2:
            shaft_rows.append((shaft, [float(point[0]), float(point[1])]))
    if not shaft_rows:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_SHAFT_CENTROID"]}

    def room_point(room):
        point = room.get("point") or room.get("centroid")
        if not (isinstance(point, (list, tuple)) and len(point) == 2):
            hosted = [row.get("point") for row in endpoints
                      if str(row.get("room_id")) == str(room.get("room_id"))
                      and isinstance(row.get("point"), (list, tuple)) and len(row.get("point")) == 2]
            if hosted:
                point = [sum(float(value[0]) for value in hosted) / len(hosted),
                         sum(float(value[1]) for value in hosted) / len(hosted)]
        return [float(point[0]), float(point[1])] if isinstance(point, (list, tuple)) and len(point) == 2 else None

    def nearest_shaft(room):
        point = room_point(room)
        return min(shaft_rows, key=lambda item: math.dist(point, item[1]))[0] if point else None

    def cooling_models(load_kw):
        models = sorted(DAIKIN_SENSIRA_FTXF_D["models"].items(),
                        key=lambda item: item[1]["nominal_cooling_kw"], reverse=True)
        max_units = max(1, int(math.ceil(load_kw / min(row[1]["nominal_cooling_kw"] for row in models))) + 1)
        choices = []
        def visit(prefix, start, remaining):
            if prefix:
                nominal = sum(DAIKIN_SENSIRA_FTXF_D["models"][name]["nominal_cooling_kw"] for name in prefix)
                if load_kw <= nominal <= load_kw * 1.25:
                    choices.append((nominal, len(prefix), tuple(prefix)))
            if remaining == 0: return
            for index in range(start, len(models)):
                visit(prefix + [models[index][0]], index, remaining - 1)
        visit([], 0, max_units)
        # Prefer the fewest source-qualified units, then the least nominal
        # oversize.  Sorting the raw tuple by nominal capacity first caused a
        # proliferation of small indoor units even when a smaller-count exact
        # manufacturer combination existed.
        return list(min(choices, key=lambda row: (row[1], row[0]))[2]) if choices else []

    selected = []
    for row in endpoints:
        kind = str(row.get("type") or "").lower()
        if deliverable_type == "MECH_GAS_PACKAGE" and kind in {"stove", "water_heater"}:
            selected.append(row)
        elif deliverable_type == "MECH_VENTILATION_PACKAGE" and kind == "exhaust_fan":
            selected.append(row)
    if deliverable_type in {"MECH_HEATING_PACKAGE", "MECH_COOLING_PACKAGE"}:
        load_key = "heating_w" if deliverable_type == "MECH_HEATING_PACKAGE" else "cooling_w"
        for room_id, room in sorted(room_by_id.items()):
            if str(room.get("room_type") or "").lower() in {"shaft", "vertical_core", "stair", "elevator"}:
                continue
            point = room_point(room)
            load = float(room.get(load_key) or 0)
            if not point or load <= 0: continue
            nearest = nearest_shaft(room)
            shaft_point = ((nearest or {}).get("centroid") or (nearest or {}).get("point"))
            if (isinstance(shaft_point, (list, tuple)) and len(shaft_point) == 2
                    and math.dist(point, [float(shaft_point[0]), float(shaft_point[1])]) <= 1e-6):
                polygon = room.get("polygon") or []
                measured = _polygon_area_centroid(polygon)
                if not measured or not polygon:
                    return {"status":"INPUT_REQUIRED", "missing_inputs":[
                        "DRAFT_DOMAIN_DISTINCT_TERMINAL_LOCATION_REQUIRED:" + room_id]}
                vertex = [float(polygon[0][0]), float(polygon[0][1])]
                # Reversible interior point derived only from the exact source
                # polygon; it is a DRAFT terminal location, never verified
                # fixture/equipment geometry.
                point = [point[0] + 0.25 * (vertex[0] - point[0]),
                         point[1] + 0.25 * (vertex[1] - point[1])]
            models = [None] if deliverable_type == "MECH_HEATING_PACKAGE" else cooling_models(load / 1000.0)
            if not models:
                return {"status": "INPUT_REQUIRED", "missing_inputs": [
                    "COOLING_MANUFACTURER_CAPACITY_SELECTION_OUT_OF_RANGE:" + room_id]}
            for ordinal, model in enumerate(models, 1):
                selected.append({"id": "DRAFT-%s-%s-%02d" % (
                    "RADIATOR" if deliverable_type == "MECH_HEATING_PACKAGE" else "SPLIT",
                    stable_hash(room_id)[:10].upper(), ordinal),
                    "type": "radiator" if deliverable_type == "MECH_HEATING_PACKAGE" else "wall_mounted_split_ac",
                    "room_id": room_id, "point": [point[0] + 0.12 * (ordinal - 1), point[1]],
                    "manufacturer_model": model, "source_sha256": valid_sha,
                    "authority": "MODEL_PROPOSED_DESIGN_ASSUMPTION", "release_allowed": False})
    if not selected:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ENDPOINTS"]}

    from .routing import _open_space_route, _score, _collision_wall_ids, _terminal_penetration_wall_ids
    system = {"MECH_HEATING_PACKAGE": "heating_supply", "MECH_COOLING_PACKAGE": "cooling",
              "MECH_GAS_PACKAGE": "gas",
              "MECH_VENTILATION_PACKAGE": "exhaust_ventilation"}[deliverable_type]
    nodes = []
    shaft_nodes = {}
    for shaft, point in sorted(shaft_rows, key=lambda item: str(item[0].get("shaft_id") or item[0].get("shaft_key"))):
        key = str(shaft.get("shaft_key") or shaft.get("shaft_id"))
        node_id = "DRAFT-DOMAIN-SHAFT-" + stable_hash(key)[:12].upper()
        shaft_nodes[key] = node_id
        source = shaft.get("source") or shaft.get("authority")
        if (source == "SOURCE_GEOMETRY_DRAFT_SHAFT_USE"
                and shaft.get("source_handles")):
            # Preserve the source geometry authority while keeping its DRAFT
            # engineering use and release=false contract.  The architecture
            # adapter performs the same normalization, but this graph consumes
            # the persisted overlay directly.
            source = "ARCHITECTURAL_SHAFT_GEOMETRY"
        nodes.append({"id": node_id, "kind": "shaft", "category": "vertical_core",
                      "point": [float(point[0]), float(point[1])], "level": level.get("id"),
                      "source": source,
                      "shaft_key": shaft.get("shaft_key") or shaft.get("shaft_id")})

    route_rows = []
    for endpoint in sorted(selected, key=lambda row: str(row.get("id") or "")):
        endpoint_id = str(endpoint.get("id") or "")
        room_id = str(endpoint.get("room_id") or "")
        point = endpoint.get("point")
        shaft_source = nearest_shaft(room_by_id.get(room_id) or {})
        shaft_key = str((shaft_source or {}).get("shaft_key") or (shaft_source or {}).get("shaft_id"))
        shaft = next((row for row in nodes if row["id"] == shaft_nodes.get(shaft_key)), None)
        if not endpoint_id or room_id not in room_by_id or not isinstance(point, (list, tuple)) or len(point) != 2:
            return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ENDPOINT_BINDING"]}
        if shaft is None:
            return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_SHAFT_BINDING:" + room_id]}
        start = tuple(shaft["point"]); end = (float(point[0]), float(point[1]))
        path = _open_space_route(start, end, bounds, walls, True, True)
        if not path:
            return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_DOMAIN_ROUTE_CONFLICT:" + endpoint_id]}
        if (len(path) == 2 and path[0][0] != path[1][0]
                and path[0][1] != path[1][1]):
            orthogonal = [[path[0], (path[1][0], path[0][1]), path[1]],
                          [path[0], (path[0][0], path[1][1]), path[1]]]
            path = min(orthogonal, key=lambda candidate: _score(candidate, walls, True, True))
        clashes, _length, penetrations = _score(path, walls, True, True)
        collision_ids = _collision_wall_ids(path, walls, True, True)
        if clashes or collision_ids:
            return {"status": "INPUT_REQUIRED", "missing_inputs": [
                "DRAFT_DOMAIN_ROUTE_WALL_CONFLICT:%s:%s" % (endpoint_id, ",".join(collision_ids))]}
        node_id = "DRAFT-DOMAIN-ENDPOINT-" + endpoint_id
        nodes.append({"id": node_id,
                      "kind": {"MECH_HEATING_PACKAGE": "heating_terminal",
                               "MECH_COOLING_PACKAGE": "split_ac_indoor_unit",
                               "MECH_GAS_PACKAGE": "gas_appliance",
                               "MECH_VENTILATION_PACKAGE": "exhaust_terminal"}[deliverable_type],
                      "category": "equipment", "point": [end[0], end[1]],
                      "level": level.get("id"), "room_id": room_id, "ports": [system],
                      "source_detection_id": endpoint_id,
                      "manufacturer_model": endpoint.get("manufacturer_model"),
                      "selected_nominal_cooling_kw": (
                          DAIKIN_SENSIRA_FTXF_D["models"].get(
                              endpoint.get("manufacturer_model"), {}).get("nominal_cooling_kw")
                          if deliverable_type == "MECH_COOLING_PACKAGE" else None),
                      "authority": endpoint.get("authority"), "release_allowed": False})
        route_rows.append({"endpoint": endpoint, "room": room_by_id[room_id],
                           "from": shaft["id"], "to": node_id, "path": path,
                           "penetrations": penetrations,
                           "penetration_wall_ids": _terminal_penetration_wall_ids(path, walls, True, True)})

    edges = []
    calculations = []
    if deliverable_type == "MECH_HEATING_PACKAGE":
        from .mechanical_execution_sizing import design_heating_network
        segment_inputs = []
        radiators = []
        for index, row in enumerate(route_rows, 1):
            edge_id = "DRAFT-HEATING-BRANCH-%02d" % index
            radiator_id = "DRAFT-HEATING-LOAD-" + stable_hash(row["endpoint"].get("room_id"))[:12].upper()
            segment_inputs.append({"id": edge_id, "system": system,
                                   "downstream_radiator_ids": [radiator_id]})
            radiators.append({"radiator_id": radiator_id,
                              "selected_output_w": float(row["room"]["heating_w"])})
        result = design_heating_network(segment_inputs, radiators, {
            "design_delta_t_k": 20, "fluid_density_kg_m3": 998,
            "fluid_specific_heat_j_kgk": 4180,
            "candidate_diameters_mm": [16, 20, 25, 32, 40], "max_velocity_m_s": 1.5})
        if result.get("status") != "PASS":
            return {"status": "INPUT_REQUIRED", "missing_inputs": result.get("errors") or ["HEATING_BRANCH_SIZING"]}
        sized_by_id = {row["segment_id"]: row for row in result["segments"]}
        for index, route in enumerate(route_rows, 1):
            edge_id = "DRAFT-HEATING-BRANCH-%02d" % index; sized = sized_by_id[edge_id]
            calculations.append({"calc_id": sized["calc_id"], "network_edge_id": edge_id,
                                 "system": "heating_supply",
                                 "size": sized["selected_dn_mm"], "material": "PEX",
                                 "load_kw": float(route["room"]["heating_w"]) / 1000,
                                 "delta_t_c": 20, "calculation_engine": "design_heating_network"})
    elif deliverable_type == "MECH_COOLING_PACKAGE":
        model_rows = DAIKIN_SENSIRA_FTXF_D["models"]
        by_room = {room_id: [row for row in route_rows if str(row["endpoint"].get("room_id")) == room_id]
                   for room_id in room_by_id}
        for key, rows in by_room.items():
            if not rows: continue
            room_load_kw = float(room_by_id[key]["cooling_w"]) / 1000.0
            nominal_kw = sum(model_rows[row["endpoint"]["manufacturer_model"]]["nominal_cooling_kw"]
                             for row in rows)
            if nominal_kw < room_load_kw or nominal_kw > room_load_kw * 1.25:
                return {"status": "INPUT_REQUIRED", "missing_inputs": [
                    "COOLING_MANUFACTURER_CAPACITY_SELECTION_OUT_OF_RANGE:" + key]}
            per_unit_kw = room_load_kw / len(rows)
            for row in rows:
                index = route_rows.index(row) + 1
                edge_id = "DRAFT-COOLING-BRANCH-%02d" % index
                length_m = sum(math.dist(a, b) for a, b in zip(row["path"], row["path"][1:]))
                if length_m > DAIKIN_SENSIRA_FTXF_D["max_pipe_length_m"]:
                    return {"status": "INPUT_REQUIRED", "missing_inputs": [
                        "COOLING_MANUFACTURER_MAX_LINE_LENGTH_EXCEEDED:" + edge_id]}
                calc_id = "CALC-COOL-" + stable_hash({"edge": edge_id, "model": row["endpoint"]["manufacturer_model"],
                                                       "load_kw": per_unit_kw, "length_m": length_m})[:12].upper()
                calculations.append({
                    "calc_id": calc_id, "network_edge_id": edge_id,
                    "system": "cooling",
                    "size": model_rows[row["endpoint"]["manufacturer_model"]]["gas_od_mm"],
                    "material": "COPPER",
                    "load_btu_h": round(per_unit_kw * 3412.142, 1),
                    "line_type": "PAIR_LIQUID_%sMM_GAS_%sMM" % (
                        model_rows[row["endpoint"]["manufacturer_model"]]["liquid_od_mm"],
                        model_rows[row["endpoint"]["manufacturer_model"]]["gas_od_mm"]),
                    "calculation_engine": "calculate_cooling_design",
                    "manufacturer": DAIKIN_SENSIRA_FTXF_D["manufacturer"],
                    "manufacturer_model": row["endpoint"]["manufacturer_model"],
                    "manufacturer_catalogue_revision": DAIKIN_SENSIRA_FTXF_D["catalogue_revision"],
                    "manufacturer_catalogue_url": DAIKIN_SENSIRA_FTXF_D["catalogue_url"],
                    "manufacturer_installation_revision": DAIKIN_SENSIRA_FTXF_D["installation_revision"],
                    "manufacturer_installation_url": DAIKIN_SENSIRA_FTXF_D["installation_url"],
                    "line_length_m": round(length_m, 3),
                })
    elif deliverable_type == "MECH_GAS_PACKAGE":
        from .mechanical_execution_sizing import design_gas_network
        segment_inputs = []; appliances = []
        complete_basis = dict((overlay.get("deterministic_calculation") or {}).get("design_basis") or {})
        gas_basis = dict(complete_basis.get("gas_kw") or {})
        capacity_table = complete_basis.get("gas_capacity_table")
        capacity_authority = complete_basis.get("gas_capacity_table_authority")
        relative_density = complete_basis.get("gas_relative_density")
        density_factor = None
        service_pressure = (answers or {}).get("gas_pressure")
        allowable_drop = complete_basis.get("gas_allowable_pressure_drop_mbar")
        if capacity_table is None and capacity_authority is None:
            if relative_density in (None, ""):
                return {"status": "INPUT_REQUIRED", "missing_inputs": [
                    "GAS_RELATIVE_DENSITY_PROJECT_CONTRACT"]}
            try:
                capacity_table = _official_iran_gas_capacity_rows(relative_density)
            except ValueError:
                return {"status": "INPUT_REQUIRED", "missing_inputs": [
                    "GAS_RELATIVE_DENSITY_EXACT_M17_TABLE_17_4_11_ROW"]}
            relative_density = float(relative_density)
            density_factor = IRAN_MABHAS17_1403_GAS_TABLE["relative_density_correction_factors"][relative_density]
            capacity_authority = IRAN_MABHAS17_1403_GAS_TABLE["authority"]
            allowable_drop = IRAN_MABHAS17_1403_GAS_TABLE["allowable_pressure_drop_mbar"]
        if (not isinstance(capacity_table, list) or not capacity_table
                or capacity_authority not in {"OFFICIAL_STANDARD", "ENGINEER_APPROVED", "SYNTHETIC_TEST_ONLY"}):
            return {"status": "INPUT_REQUIRED", "missing_inputs": [
                "GAS_CAPACITY_TABLE_OFFICIAL_OR_ENGINEER_APPROVED"]}
        if service_pressure in (None, "") or allowable_drop in (None, ""):
            return {"status": "INPUT_REQUIRED", "missing_inputs": [
                "GAS_PRESSURE_AND_ALLOWABLE_DROP_BASIS"]}
        service_pressure_value = _numeric_value(service_pressure)
        if service_pressure_value is None or service_pressure_value < IRAN_MABHAS17_1403_GAS_TABLE["inlet_pressure_mbar"]:
            return {"status": "INPUT_REQUIRED", "missing_inputs": [
                "GAS_SERVICE_PRESSURE_BELOW_OFFICIAL_TABLE_CONDITION"]}
        for index, row in enumerate(route_rows, 1):
            edge_id = "DRAFT-GAS-BRANCH-%02d" % index; appliance_id = str(row["endpoint"]["id"])
            thermal_kw = float(gas_basis.get(row["endpoint"].get("type")) or 0)
            if thermal_kw <= 0:
                total_kw = answer_number("gas_appliance_load_kw")
                thermal_kw = (total_kw / len(route_rows)) if total_kw else 0
            if thermal_kw <= 0:
                return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAFT_GAS_APPLIANCE_LOAD:" + appliance_id]}
            flow = round(thermal_kw / 10.5, 3)
            segment_inputs.append({"id": edge_id, "downstream_appliance_ids": [appliance_id],
                                   "equivalent_length_m": sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(row["path"],row["path"][1:]))})
            appliances.append({"id": appliance_id, "pmm_id": appliance_id,
                               "manufacturer": "UNSELECTED", "model": "DRAFT",
                               "thermal_input_kw": thermal_kw, "gas_consumption_m3h": flow,
                               "datasheet": {"official_url": "INPUT_REQUIRED", "revision": "DRAFT", "sha256": "0"*64},
                               "appliance_valve": "required", "flue": "required", "combustion_air": "required"})
        result = design_gas_network(segment_inputs, appliances, {
            "capacity_table": capacity_table,
            "service_pressure_mbar": IRAN_MABHAS17_1403_GAS_TABLE["inlet_pressure_mbar"],
            "allowable_pressure_drop_mbar": float(allowable_drop),
            "meter": "DRAFT_UNSELECTED", "regulator": "DRAFT_UNSELECTED",
            "service_shutoff": "required", "riser": "DRAFT", "fittings": "DRAFT", "sleeves": "required"})
        if result.get("status") != "PASS":
            return {"status": "INPUT_REQUIRED", "missing_inputs": result.get("errors") or ["GAS_BRANCH_SIZING"]}
        sized_by_id = {row["segment_id"]: row for row in result["segments"]}
        for index, route in enumerate(route_rows, 1):
            edge_id = "DRAFT-GAS-BRANCH-%02d" % index; sized = sized_by_id[edge_id]
            calculations.append({"calc_id": sized["calc_id"], "network_edge_id": edge_id,
                                 "system": "gas",
                                 "size": sized["selected_dn_mm"], "material": "BLACK_STEEL",
                                 "flow_m3_h": sized["flow_m3h"], "inlet_pressure_mbar": sized["service_pressure_mbar"],
                                 "calculation_engine": "design_gas_network",
                                 "capacity_standard": IRAN_MABHAS17_1403_GAS_TABLE["standard"],
                                 "capacity_standard_edition": IRAN_MABHAS17_1403_GAS_TABLE["edition"],
                                 "capacity_table_id": IRAN_MABHAS17_1403_GAS_TABLE["table"],
                                 "capacity_standard_printed_page": IRAN_MABHAS17_1403_GAS_TABLE["printed_page"],
                                 "capacity_standard_url": IRAN_MABHAS17_1403_GAS_TABLE["official_url"],
                                 "capacity_standard_sha256": IRAN_MABHAS17_1403_GAS_TABLE["pdf_sha256"],
                                 "gas_relative_density": relative_density,
                                 "density_correction_table_id": "17-4-11",
                                 "density_correction_factor": density_factor,
                                 "allowable_pressure_drop_mbar": sized["allowable_pressure_drop_mbar"],
                                 "capacity_applicability_limitations": IRAN_MABHAS17_1403_GAS_TABLE["applicability_limitations"],
                                 "project_reported_service_pressure_mbar": service_pressure_value})
    else:
        from .hvac_calculations import size_round_duct
        from .ventilation_rulebook import design_ventilation_from_rulebook
        complete_basis = dict((overlay.get("deterministic_calculation") or {}).get("design_basis") or {})
        typed_spaces = complete_basis.get("ventilation_spaces")
        typed_by_id = None
        if typed_spaces is not None:
            duct_basis = {key: complete_basis.get(key) for key in
                          ("max_duct_velocity_m_s", "candidate_round_duct_diameters_mm")
                          if complete_basis.get(key) is not None}
            designed = design_ventilation_from_rulebook(typed_spaces, [], duct_basis)
            if designed.get("status") != "PASS":
                return {"status": designed.get("status", "INPUT_REQUIRED"),
                        "missing_inputs": designed.get("missing_inputs") or [],
                        "errors": designed.get("errors") or []}
            typed_by_id = {str(row["space_id"]): row for row in designed["spaces"]}
        for index, route in enumerate(route_rows, 1):
            edge_id = "DRAFT-VENT-BRANCH-%02d" % index
            room_id = str(route["room"].get("room_id"))
            if typed_by_id is not None:
                source_row = typed_by_id.get(room_id)
                if source_row is None:
                    return {"status":"INPUT_REQUIRED","missing_inputs":[
                        "VENTILATION_TYPED_SPACE_FOR_ROOM:" + room_id]}
                airflow = round(float(source_row["required_exhaust_lps"]),3)
                sized = source_row["duct_sizing"]
            else:
                airflow = round(float(route["room"]["exhaust_cfm"]) * 0.47194745, 3)
                sized = size_round_duct(airflow, 6, [200, 250, 315, 355, 400])
            if sized.get("status") != "PASS":
                return {"status": "INPUT_REQUIRED", "missing_inputs": sized.get("errors") or ["VENT_BRANCH_SIZING"]}
            calculations.append({"calc_id": sized["calc_id"] + "-" + str(index), "network_edge_id": edge_id,
                                 "system": "exhaust_ventilation",
                                 "size": sized["selected"]["diameter_mm"], "material": "GI",
                                 "airflow_lps": airflow, "velocity_m_s": sized["selected"]["velocity_m_s"],
                                 "calculation_engine": "duct_velocity_sizing",
                                 "rulebook_input_mode": "M14_TYPED_SPACE" if typed_by_id is not None else "LEGACY_EXPLICIT_CFM"})

    route_by_edge = {}
    for index, route in enumerate(route_rows, 1):
        edge_id = {"MECH_HEATING_PACKAGE": "DRAFT-HEATING-BRANCH-%02d",
                   "MECH_COOLING_PACKAGE": "DRAFT-COOLING-BRANCH-%02d",
                   "MECH_GAS_PACKAGE": "DRAFT-GAS-BRANCH-%02d",
                   "MECH_VENTILATION_PACKAGE": "DRAFT-VENT-BRANCH-%02d"}[deliverable_type] % index
        route_by_edge[edge_id] = route
    for calculation in calculations:
        route = route_by_edge.get(calculation["network_edge_id"])
        if route:
            calculation["source_input_ids"] = [str(route["endpoint"].get("id")),
                                                str(route["room"].get("room_id")),
                                                str(route["from"])]
            calculation["formula_inputs"] = {
                "room_calculation": {key: route["room"].get(key) for key in
                    ("heating_w", "cooling_w", "exhaust_cfm", "gas_kw")},
                "load_lineage": next((route["room"].get(key + "_lineage") for key in
                    ("heating_w", "cooling_w", "exhaust_cfm", "gas_kw")
                    if route["room"].get(key + "_lineage")), None),
                "endpoint_type": route["endpoint"].get("type"),
                "route_length_m": round(sum(math.dist(a, b) for a, b in
                    zip(route["path"], route["path"][1:])), 3),
                "basis_status": "PROVISIONAL_DRAFT", "release_allowed": False,
            }
    calc_by_edge = {row["network_edge_id"]: row for row in calculations}
    for index, route in enumerate(route_rows, 1):
        edge_id = {"MECH_HEATING_PACKAGE": "DRAFT-HEATING-BRANCH-%02d",
                   "MECH_COOLING_PACKAGE": "DRAFT-COOLING-BRANCH-%02d",
                   "MECH_GAS_PACKAGE": "DRAFT-GAS-BRANCH-%02d",
                   "MECH_VENTILATION_PACKAGE": "DRAFT-VENT-BRANCH-%02d"}[deliverable_type] % index
        calc = calc_by_edge[edge_id]
        edge = {"id": edge_id, "from": route["from"], "to": route["to"], "system": system,
                "role": "branch", "endpoint_ids": [route["to"]], "levels": [level.get("id")],
                "calc_id": calc["calc_id"], "plan_id": calc["calc_id"],
                "riser_id": calc["calc_id"], "schedule_id": calc["calc_id"],
                "plan_path": route["path"], "draw_on_plan": True, "wall_crossings": 0,
                "coordinated_terminal_penetrations": route["penetrations"],
                "penetration_wall_ids": route["penetration_wall_ids"],
                "penetration_status": "NEW_PROPOSED_DRAFT_PENETRATION" if route["penetrations"] else None,
                "structural_approval": "NOT_PROVIDED" if route["penetrations"] else None,
                "release_allowed": False, "size": calc["size"], "material": calc["material"],
                **{key: calc[key] for key in ("load_kw", "delta_t_c", "flow_m3_h", "inlet_pressure_mbar",
                                               "airflow_lps", "velocity_m_s", "load_btu_h", "line_type",
                                               "manufacturer", "manufacturer_model", "manufacturer_catalogue_revision",
                                               "manufacturer_catalogue_url", "manufacturer_installation_revision",
                                               "manufacturer_installation_url", "line_length_m") if key in calc}}
        edges.append(edge)
    if deliverable_type == "MECH_HEATING_PACKAGE":
        # Hydronic distribution is a paired closed circuit.  Preserve the
        # calculated supply branch and add a distinct, offset return branch
        # with its own stable calculation identity; never pass a one-pipe
        # approximation through the independent heating package.
        for node in nodes:
            if node.get("kind") == "heating_terminal":
                node["ports"] = ["heating_supply", "heating_return"]
        returns=[]
        for edge in list(edges):
            source_calc=next(row for row in calculations
                             if row.get("network_edge_id")==edge.get("id"))
            return_id=str(edge["id"])+"-RETURN"
            return_calc={**source_calc,"network_edge_id":return_id,
                         "system":"heating_return",
                         "calc_id":str(source_calc["calc_id"])+"-RETURN"}
            calculations.append(return_calc)
            return_path=[[float(point[0]),float(point[1])-.08]
                         for point in reversed(edge.get("plan_path") or [])]
            returns.append({**edge,"id":return_id,"system":"heating_return",
                            "from":edge.get("to"),"to":edge.get("from"),
                            "calc_id":return_calc["calc_id"],
                            "plan_id":return_calc["calc_id"],
                            "riser_id":return_calc["calc_id"],
                            "schedule_id":return_calc["calc_id"],
                            "plan_path":return_path})
        edges.extend(returns)
    architecture_shafts=[]
    for shaft, point in shaft_rows:
        polygon=deepcopy(shaft.get("polygon") or [])
        if len(polygon) < 3:
            continue
        area=abs(sum(float(polygon[index][0])*float(polygon[(index+1)%len(polygon)][1])
                     - float(polygon[(index+1)%len(polygon)][0])*float(polygon[index][1])
                     for index in range(len(polygon))) / 2.0)
        if not math.isfinite(area) or area <= 0:
            continue
        if shaft.get("source") == "ARCHITECTURAL_SHAFT_ROOM" and shaft.get("shaft_id"):
            architecture_shafts.append({
                "shaft_id": shaft.get("shaft_id"), "polygon": polygon,
                "centroid": [float(point[0]), float(point[1])],
                "area": area, "frame_id": overlay.get("primary_frame_id"),
                "authority": "SOURCE_TYPED_ARCHITECTURE_ROOM",
                "source_entity_id": shaft.get("shaft_id"),
                "source_handles": list(shaft.get("source_handles") or []),
                "source_sha256": valid_sha, "release_allowed": False,
            })
        elif (shaft.get("authority") == "SOURCE_GEOMETRY_DRAFT_SHAFT_USE"
              and shaft.get("source_handles")):
            architecture_shafts.append({**deepcopy(shaft), "polygon": polygon,
                "centroid": [float(point[0]), float(point[1])],
                "area": area, "frame_id": shaft.get("frame_id") or overlay.get("primary_frame_id"),
                "source_sha256": valid_sha, "release_allowed": False})
    return {"status": "PASS", "network_graph": {
        "graph_id": stable_hash({"deliverable_type": deliverable_type, "nodes": nodes, "edges": edges}),
        "schema": "mechanical-network-graph/1", "nodes": nodes, "edges": edges,
        "levels": [{"id": level.get("id"), "name": level.get("name"), "type": level.get("type"),
                    "region_bounds": bounds}], "design_mode": "provisional-interpretation-draft",
        "release_allowed": False}, "calculation_rows": calculations,
        "architecture_shafts": architecture_shafts}


def _polygon_area_centroid(points):
    """Return finite positive source-polygon area and centroid, or ``None``."""
    try:
        polygon = Polygon([[float(point[0]), float(point[1])] for point in points])
    except (TypeError, ValueError, IndexError):
        return None
    if not polygon.is_valid or polygon.is_empty or not math.isfinite(polygon.area) or polygon.area <= 0:
        return None
    centroid = polygon.centroid
    return float(polygon.area), [float(centroid.x), float(centroid.y)]


def _points_inside_bounds(rows, bounds, key="point"):
    if len(bounds or []) != 4:
        return []
    try:
        min_x, min_y, max_x, max_y = [float(value) for value in bounds]
    except (TypeError, ValueError):
        return []
    if (not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y))
            or min_x >= max_x or min_y >= max_y):
        return []
    output = []
    for row in rows or []:
        point = row.get(key)
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        if (math.isfinite(x) and math.isfinite(y)
                and min_x <= x <= max_x and min_y <= y <= max_y):
            output.append(deepcopy(row))
    return output


def _aggregate_source_level_rooms(level, source_sha256):
    """Create reversible aggregate zones only from finite source-frame polygons.

    Repeated room labels over one coarse source polygon are not treated as
    separate verified rooms.  They become one explicitly aggregate DRAFT zone
    retaining the source level and project-source identity.  A polygon whose
    labels are only shaft/stair/elevator is never promoted to an occupied zone.
    """
    groups = {}
    excluded = {"shaft", "vertical_core", "stair", "elevator"}
    for row in level.get("rooms") or []:
        polygon = row.get("polygon") or []
        measured = _polygon_area_centroid(polygon)
        if not measured:
            continue
        normalized = tuple((round(float(point[0]), 6), round(float(point[1]), 6))
                           for point in polygon)
        group = groups.setdefault(normalized, {"polygon": deepcopy(polygon), "types": set()})
        group["types"].add(str(row.get("type") or "unknown").lower())
    result = []
    for polygon_key, group in sorted(groups.items()):
        occupied = sorted(group["types"] - excluded)
        if not occupied:
            continue
        area, centroid = _polygon_area_centroid(group["polygon"])
        room_id = "DRAFT-AGGREGATE-" + stable_hash({
            "source_sha256": source_sha256, "level": level.get("name"),
            "polygon": polygon_key})[:16].upper()
        result.append({
            "room_id": room_id, "room_type": "aggregate_occupied_zone",
            "source_room_types": occupied, "point": centroid, "centroid": centroid,
            "area_m2": area, "polygon": deepcopy(group["polygon"]),
            "level_id": level.get("id"), "level_name": level.get("name"),
            "source_sha256": source_sha256,
            "authority": "MODEL_PROPOSED_DESIGN_ASSUMPTION",
            "aggregation_reason": "REPEATED_LABELS_SHARE_SOURCE_POLYGON",
            "release_allowed": False,
        })
    return result


def _prefix_domain_result(result, prefix):
    """Namespace independently generated level graphs before deterministic merge."""
    result = deepcopy(result)
    graph = result["network_graph"]
    id_map = {}
    for row in graph.get("levels") or []:
        old = str(row.get("id")); row["id"] = prefix + old; id_map[old] = row["id"]
    for row in graph.get("nodes") or []:
        old = str(row.get("id")); row["id"] = prefix + old; id_map[old] = row["id"]
        row["level"] = id_map.get(str(row.get("level")), row.get("level"))
    for row in graph.get("edges") or []:
        old = str(row.get("id")); row["id"] = prefix + old; id_map[old] = row["id"]
        row["from"] = id_map.get(str(row.get("from")), row.get("from"))
        row["to"] = id_map.get(str(row.get("to")), row.get("to"))
        row["endpoint_ids"] = [id_map.get(str(value), value) for value in row.get("endpoint_ids") or []]
        row["levels"] = [id_map.get(str(value), value) for value in row.get("levels") or []]
        for key in ("calc_id", "plan_id", "riser_id", "schedule_id"):
            row[key] = prefix + str(row[key])
    for row in result.get("calculation_rows") or []:
        row["network_edge_id"] = id_map.get(str(row.get("network_edge_id")), row.get("network_edge_id"))
        row["calc_id"] = prefix + str(row.get("calc_id"))
        row["source_input_ids"] = [id_map.get(str(value), value)
                                   for value in row.get("source_input_ids") or []]
    graph["graph_id"] = stable_hash({"prefix": prefix, "graph": graph})
    return result


def _draft_domain_routed_graph(deliverable_type, pmm, architecture, overlay, answers=None):
    """Build one source-frame-bound graph per applicable level and merge safely."""
    if deliverable_type not in {"MECH_HEATING_PACKAGE", "MECH_COOLING_PACKAGE"}:
        return _draft_domain_routed_graph_single(
            deliverable_type, pmm, architecture, overlay, answers)
    system_key = ("heated_levels" if deliverable_type == "MECH_HEATING_PACKAGE"
                  else "conditioned_levels")
    target_names = [str(value) for value in ((pmm.get("systems") or {}).get(system_key) or [])]
    if len(target_names) <= 1:
        return _draft_domain_routed_graph_single(
            deliverable_type, pmm, architecture, overlay, answers)
    source_sha = str(overlay.get("source_sha256") or "")
    source_levels = list(architecture.get("levels") or [])
    by_name = {str(row.get("name")): row for row in source_levels if row.get("name")}
    pmm_by_name = {str(row.get("name")): row for row in pmm.get("levels") or [] if row.get("name")}

    def level_type(name, pmm_level, source_level):
        from .mechanical_network_topology import _typed_level, valid_level_type
        declared = pmm_level.get("type") or source_level.get("type")
        if declared and valid_level_type(declared):
            return declared
        # Architecture/PMM may carry broad display categories such as
        # ABOVE_GROUND, but riser documentation requires a canonical physical
        # level token. Derive it from the source-visible level name and fail
        # closed when that name is not specific enough.
        return _typed_level(name, bool(source_level.get("roof") or pmm_level.get("roof")))

    prepared = []
    for name in target_names:
        source_level = by_name.get(name); pmm_level = pmm_by_name.get(name)
        if not source_level or not pmm_level or len(source_level.get("region_bounds") or []) != 4:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_SOURCE_LEVEL_FRAME_BINDING_REQUIRED:" + name]}
        bounds = source_level["region_bounds"]
        try:
            min_x, min_y, max_x, max_y = [float(value) for value in bounds]
        except (TypeError, ValueError):
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_SOURCE_LEVEL_FRAME_BINDING_REQUIRED:" + name]}
        if (not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y))
                or min_x >= max_x or min_y >= max_y):
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_SOURCE_LEVEL_FRAME_BINDING_REQUIRED:" + name]}
        typed_level = level_type(name, pmm_level, source_level)
        if not typed_level:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_SOURCE_LEVEL_TYPE_REQUIRED:" + name]}
        pmm_level = deepcopy(pmm_level); pmm_level["type"] = typed_level
        # Model-proposed point/room fragments must not displace a larger exact
        # source polygon.  Detailed rooms are consumed only when their polygon
        # and source identity are explicit; otherwise one reversible aggregate
        # zone is derived from the exact source polygon.
        rooms = [row for row in _points_inside_bounds(
            overlay.get("design_rooms") or [], bounds)
            if _polygon_area_centroid(row.get("polygon") or [])
            and row.get("source_sha256") == source_sha
            and (row.get("source_handles") or row.get("source_entity_ids"))]
        aggregate_rooms = _aggregate_source_level_rooms(source_level, source_sha)
        if not rooms:
            rooms = aggregate_rooms
        if not rooms:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_AGGREGATE_SOURCE_POLYGON_REQUIRED:" + name]}
        coverage = [_polygon_area_centroid(row.get("polygon") or []) for row in rooms]
        area = sum(value[0] for value in coverage if value) or sum(
            max(float(row.get("area_m2") or 0), 0) for row in rooms)
        if not math.isfinite(area) or area <= 0:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_LEVEL_AREA_REQUIRED:" + name]}
        prepared.append((name, source_level, pmm_level, rooms, area))
    total_area = sum(row[4] for row in prepared)
    merged = {"status":"PASS", "network_graph": {"schema":"mechanical-network-graph/1",
        "nodes":[], "edges":[], "levels":[], "design_mode":"provisional-interpretation-draft",
        "release_allowed":False}, "calculation_rows":[], "architecture_shafts":[]}
    for name, source_level, pmm_level, rooms, area in prepared:
        sub_overlay = deepcopy(overlay)
        sub_overlay["design_rooms"] = deepcopy(rooms)
        existing_calc = {str(row.get("room_id")): deepcopy(row) for row in
                         (overlay.get("deterministic_calculation") or {}).get("rooms") or []}
        calc_rooms = []
        for room in rooms:
            # Preserve the exact source polygon through the calculation
            # adapter.  A scalar-only legacy calculation row must not erase
            # the geometry needed to derive a distinct reversible DRAFT
            # terminal when the aggregate-zone centroid coincides with its
            # shaft centroid.
            calc = {**deepcopy(room),
                    **deepcopy(existing_calc.get(str(room.get("room_id"))) or {})}
            calc_rooms.append(calc)
        sub_overlay["deterministic_calculation"] = {
            **deepcopy(overlay.get("deterministic_calculation") or {}), "rooms":calc_rooms}
        sub_overlay["design_zones"] = [deepcopy(row) for row in overlay.get("design_zones") or []
                                       if _points_inside_bounds(
                                           [{"point":row.get("centroid")}], source_level["region_bounds"])]
        sub_overlay["fixture_endpoints"] = _points_inside_bounds(
            overlay.get("fixture_endpoints") or [], source_level["region_bounds"])
        sub_overlay["shafts"] = [deepcopy(row) for row in overlay.get("shafts") or []
                                 if _points_inside_bounds([{"point":row.get("centroid") or row.get("point")}],
                                                          source_level["region_bounds"])]
        sub_answers = deepcopy(answers or {})
        load_key = "heating_load_kw" if deliverable_type == "MECH_HEATING_PACKAGE" else "cooling_load_kw"
        try: total_load = float(sub_answers.get(load_key))
        except (TypeError, ValueError): total_load = 0
        if not math.isfinite(total_load) or total_load <= 0:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[load_key]}
        allocated = total_load * area / total_area
        sub_answers[load_key] = allocated
        basis_key = "heating_design_basis" if deliverable_type == "MECH_HEATING_PACKAGE" else "cooling_design_basis"
        basis = deepcopy((sub_overlay.get("engineering_basis") or {}).get(basis_key) or {})
        basis[load_key] = allocated
        sub_overlay.setdefault("engineering_basis", {})[basis_key] = basis
        sub_pmm = deepcopy(pmm); sub_pmm["levels"] = [deepcopy(pmm_level)]
        sub_pmm.setdefault("systems", {})[system_key] = [name]
        sub_architecture = deepcopy(architecture); sub_architecture["levels"] = [deepcopy(source_level)]
        result = _draft_domain_routed_graph_single(
            deliverable_type, sub_pmm, sub_architecture, sub_overlay, sub_answers)
        if not result or result.get("status") != "PASS":
            return result or {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_LEVEL_GRAPH_REQUIRED:" + name]}
        prefix = "L" + stable_hash({"source":source_sha,"level":name})[:8].upper() + "-"
        result = _prefix_domain_result(result, prefix)
        merged["network_graph"]["nodes"].extend(result["network_graph"]["nodes"])
        merged["network_graph"]["edges"].extend(result["network_graph"]["edges"])
        merged["network_graph"]["levels"].extend(result["network_graph"]["levels"])
        merged["calculation_rows"].extend(result.get("calculation_rows") or [])
        merged["architecture_shafts"].extend(result.get("architecture_shafts") or [])
    # Join the exact per-level graphs with an explicit DRAFT riser assumption.
    # The sheet-frame coordinates are not asserted to be physical alignment;
    # every link stays release=false and records the source shaft identities.
    levels = merged["network_graph"]["levels"]
    def physical_level_rank(level):
        level_type = str(level.get("type") or "").upper()
        ranks = {"BASEMENT":-1.0, "GROUND":0.0, "MEZZANINE":0.5,
                 "FIRST":1.0, "SECOND":2.0, "ROOF":99.0}
        if level_type in ranks:
            return ranks[level_type]
        match = re.fullmatch(r"TYPICAL_([1-9]\d*)_([1-9]\d*)", level_type)
        return float(match.group(1)) if match else None
    for level in levels:
        rank = physical_level_rank(level)
        if rank is None:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_VERTICAL_LEVEL_ORDER_REQUIRED:" + str(level.get("name"))]}
        if level.get("elevation_m") is None:
            # A reversible diagram-only spacing assumption. It is never
            # promoted to source geometry or release authority and exists only
            # because the source identifies physical floor order but supplies
            # no surveyed elevations.
            level["elevation_m"] = rank * 3.0
            level["elevation_authority"] = "MODEL_PROPOSED_DRAFT_3M_STOREY_SPACING"
            level["release_allowed"] = False
    levels.sort(key=physical_level_rank)
    level_order = {row["id"]: index for index, row in enumerate(levels)}
    shafts_by_level = {}
    for row in merged["network_graph"]["nodes"]:
        if row.get("kind") == "shaft" and row.get("level") in level_order:
            shafts_by_level.setdefault(row["level"], []).append(row)
    systems = (["heating_supply", "heating_return"]
               if deliverable_type == "MECH_HEATING_PACKAGE" else ["cooling"])
    for lower, upper in zip(levels, levels[1:]):
        lower_shafts = shafts_by_level.get(lower["id"]) or []
        upper_shafts = shafts_by_level.get(upper["id"]) or []
        def normalized_point(node, level):
            bounds = level.get("region_bounds") or []
            point = node.get("point") or []
            if len(bounds) != 4 or len(point) != 2:
                return None
            width = float(bounds[2]) - float(bounds[0]); height = float(bounds[3]) - float(bounds[1])
            if width <= 0 or height <= 0:
                return None
            return ((float(point[0])-float(bounds[0]))/width,
                    (float(point[1])-float(bounds[1]))/height)
        candidates = []
        for lower_shaft in lower_shafts:
            a = normalized_point(lower_shaft, lower)
            if not a: continue
            for upper_shaft in upper_shafts:
                b = normalized_point(upper_shaft, upper)
                if not b: continue
                same_key = (str(lower_shaft.get("shaft_key") or "")
                            == str(upper_shaft.get("shaft_key") or "")
                            and bool(lower_shaft.get("shaft_key")))
                source_rank = sum(
                    0 if row.get("source") == "ARCHITECTURAL_SHAFT_ROOM" else 1
                    for row in (lower_shaft, upper_shaft))
                candidates.append((0 if same_key else 1, source_rank, math.dist(a, b),
                                   str(lower_shaft.get("id")), str(upper_shaft.get("id")),
                                   lower_shaft, upper_shaft))
        candidates.sort(key=lambda row: row[:5])
        if not candidates:
            return {"status":"INPUT_REQUIRED", "missing_inputs":[
                "DRAFT_DOMAIN_VERTICAL_SHAFT_PAIR_REQUIRED:%s:%s" %
                (lower.get("name"), upper.get("name"))]}
        _same_key_rank, _source_rank, _distance, _start_id, _end_id, start, end = candidates[0]
        tied = (len(candidates) > 1 and candidates[0][:2] == candidates[1][:2]
                and abs(candidates[0][2] - candidates[1][2]) <= 1e-9)
        for system in systems:
            edge_id = "DRAFT-VERTICAL-" + stable_hash({
                "system":system, "from":start["id"], "to":end["id"]})[:16].upper()
            calc_id = "CALC-" + edge_id
            branch_sizes = [float(row.get("size")) for row in merged["network_graph"]["edges"]
                            if row.get("system") == system and row.get("size") is not None]
            if not branch_sizes:
                return {"status":"INPUT_REQUIRED", "missing_inputs":[
                    "DRAFT_DOMAIN_VERTICAL_SIZE_REQUIRED:" + system]}
            size = max(branch_sizes)
            material = "PEX" if system.startswith("heating_") else "COPPER"
            branch_edge_ids = {row.get("id") for row in merged["network_graph"]["edges"]
                               if row.get("system") == system and row.get("role") == "branch"
                               and upper["id"] in (row.get("levels") or [])}
            vertical_endpoint_ids = sorted({endpoint_id
                for row in merged["network_graph"]["edges"]
                if row.get("id") in branch_edge_ids
                for endpoint_id in row.get("endpoint_ids") or []})
            branch_calcs = [row for row in merged["calculation_rows"]
                            if row.get("network_edge_id") in branch_edge_ids]
            if system.startswith("heating_"):
                calculation_engine = "design_heating_network"
                domain_fields = {
                    "load_kw":sum(float(row.get("load_kw") or 0) for row in branch_calcs),
                    "delta_t_c":20,
                }
                execution_load = {"load_unit":"kW"}
            else:
                calculation_engine = "calculate_cooling_design"
                line_types = sorted({str(row.get("line_type")) for row in branch_calcs
                                     if row.get("line_type")})
                domain_fields = {
                    "load_btu_h":sum(float(row.get("load_btu_h") or 0) for row in branch_calcs),
                    "line_type":line_types[0] if len(line_types) == 1 else "MULTI_MODEL_REFRIGERANT_RISER",
                }
                execution_load = {"load_unit":"BTU/h"}
            if any(float(value) <= 0 for key, value in domain_fields.items()
                   if key in {"load_kw", "load_btu_h"}):
                return {"status":"INPUT_REQUIRED", "missing_inputs":[
                    "DRAFT_DOMAIN_VERTICAL_LOAD_REQUIRED:" + system]}
            vertical_edge = {
                "id":edge_id, "from":start["id"], "to":end["id"],
                "system":system, "role":"vertical_riser", "endpoint_ids":vertical_endpoint_ids,
                "levels":[lower["id"], upper["id"]], "calc_id":calc_id,
                "plan_id":calc_id, "riser_id":calc_id, "schedule_id":calc_id,
                "draw_on_plan":False, "plan_path":[], "wall_crossings":0,
                "coordinated_terminal_penetrations":0, "vertical_offset_xy":[0, 0],
                "offset_declared":True, "size":size, "material":material,
                "shaft_key":"%s::%s" % (start["id"], end["id"]),
                "from_elevation_m":lower["elevation_m"],
                "to_elevation_m":upper["elevation_m"],
                "downstream_load":next(iter(domain_fields.values())),
                "size_source":"MAX_CONNECTED_BRANCH_SIZE",
                "material_source":"SYSTEM_DRAFT_MATERIAL_CONTRACT",
                "authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION",
                "shaft_pair_selection":"UNIQUE_MINIMUM_NORMALIZED_SOURCE_FRAME_DISTANCE",
                "shaft_pair_tie_break":("STABLE_SOURCE_ID_DRAFT_ASSUMPTION" if tied else None),
                "sheet_frame_transform_required":True, "release_allowed":False,
                **domain_fields, **execution_load}
            merged["network_graph"]["edges"].append(vertical_edge)
            merged["calculation_rows"].append({
                "calc_id":calc_id, "network_edge_id":edge_id, "system":system,
                "role":"vertical_riser",
                "size":size, "material":material,
                "calculation_engine":calculation_engine,
                "source_input_ids":[start["id"], end["id"]],
                "formula_inputs":{"selected_size_mm":size,
                    "selection":"MAX_CONNECTED_BRANCH_SIZE",
                    "sheet_frame_transform_required":True,
                    "release_allowed":False}, **domain_fields, **execution_load})
    merged["network_graph"]["graph_id"] = stable_hash(merged["network_graph"])
    return merged


def _independent_canonical_contract(deliverable_type, snapshot, plan_analysis, answers):
    """Build the canonical PMM transport for one isolated DRAFT system.

    This is deliberately an adapter, not a second design engine.  It uses the
    persisted architecture/fixture evidence and the normal PMM builder; network
    sizing and calculation identities remain owned by mechanical_authority.
    Callers may supply already-built canonical graph inputs, but they are never
    synthesized from answer scalars here.
    """
    definition = SYSTEM_PACKAGES[deliverable_type]
    auto = deepcopy((plan_analysis.get("architectural_auto") or {}))
    architecture = deepcopy(auto.get("architecture_model") or {})
    levels = list(architecture.get("levels") or [])
    if not auto.get("levels"):
        auto["levels"] = [{"name": row.get("name"),
                           "region_bounds": deepcopy(row.get("region_bounds"))}
                          for row in levels if row.get("name")]
    source_fixture_diagnostics = list(auto.get("fixture_detections") or [])
    fixtures = list(source_fixture_diagnostics)
    overlay = deepcopy(snapshot.get("draft_design_overlay") or
                       plan_analysis.get("draft_design_overlay") or {})
    overlay_fixtures = [row for row in overlay.get("fixture_endpoints") or []
                        if isinstance(row, dict)]
    # Once a validated DRAFT overlay exists, only its explicitly hosted design
    # endpoints enter the canonical network contract. The 47 source detections
    # remain preserved in analysis as diagnostics but include unhosted legend/
    # reference-frame occurrences and must not become authority nodes.
    if overlay_fixtures:
        fixtures = overlay_fixtures
        auto["source_fixture_diagnostics"] = source_fixture_diagnostics
    overlay_shafts = [deepcopy(row) for row in overlay.get("shafts") or []
                      if isinstance(row,dict) and row.get("topology_role") in {
                          "VERTICAL_SHAFT", "NEW_PROPOSED_DRAFT_RISER"}]
    for shaft in overlay_shafts:
        # The selected vertical core is not newly invented geometry: its
        # polygon and handle are source-bound, while only its intended DRAFT
        # engineering use is provisional. Preserve that distinction so the
        # shaft authority gate remains fail-closed for genuinely proposed
        # geometry.
        if (shaft.get("authority") == "SOURCE_GEOMETRY_DRAFT_SHAFT_USE"
                and shaft.get("source_handles")):
            shaft["source"] = "ARCHITECTURAL_SHAFT_GEOMETRY"
    if overlay_shafts:
        architecture["shafts"] = overlay_shafts
        architecture["vertical_cores"] = overlay_shafts
        architecture["draft_design_overlay"] = {
            "authority":overlay.get("authority"), "release_allowed":False,
            "overlay_hash":overlay.get("overlay_hash")}
    if overlay_fixtures and overlay.get("design_zones"):
        # The source level detector grouped distant reference/detail frames in
        # one 4 km x 10 km region. Feeding that box to the 0.25 m routing grid
        # creates billions of candidate cells. Scope this independent DRAFT to
        # the explicitly materialized design zones and their source frame.
        zone_points = [point for zone in overlay.get("design_zones") or []
                       for point in (zone.get("polygon") or []) if len(point) == 2]
        evidence_points = zone_points + [row.get("point") for row in overlay_fixtures
                                         if len(row.get("point") or []) == 2]
        if evidence_points:
            xs = [float(point[0]) for point in evidence_points]
            ys = [float(point[1]) for point in evidence_points]
            margin = 1.0
            draft_bounds = [min(xs)-margin, min(ys)-margin, max(xs)+margin, max(ys)+margin]
            def _point_inside(point):
                return (len(point or []) == 2 and draft_bounds[0] <= float(point[0]) <= draft_bounds[2]
                        and draft_bounds[1] <= float(point[1]) <= draft_bounds[3])
            def _intersects_bounds(row):
                bounds = row.get("bounds") or []
                if len(bounds) == 4:
                    return not (float(bounds[2]) < draft_bounds[0] or float(bounds[0]) > draft_bounds[2]
                                or float(bounds[3]) < draft_bounds[1] or float(bounds[1]) > draft_bounds[3])
                return _point_inside(row.get("centroid") or row.get("center") or row.get("label_point"))
            candidates = [row for row in levels if any(
                _point_inside(item.get("point")) for item in overlay_fixtures
            ) and len(row.get("region_bounds") or []) == 4 and not (
                row["region_bounds"][2] < draft_bounds[0] or row["region_bounds"][0] > draft_bounds[2]
                or row["region_bounds"][3] < draft_bounds[1] or row["region_bounds"][1] > draft_bounds[3])]
            if candidates:
                scoped = deepcopy(min(candidates, key=lambda row:
                    (row["region_bounds"][2]-row["region_bounds"][0]) *
                    (row["region_bounds"][3]-row["region_bounds"][1])))
                scoped["region_bounds"] = draft_bounds
                for key in ("rooms", "walls", "doors", "windows", "columns", "stairs",
                            "fixed_furniture", "equipment_candidate_zones"):
                    scoped[key] = [deepcopy(row) for row in scoped.get(key) or [] if _intersects_bounds(row)]
                scoped["rooms"].extend({
                    "id": zone.get("zone_id"), "type": zone.get("room_type") or "residential_unit",
                    "label": zone.get("label") or zone.get("room_type"),
                    "center": zone.get("centroid"), "centroid": zone.get("centroid"),
                    "polygon": deepcopy(zone.get("polygon") or []),
                    "authority": "MODEL_PROPOSED_DESIGN_ASSUMPTION", "release_allowed": False,
                } for zone in overlay.get("design_zones") or [])
                levels = [scoped]
                architecture["levels"] = levels
                architecture["draft_routing_scope"] = {
                    "bounds": draft_bounds, "frame_id": overlay.get("primary_frame_id"),
                    "authority": "MODEL_PROPOSED_DESIGN_ASSUMPTION", "release_allowed": False,
                }
                auto["levels"] = [{"name": scoped.get("name"), "roof": scoped.get("roof", False),
                                  "region_bounds": draft_bounds}]
    auto["fixture_detections"] = fixtures
    counts = {}
    for row in fixtures:
        kind = str(row.get("type") or row.get("kind") or "").strip().lower()
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    auto.setdefault("fixture_counts", counts)
    analysis = deepcopy(plan_analysis)
    analysis["architectural_auto"] = auto
    names = [str(row.get("name")) for row in levels if row.get("name")]
    active = set(definition["runtime_systems"])
    manifest = deepcopy(snapshot.get("approved_draft_manifest") or {})
    manifest_levels = []
    for sheet in manifest.get("sheets") or []:
        for value in sheet.get("levels") or []:
            value = str(value)
            if value in names and value not in manifest_levels:
                manifest_levels.append(value)
    roof_names = {str(row.get("name")) for row in levels
                  if row.get("roof") is True or str(row.get("type") or "").upper() == "ROOF"
                  or str(row.get("name") or "").strip().lower() in {"roof", "بام"}}
    # Heating/cooling floor-plan packages do not silently acquire a roof level
    # merely because the architecture inventory contains it.  A roof may join
    # only through an explicit sheet-level match in the approved manifest.
    applicable_names = manifest_levels or [name for name in names if name not in roof_names]
    occupied_floor_names = [name for name in applicable_names if name not in roof_names]
    scope = {
        "conditioned_levels": occupied_floor_names if "cooling" in active else [],
        "heated_levels": occupied_floor_names if "heating_supply" in active else [],
        "wet_fixture_levels": applicable_names if active & {"cold_water", "hot_water"} else [],
        "sanitary_fixture_levels": applicable_names if active & {"sanitary", "vent"} else [],
        "ventilation_required_levels": applicable_names if "exhaust_ventilation" in active else [],
        "gas_consumer_levels": applicable_names if "gas" in active else [],
        "vertical_systems": len(applicable_names) > 1,
    }
    from app.project_mechanical_model import build_project_mechanical_model
    pmm = build_project_mechanical_model(
        analysis, answers=answers, scope=scope,
        proposal={"drawing_manifest": manifest.get("sheets") or [],
                  "total_plans": len(manifest.get("sheets") or [])},
    )
    if active & {"heating_supply", "cooling"}:
        pmm["levels"] = [row for row in pmm.get("levels") or []
                         if str(row.get("name")) in occupied_floor_names]
    provisional = dict(snapshot.get("provisional_architecture") or {})
    if (provisional.get("status") == "PROVISIONAL_READY"
            and provisional.get("draft_engineering_allowed") is True
            and provisional.get("release_allowed") is False
            and provisional.get("source_sha256") == snapshot.get("source_sha256")):
        pmm["mode"] = "provisional-interpretation-draft"
        pmm["architecture_completeness"] = {
            "status":"PROVISIONAL_READY", "downstream_engineering_allowed":True,
            "release_allowed":False, "authority":"MODEL_PROPOSED_REVERSIBLE",
            "source_sha256":snapshot.get("source_sha256"),
        }
        pmm["canonical_architecture_authority"] = {
            **dict(pmm.get("canonical_architecture_authority") or {}),
            "downstream_engineering_allowed":True, "release_allowed":False,
            "policy":"PROVISIONAL_DRAFT_ONLY_NO_RELEASE_AUTHORITY",
        }
        pmm["diagnostics"] = [row for row in pmm.get("diagnostics") or []
                              if row not in {"architecture_completeness_input_required",
                                             "canonical_architecture_authority_input_required"}]
        pmm["valid"] = not any(row in {"planner_total_does_not_match_manifest_count",
            "no_architecture_levels_in_pmm","duplicate_pmm_entity_id"} for row in pmm["diagnostics"])
    source_levels = {str(row.get("name")): row for row in levels if row.get("name")}
    for index, row in enumerate(pmm.get("levels") or []):
        source = source_levels.get(str(row.get("name"))) or {}
        explicit_type = source.get("type") or source.get("level_type")
        if explicit_type:
            row["type"] = str(explicit_type)
        elif len(pmm.get("levels") or []) == 1:
            # A one-level regression/project source has no vertical ambiguity;
            # this classification does not create coordinates or elevations.
            row["type"] = "GROUND"
    if not pmm.get("valid"):
        return {"status": "INPUT_REQUIRED", "missing_inputs": [
            "PROJECT_MECHANICAL_MODEL_V3:" + str(item)
            for item in pmm.get("diagnostics") or ["INVALID"]
        ]}
    authority_fixtures = []
    for row in fixtures:
        point = row.get("point") or []
        if len(point) != 2:
            continue
        authority_fixtures.append({
            **deepcopy(row),
            "status": "detected",
            "x": float(point[0]),
            "y": float(point[1]),
            "level": row.get("level") or row.get("level_name"),
        })
    routed = (_draft_domain_routed_graph(deliverable_type, pmm, architecture, overlay, answers)
              if overlay.get("schema") == "planha-project-draft-design-overlay/1.0" else None)
    if routed and routed.get("status") != "PASS":
        return routed
    if routed and routed.get("architecture_shafts"):
        architecture["shafts"] = deepcopy(routed["architecture_shafts"])
        architecture["vertical_cores"] = deepcopy(routed["architecture_shafts"])
    return {
        "status": "PASS", "project_mechanical_model": pmm,
        "architecture_evidence": architecture,
        # The topology authority consumes persisted fixture-evidence rows, not
        # the overlay's richer endpoint schema.  Normalize explicitly so a
        # valid DRAFT overlay cannot silently fall back to source diagnostics
        # from unrelated/reference frames.
        "fixture_evidence": authority_fixtures,
        "calculation_rows": (routed or {}).get("calculation_rows") or plan_analysis.get("calculation_rows_canonical"),
        "network_graph": (routed or {}).get("network_graph") or plan_analysis.get("network_graph_canonical") or {},
    }

REGISTRY = {
    "MECH_ROOF_RAINWATER_SOURCE_PREVIEW": {
        "system": "RAINWATER_DIAGNOSTIC", "scope": "ROOF_SOURCE", "kind": "DIAGNOSTIC_PREVIEW",
        "generator": "cad_engine.mechanical_cad_roof_rainwater_source_preview",
        "generator_status": "EXISTING_GENERATOR", "formats": ["DXF"],
        "hard_requirements": ["paid_order", "source_geometry", "source_diagnostic_points"],
        "coordination_requirements": [],
        "gate_requirements": {
            "CALCULATION": ["paid_order", "source_geometry", "source_diagnostic_points"],
            "DRAWING": [],
        },
    },
    "MECH_ROOF_RAINWATER_CALC": {
        "system": "RAINWATER", "scope": "ROOF", "kind": "CALCULATION",
        "generator": "cad_engine.rainwater_calculations",
        "generator_status": "EXISTING_GENERATOR", "formats": ["JSON"],
        "hard_requirements": ["paid_order", "qualified_roof_surface", "rainfall_basis",
                              "catchment_areas", "drain_low_points", "stack_locations",
                              "roof_slope", "overflow_strategy", "capacity_tables"],
        "coordination_requirements": ["shaft_coordination"],
        "gate_requirements": {
            "CALCULATION": ["paid_order", "qualified_roof_surface", "rainfall_basis",
                            "catchment_areas", "drain_low_points", "stack_locations",
                            "roof_slope", "overflow_strategy", "capacity_tables"],
            "DRAWING": [],
        },
    },
    "MECH_HEATING_SOURCE_DIAGNOSTIC_PREVIEW": {
        "system": "HEATING_DIAGNOSTIC", "scope": "PROJECT_SOURCE",
        "kind": "DIAGNOSTIC_PREVIEW",
        "generator": "cad_engine.independent_deliverables.mechanical_source_diagnostic_preview",
        "generator_status": "EXISTING_GENERATOR", "formats": ["DXF"],
        "hard_requirements": ["paid_order", "source_geometry", "draft_network_evidence"],
        "coordination_requirements": [],
        "gate_requirements": {
            "CALCULATION": ["paid_order", "source_geometry", "draft_network_evidence"],
            "DRAWING": [],
        },
    },
    "MECH_COOLING_SOURCE_DIAGNOSTIC_PREVIEW": {
        "system": "COOLING_DIAGNOSTIC", "scope": "PROJECT_SOURCE",
        "kind": "DIAGNOSTIC_PREVIEW",
        "generator": "cad_engine.independent_deliverables.mechanical_source_diagnostic_preview",
        "generator_status": "EXISTING_GENERATOR", "formats": ["DXF"],
        "hard_requirements": ["paid_order", "source_geometry", "draft_network_evidence"],
        "coordination_requirements": [],
        "gate_requirements": {
            "CALCULATION": ["paid_order", "source_geometry", "draft_network_evidence"],
            "DRAWING": [],
        },
    },
    "MECH_COMPLETE_PACKAGE": {
        "system": "MULTI_SYSTEM", "scope": "PROJECT", "kind": "DRAWING_PACKAGE",
        "generator": "existing_mechanical_cad_engine", "generator_status": "EXISTING_GENERATOR",
        "formats": ["DXF", "ZIP"],
        "hard_requirements": ["paid_order", "approved_design_basis", "architecture_release",
                              "mechanical_scope", "source_geometry"],
        "coordination_requirements": ["cross_system_coordination"],
    },
    "MECH_ROOF_RAINWATER_PLAN": {
        "system": "RAINWATER", "scope": "ROOF", "kind": "PLAN",
        "generator": "cad_engine.independent_deliverables.rainwater_roof_plan",
        "generator_status": "EXISTING_GENERATOR", "formats": ["DXF"],
        "hard_requirements": ["paid_order", "qualified_roof_surface", "rainfall_basis",
                              "catchment_areas", "roof_slope", "drain_locations",
                              "stack_locations", "overflow_strategy", "capacity_tables",
                              "discharge_route"],
        "hard_dependencies": ["MECH_ROOF_RAINWATER_CALC"],
        "coordination_requirements": ["shaft_coordination"],
        "gate_requirements": {
            "CALCULATION": ["paid_order", "qualified_roof_surface", "rainfall_basis",
                            "catchment_areas", "roof_slope", "drain_locations",
                            "stack_locations", "overflow_strategy", "capacity_tables"],
            "DRAWING": ["discharge_route"],
        },
    },
}

for _key, _definition in SYSTEM_PACKAGES.items():
    REGISTRY[_key] = {
        "system": _definition["system"], "scope": "PROJECT", "kind": "DRAWING_PACKAGE",
        "generator": "cad_engine.main:app", "generator_status": "EXISTING_GENERATOR", "formats": ["ZIP"],
        "hard_requirements": ["paid_order", "source_geometry", "draft_architecture_interpretation",
                              "system_scope"] + list(_definition["requirements"]),
        "coordination_requirements": ["cross_system_coordination"],
    }

def stable_hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), default=str).encode()).hexdigest()


def derive_rainwater_readiness_evidence(snapshot):
    """Derive fail-closed readiness from the persisted DRAFT roof contract.

    This is deliberately evidence evaluation, not an approval step. Proposed
    items remain release-disabled and the rainfall/capacity bases must declare
    their non-certified authority explicitly.
    """
    snapshot = snapshot or {}; roof = snapshot.get("roof") or {}
    basis = snapshot.get("design_basis") or {}
    provenance = snapshot.get("geometry_provenance") or {}
    assumptions = snapshot.get("draft_assumption_basis") or {}
    boundary = roof.get("boundary") or []; catchments = roof.get("catchments") or []
    stacks = roof.get("stacks") or []
    valid_boundary = (len(boundary) >= 3 and bool(provenance.get("source_sha256"))
                      and bool(provenance.get("roof_boundary_source_handles")))
    valid_catchments = bool(catchments) and all(len(row.get("polygon") or []) >= 3 for row in catchments)
    source_drains = set(provenance.get("drain_source_handles") or [])
    valid_drains = bool(source_drains) and all(
        (row.get("drain") or {}).get("point") == row.get("low_point")
        and str((row.get("drain") or {}).get("source_handle") or "") in source_drains
        for row in catchments)
    stack_ids = {row.get("id") for row in stacks if row.get("authority") == "NEW_PROPOSED_DRAFT"}
    valid_stacks = bool(stack_ids) and all(row.get("stack_id") in stack_ids for row in catchments)
    minimum_slope = basis.get("minimum_slope_percent")
    valid_slopes = minimum_slope not in (None, "") and all(
        float(row.get("slope_percent") or 0) >= float(minimum_slope) for row in catchments)
    valid_routes = all(
        len(row.get("route") or []) >= 2
        and (row.get("route") or [None])[0] == (row.get("drain") or {}).get("point")
        for row in catchments)
    return {
        "paid_order": False,
        "qualified_roof_surface": valid_boundary,
        "rainfall_basis": (basis.get("rainfall_intensity_mm_h") not in (None, "")
                           and assumptions.get("rainfall_authority")
                           and assumptions.get("release_allowed") is False),
        "catchment_areas": valid_catchments,
        "drain_low_points": valid_drains,
        "drain_locations": valid_drains,
        "stack_locations": valid_stacks,
        "roof_slope": valid_slopes,
        "overflow_strategy": bool(catchments) and all(row.get("emergency_overflow") for row in catchments),
        "capacity_tables": (bool(basis.get("drain_capacity_table"))
                            and bool(basis.get("downpipe_capacity_table"))
                            and bool(assumptions.get("capacity_authority"))
                            and assumptions.get("release_allowed") is False),
        "discharge_route": valid_routes,
        "shaft_coordination": False,
    }


def rainwater_engineering_acceptance(snapshot):
    """Separate artifact integrity from hydraulic design acceptance."""
    assumptions = (snapshot or {}).get("draft_assumption_basis") or {}
    from .rainwater_rulebook import evaluate_rainwater_rules
    evaluation = evaluate_rainwater_rules(snapshot or {})
    blocking = [row for row in evaluation.get("evaluations") or []
                if row.get("status") in {"FAIL", "INPUT_REQUIRED"}]
    return {
        "status": "UNVERIFIED",
        "hydraulic_capacity_status": "UNVERIFIED",
        "rainfall_basis_status": "UNVERIFIED",
        "release_allowed": False,
        "assumption_origin": assumptions.get("assumption_origin") or "DETERMINISTIC_DRAFT_ASSUMPTION",
        "rainfall_authority": assumptions.get("rainfall_authority") or "UNVERIFIED",
        "capacity_authority": assumptions.get("capacity_authority") or "UNVERIFIED",
        "rulebook_status": evaluation.get("status"),
        "rulebook_dependency_identity": evaluation.get("dependency_identity"),
        "rulebook_blockers": [{"rule_id": row.get("rule_id"), "status": row.get("status"),
                               "missing_inputs": row.get("missing_inputs") or [],
                               "errors": row.get("errors") or [],
                               "message_fa": row.get("message_fa") or
                               ("ورودی معتبر این ضابطه تکمیل نشده است." if row.get("status") == "INPUT_REQUIRED"
                                else "طرح پیش‌نویس با این ضابطه منطبق نیست.")}
                              for row in blocking],
        "required_for_engineering_acceptance": [
            "OFFICIAL_PROJECT_LOCATION_RAINFALL_INTENSITY",
            "APPLICABLE_DRAIN_AND_DOWNPIPE_HYDRAULIC_CAPACITY_BASIS",
            "ENGINEER_REVIEW",
            "ALL_APPLICABLE_RULEBOOK_CONTROLS_PASS",
        ],
    }

def validate_registry(registry=None):
    registry = registry or REGISTRY
    errors = []
    for key, row in registry.items():
        if row.get("generator_status") == "EXISTING_GENERATOR" and not row.get("generator"):
            errors.append(f"GENERATOR_MISSING:{key}")
        if not set(row.get("formats") or []) <= {"DXF", "ZIP", "PDF", "JSON"}:
            errors.append(f"FORMAT_UNSUPPORTED:{key}")
    return errors

def validate_dependency_dag(definitions):
    graph = {key: list(row.get("hard_dependencies") or []) for key, row in definitions.items()}
    errors, visiting, visited = [], set(), set()
    def visit(node):
        if node in visiting: errors.append(f"DEPENDENCY_CYCLE:{node}"); return
        if node in visited: return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep not in graph: errors.append(f"DEPENDENCY_UNKNOWN:{node}:{dep}")
            else: visit(dep)
        visiting.remove(node); visited.add(node)
    for node in graph: visit(node)
    return sorted(set(errors))

def evaluate_readiness(deliverable_type, evidence, registry=None):
    definition = (registry or REGISTRY).get(deliverable_type)
    if not definition:
        return {"status": "BLOCKED_INPUT", "errors": ["DELIVERABLE_NOT_REGISTERED"]}
    missing = [key for key in definition["hard_requirements"] if evidence.get(key) is not True]
    generator_ready = definition["generator_status"] == "EXISTING_GENERATOR"
    if not generator_ready: missing.append("implemented_generator")
    coordination_missing = [key for key in definition["coordination_requirements"]
                            if evidence.get(key) is not True]
    gate_requirements = definition.get("gate_requirements") or {}
    if gate_requirements:
        calculation_missing = [key for key in missing
                               if key in set(gate_requirements.get("CALCULATION") or [])]
        drawing_missing = [key for key in missing
                           if key in set(gate_requirements.get("DRAWING") or [])]
    else:
        calculation_missing = [key for key in missing if key in
                               {"approved_design_basis", "rainfall_basis"}]
        drawing_missing = [key for key in missing if key not in calculation_missing]
    gates = {
        "CALCULATION": {"status": "PASS" if not calculation_missing else "INPUT_REQUIRED",
                        "missing": calculation_missing},
        "DRAWING": {"status": "PASS" if not drawing_missing else "INPUT_REQUIRED",
                    "missing": drawing_missing},
        "DELIVERABLE_QA": {"status": "NOT_RUN", "missing": []},
        "COORDINATION": {"status": "PASS" if not coordination_missing else "PENDING",
                         "missing": coordination_missing},
    }
    return {"status": "READY" if not missing else "BLOCKED_INPUT", "gates": gates,
            "missing": missing, "coordination_pending": coordination_missing,
            "registry_version": CONTRACT_VERSION}

def idempotency_key(order_identity, deliverable_type, scope, snapshot_hash, generator_version):
    return stable_hash({"order": order_identity, "deliverable_type": deliverable_type,
                        "scope": scope, "snapshot": snapshot_hash,
                        "generator_version": generator_version})

def affected_deliverables(changed_inputs, registry=None):
    changed = set(changed_inputs)
    return sorted(key for key, row in (registry or REGISTRY).items()
                  if changed & set(row.get("hard_requirements", []) +
                                   row.get("coordination_requirements", [])))


def _rainwater_independent_qa(snapshot, result):
    """Recompute critical rainwater invariants without trusting producer flags."""
    errors = []
    if result.get("status") != "PASS":
        errors.append("GENERATOR_NOT_PASS")
    roof = snapshot.get("roof") or {}
    basis = snapshot.get("design_basis") or {}
    source = {str(row.get("id")): row for row in roof.get("catchments") or []}
    rows = result.get("catchments") or []
    if len(rows) != len(source):
        errors.append("CATCHMENT_COUNT_MISMATCH")
    for row in rows:
        source_row = source.get(str(row.get("catchment_id")))
        if not source_row:
            errors.append(f"UNKNOWN_CATCHMENT:{row.get('catchment_id')}")
            continue
        polygon = source_row.get("polygon") or []
        if len(polygon) < 3:
            errors.append(f"INVALID_POLYGON:{row.get('catchment_id')}")
            continue
        area = abs(sum(
            float(polygon[index][0]) * float(polygon[(index + 1) % len(polygon)][1])
            - float(polygon[(index + 1) % len(polygon)][0]) * float(polygon[index][1])
            for index in range(len(polygon))
        ) / 2.0)
        expected_flow = (
            area * float(basis.get("rainfall_intensity_mm_h"))
            * float(basis.get("runoff_coefficient")) / 3600.0
        )
        actual_flow = float(row.get("design_flow_lps"))
        if not math.isfinite(actual_flow) or abs(actual_flow - round(expected_flow, 4)) > 1e-9:
            errors.append(f"FLOW_RECOMPUTE_MISMATCH:{row.get('catchment_id')}")
        if abs(float(row.get("area_m2")) - round(area, 3)) > 1e-9:
            errors.append(f"AREA_RECOMPUTE_MISMATCH:{row.get('catchment_id')}")
        if row.get("calc_id") not in {
            segment.get("calc_id") for segment in result.get("segments") or []
        }:
            errors.append(f"ORPHAN_CALCULATION:{row.get('catchment_id')}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "qa_version": QA_VERSIONS["MECH_ROOF_RAINWATER_CALC"],
        "checks": {
            "producer_pass": result.get("status") == "PASS",
            "catchment_count_reconciled": len(rows) == len(source),
            "critical_values_recomputed": not any(
                token in error for error in errors
                for token in ("FLOW_RECOMPUTE", "AREA_RECOMPUTE")
            ),
            "calculation_identity_linked": not any(
                error.startswith("ORPHAN_CALCULATION") for error in errors
            ),
        },
        "errors": errors,
    }


def _as_point(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label}:POINT_INVALID")
    point = tuple(float(coordinate) for coordinate in value)
    if not all(math.isfinite(coordinate) for coordinate in point):
        raise ValueError(f"{label}:POINT_NONFINITE")
    return point


def _rainwater_plan_dxf(snapshot, calculation):
    """Materialize only explicitly supplied, calculation-linked roof geometry."""
    roof = snapshot.get("roof") or {}
    project = snapshot.get("project") or {}
    boundary = [_as_point(point, "ROOF_BOUNDARY") for point in roof.get("boundary") or []]
    if len(boundary) < 3:
        raise ValueError("ROOF_BOUNDARY_INVALID")
    catchments = {str(row.get("id")): row for row in roof.get("catchments") or []}
    stacks = {str(row.get("id")): row for row in roof.get("stacks") or []}
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    for name, color, lineweight in (("RW-ROOF", 7, 35), ("RW-CATCHMENT", 3, 18),
                                    ("RW-DRAIN", 1, 35), ("RW-STACK", 6, 35),
                                    ("RW-SLOPE", 4, 25), ("RW-PIPE", 5, 50),
                                    ("RW-OVERFLOW", 30, 25), ("RW-SECONDARY", 30, 50),
                                    ("RW-SECONDARY-DISCHARGE", 1, 50),
                                    ("RW-RULE", 6, 18), ("RW-ANNOTATION", 2, 18),
                                    ("RW-SCHEDULE", 3, 18), ("RW-DETAIL", 4, 25),
                                    ("RW-WIND-CANONICAL-ROOF", 7, 25), ("RW-WIND-ROOF", 2, 18), ("RW-WIND-ZONE", 4, 18),
                                    ("RW-WIND-ATTACHMENT", 1, 25), ("RW-WIND-PROFILE", 6, 18),
                                    ("RW-TITLE", 7, 25), ("RW-SHEET", 7, 25)):
        doc.layers.add(name, color=color, lineweight=lineweight)
    msp = doc.modelspace()
    def note(text, point, width=3.5, height=0.18, layer="RW-ANNOTATION"):
        entity = msp.add_mtext(text, dxfattribs={"layer": layer, "char_height": height})
        entity.dxf.insert = point
        entity.dxf.width = width
        return entity
    msp.add_lwpolyline(boundary, close=True, dxfattribs={"layer": "RW-ROOF"})
    roof_center_x = (min(point[0] for point in boundary) + max(point[0] for point in boundary)) / 2
    result_rows = {str(row["catchment_id"]): row for row in calculation.get("catchments") or []}
    drawn_stacks = set()
    for catchment_index, catchment_id in enumerate(sorted(catchments), 1):
        source = catchments[catchment_id]
        result = result_rows.get(catchment_id)
        if not result:
            raise ValueError(f"{catchment_id}:CALCULATION_MISSING")
        polygon = [_as_point(point, f"{catchment_id}:POLYGON") for point in source.get("polygon") or []]
        drain_point = _as_point((source.get("drain") or {}).get("point"), f"{catchment_id}:DRAIN")
        stack = stacks.get(str(source.get("stack_id")))
        if not stack:
            raise ValueError(f"{catchment_id}:STACK_MISSING")
        stack_point = _as_point(stack.get("point"), f"{catchment_id}:STACK")
        route = source.get("route")
        if not isinstance(route, list) or len(route) < 2:
            raise ValueError(f"{catchment_id}:DISCHARGE_ROUTE_MISSING")
        route_points = [_as_point(point, f"{catchment_id}:ROUTE") for point in route]
        if route_points[0] != drain_point or route_points[-1] != stack_point:
            raise ValueError(f"{catchment_id}:ROUTE_ENDPOINT_MISMATCH")
        if drain_point == stack_point or all(
                route_points[index] == route_points[index + 1]
                for index in range(len(route_points) - 1)):
            raise ValueError(f"{catchment_id}:DISCHARGE_ROUTE_DEGENERATE")
        if any(route_points[index] == route_points[index + 1]
               for index in range(len(route_points) - 1)):
            raise ValueError(f"{catchment_id}:ROUTE_ZERO_LENGTH_SEGMENT")
        overflow = source.get("emergency_overflow") or {}
        overflow_point = _as_point(overflow.get("point"), f"{catchment_id}:OVERFLOW")
        msp.add_lwpolyline(polygon, close=True, dxfattribs={"layer": "RW-CATCHMENT"})
        msp.add_circle(drain_point, radius=0.12, dxfattribs={"layer": "RW-DRAIN"})
        if str(source.get("stack_id")) not in drawn_stacks:
            msp.add_circle(stack_point, radius=0.16, dxfattribs={"layer": "RW-STACK"})
            drawn_stacks.add(str(source.get("stack_id")))
        msp.add_lwpolyline(route_points, dxfattribs={"layer": "RW-PIPE"})
        centroid = (sum(point[0] for point in polygon) / len(polygon),
                    sum(point[1] for point in polygon) / len(polygon))
        if centroid == drain_point:
            raise ValueError(f"{catchment_id}:SLOPE_DIRECTION_DEGENERATE")
        msp.add_lwpolyline([centroid, drain_point], dxfattribs={"layer": "RW-SLOPE"})
        angle = math.atan2(drain_point[1] - centroid[1], drain_point[0] - centroid[0])
        arrow_length = 0.28
        for offset in (2.55, -2.55):
            msp.add_line(drain_point,
                         (drain_point[0] + arrow_length * math.cos(angle + offset),
                          drain_point[1] + arrow_length * math.sin(angle + offset)),
                         dxfattribs={"layer": "RW-SLOPE"})
        msp.add_circle(overflow_point, radius=0.10, dxfattribs={"layer": "RW-OVERFLOW"})
        overflow_x = overflow_point[0] + 0.16 if overflow_point[0] <= roof_center_x else overflow_point[0] - 1.05
        note(f"OF-C{catchment_index}", (overflow_x, overflow_point[1] + 0.28), width=1.0)
        label = (f"{result['drain_id']}  DN{int(result['drain_dn_mm'])}  "
                 f"Q={result['design_flow_lps']:.4f} L/s | Aeff={result.get('effective_area_m2',result['area_m2']):.3f} m2\n{result['calc_id']}")
        label_x = centroid[0] - 1.35
        note(label, (label_x, centroid[1] + 1.25), width=2.7, height=0.14)
        note(f"S={result['slope_percent']:.2f}% -> {result['drain_id']}",
             (label_x, centroid[1] + 0.25), width=2.2)
        note(f"RW DN{int(result['downpipe_dn_mm'])} -> {source['stack_id']}",
             (label_x, centroid[1] - 0.55), width=2.4, height=0.14)
        note(f"STACK {source['stack_id']} | DN{int(result['downpipe_dn_mm'])}",
             (label_x, centroid[1] - 1.35), width=2.7, height=0.14)
    secondary = roof.get("secondary_network") or {}
    for index, route in enumerate(secondary.get("routes") or [], 1):
        points = [_as_point(point, f"SECONDARY_ROUTE_{index}") for point in route.get("points") or []]
        if len(points) < 2:
            raise ValueError(f"SECONDARY_ROUTE_{index}:POINTS_MISSING")
        msp.add_lwpolyline(points, dxfattribs={"layer": "RW-SECONDARY"})
        note(f"SECONDARY ROUTE SR-{index} | ELEV={secondary.get('elevation_m','INPUT_REQUIRED')} m",
             points[len(points)//2], width=4.5, height=0.14, layer="RW-RULE")
    for index, discharge in enumerate(secondary.get("discharge_points") or [], 1):
        point = _as_point(discharge.get("point"), f"SECONDARY_DISCHARGE_{index}")
        msp.add_circle(point, radius=0.14, dxfattribs={"layer": "RW-SECONDARY-DISCHARGE"})
        note(f"SECONDARY DISCHARGE SD-{index} | VISIBLE={secondary.get('outlet_visible','INPUT_REQUIRED')}",
             (point[0] + 0.18, point[1] + 0.18), width=4.5, height=0.14, layer="RW-RULE")
    minimum_x = min(point[0] for point in boundary)
    minimum_y = min(point[1] for point in boundary)
    title = (f"ROOF RAINWATER COLLECTION PLAN | DRAFT | "
             f"PROJECT {project.get('project_identity', 'ISOLATED-FIXTURE')} | "
             f"REV {project.get('revision_identity', '1')} | MODEL 1:1 | PLOT NTS | UNITS m")
    sheet_width = max(12.0, max(point[0] for point in boundary) - minimum_x)
    msp.add_lwpolyline([(minimum_x, minimum_y - 4.20),
                        (minimum_x + sheet_width, minimum_y - 4.20),
                        (minimum_x + sheet_width, minimum_y - 0.35),
                        (minimum_x, minimum_y - 0.35)], close=True,
                       dxfattribs={"layer": "RW-SHEET"})
    note(title, (minimum_x + 0.20, minimum_y - 0.70), width=sheet_width - 0.4,
         height=0.16, layer="RW-TITLE")
    note("LEGEND: RD=ROOF DRAIN | RW=RAINWATER PIPE | STACK=DOWNPIPE | OF=OVERFLOW",
         (minimum_x + 0.20, minimum_y - 1.32), width=sheet_width - 0.4,
         height=0.14, layer="RW-TITLE")
    assumption = snapshot.get("draft_assumption_basis") or {}
    note("DRAFT: SOURCE-BOUND ROOF/DRAIN EVIDENCE + REVERSIBLE PROPOSED CATCHMENTS, ROUTES AND OVERFLOWS. RELEASE NOT AUTHORIZED.",
         (minimum_x + 0.20, minimum_y - 1.88), width=sheet_width - 0.4,
         height=0.14, layer="RW-TITLE")
    if assumption:
        note((f"HYDRAULIC CAPACITY UNVERIFIED | ASSUMPTION ORIGIN={assumption.get('assumption_origin','DETERMINISTIC_DRAFT_ASSUMPTION')}; "
              f"RAINFALL={assumption.get('rainfall_authority','UNAPPROVED_DRAFT')}; "
              f"CAPACITY={assumption.get('capacity_authority','UNAPPROVED_DRAFT')}; "
              "OWNER/ENGINEER CONFIRMATION REQUIRED."),
             (minimum_x + 0.20, minimum_y - 2.22), width=sheet_width - 0.4,
             height=0.14, layer="RW-TITLE")
    schedule_x = minimum_x + sheet_width + 0.60
    schedule_y = max(point[1] for point in boundary)
    note("RAINWATER HYDRAULIC SCHEDULE", (schedule_x, schedule_y), width=7.0,
         height=0.18, layer="RW-SCHEDULE")
    for index,row in enumerate(calculation.get("catchments") or []):
        appendix=row.get("appendix7_evidence") or {}
        note((f"{row.get('catchment_id')} | Aplan={row.get('area_m2')} | Aeff={row.get('effective_area_m2')} m2 | "
              f"Q={row.get('design_flow_lps')} L/s | V=DN{int(row.get('drain_dn_mm'))} | "
              f"H=DN{int(row.get('downpipe_dn_mm'))}@{row.get('horizontal_pipe_slope_percent')}% | "
              f"TABLE={appendix.get('base_rainfall_mm_h','PROJECT')}mm/h"),
             (schedule_x, schedule_y - 0.35 - index*0.30), width=8.0,
             height=0.13, layer="RW-SCHEDULE")
    components=(snapshot.get("rule_context") or {}).get("rainwater_components") or []
    material_y=schedule_y-0.75-len(calculation.get("catchments") or [])*0.30
    note("MATERIAL APPROVAL SCHEDULE", (schedule_x,material_y), width=7.0,
         height=0.18, layer="RW-SCHEDULE")
    for index,row in enumerate(components):
        cert=row.get("certificate") or {}
        note((f"{row.get('product_identity','INPUT_REQUIRED')} | MFR MARK={row.get('manufacturer_mark_permanent','INPUT_REQUIRED')} | "
              f"STD MARK={row.get('standard_mark_permanent','INPUT_REQUIRED')} | CERT={cert.get('id','INPUT_REQUIRED')} | "
              f"ISSUER COMPETENT={cert.get('issuer_competent','INPUT_REQUIRED')}"),
             (schedule_x,material_y-0.35-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    destinations=(snapshot.get("rule_context") or {}).get("rainwater_discharge_destinations") or []
    destination_y=material_y-0.75-len(components)*0.30
    note("DISCHARGE DESTINATION / PROPERTY BOUNDARY SCHEDULE",(schedule_x,destination_y),
         width=8.0,height=0.18,layer="RW-SCHEDULE")
    for index,row in enumerate(destinations):
        permit=row.get("permit") or {}
        note((f"{row.get('id')} | DEST={row.get('destination_type')} | INSIDE PROPERTY={row.get('inside_property')} | "
              f"NUISANCE={row.get('causes_nuisance')} | PERMIT={permit.get('id','NA')}:{permit.get('status','NA')}"),
             (schedule_x,destination_y-0.35-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    pollution_rows=(snapshot.get("rule_context") or {}).get("rainwater_pollution_prevention_interfaces") or []
    pollution_y=destination_y-0.75-len(destinations)*0.30
    for index,row in enumerate(pollution_rows):
        route=row.get("rainwater_route_points") or []
        if len(route)>=2:msp.add_lwpolyline(route,dxfattribs={"layer":"RW-POLLUTION-AUDIT"})
        for polygon in row.get("waste_or_sewage_source_polygons") or []:
            if len(polygon)>=3:msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-POLLUTION-SOURCE"})
        response=row.get("environmental_health_response") or {}
        note((f"POLLUTION INTERFACE {row.get('interface_id')} | OWNER={response.get('response_id')} | "
              f"MIN SEPARATION={response.get('minimum_separation_m')}m"),
             (schedule_x,pollution_y-index*0.30),width=8.0,height=0.13,layer="RW-POLLUTION-AUDIT")
    site_rows=(snapshot.get("rule_context") or {}).get("rainwater_site_projection_interfaces") or []
    site_y=pollution_y-0.75-len(pollution_rows)*0.30
    for index,row in enumerate(site_rows):
        polygon=row.get("component_polygon") if row.get("interface_kind")=="BURIED_COMPONENT_PROPERTY_BOUNDARY" else row.get("projection_polygon")
        if len(polygon or [])>=3:msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-SITE-PROJECTION"})
        if len(row.get("property_polygon") or [])>=3:msp.add_lwpolyline(row["property_polygon"],close=True,dxfattribs={"layer":"RW-PROPERTY-BOUNDARY"})
        if len(row.get("building_footprint_polygon") or [])>=3:msp.add_lwpolyline(row["building_footprint_polygon"],close=True,dxfattribs={"layer":"RW-BUILDING-FOOTPRINT"})
        for way in row.get("public_way_polygons") or []:
            if len(way)>=3:msp.add_lwpolyline(way,close=True,dxfattribs={"layer":"RW-PUBLIC-WAY"})
        if len(row.get("public_way_polygon") or [])>=3:msp.add_lwpolyline(row["public_way_polygon"],close=True,dxfattribs={"layer":"RW-PUBLIC-WAY"})
        if len(row.get("carriageway_edge_line") or [])>=2:msp.add_lwpolyline(row["carriageway_edge_line"],dxfattribs={"layer":"RW-CARRIAGEWAY-EDGE"})
        for zone in (row.get("light_vent_patio_polygons") or [])+(row.get("power_line_corridor_polygons") or []):
            if len(zone)>=3:msp.add_lwpolyline(zone,close=True,dxfattribs={"layer":"RW-SITE-EXCLUSION"})
        response=row.get("urban_structural_authority_response") or {}
        note((f"SITE INTERFACE {row.get('interface_id')} | KIND={row.get('interface_kind')} | "
              f"ADJ={row.get('adjacency_type','PROPERTY')} | OWNER={response.get('response_id','NA')}"),
             (schedule_x,site_y-index*0.30),width=8.0,height=0.13,layer="RW-SITE-PROJECTION")
    waterproofing=(snapshot.get("rule_context") or {}).get("waterproofing_interfaces") or []
    architecture_y=destination_y-0.75-len(destinations)*0.30
    note("ARCHITECTURAL WATERPROOFING / BASEMENT RUNOFF DETAILS",(schedule_x,architecture_y),
         width=8.0,height=0.18,layer="RW-DETAIL")
    for index,row in enumerate(waterproofing):
        note((f"{row.get('entity_id')} | SURFACE={row.get('surface_type')} | SOURCE={row.get('source_geometry_id')} | "
              f"MEMBRANE={row.get('membrane_continuous')} | DRAIN SEAL={row.get('drain_penetration_sealed')} | "
              f"UPSTAND={row.get('upstand_detail_id','INPUT_REQUIRED')}"),
             (schedule_x,architecture_y-0.35-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    basement=(snapshot.get("rule_context") or {}).get("basement_openings") or []
    basement_y=architecture_y-0.75-len(waterproofing)*0.30
    for index,row in enumerate(basement):
        note((f"BASEMENT {row.get('entity_id')} | SOURCE={row.get('source_geometry_id')} | "
              f"INTERCEPTOR={row.get('runoff_interceptor_id','INPUT_REQUIRED')} | "
              f"ENTRY PREVENTED={row.get('surface_water_entry_prevented')} | "
              f"WATERPROOFING={row.get('below_grade_waterproofing_continuous')}"),
             (schedule_x,basement_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    routes=(snapshot.get("rule_context") or {}).get("rainwater_route_entities") or []
    route_y=basement_y-0.75-len(basement)*0.30
    for index,row in enumerate(routes):
        rendered_points=row.get("rerouted_route_points") if row.get("rerouted_route_id") else row.get("route_points")
        if rendered_points and len(rendered_points)>=2:
            msp.add_lwpolyline(rendered_points,dxfattribs={"layer":"RW-ARCH-ROUTE-AUDIT"})
        for zone in row.get("private_space_polygons") or []:
            if len(zone.get("polygon") or [])>=3:
                msp.add_lwpolyline(zone["polygon"],close=True,dxfattribs={"layer":"RW-PRIVATE-SPACE-AUDIT"})
        note((f"ROUTE {row.get('route_id')} | SOURCE={row.get('source_geometry_id')} | OWNER={row.get('owner_unit_id')} | "
              f"ACCESS={row.get('accessible_everywhere')} | SHAFT={row.get('shaft_id','NA')} | "
              f"ACCESS PANEL={row.get('shaft_access_panel_id','INPUT_REQUIRED')} | REROUTE={row.get('rerouted_route_id','NONE')}"),
             (schedule_x,route_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    ceilings=(snapshot.get("rule_context") or {}).get("suspended_ceiling_route_interfaces") or []
    ceiling_y=route_y-0.75-len(routes)*0.30
    for index,row in enumerate(ceilings):
        clear=(float(row.get("finished_ceiling_elevation_m",0))-float(row.get("finished_floor_elevation_m",0)))
        note((f"CEILING {row.get('interface_id')} | SOURCE={row.get('source_geometry_id')} | CLEAR={clear:.3f}m | "
              f"MIN={row.get('minimum_legal_clear_height_m')}m | INDEPENDENT SUPPORT={row.get('independent_pipe_support')} | "
              f"NO CONTACT={row.get('no_ceiling_contact')}"),
             (schedule_x,ceiling_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    pitched=(snapshot.get("rule_context") or {}).get("pitched_roof_edges") or []
    pitched_y=ceiling_y-0.75-len(ceilings)*0.30
    for index,row in enumerate(pitched):
        edge=row.get("edge_points") or [];boundary=row.get("boundary_points") or []
        setback=(LineString(edge).distance(LineString(boundary)) if len(edge)>=2 and len(boundary)>=2 else None)
        note((f"PITCHED EDGE {row.get('edge_id')} | SETBACK={setback if setback is not None else 'INPUT_REQUIRED'}m | "
              f"SLOPES TO BOUNDARY={row.get('slopes_toward_boundary')} | SNOW RETENTION={row.get('snow_ice_retention')} | "
              f"SAFETY ANCHOR={row.get('worker_safety_anchor_id','INPUT_REQUIRED')}"),
             (schedule_x,pitched_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    exterior=(snapshot.get("rule_context") or {}).get("exterior_drainage_spaces") or []
    exterior_y=pitched_y-0.75-len(pitched)*0.30
    for index,row in enumerate(exterior):
        note((f"EXTERIOR {row.get('space_id')} | TYPE={row.get('space_type')} | DRAIN={row.get('drain_point')} | "
              f"DEST={row.get('destination_type')} | PONDING FREE={row.get('ponding_free')} | CLEAN ACCESS={row.get('cleaning_access_id','NA')}"),
             (schedule_x,exterior_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    parking=(snapshot.get("rule_context") or {}).get("parking_drainage_areas") or []
    parking_y=exterior_y-0.75-len(exterior)*0.30
    for index,row in enumerate(parking):
        note((f"PARKING {row.get('area_id')} | DRAIN={row.get('drain_point')} | PONDING FREE={row.get('ponding_free')} | "
              f"ENTRY CREST={row.get('entrance_crest_above_exterior_m','NA')}m | ALT APPROVAL={(row.get('approved_alternative') or {}).get('id','NA')}"),
             (schedule_x,parking_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    installation=(snapshot.get("rule_context") or {}).get("rainwater_installation_interfaces") or []
    installation_y=parking_y-0.75-len(parking)*0.30
    for index,row in enumerate(installation):
        note((f"INSTALL {row.get('interface_id')} | TYPE={row.get('interface_type')} | SOURCE={row.get('source_geometry_id')} | "
              f"PROTECTION={row.get('protection_detail_id','NA')} | SLEEVE={row.get('sleeve_or_clearance_detail_id','NA')} | "
              f"GRATE={row.get('grate_detail_id','NA')}"),
             (schedule_x,installation_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    nonpotable=(snapshot.get("rule_context") or {}).get("nonpotable_reuse_connections") or []
    nonpotable_y=installation_y-0.75-len(installation)*0.30
    for index,row in enumerate(nonpotable):
        device=row.get("backflow_device") or {}
        note((f"NONPOTABLE {row.get('connection_id')} | TYPE={row.get('connection_type')} | SEPARATE={row.get('potable_network_separate')} | "
              f"IDENT={row.get('nonpotable_identification')} | AIR GAP={row.get('air_gap_mm','NA')}mm | BACKFLOW={device.get('product_identity','NA')}"),
             (schedule_x,nonpotable_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    roof_access=(snapshot.get("rule_context") or {}).get("roof_access_safety") or {}
    roof_access_y=nonpotable_y-0.75-len(nonpotable)*0.30
    if roof_access:
        note((f"ROOF ACCESS | TYPE={roof_access.get('access_type')} | STOREYS={roof_access.get('storeys_above_ground')} | "
              f"ROOF SLOPE={roof_access.get('roof_slope_percent')}% | HEADHOUSE={roof_access.get('stair_headhouse_area_m2','NA')}m2/"
              f"{roof_access.get('stair_enclosure_area_m2','NA')}m2 | PARAPET={roof_access.get('parapet_height_m','NA')}m"),
             (schedule_x,roof_access_y),width=8.0,height=0.13,layer="RW-DETAIL")
    entrances=(snapshot.get("rule_context") or {}).get("entrance_landing_interfaces") or []
    entrance_y=roof_access_y-(0.45 if roof_access else 0)
    for index,row in enumerate(entrances):
        note((f"ENTRANCE {row.get('entrance_id')} | INSIDE={row.get('inside_landing_elevation_mm')}mm | "
              f"OUTSIDE={row.get('outside_landing_elevation_mm')}mm | THRESHOLD={row.get('threshold_top_elevation_mm')}mm | "
              f"ACCESSIBLE={row.get('accessible_route')} | EGRESS={row.get('required_egress')} | OCC={row.get('occupancy_group')}"),
             (schedule_x,entrance_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    entrance_runoff_rows=(snapshot.get("rule_context") or {}).get("main_entrance_runoff_elevation_interfaces") or []
    for index,row in enumerate(entrance_runoff_rows):
        approval=row.get("local_authority_adjustment") or {}
        note((f"ENTRANCE RUNOFF {row.get('entrance_id')} | INTERFACE={row.get('rainwater_runoff_interface')} | MAIN FLOOR={row.get('main_entrance_floor_elevation_mm')}mm | AVERAGE WAY={row.get('average_adjacent_way_elevation_mm')}mm | SITE={row.get('site_condition')} | BASIS={approval.get('approval_id','SOURCE_STANDARD')}"),(schedule_x,entrance_y-(len(entrances)+index)*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    rain_snow=(snapshot.get("rule_context") or {}).get("rain_on_snow_load_case") or {}
    rain_snow_y=entrance_y-0.45-len(entrances)*0.30
    if rain_snow:
        note((f"RAIN ON SNOW | REGION={rain_snow.get('snow_region')} | SLOPE={rain_snow.get('roof_slope_deg')}deg | "
              f"W={rain_snow.get('slope_run_w_m')}m | BALANCED={rain_snow.get('balanced_snow_load_kn_m2')}kN/m2 | "
              f"RAIN={rain_snow.get('rain_surcharge_kn_m2')}kN/m2 | COMBINED={rain_snow.get('declared_combined_load_kn_m2')}kN/m2"),
             (schedule_x,rain_snow_y),width=8.0,height=0.13,layer="RW-DETAIL")
    live_loads=(snapshot.get("rule_context") or {}).get("roof_service_live_loads") or []
    live_load_y=rain_snow_y-(0.45 if rain_snow else 0)
    for index,row in enumerate(live_loads):
        note((f"ROOF LIVE LOAD {row.get('area_id')} | TYPE={row.get('load_area_type')} | "
              f"UNIFORM={row.get('uniform_load_kn_m2','NA')}kN/m2 | POINT={row.get('concentrated_load_kn',row.get('point_load_kn','NA'))}kN | "
              f"SPACING={row.get('point_load_spacing_m','NA')}m"),
             (schedule_x,live_load_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    material_rows=(snapshot.get("rule_context") or {}).get("rainwater_material_installations") or []
    material_y=live_load_y-0.45-len(live_loads)*0.30
    for index,row in enumerate(material_rows):
        note((f"MATERIAL {row.get('installation_id')} | {row.get('material')} | STD={row.get('standard')} | "
              f"JOINT={row.get('joint_method')} | BURIED={row.get('buried')} | MARK={row.get('burial_marking','NA')} | "
              f"MFR={row.get('manufacturer_instruction_id')}"),
             (schedule_x,material_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    support_installations=(snapshot.get("rule_context") or {}).get("rainwater_material_support_installations") or []
    support_installation_y=material_y-0.45-len(material_rows)*0.30
    for index,row in enumerate(support_installations):
        note((f"SUPPORT INSTALL {row.get('installation_id')} | {row.get('material_group')}/{row.get('orientation')} | "
              f"CLAMP={row.get('clamp_type')}/{row.get('clamp_material')} | BUILDING CONNECTED={row.get('support_connected_to_building')} | "
              f"MOVEMENT={row.get('longitudinal_movement_allowed')} | BASE={row.get('base_bearing','NA')} | "
              f"SAND BED={row.get('continuous_sand_bedding','NA')}"),
             (schedule_x,support_installation_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    air_gaps=(snapshot.get("rule_context") or {}).get("potable_outlets_over_rainwater_receptors") or []
    air_gap_y=support_installation_y-0.45-len(support_installations)*0.30
    for index,row in enumerate(air_gaps):
        note((f"POTABLE AIR GAP {row.get('outlet_id')} | GROUP={row.get('outlet_group')} | "
              f"DIA={row.get('effective_diameter_mm')}mm | NEAR WALL={row.get('near_wall')} | "
              f"VERTICAL GAP={row.get('vertical_air_gap_mm')}mm"),
             (schedule_x,air_gap_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    load_combos=(snapshot.get("rule_context") or {}).get("structural_rainwater_load_combinations") or {}
    load_combo_y=air_gap_y-0.45-len(air_gaps)*0.30
    if load_combos:
        live_basis=load_combos.get("live_load_factor_basis") or {}
        note((f"LRFD RAINWATER LOAD COMBINATIONS | GOVERNING={load_combos.get('governing_case_id')} | "
              f"L FACTOR={live_basis.get('declared_factor')} | L0={live_basis.get('nominal_live_load_kpa')}kPa | OCCUPANCY={live_basis.get('occupancy_type')} | LIVE REDUCED={live_basis.get('live_load_reduction_applied')} | "
              f"EFFECT={load_combos.get('effect_type')}/{load_combos.get('effect_unit')} | "
              f"CAPACITY ABS={load_combos.get('design_capacity_abs')} | ANALYSIS={load_combos.get('structural_analysis_id')}"),
             (schedule_x,load_combo_y),width=8.0,height=0.13,layer="RW-DETAIL")
    asd_combos=(snapshot.get("rule_context") or {}).get("structural_rainwater_asd_combinations") or {}
    asd_combo_y=load_combo_y-(0.30 if load_combos else 0)
    if asd_combos:
        note((f"ASD RAINWATER LOAD COMBINATIONS | GOVERNING={asd_combos.get('governing_case_id')} | "
              f"EFFECT={asd_combos.get('effect_type')}/{asd_combos.get('effect_unit')} | "
              f"ALLOWABLE ABS={asd_combos.get('allowable_capacity_abs')} | ANALYSIS={asd_combos.get('structural_analysis_id')}"),
             (schedule_x,asd_combo_y),width=8.0,height=0.13,layer="RW-DETAIL")
    blockage_rows=(snapshot.get("rule_context") or {}).get("roof_primary_blockage_rain_loads") or []
    blockage_y=asd_combo_y-(0.30 if asd_combos else 0)
    for index,row in enumerate(blockage_rows):
        ds=(float(row.get("secondary_inlet_elevation_mm",0))-float(row.get("undeformed_roof_elevation_mm",0)))
        pond=row.get("ponding_analysis") or {}
        note((f"PRIMARY BLOCKAGE RAIN LOAD {row.get('roof_area_id')} | DS={ds}mm | DH={row.get('hydraulic_head_mm')}mm | "
              f"R={row.get('declared_rain_load_kn_m2')}kN/m2 | PONDING={pond.get('analysis_id','INPUT_REQUIRED')}/"
              f"{pond.get('stable','INPUT_REQUIRED')} | STRUCT={row.get('structural_analysis_id')}"),
             (schedule_x,blockage_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    snow_rows=(snapshot.get("rule_context") or {}).get("roof_snow_load_basis") or []
    snow_y=blockage_y-(0.30*len(blockage_rows) if blockage_rows else 0)
    for index,row in enumerate(snow_rows):
        note((f"ROOF SNOW LOAD {row.get('roof_area_id')} | PR={row.get('declared_balanced_roof_snow_pr_kn_m2')}kN/m2 | "
              f"GAMMA={row.get('declared_snow_unit_weight_kn_m3')}kN/m3 | HB={row.get('declared_balanced_snow_height_m')}m | "
              f"GEOMETRY={row.get('exposure_geometry_analysis_id')}"),
             (schedule_x,snow_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    drift_rows=(snapshot.get("rule_context") or {}).get("rooftop_snow_drift_features") or []
    drift_y=snow_y-(0.30*len(snow_rows) if snow_rows else 0)
    for index,row in enumerate(drift_rows):
        note((f"SNOW DRIFT {row.get('feature_id')} | REGION={row.get('snow_region')} | TYPE={row.get('feature_type')} | "
              f"LU={row.get('declared_lu_m')}m | HD MAX={row.get('declared_max_drift_height_m')}m | "
              f"BASE CALC={row.get('base_calculation_id')}"),
             (schedule_x,drift_y-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    fluid_rows=(snapshot.get("rule_context") or {}).get("fluid_load_combination_extensions") or []
    fluid_y=drift_y-(0.30*len(drift_rows) if drift_rows else 0)
    for index,row in enumerate(fluid_rows):
        note((f"FLUID LOAD {row.get('method')}-{row.get('base_combination_number')} | "
              f"EFFECT={row.get('effect_type')}/{row.get('effect_unit')} | BASE={row.get('base_effect_excluding_f')} | "
              f"F={row.get('fluid_effect_f')} | TOTAL={row.get('declared_effect_including_f')} | ANALYSIS={row.get('analysis_id')}"),
             (schedule_x,fluid_y-index*0.22),width=8.0,height=0.11,layer="RW-DETAIL")
    equipment_rows=(snapshot.get("rule_context") or {}).get("heavy_rooftop_equipment_placements") or []
    equipment_y=fluid_y-(0.22*len(fluid_rows) if fluid_rows else 0)
    for index,row in enumerate(equipment_rows):
        placement=row.get("placement_structural_analysis") or {};seismic=row.get("seismic_nonstructural_analysis") or {}
        note((f"ROOFTOP EQUIPMENT {row.get('equipment_id')} | MASS={row.get('operating_mass_kg')}kg | SUPPORT={row.get('support_member_type')} | "
              f"PLACEMENT={placement.get('analysis_id','INPUT_REQUIRED')} | SEISMIC={seismic.get('analysis_id','INPUT_REQUIRED')} | MODEL={row.get('structural_model_sha256')}"),
             (schedule_x,equipment_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
    live_rows=(snapshot.get("rule_context") or {}).get("roof_live_load_reductions") or []
    live_y=equipment_y-(0.25*len(equipment_rows) if equipment_rows else 0)
    for index,row in enumerate(live_rows):
        note((f"ROOF LIVE REDUCTION {row.get('roof_area_id')} | At={row.get('tributary_area_m2')}m2 | "
              f"S={row.get('slope_parameter_s')} | L0={row.get('unreduced_l0_kn_m2')}kN/m2 | Lr={row.get('declared_lr_kn_m2')}kN/m2"),
             (schedule_x,live_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
    special_rows=(snapshot.get("rule_context") or {}).get("special_use_roof_live_load_reductions") or []
    deflection_rows=(snapshot.get("rule_context") or {}).get("roof_serviceability_deflection_checks") or []
    service_y=live_y-(0.25*len(live_rows) if live_rows else 0)
    for index,row in enumerate(special_rows):
        calc=row.get("section_6_5_5_calculation") or {}
        note((f"SPECIAL ROOF LOAD {row.get('roof_area_id')} | USE={row.get('special_use_type')} | "
              f"KLL={row.get('member_location_factor_kll')} | At={row.get('tributary_area_m2')}m2 | "
              f"FLOORS={row.get('supported_floor_count')} | L0={row.get('unreduced_l0_kn_m2')} | "
              f"L={calc.get('result_kn_m2')} | DESIGN={row.get('declared_design_live_load_kn_m2')} | CALC={calc.get('calculation_id')}"),
             (schedule_x,service_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
    vibration_rows=(snapshot.get("rule_context") or {}).get("rainwater_equipment_vibration_isolation_interfaces") or []
    vibration_y=service_y-0.25*len(special_rows)
    for index,row in enumerate(vibration_rows):
        response=row.get("vibration_isolation_response") or {};product=row.get("selected_isolator") or {}
        note((f"VIBRATION ISOLATION {row.get('equipment_id')} | TYPE={row.get('equipment_type')} | "
              f"CAPABLE={row.get('can_create_undesirable_vibration')} | SUPPORTS={len(row.get('support_points') or [])} | "
              f"ISOLATOR={product.get('product_id')}:{product.get('isolator_type')} | ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,vibration_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
        polygon=row.get("equipment_footprint") or []
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-VIBRATION-ISOLATION"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("equipment_id"))),(1000,str(product.get("product_id"))),(1000,str(response.get("analysis_id")))])
    buried_rows=(snapshot.get("rule_context") or {}).get("buried_rainwater_geotechnical_interfaces") or []
    buried_y=vibration_y-0.25*len(vibration_rows)
    for index,row in enumerate(buried_rows):
        response=row.get("geotechnical_structural_response") or {}
        note((f"BURIED RAINWATER {row.get('asset_id')} | TYPE={row.get('asset_type')} | H={row.get('retained_height_m')}m | "
              f"GW={row.get('groundwater_head_m')}m | Q={row.get('surface_surcharge_kpa')}kPa | "
              f"LATERAL={response.get('reviewed_lateral_pressure_at_base_kpa')}kPa | UPLIFT={response.get('reviewed_uplift_pressure_kpa')}kPa | ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,buried_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
        polygon=row.get("footprint") or []
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-BURIED-GEOTECH"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("asset_id"))),(1000,str(response.get("analysis_id"))),(1040,float(response.get("reviewed_lateral_pressure_at_base_kpa") or 0)),(1040,float(response.get("reviewed_uplift_pressure_kpa") or 0))])
    buried_h_rows=(snapshot.get("rule_context") or {}).get("rainwater_buried_h_load_combination_extensions") or []
    buried_h_y=buried_y-0.25*len(buried_rows)
    for index,row in enumerate(buried_h_rows):
        note((f"BURIED H COMBINATIONS {row.get('asset_id')} | H={row.get('h_effect_abs')}{row.get('effect_unit')} | PERMANENT={row.get('h_is_permanent')} | GOVERNING={row.get('governing_case_id')} | CAPACITY={row.get('capacity_abs')}{row.get('effect_unit')} | ANALYSIS={row.get('structural_analysis_id')}"),(schedule_x,buried_h_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
    construction_rows=(snapshot.get("rule_context") or {}).get("rainwater_construction_stage_loads") or []
    construction_y=buried_h_y-0.25*len(buried_h_rows)
    for index,row in enumerate(construction_rows):
        response=row.get("temporary_structural_response") or {}
        note((f"RAINWATER CONSTRUCTION LOAD {row.get('load_case_id')} | STAGE={row.get('construction_stage')} | MASS={row.get('declared_total_mass_kg')}kg | LOAD={row.get('declared_distributed_load_kpa')}kPa | ANALYSIS={response.get('analysis_id')}"),(schedule_x,construction_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
        polygon=row.get("loaded_footprint") or []
        if len(polygon)>=3:msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-CONSTRUCTION-LOAD"})
    impact_rows=(snapshot.get("rule_context") or {}).get("rainwater_machinery_impact_loads") or []
    impact_y=construction_y-0.25*len(construction_rows)
    for index,row in enumerate(impact_rows):
        response=row.get("support_structural_response") or {}
        note((f"RAINWATER MACHINERY IMPACT {row.get('equipment_id')} | MOTION={row.get('motion_type')} | MASS={row.get('operating_mass_kg')}kg | FACTOR={row.get('manufacturer_impact_factor')} | LOAD={row.get('declared_design_gravity_load_kn')}kN | ANALYSIS={response.get('analysis_id')}"),(schedule_x,impact_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
    movement_rows=(snapshot.get("rule_context") or {}).get("rainwater_serviceability_movement_interfaces") or []
    movement_y=impact_y-0.25*len(impact_rows)
    for index,row in enumerate(movement_rows):
        response=row.get("structural_movement_response") or {}
        note((f"RAINWATER MOVEMENT {row.get('interface_id')} | COMPONENT={row.get('component_id')} | CAUSES={','.join(row.get('self_straining_causes') or [])} | CASE={row.get('declared_governing_case_id')} | VECTOR={row.get('declared_governing_relative_displacement_xyz_mm')}mm | NORM={row.get('declared_governing_relative_displacement_norm_mm')}mm | CAPACITY={row.get('selected_joint_capacity_xyz_mm')}mm | ANALYSIS={response.get('analysis_id')}"),(schedule_x,movement_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
        points=row.get("route_points_3d") or []
        if len(points)>=2:msp.add_lwpolyline([(p[0],p[1]) for p in points],dxfattribs={"layer":"RW-SERVICE-MOVEMENT"})
    extension=(snapshot.get("rule_context") or {}).get("rainwater_flood_ice_load_combination_extensions") or {}
    extension_y=movement_y-0.25*len(movement_rows)
    if extension.get("flood_load_applicable") or extension.get("atmospheric_ice_load_applicable"):
        note((f"FLOOD ICE COMBINATIONS | FLOOD={extension.get('flood_load_applicable')}:{extension.get('flood_interface_id')} | ICE={extension.get('atmospheric_ice_load_applicable')}:{extension.get('atmospheric_ice_component_id')} | GOVERNING={extension.get('governing_case_id')} | CAPACITY={extension.get('capacity_abs')}{extension.get('effect_unit')} | ANALYSIS={extension.get('structural_analysis_id')}"),(schedule_x,extension_y),width=8.0,height=0.11,layer="RW-DETAIL")
    clearance_rows=(snapshot.get("rule_context") or {}).get("occupied_space_rainwater_clearance_routes") or []
    clearance_y=extension_y-(0.25 if extension.get("flood_load_applicable") or extension.get("atmospheric_ice_load_applicable") else 0)
    for index,row in enumerate(clearance_rows):
        minimum=min((float(point[2]) for point in row.get("bottom_envelope_points") or []),default=0)-float(row.get("finished_floor_elevation_m") or 0)
        note((f"OCCUPIED CLEARANCE {row.get('route_id')} | SPACE={row.get('space_id')}:{row.get('space_type')} | LOCAL_OVERHEAD={row.get('crossing_is_local_overhead_projection')} | GENERAL_SPACE_HEIGHT={row.get('general_space_clear_height_m')}m | CLEARANCE={minimum}m | ENVELOPE={','.join(row.get('envelope_components') or [])}"),(schedule_x,clearance_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
        polygon=row.get("space_polygon") or []
        if len(polygon)>=3:msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-OCCUPIED-CLEARANCE-ZONE"})
        points=row.get("bottom_envelope_points") or []
        if len(points)>=2:msp.add_lwpolyline([(p[0],p[1]) for p in points],dxfattribs={"layer":"RW-OCCUPIED-CLEARANCE-ROUTE"})
    egress_rows=(snapshot.get("rule_context") or {}).get("rainwater_egress_width_interfaces") or []
    egress_y=clearance_y-0.25*len(clearance_rows)
    for index,row in enumerate(egress_rows):
        note((f"EGRESS WIDTH {row.get('egress_id')} | REQUIRED={row.get('required_clear_width_m')}m | SECTIONS={len(row.get('cross_sections') or [])} | INVENTORY_COMPLETE={row.get('component_inventory_complete')}"),(schedule_x,egress_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
        polygon=row.get("egress_polygon") or []
        if len(polygon)>=3:msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-EGRESS-CLEARANCE-ZONE"})
        axis=row.get("longitudinal_axis") or []
        if len(axis)==2:msp.add_lwpolyline(axis,dxfattribs={"layer":"RW-EGRESS-LONGITUDINAL-AXIS"})
        for component in row.get("rainwater_component_footprints") or []:
            footprint=component.get("polygon") or []
            if len(footprint)>=3:msp.add_lwpolyline(footprint,close=True,dxfattribs={"layer":"RW-EGRESS-OBSTRUCTION"})
        for section in row.get("cross_sections") or []:
            points=section.get("points") or []
            if len(points)==2:msp.add_lwpolyline(points,dxfattribs={"layer":"RW-EGRESS-CROSS-SECTION"})
    deflection_y=egress_y-0.25*len(egress_rows)
    for index,row in enumerate(deflection_rows):
        note((f"ROOF DEFLECTION {row.get('member_id')} | SPAN={row.get('span_mm')}mm | RATIO=L/{row.get('allowable_deflection_ratio')} | "
              f"ACTUAL={row.get('calculated_deflection_mm')}mm | COMBO={row.get('load_combination_id')} | ANALYSIS={row.get('analysis_id')}"),
             (schedule_x,deflection_y-index*0.25),width=8.0,height=0.11,layer="RW-DETAIL")
    for row in (snapshot.get("rule_context") or {}).get("rainwater_maintenance_access_paths") or []:
        points=row.get("path_points") or []
        if len(points)>=2:
            entity=msp.add_lwpolyline(points,dxfattribs={"layer":"RW-MAINT-ACCESS"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("path_id"))),(1000,str(row.get("target_type"))),(1040,float(row.get("required_clear_width_m") or 0))])
    for row in (snapshot.get("rule_context") or {}).get("parking_ramp_profiles") or []:
        points=row.get("profile_points") or []
        if len(points)>=2:
            entity=msp.add_lwpolyline(points,dxfattribs={"layer":"RW-PARKING-RAMP-PROFILE"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("ramp_id"))),(1000,str(row.get("parking_type"))),(1000,"COVERED" if row.get("covered") else "OPEN")])
    for row in (snapshot.get("rule_context") or {}).get("pedestrian_ramp_runoff_interfaces") or []:
        profile=row.get("profile_points") or [];surface=row.get("selected_surface") or {};review=row.get("accessibility_review") or {}
        if len(profile)>=2:
            entity=msp.add_lwpolyline(profile,dxfattribs={"layer":"RW-PEDESTRIAN-RAMP-PROFILE"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("ramp_id"))),(1000,str(row.get("drainage_route_id"))),(1000,str(surface.get("product_identity")))])
        for landing in row.get("landings") or []:
            polygon=landing.get("polygon") or []
            if len(polygon)>=3:msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-PEDESTRIAN-RAMP-LANDING"})
        note((f"PEDESTRIAN RAMP {row.get('ramp_id')} | CLASS={row.get('route_class')} | ACCESSIBLE={row.get('accessible_required')}:{review.get('review_id')} | DRAIN={row.get('drainage_route_id')} | SURFACE={surface.get('product_identity')} | PONDING_FREE={row.get('ponding_free')}"),(schedule_x,deflection_y-0.25*(len(deflection_rows)+1)),width=8.0,height=0.11,layer="RW-DETAIL")
    for row in (snapshot.get("rule_context") or {}).get("parking_service_clearance_routes") or []:
        polygon=row.get("parking_polygon") or []
        if len(polygon)>=3:
            zone=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-PARKING-CLEARANCE-ZONE"})
            zone.set_xdata("PLANHA",[(1000,str(row.get("parking_zone_id"))),(1000,str(row.get("parking_size"))),(1040,float(row.get("floor_elevation_m") or 0))])
        route=(row.get("reroute_bottom_envelope_points") if row.get("selected_route")=="REROUTE"
               else row.get("bottom_envelope_points")) or []
        if len(route)>=2:
            path=msp.add_lwpolyline([(point[0],point[1]) for point in route],dxfattribs={"layer":"RW-PARKING-CLEARANCE-ROUTE"})
            path.set_xdata("PLANHA",[(1000,str(row.get("route_id"))),(1000,str(row.get("selected_route"))),
                                      (1000,",".join(sorted(str(value) for value in row.get("envelope_components") or [])))])
            for index,point in enumerate(route):
                msp.add_text(f"{row.get('route_id')}:{index} ZBOTTOM={float(point[2]):.3f}m",
                             dxfattribs={"layer":"RW-PARKING-CLEARANCE-ROUTE","height":0.10,
                                         "insert":(float(point[0]),float(point[1]))})
    for row in (snapshot.get("rule_context") or {}).get("covered_patio_natural_ventilation_reviews") or []:
        polygon=row.get("patio_polygon") or [];analysis=row.get("ventilation_analysis") or {}
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-ARCH-VENT-DEPENDENCY"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("patio_id"))),(1000,str(analysis.get("analysis_id"))),
                                        (1000,str(analysis.get("model_sha256")))])
            note((f"ARCH VENT DEPENDENCY {row.get('patio_id')} | ANALYSIS={analysis.get('analysis_id')} | "
                  f"MODEL={analysis.get('model_sha256')} | REQUIRED={analysis.get('required_open_area_m2')}m2 | "
                  f"PROVIDED={analysis.get('provided_open_area_m2')}m2 | OWNER REVIEW={analysis.get('owner_review_id')} | "
                  "RAINWATER MODULE DID NOT PERFORM VENTILATION ANALYSIS"),
                 (polygon[0][0],polygon[0][1]),width=7.0,height=0.11,layer="RW-ARCH-VENT-DEPENDENCY")
    for row in (snapshot.get("rule_context") or {}).get("visible_rainwater_facade_interfaces") or []:
        points=row.get("elevation_polyline") or [];response=row.get("architecture_response") or {}
        if len(points)>=2:
            entity=msp.add_lwpolyline(points,dxfattribs={"layer":"RW-FACADE-COORDINATION"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("component_id"))),(1000,str(row.get("facade_id"))),(1000,str(response.get("review_id")))])
            note((f"FACADE RAINWATER {row.get('component_id')} | TYPE={row.get('component_type')} | FACADE={row.get('facade_id')} | REVIEW={response.get('review_id')}"),(points[0][0],points[0][1]),width=7.0,height=0.11,layer="RW-DETAIL")
    for row in (snapshot.get("rule_context") or {}).get("exterior_intermediary_element_finishes") or []:
        polygon=row.get("element_polygon") or [];finish=row.get("selected_finish") or {};approval=finish.get("product_approval") or {}
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-EXTERIOR-FINISH"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("element_id"))),(1000,str(finish.get("product_identity"))),
                                        (1000,str(approval.get("approval_id")))])
            note((f"EXTERIOR FINISH {row.get('element_id')} | PRODUCT={finish.get('product_identity')} | "
                  f"STD={finish.get('standard')} | APPROVAL={approval.get('approval_id')} | "
                  f"DETAIL={finish.get('application_detail_id')} | MAINT={row.get('maintenance_plan_id')}"),
                 (polygon[0][0],polygon[0][1]),width=7.0,height=0.11,layer="RW-EXTERIOR-FINISH")
    for row in (snapshot.get("rule_context") or {}).get("external_light_air_conduit_route_inventories") or []:
        polygon=row.get("conduit_polygon") or []
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-LIGHT-AIR-CONDUIT-AUDIT"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("conduit_id"))),(1000,str(row.get("service_route_inventory_sha256")))])
            note((f"LIGHT/AIR CONDUIT {row.get('conduit_id')} | FUNCTIONS={','.join(row.get('required_functions') or [])} | "
                  f"ROUTE INVENTORY={row.get('service_route_inventory_sha256')} | COMPLETE={row.get('service_route_inventory_complete')}"),
                 (polygon[0][0],polygon[0][1]),width=7.0,height=0.11,layer="RW-LIGHT-AIR-CONDUIT-AUDIT")
    for row in (snapshot.get("rule_context") or {}).get("parking_ramp_surface_finishes") or []:
        polygon=row.get("ramp_polygon") or [];surface=row.get("selected_surface") or {};approval=surface.get("product_approval") or {};test=surface.get("wet_slip_test") or {}
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-PARKING-RAMP-FINISH"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("ramp_id"))),(1000,str(surface.get("product_identity"))),
                                        (1000,str(approval.get("approval_id"))),(1000,str(test.get("report_id")))])
            note((f"RAMP FINISH {row.get('ramp_id')} | PRODUCT={surface.get('product_identity')} | "
                  f"APPROVAL={approval.get('approval_id')} | WET SLIP TEST={test.get('report_id')}:{test.get('status')} | "
                  f"DETAIL={surface.get('application_detail_id')}"),
                 (polygon[0][0],polygon[0][1]),width=7.0,height=0.11,layer="RW-PARKING-RAMP-FINISH")
    for row in (snapshot.get("rule_context") or {}).get("external_light_air_conduit_traffic_guards") or []:
        points=row.get("top_surface_elevation_points") or [];structural=row.get("structural_guard_analysis") or {};access=row.get("accessibility_review") or {}
        if len(points)>=2:
            entity=msp.add_lwpolyline([(point[0],point[1]) for point in points],dxfattribs={"layer":"RW-LIGHT-AIR-GUARD-DEPENDENCY"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("conduit_id"))),(1000,str(structural.get("analysis_id"))),
                                        (1000,str(access.get("review_id")))])
            note((f"LIGHT/AIR GUARD {row.get('conduit_id')} | TRAFFIC={','.join(row.get('traffic_types') or [])} | "
                  f"STRUCT={structural.get('analysis_id')} | ACCESS={access.get('review_id')} | "
                  "RAINWATER MODULE DID NOT PERFORM STRUCTURAL/ACCESSIBILITY ANALYSIS"),
                 (points[0][0],points[0][1]),width=8.0,height=0.11,layer="RW-LIGHT-AIR-GUARD-DEPENDENCY")
    for row in (snapshot.get("rule_context") or {}).get("external_light_air_conduit_semi_open_finish_reviews") or []:
        polygon=row.get("floor_polygon") or [];review=row.get("semi_open_finish_review") or {}
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-LIGHT-AIR-FINISH-DEPENDENCY"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("conduit_id"))),(1000,str(review.get("review_id"))),
                                        (1000,str(review.get("model_sha256")))])
            note((f"LIGHT/AIR FINISH DEPENDENCY {row.get('conduit_id')} | ARCH REVIEW={review.get('review_id')} | "
                  f"FLOOR={review.get('floor_finish_schedule_id')} | WALLS={','.join(review.get('wall_finish_schedule_ids') or [])} | "
                  "RAINWATER MODULE DID NOT PERFORM FINISH COMPLIANCE ANALYSIS"),
                 (polygon[0][0],polygon[0][1]),width=8.0,height=0.11,layer="RW-LIGHT-AIR-FINISH-DEPENDENCY")
    for row in (snapshot.get("rule_context") or {}).get("under_open_space_parking_reviews") or []:
        polygon=row.get("parking_footprint_polygon") or []
        if len(polygon)>=3:
            entity=msp.add_lwpolyline(polygon,close=True,dxfattribs={"layer":"RW-UNDER-OPEN-PARKING-DEPENDENCY"})
            entity.set_xdata("PLANHA",[(1000,str(row.get("parking_id"))),(1000,str(row.get("architecture_geometry_sha256")))])
            note((f"UNDER-OPEN PARKING {row.get('parking_id')} | GROUP={row.get('building_group')} | "
                  f"RAINWATER INTERFACES={','.join(row.get('rainwater_interface_ids') or [])} | "
                  "OWNER REVIEWS=URBAN/ARCHITECTURE/EMERGENCY ACCESS | RAINWATER MODULE DOES NOT GRANT PERMISSION"),
                 (polygon[0][0],polygon[0][1]),width=8.0,height=0.11,layer="RW-UNDER-OPEN-PARKING-DEPENDENCY")
    strategy_y=deflection_y-0.25*len(deflection_rows)-0.45
    for index,row in enumerate((snapshot.get("rule_context") or {}).get("basement_parking_light_ventilation_strategies") or []):
        note((f"BASEMENT PARKING STRATEGY {row.get('parking_id')} | STOREYS={row.get('basement_storey_count')} | "
              f"STRATEGY={row.get('selected_strategy')} | GEOMETRY={','.join(row.get('strategy_geometry_ids') or [])} | "
              "OWNER ANALYSES NOT PERFORMED BY RAINWATER MODULE"),
             (schedule_x,strategy_y-index*0.25),width=8.0,height=0.11,layer="RW-BASEMENT-PARKING-DEPENDENCY")
    structural=(snapshot.get("rule_context") or {}).get("structural_rainwater_loads") or []
    structural_y=deflection_y-(0.45 if deflection_rows else 0)
    note("STRUCTURAL RAINWATER DEAD-LOAD SCHEDULE",(schedule_x,structural_y),
         width=8.0,height=0.18,layer="RW-SCHEDULE")
    for index,row in enumerate(structural):
        review=row.get("structural_review") or {}
        note((f"{row.get('component_id')} | EMPTY={row.get('empty_component_mass_kg')}kg | "
              f"WATER-FULL={row.get('water_full_mass_kg')}kg | REACTION={row.get('support_reaction_id')} | "
              f"STRUCT REVIEW={review.get('approval_id','INPUT_REQUIRED')}:{review.get('status','INPUT_REQUIRED')}"),
             (schedule_x,structural_y-0.35-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    roof_materials=(snapshot.get("rule_context") or {}).get("roof_material_volumetric_loads") or []
    roof_coverings=(snapshot.get("rule_context") or {}).get("roof_covering_surface_loads") or []
    material_load_y=structural_y-0.45-len(structural)*0.30
    for index,row in enumerate(roof_materials):
        review=row.get("structural_response") or {}
        note((f"ROOF MATERIAL LOAD {row.get('component_id')} | CODE={row.get('material_code')} | "
              f"VOLUME={row.get('volume_m3')}m3 | MASS={row.get('declared_mass_kg')}kg | "
              f"STRUCT={review.get('analysis_id')}:{review.get('reviewed_load_kn')}kN"),
             (schedule_x,material_load_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    covering_load_y=material_load_y-len(roof_materials)*0.30
    for index,row in enumerate(roof_coverings):
        review=row.get("structural_response") or {};interpretation=row.get("official_unit_interpretation") or {}
        note((f"ROOF COVERING LOAD {row.get('component_id')} | CODE={row.get('covering_code')} | "
              f"AREA={row.get('area_m2')}m2 | MASS={row.get('declared_mass_kg')}kg | "
              f"UNIT INTERPRETATION={interpretation.get('interpretation_id')}:{interpretation.get('unit')} | "
              f"STRUCT={review.get('analysis_id')}:{review.get('reviewed_load_kn')}kN"),
             (schedule_x,covering_load_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    drift_y=covering_load_y-len(roof_coverings)*0.30
    for index,row in enumerate((snapshot.get("rule_context") or {}).get("vertical_rainwater_drift_interfaces") or []):
        response=row.get("structural_drift_response") or {}
        note((f"RAINWATER DRIFT {row.get('interface_id')} | HEIGHT={row.get('storey_height_m')}m | "
              f"DISPLACEMENT={response.get('relative_displacement_mm')}mm | JOINT={row.get('selected_joint_allowance_mm')}mm | "
              f"ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,drift_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    wind_y=drift_y-len((snapshot.get("rule_context") or {}).get("vertical_rainwater_drift_interfaces") or [])*0.30
    for index,row in enumerate((snapshot.get("rule_context") or {}).get("exposed_rainwater_pipe_wind_loads") or []):
        response=row.get("support_structural_response") or {}
        vortex=row.get("vortex_dynamic_response") or {}
        note((f"EXPOSED PIPE WIND {row.get('pipe_id')} | D={row.get('diameter_m')}m | L={row.get('exposed_length_m')}m | "
              f"FORCE={row.get('declared_force_kn')}kN | ANALYSIS={response.get('analysis_id')} | "
              f"VORTEX={row.get('vortex_shedding_applicable')}:{row.get('declared_vortex_critical_speed_m_s')}m/s | "
              f"DYNAMIC={vortex.get('analysis_id')}"),
             (schedule_x,wind_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    ice_y=wind_y-len((snapshot.get("rule_context") or {}).get("exposed_rainwater_pipe_wind_loads") or [])*0.30
    ice_rows=(snapshot.get("rule_context") or {}).get("atmospheric_ice_rainwater_components") or []
    nominal_by_region={1:0.0,2:0.0,3:0.0,4:7.5,5:12.5,6:15.0}
    for index,row in enumerate(ice_rows):
        region=int(row.get("snow_region") or 0);z=float(row.get("height_above_ground_m") or 0)
        nominal=float(row.get("official_local_nominal_ice_thickness_mm") if row.get("mountainous_extreme_precipitation") else nominal_by_region.get(region,0))
        td=2*(nominal/1000)*float(row.get("importance_factor") or 0)*min((z/10)**.1,1.4) if z>0 else 0
        area=math.pi*td*(float(row.get("circumscribed_diameter_m") or 0)+td)
        volume=area*float(row.get("exposed_length_m") or 0)
        weight=volume*.9*float(row.get("water_unit_weight_kn_m3") or 0)
        iced=float(row.get("circumscribed_diameter_m") or 0)+2*td
        response=row.get("support_structural_response") or {}
        note((f"ATMOSPHERIC ICE {row.get('component_id')} | TD={td:.5f}m | WEIGHT={weight:.5f}kN | "
              f"ICED D={iced:.5f}m | ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,ice_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    wind_zone_y=ice_y-len(ice_rows)*0.30
    for interface in (snapshot.get("rule_context") or {}).get("canonical_roof_wind_interfaces") or []:
        if len(interface.get("roof_polygon") or [])>=3:msp.add_lwpolyline(interface["roof_polygon"],close=True,dxfattribs={"layer":"RW-WIND-CANONICAL-ROOF"})
    wind_zones=(snapshot.get("rule_context") or {}).get("roof_cladding_wind_zones") or []
    for index,row in enumerate(wind_zones):
        response=row.get("cladding_structural_response") or {}
        if len(row.get("roof_polygon") or [])>=3:msp.add_lwpolyline(row["roof_polygon"],close=True,dxfattribs={"layer":"RW-WIND-ROOF"})
        for zone in row.get("wind_zone_polygons") or []:
            if len(zone.get("polygon") or [])>=3:msp.add_lwpolyline(zone["polygon"],close=True,dxfattribs={"layer":"RW-WIND-ZONE"})
        for attachment in row.get("rainwater_component_attachments") or []:
            if len(attachment.get("footprint_polygon") or [])>=3:msp.add_lwpolyline(attachment["footprint_polygon"],close=True,dxfattribs={"layer":"RW-WIND-ATTACHMENT"})
            if len(attachment.get("projected_profile_polygon") or [])>=3:msp.add_lwpolyline(attachment["projected_profile_polygon"],close=True,dxfattribs={"layer":"RW-WIND-PROFILE"})
        note((f"ROOF WIND ZONE {row.get('roof_area_id')} | FORM={row.get('roof_form')} | "
              f"SLOPE={row.get('roof_slope_degrees')}deg | EDGE={row.get('declared_edge_strip_width_m')}m | "
              f"PRESSURE={row.get('pressure_case_id')} | SUCTION={row.get('suction_case_id')} | "
              f"ATTACHMENTS={','.join(str(x.get('component_id'))+':Aproj='+str(x.get('effective_projected_area_m2'))+'m2:'+str(x.get('declared_support_force_kn'))+'kN' for x in row.get('rainwater_component_attachments') or [])} | "
              f"ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,wind_zone_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    net_wind_y=wind_zone_y-len(wind_zones)*0.30
    net_wind_rows=(snapshot.get("rule_context") or {}).get("rainwater_attachment_net_wind_pressures") or []
    for index,row in enumerate(net_wind_rows):
        response=row.get("support_structural_response") or {}
        for key,layer in (("selected_wind_zone_polygon","RW-WIND-ZONE"),("attachment_footprint_polygon","RW-WIND-ATTACHMENT"),("projected_profile_polygon","RW-WIND-PROFILE")):
            if len(row.get(key) or [])>=3:msp.add_lwpolyline(row[key],close=True,dxfattribs={"layer":layer})
        note((f"NET WIND {row.get('component_id')} | EXTERNAL={row.get('declared_external_pressure_kn_m2')}kPa | "
              f"INTERNAL={row.get('internal_pressure_kn_m2')}kPa | NET={row.get('declared_net_pressure_kn_m2')}kPa | "
              f"AREA={row.get('effective_projected_area_m2')}m2 | FORCE={row.get('declared_net_force_kn')}kN | "
              f"ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,net_wind_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    tank_wind_y=net_wind_y-len(net_wind_rows)*0.30
    tank_wind_rows=(snapshot.get("rule_context") or {}).get("rainwater_storage_tank_wind_loads") or []
    for index,row in enumerate(tank_wind_rows):
        response=row.get("support_structural_response") or {}
        note((f"RAINWATER TANK WIND {row.get('tank_id')} | SHAPE={row.get('tank_shape')} | "
              f"AREA={row.get('declared_projected_area_m2')}m2 | FORCE={row.get('declared_force_kn')}kN | "
              f"EXTERNAL={row.get('declared_external_pressure_kn_m2')}kPa | "
              f"INTERNAL={row.get('declared_internal_pressure_kn_m2')}kPa | "
              f"NET={row.get('declared_net_pressure_kn_m2')}kPa | ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,tank_wind_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    member_wind_y=tank_wind_y-len(tank_wind_rows)*0.30
    member_wind_rows=(snapshot.get("rule_context") or {}).get("rainwater_support_member_wind_loads") or []
    for index,row in enumerate(member_wind_rows):
        response=row.get("structural_response") or {}
        note((f"RAINWATER SUPPORT WIND {row.get('member_id')} | FN={row.get('declared_fn_kn')}kN | "
              f"FT={row.get('declared_ft_kn')}kN | ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,member_wind_y-index*.30),width=8.0,height=.13,layer="RW-SCHEDULE")
    canopy_y=member_wind_y-len(member_wind_rows)*0.30
    canopy_rows=(snapshot.get("rule_context") or {}).get("rainwater_canopy_wind_loads") or []
    for index,row in enumerate(canopy_rows):
        response=row.get("structural_response") or {}
        note((f"RAINWATER CANOPY WIND {row.get('canopy_id')} | TYPE={row.get('canopy_type')} | PHI={row.get('blockage_phi')} | "
              f"FORCE={row.get('declared_force_kn')}kN | PRESSURE={row.get('declared_pressure_kn_m2')}kPa | ANALYSIS={response.get('analysis_id')}"),
             (schedule_x,canopy_y-index*.30),width=8,height=.13,layer="RW-SCHEDULE")
    outdoor_y=canopy_y-len(canopy_rows)*0.30
    for index,row in enumerate((snapshot.get("rule_context") or {}).get("outdoor_rainwater_equipment_installations") or []):
        architecture=row.get("architecture_response") or {};anchorage=row.get("anchorage_response") or {}
        footprint=Polygon(row.get("equipment_footprint") or [])
        note((f"OUTDOOR RAIN EQUIPMENT {row.get('equipment_id')} | SPACE={row.get('space_type')} | "
              f"FOOTPRINT={footprint.area:.3f}m2 | ATTACHMENTS={len(row.get('attachment_points') or [])} | "
              f"ARCH={architecture.get('analysis_id')} | ANCHORAGE={anchorage.get('analysis_id')}"),
             (schedule_x,outdoor_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    removal_y=outdoor_y-len((snapshot.get("rule_context") or {}).get("outdoor_rainwater_equipment_installations") or [])*0.30
    for index,row in enumerate((snapshot.get("rule_context") or {}).get("rainwater_heavy_equipment_removal_routes") or []):
        path=LineString(row.get("selected_path") or [])
        segments=row.get("clearance_segments") or []
        min_width=min((float(segment.get("clear_width_m")) for segment in segments),default=0.0)
        min_height=min((float(segment.get("clear_height_m")) for segment in segments),default=0.0)
        corridor=Polygon(row.get("clearance_corridor_polygon") or [])
        swept=path.buffer(float(row.get("equipment_width_m")) / 2.0,cap_style=2,join_style=2)
        msp.add_lwpolyline(list(path.coords),dxfattribs={"layer":"RW-EQUIPMENT-REMOVAL"})
        msp.add_lwpolyline(list(corridor.exterior.coords),close=True,dxfattribs={"layer":"RW-EQUIPMENT-REMOVAL"})
        msp.add_lwpolyline(list(swept.exterior.coords),close=True,dxfattribs={"layer":"RW-EQUIPMENT-REMOVAL"})
        note((f"HEAVY EQUIPMENT REMOVAL {row.get('equipment_id')} | PATH={path.length:.3f}m | "
              f"EQUIPMENT={row.get('equipment_width_m')}x{row.get('equipment_height_m')}m | "
              f"MIN CONTINUOUS CLEAR={min_width}x{min_height}m | SWEPT={swept.area:.3f}m2"),
             (schedule_x,removal_y-index*0.30),width=8.0,height=0.13,layer="RW-SCHEDULE")
    buried=(snapshot.get("rule_context") or {}).get("buried_gravity_rainwater_segments") or []
    detail_y=structural_y-0.75-len(structural)*0.30
    if buried:
        note("TRENCH DETAIL | CONTINUOUS SHAPED SOFT BEDDING",(schedule_x,detail_y),
             width=7.0,height=0.18,layer="RW-DETAIL")
        msp.add_lwpolyline([(schedule_x,detail_y-0.35),(schedule_x+4,detail_y-0.35),
                            (schedule_x+3.5,detail_y-2.0),(schedule_x+0.5,detail_y-2.0)],
                           dxfattribs={"layer":"RW-DETAIL"})
        msp.add_circle((schedule_x+2,detail_y-1.35),radius=0.35,dxfattribs={"layer":"RW-DETAIL"})
        for index,row in enumerate(buried):
            note((f"{row.get('id')} | SOIL={row.get('soil_condition')} | LIFTS<={row.get('lift_mm')}mm | "
                  f"ROCK OVERCUT={row.get('rock_overcut_mm','NA')}mm | WEAK SOIL={row.get('weak_soil_overexcavation_diameters','NA')}D | "
                  f"INSPECT BEFORE COVER={row.get('inspection_before_covering')}"),
                 (schedule_x,detail_y-2.30-index*0.30),width=8.0,height=0.13,layer="RW-DETAIL")
    rule_evaluation = calculation.get("rule_evaluation") or {}
    note((f"RULEBOOK {rule_evaluation.get('module_version','UNKNOWN')} | "
          f"DEPENDENCY {str(rule_evaluation.get('dependency_identity','UNKNOWN'))[:16]} | "
          f"COMPLIANCE={rule_evaluation.get('status','INPUT_REQUIRED')} | RELEASE NOT AUTHORIZED"),
         (minimum_x + 0.20, minimum_y - 2.62), width=sheet_width - 0.4,
         height=0.14, layer="RW-RULE")
    blocking = [row for row in rule_evaluation.get("evaluations") or []
                if row.get("status") in {"FAIL", "INPUT_REQUIRED"}]
    for index, row in enumerate(blocking[:4]):
        note(f"{row.get('status')} | {row.get('rule_id')} | "
             f"{','.join((row.get('errors') or row.get('missing_inputs') or [])[:2])}",
             (minimum_x + 0.20, minimum_y - 2.90 - index * 0.27), width=sheet_width - 0.4,
             height=0.14, layer="RW-RULE")
    simulation = snapshot.get("simulation") or {}
    if simulation.get("scenario_type") == "SIMULATION_PREVIEW":
        note(SIMULATION_DISCLAIMER_FA,
             (minimum_x + 0.20, minimum_y - 2.28), width=sheet_width - 0.4,
             height=0.14, layer="RW-TITLE")
    stream = StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def _rainwater_plan_independent_qa(snapshot, calculation, content):
    """Reopen the exact DXF and reconcile source geometry and calculation IDs."""
    errors = []
    try:
        doc = ezdxf.read(StringIO(content.decode("utf-8")))
        msp = doc.modelspace()
    except Exception as exc:
        return {"status": "FAIL", "qa_version": QA_VERSIONS["MECH_ROOF_RAINWATER_PLAN"],
                "checks": {}, "errors": [f"DXF_REOPEN_FAILED:{type(exc).__name__}"]}
    roof_polylines = list(msp.query('LWPOLYLINE[layer=="RW-ROOF"]'))
    catchment_polylines = list(msp.query('LWPOLYLINE[layer=="RW-CATCHMENT"]'))
    drains = list(msp.query('CIRCLE[layer=="RW-DRAIN"]'))
    routes = list(msp.query('LWPOLYLINE[layer=="RW-PIPE"]'))
    stacks = list(msp.query('CIRCLE[layer=="RW-STACK"]'))
    slopes = list(msp.query('LWPOLYLINE[layer=="RW-SLOPE"]'))
    overflows = list(msp.query('CIRCLE[layer=="RW-OVERFLOW"]'))
    secondary_routes = list(msp.query('LWPOLYLINE[layer=="RW-SECONDARY"]'))
    secondary_discharges = list(msp.query('CIRCLE[layer=="RW-SECONDARY-DISCHARGE"]'))
    architecture_routes = list(msp.query('LWPOLYLINE[layer=="RW-ARCH-ROUTE-AUDIT"]'))
    parking_clearance_zones = list(msp.query('LWPOLYLINE[layer=="RW-PARKING-CLEARANCE-ZONE"]'))
    parking_clearance_routes = list(msp.query('LWPOLYLINE[layer=="RW-PARKING-CLEARANCE-ROUTE"]'))
    patio_ventilation_dependencies = list(msp.query('LWPOLYLINE[layer=="RW-ARCH-VENT-DEPENDENCY"]'))
    exterior_finish_polygons = list(msp.query('LWPOLYLINE[layer=="RW-EXTERIOR-FINISH"]'))
    light_air_conduit_polygons = list(msp.query('LWPOLYLINE[layer=="RW-LIGHT-AIR-CONDUIT-AUDIT"]'))
    parking_ramp_finish_polygons = list(msp.query('LWPOLYLINE[layer=="RW-PARKING-RAMP-FINISH"]'))
    pollution_routes = list(msp.query('LWPOLYLINE[layer=="RW-POLLUTION-AUDIT"]'))
    pollution_sources = list(msp.query('LWPOLYLINE[layer=="RW-POLLUTION-SOURCE"]'))
    site_projection_polygons = list(msp.query('LWPOLYLINE[layer=="RW-SITE-PROJECTION"]'))
    property_boundary_polygons = list(msp.query('LWPOLYLINE[layer=="RW-PROPERTY-BOUNDARY"]'))
    site_exclusion_polygons = list(msp.query('LWPOLYLINE[layer=="RW-SITE-EXCLUSION"]'))
    building_footprint_polygons = list(msp.query('LWPOLYLINE[layer=="RW-BUILDING-FOOTPRINT"]'))
    public_way_polygons = list(msp.query('LWPOLYLINE[layer=="RW-PUBLIC-WAY"]'))
    carriageway_edges = list(msp.query('LWPOLYLINE[layer=="RW-CARRIAGEWAY-EDGE"]'))
    light_air_guard_lines = list(msp.query('LWPOLYLINE[layer=="RW-LIGHT-AIR-GUARD-DEPENDENCY"]'))
    light_air_finish_polygons = list(msp.query('LWPOLYLINE[layer=="RW-LIGHT-AIR-FINISH-DEPENDENCY"]'))
    under_open_parking_polygons = list(msp.query('LWPOLYLINE[layer=="RW-UNDER-OPEN-PARKING-DEPENDENCY"]'))
    canonical_wind_roof_polygons = list(msp.query('LWPOLYLINE[layer=="RW-WIND-CANONICAL-ROOF"]'))
    wind_roof_polygons = list(msp.query('LWPOLYLINE[layer=="RW-WIND-ROOF"]'))
    wind_zone_polygons = list(msp.query('LWPOLYLINE[layer=="RW-WIND-ZONE"]'))
    wind_attachment_polygons = list(msp.query('LWPOLYLINE[layer=="RW-WIND-ATTACHMENT"]'))
    wind_profile_polygons = list(msp.query('LWPOLYLINE[layer=="RW-WIND-PROFILE"]'))
    title_blocks = list(msp.query('LWPOLYLINE[layer=="RW-SHEET"]'))
    annotations = ([entity.dxf.text for entity in msp.query('TEXT[layer=="RW-ANNOTATION"]')]
                   + [entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-ANNOTATION"]')])
    titles = ([entity.dxf.text for entity in msp.query('TEXT[layer=="RW-TITLE"]')]
              + [entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-TITLE"]')])
    rule_annotations = ([entity.dxf.text for entity in msp.query('TEXT[layer=="RW-RULE"]')]
                        + [entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-RULE"]')])
    schedule_annotations = [entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-SCHEDULE"]')]
    detail_annotations = [entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-DETAIL"]')]
    source_catchments = snapshot.get("roof", {}).get("catchments") or []
    if len(roof_polylines) != 1 or not roof_polylines[0].closed:
        errors.append("ROOF_BOUNDARY_NOT_EXACTLY_ONE_CLOSED_POLYLINE")
    else:
        actual = [(round(point[0], 9), round(point[1], 9)) for point in roof_polylines[0].get_points("xy")]
        expected = [(round(float(point[0]), 9), round(float(point[1]), 9))
                    for point in snapshot.get("roof", {}).get("boundary") or []]
        if actual != expected:
            errors.append("ROOF_BOUNDARY_SOURCE_MISMATCH")
    expected_count = len(source_catchments)
    expected_stack_count = len({str(row.get("stack_id")) for row in source_catchments})
    if (len(catchment_polylines), len(drains), len(routes), len(slopes), len(overflows)) != (
            expected_count,) * 5 or len(stacks) != expected_stack_count:
        errors.append("PLAN_ENTITY_COUNT_MISMATCH")
    def points(entity):
        return [(round(float(point[0]), 9), round(float(point[1]), 9))
                for point in entity.get_points("xy")]
    ordered_source = sorted(source_catchments, key=lambda row: str(row.get("id")))
    for index, source in enumerate(ordered_source):
        if index >= min(len(catchment_polylines), len(drains), len(routes), len(slopes), len(overflows)):
            break
        expected_polygon = [(round(float(point[0]), 9), round(float(point[1]), 9))
                            for point in source.get("polygon") or []]
        expected_route = [(round(float(point[0]), 9), round(float(point[1]), 9))
                          for point in source.get("route") or []]
        expected_drain = tuple(round(float(value), 9) for value in (source.get("drain") or {}).get("point") or [])
        expected_overflow = tuple(round(float(value), 9) for value in
                                  (source.get("emergency_overflow") or {}).get("point") or [])
        centroid = (round(sum(point[0] for point in expected_polygon) / len(expected_polygon), 9),
                    round(sum(point[1] for point in expected_polygon) / len(expected_polygon), 9))
        if points(catchment_polylines[index]) != expected_polygon:
            errors.append(f"CATCHMENT_SOURCE_MISMATCH:{source.get('id')}")
        center = drains[index].dxf.center
        actual_drain = (round(float(center.x), 9), round(float(center.y), 9))
        if actual_drain != expected_drain:
            errors.append(f"DRAIN_SOURCE_MISMATCH:{source.get('id')}")
        if points(routes[index]) != expected_route:
            errors.append(f"ROUTE_SOURCE_MISMATCH:{source.get('id')}")
        if points(slopes[index]) != [centroid, expected_drain]:
            errors.append(f"SLOPE_SOURCE_MISMATCH:{source.get('id')}")
        center = overflows[index].dxf.center
        actual_overflow = (round(float(center.x), 9), round(float(center.y), 9))
        if actual_overflow != expected_overflow:
            errors.append(f"OVERFLOW_SOURCE_MISMATCH:{source.get('id')}")
    expected_stacks = sorted((str(row.get("id")), tuple(round(float(value), 9)
                              for value in row.get("point") or []))
                             for row in snapshot.get("roof", {}).get("stacks") or []
                             if str(row.get("id")) in {str(item.get("stack_id")) for item in source_catchments})
    actual_stacks = sorted((round(float(entity.dxf.center.x), 9),
                            round(float(entity.dxf.center.y), 9)) for entity in stacks)
    if sorted(point for _identifier, point in expected_stacks) != actual_stacks:
        errors.append("STACK_SOURCE_MISMATCH")
    secondary = snapshot.get("roof", {}).get("secondary_network") or {}
    if len(secondary_routes) != len(secondary.get("routes") or []):
        errors.append("SECONDARY_ROUTE_COUNT_MISMATCH")
    if len(secondary_discharges) != len(secondary.get("discharge_points") or []):
        errors.append("SECONDARY_DISCHARGE_COUNT_MISMATCH")
    for index, source in enumerate(secondary.get("routes") or []):
        if index < len(secondary_routes):
            expected = [(round(float(point[0]), 9), round(float(point[1]), 9))
                        for point in source.get("points") or []]
            if points(secondary_routes[index]) != expected:
                errors.append(f"SECONDARY_ROUTE_SOURCE_MISMATCH:{index}")
    rule_evaluation = calculation.get("rule_evaluation") or {}
    if not any("RULEBOOK" in value and str(rule_evaluation.get("module_version")) in value
               for value in rule_annotations):
        errors.append("RULEBOOK_IDENTITY_ANNOTATION_MISSING")
    for row in rule_evaluation.get("evaluations") or []:
        if row.get("status") in {"FAIL", "INPUT_REQUIRED"} and not any(
                str(row.get("rule_id")) in value for value in rule_annotations):
            if row not in [item for item in rule_evaluation.get("evaluations") or []
                           if item.get("status") in {"FAIL", "INPUT_REQUIRED"}][:4]:
                continue
            errors.append(f"RULE_STATUS_ANNOTATION_MISSING:{row.get('rule_id')}")
    calc_ids = {str(row.get("calc_id")) for row in calculation.get("catchments") or []}
    for calc_id in calc_ids:
        if not any(calc_id in label for label in annotations):
            errors.append(f"CALCULATION_LINK_MISSING:{calc_id}")
    for row in calculation.get("catchments") or []:
        if not any(str(row.get("catchment_id")) in label and
                   f"Aeff={row.get('effective_area_m2')}" in label for label in schedule_annotations):
            errors.append(f"HYDRAULIC_SCHEDULE_MISSING:{row.get('catchment_id')}")
    components=(snapshot.get("rule_context") or {}).get("rainwater_components") or []
    for row in components:
        certificate=(row.get("certificate") or {}).get("id")
        if certificate and not any(str(certificate) in label for label in schedule_annotations):
            errors.append(f"MATERIAL_CERTIFICATE_SCHEDULE_MISSING:{certificate}")
    destinations=(snapshot.get("rule_context") or {}).get("rainwater_discharge_destinations") or []
    for row in destinations:
        if not any(str(row.get("id")) in label and str(row.get("destination_type")) in label
                   for label in schedule_annotations):
            errors.append(f"DISCHARGE_DESTINATION_SCHEDULE_MISSING:{row.get('id')}")
    pollution_rows=(snapshot.get("rule_context") or {}).get("rainwater_pollution_prevention_interfaces") or []
    if len(pollution_routes)!=len(pollution_rows):errors.append("POLLUTION_ROUTE_COUNT_MISMATCH")
    if len(pollution_sources)!=sum(len(row.get("waste_or_sewage_source_polygons") or []) for row in pollution_rows):errors.append("POLLUTION_SOURCE_COUNT_MISMATCH")
    expected_pollution_routes=[[tuple(round(float(value),9) for value in point[:2]) for point in row.get("rainwater_route_points") or []] for row in pollution_rows]
    expected_pollution_sources=[[tuple(round(float(value),9) for value in point[:2]) for point in polygon] for row in pollution_rows for polygon in row.get("waste_or_sewage_source_polygons") or []]
    if [points(entity) for entity in pollution_routes]!=expected_pollution_routes:errors.append("POLLUTION_ROUTE_GEOMETRY_MISMATCH")
    if [points(entity) for entity in pollution_sources]!=expected_pollution_sources:errors.append("POLLUTION_SOURCE_GEOMETRY_MISMATCH")
    pollution_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-POLLUTION-AUDIT"]')]
    for row in pollution_rows:
        response=row.get("environmental_health_response") or {}
        if not any(str(row.get("interface_id")) in label and str(response.get("response_id")) in label for label in pollution_labels):errors.append(f"POLLUTION_SCHEDULE_MISSING:{row.get('interface_id')}")
    site_rows=(snapshot.get("rule_context") or {}).get("rainwater_site_projection_interfaces") or []
    if len(site_projection_polygons)!=len(site_rows):errors.append("SITE_PROJECTION_COUNT_MISMATCH")
    if len(property_boundary_polygons)!=sum(1 for row in site_rows if row.get("property_polygon")):errors.append("PROPERTY_BOUNDARY_COUNT_MISMATCH")
    expected_site=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in (row.get("component_polygon") if row.get("interface_kind")=="BURIED_COMPONENT_PROPERTY_BOUNDARY" else row.get("projection_polygon")) or []] for row in site_rows]
    expected_property=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in row.get("property_polygon") or []] for row in site_rows if row.get("property_polygon")]
    expected_exclusions=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in polygon] for row in site_rows for polygon in (row.get("light_vent_patio_polygons") or [])+(row.get("power_line_corridor_polygons") or [])]
    expected_building=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in row.get("building_footprint_polygon") or []] for row in site_rows if row.get("building_footprint_polygon")]
    expected_ways=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in polygon] for row in site_rows for polygon in ((row.get("public_way_polygons") or [])+([row["public_way_polygon"]] if row.get("public_way_polygon") else []))]
    expected_edges=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in row.get("carriageway_edge_line") or []] for row in site_rows if row.get("carriageway_edge_line")]
    if [points(entity) for entity in site_projection_polygons]!=expected_site:errors.append("SITE_PROJECTION_GEOMETRY_MISMATCH")
    if [points(entity) for entity in property_boundary_polygons]!=expected_property:errors.append("PROPERTY_BOUNDARY_GEOMETRY_MISMATCH")
    if [points(entity) for entity in site_exclusion_polygons]!=expected_exclusions:errors.append("SITE_EXCLUSION_GEOMETRY_MISMATCH")
    if [points(entity) for entity in building_footprint_polygons]!=expected_building:errors.append("BUILDING_FOOTPRINT_GEOMETRY_MISMATCH")
    if [points(entity) for entity in public_way_polygons]!=expected_ways:errors.append("PUBLIC_WAY_GEOMETRY_MISMATCH")
    if [points(entity) for entity in carriageway_edges]!=expected_edges:errors.append("CARRIAGEWAY_EDGE_GEOMETRY_MISMATCH")
    site_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-SITE-PROJECTION"]')]
    for row in site_rows:
        if not any(str(row.get("interface_id")) in label for label in site_labels):errors.append(f"SITE_PROJECTION_SCHEDULE_MISSING:{row.get('interface_id')}")
    structural=(snapshot.get("rule_context") or {}).get("structural_rainwater_loads") or []
    for row in structural:
        if not any(str(row.get("component_id")) in label and
                   str(row.get("support_reaction_id")) in label for label in schedule_annotations):
            errors.append(f"STRUCTURAL_LOAD_SCHEDULE_MISSING:{row.get('component_id')}")
    for row in (snapshot.get("rule_context") or {}).get("roof_material_volumetric_loads") or []:
        if not any(f"ROOF MATERIAL LOAD {row.get('component_id')}" in label and
                   str((row.get("structural_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"ROOF_MATERIAL_LOAD_SCHEDULE_MISSING:{row.get('component_id')}")
    for row in (snapshot.get("rule_context") or {}).get("roof_covering_surface_loads") or []:
        if not any(f"ROOF COVERING LOAD {row.get('component_id')}" in label and
                   str((row.get("official_unit_interpretation") or {}).get("interpretation_id")) in label
                   for label in schedule_annotations):
            errors.append(f"ROOF_COVERING_LOAD_SCHEDULE_MISSING:{row.get('component_id')}")
    for row in (snapshot.get("rule_context") or {}).get("vertical_rainwater_drift_interfaces") or []:
        if not any(f"RAINWATER DRIFT {row.get('interface_id')}" in label and
                   str((row.get("structural_drift_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"RAINWATER_DRIFT_SCHEDULE_MISSING:{row.get('interface_id')}")
    for row in (snapshot.get("rule_context") or {}).get("exposed_rainwater_pipe_wind_loads") or []:
        if not any(f"EXPOSED PIPE WIND {row.get('pipe_id')}" in label and
                   str((row.get("support_structural_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"EXPOSED_PIPE_WIND_SCHEDULE_MISSING:{row.get('pipe_id')}")
        if row.get("vortex_shedding_applicable") is True and row.get("declared_vortex_negligible") is False:
            dynamic_id=(row.get("vortex_dynamic_response") or {}).get("analysis_id")
            if not any(f"EXPOSED PIPE WIND {row.get('pipe_id')}" in label and str(dynamic_id) in label
                       for label in schedule_annotations):
                errors.append(f"EXPOSED_PIPE_VORTEX_SCHEDULE_MISSING:{row.get('pipe_id')}")
    for row in (snapshot.get("rule_context") or {}).get("atmospheric_ice_rainwater_components") or []:
        if not any(f"ATMOSPHERIC ICE {row.get('component_id')}" in label and
                   str((row.get("support_structural_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"ATMOSPHERIC_ICE_SCHEDULE_MISSING:{row.get('component_id')}")
    for row in (snapshot.get("rule_context") or {}).get("roof_cladding_wind_zones") or []:
        if not any(f"ROOF WIND ZONE {row.get('roof_area_id')}" in label and
                   str((row.get("cladding_structural_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"ROOF_WIND_ZONE_SCHEDULE_MISSING:{row.get('roof_area_id')}")
    wind_rows=(snapshot.get("rule_context") or {}).get("roof_cladding_wind_zones") or []
    net_wind_rows=(snapshot.get("rule_context") or {}).get("rainwater_attachment_net_wind_pressures") or []
    expected_wind_roofs=[[tuple(round(float(value),9) for value in point[:2]) for point in row.get("roof_polygon") or []] for row in wind_rows]
    expected_canonical_wind_roofs=[[tuple(round(float(value),9) for value in point[:2]) for point in row.get("roof_polygon") or []] for row in (snapshot.get("rule_context") or {}).get("canonical_roof_wind_interfaces") or []]
    expected_wind_zones=[[tuple(round(float(value),9) for value in point[:2]) for point in zone.get("polygon") or []] for row in wind_rows for zone in row.get("wind_zone_polygons") or []]
    expected_wind_zones += [[tuple(round(float(value),9) for value in point[:2]) for point in row.get("selected_wind_zone_polygon") or []] for row in net_wind_rows]
    expected_wind_attachments=[[tuple(round(float(value),9) for value in point[:2]) for point in attachment.get("footprint_polygon") or []] for row in wind_rows for attachment in row.get("rainwater_component_attachments") or []]
    expected_wind_attachments += [[tuple(round(float(value),9) for value in point[:2]) for point in row.get("attachment_footprint_polygon") or []] for row in net_wind_rows]
    expected_wind_profiles=[[tuple(round(float(value),9) for value in point[:2]) for point in attachment.get("projected_profile_polygon") or []] for row in wind_rows for attachment in row.get("rainwater_component_attachments") or []]
    expected_wind_profiles += [[tuple(round(float(value),9) for value in point[:2]) for point in row.get("projected_profile_polygon") or []] for row in net_wind_rows]
    if [points(entity) for entity in canonical_wind_roof_polygons]!=expected_canonical_wind_roofs:errors.append("WIND_CANONICAL_ROOF_GEOMETRY_MISMATCH")
    if [points(entity) for entity in wind_roof_polygons]!=expected_wind_roofs:errors.append("WIND_ROOF_GEOMETRY_MISMATCH")
    if [points(entity) for entity in wind_zone_polygons]!=expected_wind_zones:errors.append("WIND_ZONE_GEOMETRY_MISMATCH")
    if [points(entity) for entity in wind_attachment_polygons]!=expected_wind_attachments:errors.append("WIND_ATTACHMENT_GEOMETRY_MISMATCH")
    if [points(entity) for entity in wind_profile_polygons]!=expected_wind_profiles:errors.append("WIND_PROFILE_GEOMETRY_MISMATCH")
    for row in (snapshot.get("rule_context") or {}).get("rainwater_attachment_net_wind_pressures") or []:
        if not any(f"NET WIND {row.get('component_id')}" in label and
                   str((row.get("support_structural_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"NET_WIND_SCHEDULE_MISSING:{row.get('component_id')}")
    for row in (snapshot.get("rule_context") or {}).get("rainwater_storage_tank_wind_loads") or []:
        if not any(f"RAINWATER TANK WIND {row.get('tank_id')}" in label and
                   str((row.get("support_structural_response") or {}).get("analysis_id")) in label and
                   str(row.get("declared_net_pressure_kn_m2")) in label
                   for label in schedule_annotations):
            errors.append(f"RAINWATER_TANK_WIND_SCHEDULE_MISSING:{row.get('tank_id')}")
    for row in (snapshot.get("rule_context") or {}).get("rainwater_support_member_wind_loads") or []:
        if not any(f"RAINWATER SUPPORT WIND {row.get('member_id')}" in label and
                   str((row.get("structural_response") or {}).get("analysis_id")) in label
                   for label in schedule_annotations):
            errors.append(f"RAINWATER_SUPPORT_WIND_SCHEDULE_MISSING:{row.get('member_id')}")
    for row in (snapshot.get("rule_context") or {}).get("rainwater_canopy_wind_loads") or []:
        if not any(f"RAINWATER CANOPY WIND {row.get('canopy_id')}" in label and str((row.get("structural_response") or {}).get("analysis_id")) in label for label in schedule_annotations):
            errors.append(f"RAINWATER_CANOPY_WIND_SCHEDULE_MISSING:{row.get('canopy_id')}")
    buried=(snapshot.get("rule_context") or {}).get("buried_gravity_rainwater_segments") or []
    if buried and (not detail_annotations or not list(msp.query('CIRCLE[layer=="RW-DETAIL"]'))):
        errors.append("TRENCH_DETAIL_MISSING")
    expected_architecture_routes=[]
    for row in (snapshot.get("rule_context") or {}).get("rainwater_route_entities") or []:
        route=row.get("rerouted_route_points") if row.get("rerouted_route_id") else row.get("route_points")
        if route:expected_architecture_routes.append([(round(float(x),9),round(float(y),9)) for x,y in route])
    actual_architecture_routes=[points(entity) for entity in architecture_routes]
    if actual_architecture_routes != expected_architecture_routes:
        errors.append("ARCHITECTURE_ROUTE_GEOMETRY_MISMATCH")
    clearance_rows=(snapshot.get("rule_context") or {}).get("parking_service_clearance_routes") or []
    expected_zones=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("parking_polygon") or []]
                    for row in clearance_rows]
    expected_clearance_routes=[]
    for row in clearance_rows:
        route=(row.get("reroute_bottom_envelope_points") if row.get("selected_route")=="REROUTE"
               else row.get("bottom_envelope_points")) or []
        expected_clearance_routes.append([(round(float(point[0]),9),round(float(point[1]),9)) for point in route])
    if [points(entity) for entity in parking_clearance_zones]!=expected_zones:
        errors.append("PARKING_CLEARANCE_ZONE_GEOMETRY_MISMATCH")
    if [points(entity) for entity in parking_clearance_routes]!=expected_clearance_routes:
        errors.append("PARKING_CLEARANCE_ROUTE_GEOMETRY_MISMATCH")
    clearance_labels=[entity.dxf.text for entity in msp.query('TEXT[layer=="RW-PARKING-CLEARANCE-ROUTE"]')]
    for row in clearance_rows:
        route=(row.get("reroute_bottom_envelope_points") if row.get("selected_route")=="REROUTE"
               else row.get("bottom_envelope_points")) or []
        for index,point in enumerate(route):
            token=f"{row.get('route_id')}:{index} ZBOTTOM={float(point[2]):.3f}m"
            if token not in clearance_labels:errors.append(f"PARKING_CLEARANCE_Z_EVIDENCE_MISSING:{row.get('route_id')}:{index}")
    patio_rows=(snapshot.get("rule_context") or {}).get("covered_patio_natural_ventilation_reviews") or []
    expected_patios=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("patio_polygon") or []] for row in patio_rows]
    if [points(entity) for entity in patio_ventilation_dependencies]!=expected_patios:
        errors.append("PATIO_VENTILATION_DEPENDENCY_GEOMETRY_MISMATCH")
    patio_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-ARCH-VENT-DEPENDENCY"]')]
    for row in patio_rows:
        analysis=row.get("ventilation_analysis") or {}
        if not any(str(row.get("patio_id")) in label and str(analysis.get("analysis_id")) in label and
                   "DID NOT PERFORM VENTILATION ANALYSIS" in label for label in patio_labels):
            errors.append(f"PATIO_VENTILATION_DEPENDENCY_ANNOTATION_MISSING:{row.get('patio_id')}")
    finish_rows=(snapshot.get("rule_context") or {}).get("exterior_intermediary_element_finishes") or []
    expected_finishes=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("element_polygon") or []] for row in finish_rows]
    if [points(entity) for entity in exterior_finish_polygons]!=expected_finishes:
        errors.append("EXTERIOR_FINISH_GEOMETRY_MISMATCH")
    finish_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-EXTERIOR-FINISH"]')]
    for row in finish_rows:
        finish=row.get("selected_finish") or {};approval=finish.get("product_approval") or {}
        if not any(str(row.get("element_id")) in label and str(finish.get("product_identity")) in label and
                   str(approval.get("approval_id")) in label for label in finish_labels):
            errors.append(f"EXTERIOR_FINISH_SCHEDULE_MISSING:{row.get('element_id')}")
    conduit_rows=(snapshot.get("rule_context") or {}).get("external_light_air_conduit_route_inventories") or []
    expected_conduits=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("conduit_polygon") or []] for row in conduit_rows]
    if [points(entity) for entity in light_air_conduit_polygons]!=expected_conduits:
        errors.append("LIGHT_AIR_CONDUIT_GEOMETRY_MISMATCH")
    conduit_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-LIGHT-AIR-CONDUIT-AUDIT"]')]
    for row in conduit_rows:
        if not any(str(row.get("conduit_id")) in label and str(row.get("service_route_inventory_sha256")) in label for label in conduit_labels):
            errors.append(f"LIGHT_AIR_CONDUIT_AUDIT_MISSING:{row.get('conduit_id')}")
    ramp_finish_rows=(snapshot.get("rule_context") or {}).get("parking_ramp_surface_finishes") or []
    expected_ramp_finishes=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("ramp_polygon") or []] for row in ramp_finish_rows]
    if [points(entity) for entity in parking_ramp_finish_polygons]!=expected_ramp_finishes:
        errors.append("PARKING_RAMP_FINISH_GEOMETRY_MISMATCH")
    ramp_finish_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-PARKING-RAMP-FINISH"]')]
    for row in ramp_finish_rows:
        surface=row.get("selected_surface") or {};test=surface.get("wet_slip_test") or {}
        if not any(str(row.get("ramp_id")) in label and str(surface.get("product_identity")) in label and str(test.get("report_id")) in label for label in ramp_finish_labels):
            errors.append(f"PARKING_RAMP_FINISH_SCHEDULE_MISSING:{row.get('ramp_id')}")
    guard_rows=(snapshot.get("rule_context") or {}).get("external_light_air_conduit_traffic_guards") or []
    expected_guard_lines=[[(round(float(point[0]),9),round(float(point[1]),9)) for point in row.get("top_surface_elevation_points") or []] for row in guard_rows]
    if [points(entity) for entity in light_air_guard_lines]!=expected_guard_lines:errors.append("LIGHT_AIR_GUARD_GEOMETRY_MISMATCH")
    guard_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-LIGHT-AIR-GUARD-DEPENDENCY"]')]
    for row in guard_rows:
        structural=row.get("structural_guard_analysis") or {};access=row.get("accessibility_review") or {}
        if not any(str(row.get("conduit_id")) in label and str(structural.get("analysis_id")) in label and str(access.get("review_id")) in label and "DID NOT PERFORM" in label for label in guard_labels):
            errors.append(f"LIGHT_AIR_GUARD_DEPENDENCY_ANNOTATION_MISSING:{row.get('conduit_id')}")
    semi_finish_rows=(snapshot.get("rule_context") or {}).get("external_light_air_conduit_semi_open_finish_reviews") or []
    expected_semi_finishes=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("floor_polygon") or []] for row in semi_finish_rows]
    if [points(entity) for entity in light_air_finish_polygons]!=expected_semi_finishes:errors.append("LIGHT_AIR_FINISH_GEOMETRY_MISMATCH")
    semi_finish_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-LIGHT-AIR-FINISH-DEPENDENCY"]')]
    for row in semi_finish_rows:
        review=row.get("semi_open_finish_review") or {}
        if not any(str(row.get("conduit_id")) in label and str(review.get("review_id")) in label and "DID NOT PERFORM" in label for label in semi_finish_labels):
            errors.append(f"LIGHT_AIR_FINISH_DEPENDENCY_ANNOTATION_MISSING:{row.get('conduit_id')}")
    under_open_rows=(snapshot.get("rule_context") or {}).get("under_open_space_parking_reviews") or []
    expected_under_open=[[(round(float(x),9),round(float(y),9)) for x,y in row.get("parking_footprint_polygon") or []] for row in under_open_rows]
    if [points(entity) for entity in under_open_parking_polygons]!=expected_under_open:errors.append("UNDER_OPEN_PARKING_GEOMETRY_MISMATCH")
    under_open_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-UNDER-OPEN-PARKING-DEPENDENCY"]')]
    for row in under_open_rows:
        if not any(str(row.get("parking_id")) in label and "DOES NOT GRANT PERMISSION" in label for label in under_open_labels):errors.append(f"UNDER_OPEN_PARKING_DEPENDENCY_ANNOTATION_MISSING:{row.get('parking_id')}")
    strategy_rows=(snapshot.get("rule_context") or {}).get("basement_parking_light_ventilation_strategies") or []
    strategy_labels=[entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-BASEMENT-PARKING-DEPENDENCY"]')]
    for row in strategy_rows:
        if not any(str(row.get("parking_id")) in label and str(row.get("selected_strategy")) in label and "NOT PERFORMED" in label for label in strategy_labels):errors.append(f"BASEMENT_PARKING_DEPENDENCY_ANNOTATION_MISSING:{row.get('parking_id')}")
    if int(doc.header.get("$INSUNITS", 0)) != 6:
        errors.append("DRAWING_UNITS_NOT_METRES")
    title_text = " ".join(titles)
    for token in ("DRAFT", "MODEL 1:1", "PLOT NTS", "UNITS m", "LEGEND:"):
        if token not in title_text:
            errors.append(f"DRAWING_PRESENTATION_MISSING:{token}")
    simulation = snapshot.get("simulation") or {}
    if simulation.get("scenario_type") == "SIMULATION_PREVIEW":
        if SIMULATION_DISCLAIMER_FA not in title_text:
            errors.append("SIMULATION_DISCLAIMER_MISSING")
    if len(title_blocks) != 1 or not title_blocks[0].closed:
        errors.append("TITLE_BLOCK_INVALID")
    return {
        "status": "PASS" if not errors else "FAIL",
        "qa_version": QA_VERSIONS["MECH_ROOF_RAINWATER_PLAN"],
        "checks": {"exact_file_reopened": True, "roof_boundary_reconciled": not any(
            error == "ROOF_BOUNDARY_SOURCE_MISMATCH" for error in errors),
            "calculation_identity_linked": not any(error.startswith("CALCULATION_LINK_MISSING") for error in errors),
            "source_geometry_reconciled": not any("SOURCE_MISMATCH" in error for error in errors),
            "drawing_presentation_complete": not any(error.startswith("DRAWING_PRESENTATION") or
                                                       error == "TITLE_BLOCK_INVALID" for error in errors),
            "rulebook_identity_present": "RULEBOOK_IDENTITY_ANNOTATION_MISSING" not in errors,
            "hydraulic_schedule_reconciled": not any(error.startswith("HYDRAULIC_SCHEDULE") for error in errors),
            "material_schedule_reconciled": not any(error.startswith("MATERIAL_CERTIFICATE_SCHEDULE") for error in errors),
            "discharge_schedule_reconciled": not any(error.startswith("DISCHARGE_DESTINATION_SCHEDULE") for error in errors),
            "structural_load_schedule_reconciled": not any(error.startswith("STRUCTURAL_LOAD_SCHEDULE") for error in errors),
            "trench_detail_reconciled": "TRENCH_DETAIL_MISSING" not in errors,
            "secondary_network_reconciled": not any(error.startswith("SECONDARY_") for error in errors),
            "architecture_route_geometry_reconciled": "ARCHITECTURE_ROUTE_GEOMETRY_MISMATCH" not in errors,
            "parking_clearance_geometry_reconciled": not any(error.startswith("PARKING_CLEARANCE_") for error in errors),
            "patio_ventilation_dependency_reconciled": not any(error.startswith("PATIO_VENTILATION_") for error in errors),
            "exterior_finish_reconciled": not any(error.startswith("EXTERIOR_FINISH_") for error in errors),
            "light_air_conduit_reconciled": not any(error.startswith("LIGHT_AIR_CONDUIT_") for error in errors),
            "parking_ramp_finish_reconciled": not any(error.startswith("PARKING_RAMP_FINISH_") for error in errors),
            "light_air_guard_dependency_reconciled": not any(error.startswith("LIGHT_AIR_GUARD_") for error in errors),
            "light_air_finish_dependency_reconciled": not any(error.startswith("LIGHT_AIR_FINISH_") for error in errors),
            "under_open_parking_dependency_reconciled": not any(error.startswith("UNDER_OPEN_PARKING_") for error in errors),
            "basement_parking_dependency_reconciled": not any(error.startswith("BASEMENT_PARKING_") for error in errors),
            "release_level": "DRAFT"},
        "errors": errors,
    }


def _execute_system_package(deliverable_type, snapshot):
    """Run one filtered mechanical family through the canonical CAD runtime.

    The independent worker owns retry/version/publication.  The canonical engine
    still owns engineering calculations and exact-file QA; this adapter merely
    supplies an isolated approved DRAFT manifest and returns its ZIP bytes.
    """
    definition = SYSTEM_PACKAGES[deliverable_type]
    answers = deepcopy(snapshot.get("answers") or {})
    def supplied_number(*keys):
        for key in keys:
            value = answers.get(key)
            try:
                if isinstance(value,str):
                    match=re.search(r"[-+]?\d+(?:[.,]\d+)?",value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789")))
                    value=match.group(0).replace(",",".") if match else None
                if value not in (None, "", []) and math.isfinite(float(value)):
                    return True
            except (TypeError, ValueError):
                continue
        return False
    input_provenance = dict(answers.get("_engineering_input_provenance") or {})
    plan_analysis = deepcopy(snapshot.get("plan_analysis") or {})
    fixture_rows = list(((plan_analysis.get("architectural_auto") or {})
                         .get("fixture_detections") or []))
    design_overlay = dict(snapshot.get("draft_design_overlay") or
                          plan_analysis.get("draft_design_overlay") or {})
    engineering_basis = dict(design_overlay.get("engineering_basis") or {})
    fixture_rows.extend(row for row in design_overlay.get("fixture_endpoints") or []
                        if isinstance(row, dict))
    plumbing_kinds = {"wc", "toilet", "basin", "sink", "shower", "floor_drain", "bath"}
    wet_room_types = {"bathroom", "toilet", "wc", "kitchen", "laundry", "wet_room"}
    has_source_bound_plumbing = any(
        isinstance(row, dict)
        and str(row.get("type") or row.get("kind") or "").lower() in plumbing_kinds
        and (row.get("point") or (row.get("x") is not None and row.get("y") is not None))
        and (row.get("wet_core_id") or str(row.get("room_type") or "").lower() in wet_room_types
             or (row.get("authority") == "MODEL_PROPOSED_DESIGN_ASSUMPTION"
                 and row.get("release_allowed") is False and row.get("room_id")))
        and str(row.get("source_sha256") or "") == str(snapshot.get("source_sha256") or "")
        for row in fixture_rows)
    def traceable_load(key):
        record = dict(input_provenance.get(key) or {})
        basis_name = {"heating_load_kw": "heating_design_basis",
                      "cooling_load_kw": "cooling_design_basis"}.get(key)
        basis = dict(engineering_basis.get(basis_name) or {}) if basis_name else {}
        if (not record and basis.get("authority") == "OWNER_DECLARED_PROJECT_FACT"
                and basis.get(key) == answers.get(key)):
            record = {"authority": "OWNER_DECLARED_PROJECT_FACT",
                      "source_sha256": snapshot.get("source_sha256")}
        return (supplied_number(key) and record.get("authority") in {
            "USER_CONFIRMED", "ENGINEERING_CALCULATION", "SOURCE_DOCUMENT",
            "MODEL_PROPOSED_DRAFT_CALCULATION", "OWNER_DECLARED_PROJECT_FACT",
        } and (not record.get("source_sha256") or record.get("source_sha256") == snapshot.get("source_sha256")))
    preflight = {
        "MECH_WATER_SUPPLY_PACKAGE": {
            "water_pressure_basis": supplied_number("water_inlet_pressure", "water_pressure"),
            "fixture_schedule": (bool(str(answers.get("fixture_schedule") or "").strip())
                                 and has_source_bound_plumbing),
        },
        "MECH_SANITARY_VENT_PACKAGE": {
            "fixture_schedule": (bool(str(answers.get("fixture_schedule") or "").strip())
                                 and has_source_bound_plumbing),
            "shaft_coordination": bool(str(answers.get("mechanical_shaft_route") or "").strip()),
        },
        "MECH_HEATING_PACKAGE": {
            "heating_basis": bool(str(answers.get("heating_system") or "").strip()),
            "heating_loads": traceable_load("heating_load_kw"),
        },
        "MECH_COOLING_PACKAGE": {
            "cooling_basis": bool(str(answers.get("cooling_system") or "").strip()),
            "cooling_loads": traceable_load("cooling_load_kw"),
        },
        "MECH_GAS_PACKAGE": {
            "gas_pressure_basis": supplied_number("gas_pressure", "gas_service_pressure"),
            "gas_appliance_loads": supplied_number("gas_appliance_load_kw", "gas_appliance_load_m3_h"),
        },
        "MECH_VENTILATION_PACKAGE": {
            "ventilation_basis": bool(str(answers.get("ventilation_design_basis") or "").strip()),
            "airflow_loads": supplied_number("ventilation_airflow_lps", "ventilation_airflow_m3_h"),
        },
    }[deliverable_type]
    missing = [key for key, present in preflight.items() if not present]
    if missing:
        return {"status":"FAILED", "errors":["INPUT_REQUIRED:" + key for key in missing],
                "detail":{"stage":"independent_system_input_preflight", "missing_inputs":missing}}
    provisional = dict(snapshot.get("provisional_architecture") or {})
    if (provisional.get("status") != "PROVISIONAL_READY"
            or provisional.get("draft_engineering_allowed") is not True
            or provisional.get("release_allowed") is not False):
        return {"status":"FAILED", "errors":["DRAFT_ARCHITECTURE_CONTRACT_INVALID"]}
    source_sha = str(snapshot.get("source_sha256") or "")
    if not source_sha or source_sha != str(provisional.get("source_sha256") or ""):
        return {"status":"FAILED", "errors":["DRAFT_ARCHITECTURE_SOURCE_MISMATCH"]}
    archive = snapshot.get("architecture_archive_b64")
    manifest = deepcopy(snapshot.get("approved_draft_manifest") or {})
    sheets = list(manifest.get("sheets") or [])
    if not archive or not sheets or any(row.get("family") != definition["family"] for row in sheets):
        return {"status":"FAILED", "errors":["SYSTEM_MANIFEST_OR_SOURCE_INVALID"]}
    manifest["total_sheets"] = len(sheets)
    answers["_approved_drawing_manifest"] = manifest
    answers["_independent_runtime_systems"] = list(definition["runtime_systems"])
    from cad_engine.runtime_contract import runtime_contract
    answers["_runtime_contract"] = runtime_contract()
    from app.mechanical_rulebook import network_design_basis
    canonical = _independent_canonical_contract(
        deliverable_type, snapshot, plan_analysis, answers)
    if canonical.get("status") != "PASS":
        canonical_missing = list(canonical.get("missing_inputs") or [])
        return {"status":"FAILED", "errors":["CANONICAL_DRAFT_ADAPTER_INPUT_REQUIRED"] + [
                    "INPUT_REQUIRED:" + str(item) for item in canonical_missing],
                "detail":{"stage":"independent_canonical_adapter",
                          "missing_inputs":canonical_missing}}
    # The persisted monolithic analysis may contain an absent or stale graph.
    # Validate the freshly derived, source-bound independent graph instead of
    # blocking before the canonical adapter has had a chance to create it.
    canonical_domain_errors = _validate_system_calculation_contract(
        deliverable_type, {
            "network_graph_canonical": canonical["network_graph"],
            "calculation_rows_canonical": canonical["calculation_rows"],
        })
    if canonical_domain_errors:
        return {"status":"FAILED", "errors":canonical_domain_errors,
                "detail":{"stage":"independent_domain_calculation_contract",
                          "missing_inputs":canonical_domain_errors}}
    canonical_network_basis = deepcopy(
        plan_analysis.get("network_design_basis_canonical") or network_design_basis())
    basis_systems = canonical_network_basis.setdefault("systems", {})
    canonical_edges_by_id = {str(row.get("id")): row
                             for row in canonical["network_graph"].get("edges") or []}
    for system in ("heating_supply", "heating_return", "cooling"):
        endpoint_loads = {}
        for row in canonical["calculation_rows"]:
            if row.get("system") != system or row.get("role") == "vertical_riser":
                continue
            edge = canonical_edges_by_id.get(str(row.get("network_edge_id"))) or {}
            endpoint_ids = list(edge.get("endpoint_ids") or [])
            if not endpoint_ids:
                continue
            load = row.get("load_kw") if system.startswith("heating_") else row.get("load_btu_h")
            if load is not None:
                per_endpoint = float(load) / len(endpoint_ids)
                for endpoint_id in endpoint_ids:
                    endpoint_loads[str(endpoint_id)] = per_endpoint
        if endpoint_loads:
            basis_systems.setdefault(system, {}).update({
                "endpoint_loads":endpoint_loads,
                "load_unit":"kW" if system.startswith("heating_") else "BTU/h",
            })
    answers["_canonical_input_contract"] = {
        "project_mechanical_model": canonical["project_mechanical_model"],
        "architecture_evidence": canonical["architecture_evidence"],
        "fixture_evidence": canonical["fixture_evidence"],
        "declared_fixture_schedule": answers.get("fixture_schedule"),
        "mechanical_shaft_route": answers.get("mechanical_shaft_route"),
        "calculation_rows": canonical["calculation_rows"],
        "active_systems": {name: name in set(definition["runtime_systems"])
                           for name in ("cold_water","hot_water","sanitary","vent","heating_supply",
                                        "heating_return","cooling","condensate","gas","exhaust_ventilation")},
        "network_graph": canonical["network_graph"],
        "network_design_basis": canonical_network_basis,
    }
    # main_transport may run with the v19 authority adapter installed.  Both
    # entrypoints must receive the exact same canonical payload; otherwise the
    # installed adapter sees an empty contract and incorrectly reports PMM v3
    # missing even though the independent adapter just built it.
    answers["_v19_input_contract"] = deepcopy(answers["_canonical_input_contract"])
    answers["_draft_provisional_architecture"] = {
        "status":"PROVISIONAL_READY", "source_sha256":source_sha,
        "draft_engineering_allowed":True, "release_allowed":False,
        "lineage":provisional.get("lineage") or {},
    }
    answers["_draft_design_overlay"] = design_overlay
    answers["_plan_fixture_evidence"] = [
        {"kind":row.get("type"), "x":(row.get("point") or [None,None])[0],
         "y":(row.get("point") or [None,None])[1], "name":row.get("source_handle") or row.get("id"),
         "source_file":"SOURCE_BOUND_REVERSIBLE_DRAFT_OVERLAY"}
        for row in design_overlay.get("fixture_endpoints") or []
        if isinstance(row,dict) and row.get("point")]
    try:
        raw = base64.b64decode(str(archive), validate=True)
        with tempfile.TemporaryDirectory(prefix="planha-system-package-") as directory:
            root = Path(directory)
            with zipfile.ZipFile(io.BytesIO(raw)) as source_zip:
                members = []
                for row in source_zip.infolist():
                    path = Path(row.filename)
                    if (row.is_dir() or path.suffix.lower() != ".dxf"
                            or "__MACOSX" in path.parts or path.name.startswith("._")):
                        continue
                    # An independent package is bound to the exact DXF whose
                    # digest was accepted for this project.  Resource forks or
                    # unrelated DXFs in the upload archive must not become a
                    # second, unbound design input.
                    if sha256(source_zip.read(row)).hexdigest() == source_sha:
                        members.append(row)
                if not members:
                    return {"status":"FAILED", "errors":["SOURCE_DXF_BINDING_MISSING"]}
                for index, member in enumerate(members, 1):
                    target = root / f"source-{index}.dxf"
                    with source_zip.open(member) as source, target.open("wb") as destination:
                        destination.write(source.read())
            from cad_engine.main_transport import design
            from cad_engine.runtime_core import DesignRequest
            response = design(DesignRequest(
                project_id="independent-" + stable_hash({"type":deliverable_type,"source":source_sha})[:16],
                discipline="mechanical", architecture_dir=str(root), answers=answers,
                plan_analysis=plan_analysis,
                output_scope={"discipline":"mechanical", "systems":definition["runtime_systems"],
                              "only_this_discipline":True, "include_other_disciplines":False},
                revision=int(snapshot.get("revision") or 1),
                revision_instructions="Independent provisional DRAFT; not release-authorized.",
            ))
        content = base64.b64decode(response.get("zip_base64") or "", validate=True)
        reopened = zipfile.ZipFile(io.BytesIO(content))
        dxf_members = [name for name in reopened.namelist() if name.lower().endswith(".dxf")]
        for name in dxf_members:
            ezdxf.read(io.StringIO(reopened.read(name).decode("utf-8", errors="strict")))
        reopened.close()
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        codes=["CANONICAL_SYSTEM_GENERATOR_FAILED"]
        if isinstance(detail,dict):
            if detail.get("stage"): codes.append("STAGE:"+str(detail["stage"]))
            codes.extend("INPUT:"+str(item) for item in (detail.get("missing_inputs") or [])[:40])
            pipeline_qa = detail.get("pipeline_qa") or {}
            codes.extend("QA:"+str(item) for item in (pipeline_qa.get("errors") or [])[:40])
            dxf_qa = detail.get("dxf_qa") or {}
            codes.extend("DXF_QA:"+str(item) for item in (dxf_qa.get("errors") or [])[:40])
            semantic_qa = detail.get("semantic_qa") or {}
            codes.extend("SEMANTIC_QA:"+str(item) for item in
                         (semantic_qa.get("errors") or semantic_qa.get("missing_family_content") or [])[:40])
            failed_stage_qa = detail.get("failed_stage_qa") or {}
            codes.extend("STAGE_QA:" + str(item) for item in
                         (failed_stage_qa.get("errors") or failed_stage_qa.get("missing_inputs") or [])[:80])
            dimension_qa = dxf_qa.get("dimension_qa") or {}
            codes.extend("DIMENSION_QA:"+str(item) for item in
                         (dimension_qa.get("errors") or [])[:40])
            preservation = detail.get("architecture_preservation_qa") or {}
            codes.extend("ARCH_PRESERVATION:"+str(item) for item in
                         (preservation.get("failures") or [])[:20])
            if preservation:
                codes.append("ARCH_MISSING_COUNTS:" + json.dumps({
                    "critical": preservation.get("critical_missing_count", 0),
                    "important": preservation.get("important_missing_count", 0),
                    "all": preservation.get("all_missing_count", 0),
                }, sort_keys=True))
                for sheet in (preservation.get("sheet_results") or []):
                    for missing in ((sheet.get("preservation_match") or {}).get("missing") or [])[:12]:
                        source = missing.get("source") or missing
                        codes.append("ARCH_MISSING:" + json.dumps({
                            "sheet": sheet.get("sheet"),
                            "handle": source.get("handle"),
                            "type": source.get("entity_type"),
                            "layer": source.get("layer"),
                            "class": source.get("semantic_class"),
                            "bbox": source.get("bbox"),
                        }, sort_keys=True, ensure_ascii=False))
            preservation_100 = detail.get("architecture_preservation_100_qa") or {}
            codes.extend("ARCH_100:" + str(item) for item in
                         (preservation_100.get("failures") or [])[:20])
            if (preservation_100.get("evidence") or {}).get("shaft_evidence_incomplete"):
                codes.append("ARCH_100_SHAFT:" + json.dumps(
                    preservation_100["evidence"]["shaft_evidence_incomplete"],
                    sort_keys=True, ensure_ascii=False))
            visual_qa = (detail.get("all_sheet_visual_qa") or
                         (detail.get("failed_stage_qa") or {})
                         if detail.get("stage") in {"all_sheet_visual_gate", "post_materialization_visual_gate"} else {})
            codes.extend("VISUAL_QA:"+str(item) for item in
                         (visual_qa.get("errors") or [])[:80])
            for sheet in (visual_qa.get("sheets") or []):
                for overlap in (sheet.get("annotation_overlap_evidence") or [])[:20]:
                    codes.append("VISUAL_OVERLAP:" + json.dumps({
                        "sheet": sheet.get("code"),
                        "first": overlap.get("first"),
                        "second": overlap.get("second"),
                        "ratio": overlap.get("intersection_ratio"),
                    }, sort_keys=True, ensure_ascii=False))
            for sheet, entities in (dxf_qa.get("title_overlap_entities") or {}).items():
                for entity in (entities or [])[:40]:
                    codes.append("TITLE_OVERLAP:" + json.dumps({
                        "sheet": sheet, "handle": entity.get("handle"),
                        "type": entity.get("type"), "layer": entity.get("layer"),
                        "bounds": entity.get("bounds"),
                    }, sort_keys=True, ensure_ascii=False))
            for sheet, dimension_report in (detail.get("dimensioning") or {}).items():
                conflict_ids = set(dimension_report.get("critical_source_conflicts") or [])
                registry_rows = ((dimension_report.get("source_registry") or {}).get("records") or [])
                for row in registry_rows:
                    if row.get("id") in conflict_ids:
                        codes.append("DIMENSION_CONFLICT:" + json.dumps({
                            "sheet": sheet, "id": row.get("id"),
                            "source_handle": row.get("source_handle"),
                            "measured_value": row.get("measured_value"),
                            "source_display_text": row.get("source_display_text"),
                            "semantic_type": row.get("semantic_type"),
                            "reason": row.get("conflict"), "p1": row.get("p1"),
                            "p2": row.get("p2"),
                        }, sort_keys=True, ensure_ascii=False))
                for intent_id in (dimension_report.get("collision_intents") or [])[:20]:
                    codes.append("DIMENSION_COLLISION:" + json.dumps({
                        "sheet": sheet, "intent_id": intent_id,
                    }, sort_keys=True, ensure_ascii=False))
            acceptance = detail.get("engineering_acceptance") or {}
            codes.extend("ACCEPTANCE:"+str(item) for item in (acceptance.get("errors") or [])[:40])
            route_gate = next((row for row in acceptance.get("gates") or []
                               if row.get("name") == "routing"), {})
            for row in (route_gate.get("metrics") or {}).get("uncoordinated_routes") or []:
                codes.append("ROUTE_COLLISION:" + json.dumps(row, sort_keys=True,
                                                              ensure_ascii=False))
        return {"status":"FAILED", "errors":codes,
                "detail":detail if isinstance(detail, dict) else type(exc).__name__}
    errors=[]
    if not content: errors.append("EMPTY_SYSTEM_PACKAGE")
    if len(dxf_members) != len(members): errors.append("SOURCE_OUTPUT_COUNT_MISMATCH")
    if response.get("submission_state") not in {"PRE_SUBMISSION","SUBMISSION_READY"}:
        errors.append("DRAFT_SUBMISSION_STATE_INVALID")
    qa={"status":"PASS" if not errors else "FAIL", "qa_version":QA_VERSIONS[deliverable_type],
        "checks":{"exact_zip_reopened":True,"dxf_count":len(dxf_members),
                  "system_family":definition["family"],"release_level":"DRAFT",
                  "provisional_architecture":True},"errors":errors}
    if errors: return {"status":"QA_FAILED","qa":qa,"errors":errors}
    return {"status":"PASS","content":content,"format":"ZIP","media_type":"application/zip",
            "filename":definition["family"]+"-draft.zip","sha256":sha256(content).hexdigest(),
            "generator_version":GENERATOR_VERSIONS[deliverable_type],"qa":qa,
            "provenance":{"input_snapshot_hash":stable_hash(snapshot),"source_sha256":source_sha,
                          "architecture_authority":"MODEL_PROPOSED_REVERSIBLE",
                          "release_allowed":False,"system_family":definition["family"]}}


_SYSTEM_DIAGNOSTIC_BASE = {
    "MECH_HEATING_SOURCE_DIAGNOSTIC_PREVIEW": "MECH_HEATING_PACKAGE",
    "MECH_COOLING_SOURCE_DIAGNOSTIC_PREVIEW": "MECH_COOLING_PACKAGE",
}


def _numeric_source_dimension_evidence(doc):
    """Separate accepted written dimensions from unresolved contradictions."""
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    conflicts, accepted = [], []
    for entity in doc.modelspace().query("DIMENSION"):
        raw = str(entity.dxf.get("text", "")).strip().translate(translation)
        if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", raw):
            continue
        try:
            displayed = float(raw)
            measured = float(entity.dxf.get("actual_measurement", entity.get_measurement()))
        except (TypeError, ValueError, AttributeError, ezdxf.DXFValueError):
            continue
        if not all(math.isfinite(value) for value in (displayed, measured)):
            continue
        policy = source_numeric_dimension_policy(measured, raw)
        midpoint = entity.dxf.get("text_midpoint", entity.dxf.get("defpoint", (0, 0, 0)))
        row = {
            "source_handle": str(entity.dxf.handle or ""),
            "source_display_text": raw,
            "measured_value": measured,
            "dimstyle": str(entity.dxf.get("dimstyle", "")),
            "relative_difference": policy.get("relative_difference"),
            "relative_difference_denominator": policy.get("denominator"),
            "relative_threshold": policy.get("threshold"),
            "point": [float(midpoint.x), float(midpoint.y)],
        }
        if policy.get("status") == "SOURCE_TEXT_AUTHORITY_WITHIN_10_PERCENT":
            accepted.append({**row, "design_value_native": displayed,
                             "authority": "SOURCE_WRITTEN_DIMENSION"})
        elif not policy.get("accepted"):
            conflicts.append({**row, "authority": "UNRESOLVED_SOURCE_CONTRADICTION"})
    return {"conflicts": sorted(conflicts, key=lambda row: row["source_handle"]),
            "accepted": sorted(accepted, key=lambda row: row["source_handle"])}


def _numeric_source_dimension_conflicts(doc):
    return _numeric_source_dimension_evidence(doc)["conflicts"]


def _build_mechanical_source_diagnostic_preview(source_path, expected_source_sha256,
                                                graph, allowed_bounds, family):
    """Overlay a reversible DRAFT graph on an exact source DXF.

    This is intentionally not a design package.  It draws only the supplied
    graph identities and makes source dimension contradictions conspicuous.
    """
    path = Path(source_path)
    source_bytes = path.read_bytes()
    source_sha = sha256(source_bytes).hexdigest()
    if source_sha != str(expected_source_sha256):
        raise ValueError("SOURCE_SHA_MISMATCH")
    if family not in {"heating", "cooling"}:
        raise ValueError("DIAGNOSTIC_FAMILY_INVALID")
    doc = ezdxf.readfile(path)
    from cad_engine.mechanical_cad_roof_rainwater_source_preview import _source_entity_manifest
    source_manifest = _source_entity_manifest(doc)
    layer = "PLANHA-DIAG-HEAT" if family == "heating" else "PLANHA-DIAG-COOL"
    warning_layer = "PLANHA-DIAG-WARN"
    if any(str(entity.dxf.layer) in {layer, warning_layer} for entity in doc.modelspace()):
        raise ValueError("DIAGNOSTIC_LAYER_ALREADY_PRESENT")
    bounds = []
    for row in allowed_bounds or []:
        if (isinstance(row, (list, tuple)) and len(row) == 4
                and all(math.isfinite(float(value)) for value in row)
                and float(row[2]) > float(row[0]) and float(row[3]) > float(row[1])):
            bounds.append([float(value) for value in row])
    if not bounds:
        raise ValueError("SOURCE_LEVEL_BOUNDS_REQUIRED")
    nodes = {}
    for row in graph.get("nodes") or []:
        node_id = str(row.get("id") or "")
        point = row.get("point") or []
        if (not node_id or node_id in nodes or len(point) != 2
                or not all(math.isfinite(float(value)) for value in point)):
            raise ValueError("DIAGNOSTIC_NODE_INVALID")
        point = [float(point[0]), float(point[1])]
        if not any(b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3] for b in bounds):
            raise ValueError("DIAGNOSTIC_NODE_OUTSIDE_SOURCE_LEVEL")
        nodes[node_id] = {"id": node_id, "point": point,
                          "kind": str(row.get("kind") or ""),
                          "level": str(row.get("level") or ""),
                          "authority": str(row.get("authority") or
                                           "MODEL_PROPOSED_DESIGN_ASSUMPTION")}
    edges = []
    for row in graph.get("edges") or []:
        edge_id = str(row.get("id") or "")
        start = nodes.get(str(row.get("from") or ""))
        end = nodes.get(str(row.get("to") or ""))
        if not edge_id or not start or not end or start["point"] == end["point"]:
            raise ValueError("DIAGNOSTIC_EDGE_INVALID")
        if row.get("release_allowed") is not False:
            raise ValueError("DIAGNOSTIC_EDGE_AUTHORITY_LEAK")
        edges.append({"id": edge_id, "from": start["id"], "to": end["id"],
                      "system": str(row.get("system") or ""),
                      "role": str(row.get("role") or ""),
                      "release_allowed": False})
    if not nodes or not edges:
        raise ValueError("DIAGNOSTIC_NETWORK_EVIDENCE_REQUIRED")
    doc.layers.add(layer, color=1 if family == "heating" else 5)
    doc.layers.add(warning_layer, color=2)
    if "PLANHA" not in doc.appids:
        doc.appids.add("PLANHA")
    msp = doc.modelspace()
    for row in edges:
        start, end = nodes[row["from"]], nodes[row["to"]]
        entity = msp.add_line(start["point"], end["point"], dxfattribs={"layer": layer})
        entity.set_xdata("PLANHA", [(1000, "DRAFT_DIAGNOSTIC_ONLY"), (1000, row["id"])])
    span = max(max(b[2] - b[0], b[3] - b[1]) for b in bounds)
    marker_radius = max(0.05, min(0.25, span / 1000.0))
    for row in nodes.values():
        msp.add_circle(row["point"], marker_radius, dxfattribs={"layer": layer})
    dimension_evidence = _numeric_source_dimension_evidence(doc)
    conflicts = dimension_evidence["conflicts"]
    for row in conflicts:
        message = (f"UNRESOLVED SOURCE DIMENSION | handle={row['source_handle']} | "
                   f"text={row['source_display_text']} | geometry={row['measured_value']:.9f}")
        msp.add_text(message, height=max(0.08, marker_radius * 0.8),
                     dxfattribs={"layer": warning_layer}).set_placement(row["point"])
    anchor = [min(b[0] for b in bounds), max(b[3] for b in bounds) + marker_radius * 4]
    msp.add_text(
        "DRAFT DIAGNOSTIC ONLY - SOURCE/PROPOSED EVIDENCE - NOT ENGINEERING DESIGN",
        height=max(0.1, marker_radius), dxfattribs={"layer": warning_layer}).set_placement(anchor)
    stream = StringIO(); doc.write(stream)
    content = stream.getvalue().encode("utf-8")
    manifest = {
        "contract": "planha-mechanical-source-diagnostic-preview/1.0",
        "family": family, "source_sha256": source_sha,
        "source_entity_count": len(source_manifest),
        "source_manifest_hash": stable_hash(source_manifest),
        "nodes": sorted(nodes.values(), key=lambda row: row["id"]),
        "edges": sorted(edges, key=lambda row: row["id"]),
        "dimension_conflicts": conflicts,
        "accepted_source_dimensions": dimension_evidence["accepted"],
        "diagnostic_layers": [layer, warning_layer],
        "release_level": "DRAFT_DIAGNOSTIC_ONLY",
        "engineering_release_allowed": False,
        "review_required": True,
        "forbidden_authority": ["ENGINEERING_DESIGN", "CALCULATION_APPROVAL",
                                "ROUTE_APPROVAL", "EQUIPMENT_APPROVAL",
                                "CONSTRUCTION", "ENGINEERING_RELEASE"],
    }
    manifest["diagnostic_fingerprint"] = stable_hash(manifest)
    return {"content": content, "manifest": manifest}


def _validate_mechanical_source_diagnostic_preview(source_path, output_content, manifest):
    errors = []
    source_path = Path(source_path)
    if sha256(source_path.read_bytes()).hexdigest() != manifest.get("source_sha256"):
        errors.append("SOURCE_SHA_MISMATCH")
    try:
        source_doc = ezdxf.readfile(source_path)
        output_doc = ezdxf.read(StringIO(output_content.decode("utf-8", errors="strict")))
        from cad_engine.mechanical_cad_roof_rainwater_source_preview import _source_entity_manifest
        source_entities = _source_entity_manifest(source_doc)
        output_entities = _source_entity_manifest(output_doc)
        for handle, signature in source_entities.items():
            if output_entities.get(handle) != signature:
                errors.append("SOURCE_ENTITY_CHANGED:" + handle)
        if stable_hash(source_entities) != manifest.get("source_manifest_hash"):
            errors.append("SOURCE_MANIFEST_HASH_MISMATCH")
        dimension_evidence = _numeric_source_dimension_evidence(source_doc)
        conflicts = dimension_evidence["conflicts"]
        if conflicts != manifest.get("dimension_conflicts"):
            errors.append("DIMENSION_CONFLICT_MANIFEST_MISMATCH")
        if dimension_evidence["accepted"] != manifest.get("accepted_source_dimensions"):
            errors.append("DIMENSION_ACCEPTANCE_MANIFEST_MISMATCH")
        layers = set(manifest.get("diagnostic_layers") or [])
        added = [entity for entity in output_doc.modelspace()
                 if str(entity.dxf.handle or "") not in source_entities]
        if not added or any(str(entity.dxf.layer) not in layers for entity in added):
            errors.append("DIAGNOSTIC_ENTITY_SCOPE_INVALID")
        expected_lines = len(manifest.get("edges") or [])
        actual_lines = sum(entity.dxftype() == "LINE" and str(entity.dxf.layer) in layers
                           for entity in added)
        if actual_lines != expected_lines:
            errors.append("DIAGNOSTIC_EDGE_COUNT_MISMATCH")
    except Exception as exc:
        errors.append("DIAGNOSTIC_REOPEN_FAILED:" + type(exc).__name__)
    if (manifest.get("engineering_release_allowed") is not False
            or manifest.get("review_required") is not True
            or manifest.get("release_level") != "DRAFT_DIAGNOSTIC_ONLY"):
        errors.append("DIAGNOSTIC_AUTHORITY_LEAK")
    fingerprint = dict(manifest); fingerprint.pop("diagnostic_fingerprint", None)
    if stable_hash(fingerprint) != manifest.get("diagnostic_fingerprint"):
        errors.append("DIAGNOSTIC_FINGERPRINT_MISMATCH")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors,
            "checks": {"exact_source_preserved": not any(
                error.startswith("SOURCE_ENTITY_CHANGED") for error in errors),
                "dimension_conflicts_reconstructed":
                    "DIMENSION_CONFLICT_MANIFEST_MISMATCH" not in errors,
                "authority_fail_closed": "DIAGNOSTIC_AUTHORITY_LEAK" not in errors}}


def execute_registered_generator(deliverable_type, snapshot):
    """Execute a real allow-listed generator and return deterministic file bytes."""
    if deliverable_type in _SYSTEM_DIAGNOSTIC_BASE:
        base_type = _SYSTEM_DIAGNOSTIC_BASE[deliverable_type]
        family = SYSTEM_PACKAGES[base_type]["family"]
        try:
            source_sha = str(snapshot.get("source_sha256") or "")
            provisional = dict(snapshot.get("provisional_architecture") or {})
            if (not source_sha or provisional.get("source_sha256") != source_sha
                    or provisional.get("release_allowed") is not False):
                return {"status":"FAILED", "errors":["DIAGNOSTIC_SOURCE_CONTRACT_INVALID"]}
            plan_analysis = deepcopy(snapshot.get("plan_analysis") or {})
            canonical = _independent_canonical_contract(
                base_type, snapshot, plan_analysis, deepcopy(snapshot.get("answers") or {}))
            if canonical.get("status") != "PASS":
                return {"status":"FAILED", "errors":["DIAGNOSTIC_NETWORK_INPUT_REQUIRED"] +
                        list(canonical.get("missing_inputs") or [])}
            graph = canonical.get("network_graph") or {}
            allowed_bounds = [row.get("region_bounds") for row in
                ((((plan_analysis.get("architectural_auto") or {}).get("architecture_model") or {})
                  .get("levels") or []))]
            archive_bytes = base64.b64decode(snapshot.get("architecture_archive_b64") or "",
                                             validate=True)
            with tempfile.TemporaryDirectory(prefix="planha-system-source-preview-") as tmp:
                root = Path(tmp); source_path = root / "source.dxf"
                with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                    members = [row for row in archive.infolist()
                               if (not row.is_dir() and Path(row.filename).suffix.lower() == ".dxf"
                                   and "__MACOSX" not in Path(row.filename).parts
                                   and not Path(row.filename).name.startswith("._")
                                   and sha256(archive.read(row)).hexdigest() == source_sha)]
                    if len(members) != 1:
                        return {"status":"FAILED", "errors":["DIAGNOSTIC_SOURCE_DXF_BINDING_INVALID"]}
                    source_path.write_bytes(archive.read(members[0]))
                generated = _build_mechanical_source_diagnostic_preview(
                    source_path, source_sha, graph, allowed_bounds, family)
                qa = _validate_mechanical_source_diagnostic_preview(
                    source_path, generated["content"], generated["manifest"])
                qa["qa_version"] = QA_VERSIONS[deliverable_type]
        except (ValueError, OSError, zipfile.BadZipFile, binascii.Error) as exc:
            return {"status":"FAILED", "errors":["SYSTEM_SOURCE_PREVIEW_INVALID:" + str(exc)]}
        if qa.get("status") != "PASS":
            return {"status":"QA_FAILED", "qa":qa, "errors":qa.get("errors") or []}
        return {"status":"PASS", "content":generated["content"], "format":"DXF",
                "media_type":"application/dxf",
                "filename":family + "-source-diagnostic-review-required.dxf",
                "sha256":sha256(generated["content"]).hexdigest(),
                "generator_version":GENERATOR_VERSIONS[deliverable_type], "qa":qa,
                "provenance":{"input_snapshot_hash":stable_hash(snapshot),
                    "diagnostic_manifest":generated["manifest"],
                    "engineering_release_allowed":False, "review_required":True}}
    if deliverable_type == "MECH_ROOF_RAINWATER_SOURCE_PREVIEW":
        from cad_engine.mechanical_cad_roof_rainwater_source_preview import (
            build_source_grounded_roof_drainage_preview,
            validate_source_grounded_roof_drainage_preview,
        )
        try:
            archive_bytes = base64.b64decode(snapshot.get("architecture_archive_b64") or "",
                                             validate=True)
            with tempfile.TemporaryDirectory(prefix="planha-rw-source-preview-") as tmp:
                root = Path(tmp)
                with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                    members = [name for name in archive.namelist()
                               if (not name.endswith("/")
                                   and Path(name).suffix.lower() == ".dxf"
                                   and "__MACOSX" not in Path(name).parts
                                   and not Path(name).name.startswith("._"))]
                    if len(members) != 1:
                        return {"status":"FAILED", "errors":["SOURCE_PREVIEW_SINGLE_DXF_REQUIRED"]}
                    source_path = root / "source.dxf"
                    source_path.write_bytes(archive.read(members[0]))
                generated = build_source_grounded_roof_drainage_preview(
                    source_path, snapshot.get("source_sha256"),
                    snapshot.get("source_plans") or [], snapshot.get("source_evidence") or [])
                qa = validate_source_grounded_roof_drainage_preview(
                    source_path, generated["content"], generated["manifest"])
                # The source-preservation validator intentionally owns only
                # semantic checks.  Publication still requires the registered
                # QA contract identity carried by every independent artifact.
                qa["qa_version"] = QA_VERSIONS[deliverable_type]
        except (ValueError, OSError, zipfile.BadZipFile, binascii.Error) as exc:
            return {"status":"FAILED", "errors":["SOURCE_PREVIEW_INVALID:" + str(exc)]}
        if qa.get("status") != "PASS":
            return {"status":"QA_FAILED", "qa":qa, "errors":qa.get("errors") or []}
        manifest = generated["manifest"]
        return {"status":"PASS", "content":generated["content"], "format":"DXF",
                "media_type":"application/dxf",
                "filename":"rainwater-source-diagnostic-review-required.dxf",
                "sha256":sha256(generated["content"]).hexdigest(),
                "generator_version":GENERATOR_VERSIONS[deliverable_type], "qa":qa,
                "provenance":{"input_snapshot_hash":stable_hash(snapshot),
                    "diagnostic_manifest":manifest, "engineering_release_allowed":False,
                    "review_required":True}}
    if deliverable_type in SYSTEM_PACKAGES:
        return _execute_system_package(deliverable_type, snapshot)
    if deliverable_type not in {"MECH_ROOF_RAINWATER_CALC", "MECH_ROOF_RAINWATER_PLAN"}:
        return {"status": "FAILED", "errors": ["GENERATOR_DISPATCH_UNSUPPORTED"]}
    if not isinstance(snapshot, dict):
        return {"status": "FAILED", "errors": ["INPUT_SNAPSHOT_INVALID"]}
    result = design_roof_rainwater(
        snapshot.get("roof") or {}, snapshot.get("design_basis") or {},
        rule_context=snapshot.get("rule_context") or {},
        draft_assumption_basis=snapshot.get("draft_assumption_basis") or {},
        llm_suggestions=snapshot.get("llm_rule_suggestions"))
    engineering_acceptance = rainwater_engineering_acceptance(snapshot)
    result["engineering_acceptance"] = engineering_acceptance
    qa = _rainwater_independent_qa(snapshot, result)
    qa["scope"] = "ARTIFACT_AND_ARITHMETIC_INTEGRITY_ONLY"
    qa.setdefault("checks", {})["engineering_capacity_verified"] = False
    if result.get("status") != "PASS" or qa["status"] != "PASS":
        return {"status": "QA_FAILED", "result": result, "qa": qa}
    if deliverable_type == "MECH_ROOF_RAINWATER_PLAN":
        try:
            content = _rainwater_plan_dxf(snapshot, result)
        except (TypeError, ValueError) as exc:
            return {"status": "QA_FAILED", "result": result,
                    "qa": {"status": "FAIL", "qa_version": QA_VERSIONS[deliverable_type],
                           "checks": {}, "errors": [str(exc)]}}
        plan_qa = _rainwater_plan_independent_qa(snapshot, result, content)
        plan_qa["scope"] = "ARTIFACT_AND_ARITHMETIC_INTEGRITY_ONLY"
        plan_qa.setdefault("checks", {})["engineering_capacity_verified"] = False
        if plan_qa["status"] != "PASS":
            return {"status": "QA_FAILED", "result": result, "qa": plan_qa}
        return {"status": "PASS", "content": content, "format": "DXF", "result": result,
                "media_type": "application/dxf", "filename": "roof-rainwater-plan.dxf",
                "sha256": sha256(content).hexdigest(),
                "generator_version": GENERATOR_VERSIONS[deliverable_type], "qa": plan_qa,
                "provenance": {"input_snapshot_hash": stable_hash(snapshot),
                               "engineering_acceptance": engineering_acceptance,
                               "rulebook_dependency_identity": (
                                   result.get("rule_evaluation") or {}).get("dependency_identity"),
                               "calculation_ids": sorted(row["calc_id"] for row in result["catchments"])}}
    envelope = {
        "contract": CONTRACT_VERSION,
        "deliverable_type": deliverable_type,
        "generator": REGISTRY[deliverable_type]["generator"],
        "generator_version": GENERATOR_VERSIONS[deliverable_type],
        "qa": qa,
        "engineering_acceptance": engineering_acceptance,
        "result": result,
    }
    content = (json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    return {
        "status": "PASS",
        "content": content,
        "format": "JSON",
        "media_type": "application/json",
        "filename": "roof-rainwater-calculation.json",
        "sha256": sha256(content).hexdigest(),
        "generator_version": GENERATOR_VERSIONS[deliverable_type],
        "qa": qa,
        "provenance": {"input_snapshot_hash": stable_hash(snapshot),
                       "engineering_acceptance": engineering_acceptance,
                       "rulebook_dependency_identity": (
                           result.get("rule_evaluation") or {}).get("dependency_identity")},
    }


def execute_rainwater_simulation_preview(deliverable_type, synthetic_snapshot,
                                         rainfall_intensity_mm_h=100.0):
    """Run a disposable preview without satisfying authoritative readiness.

    The caller must supply explicitly synthetic geometry.  This path never
    writes persistence records and never returns an engineering release level.
    """
    if deliverable_type not in {"MECH_ROOF_RAINWATER_CALC", "MECH_ROOF_RAINWATER_PLAN"}:
        return {"status": "FAILED", "errors": ["SIMULATION_GENERATOR_UNSUPPORTED"]}
    if not isinstance(synthetic_snapshot, dict):
        return {"status": "FAILED", "errors": ["SIMULATION_SNAPSHOT_INVALID"]}
    geometry = synthetic_snapshot.get("geometry_provenance") or {}
    if geometry.get("source") != "SYNTHETIC_TEST" or geometry.get("authoritative") is not False:
        return {"status": "FAILED", "errors": ["SYNTHETIC_GEOMETRY_PROVENANCE_REQUIRED"]}
    try:
        intensity = float(rainfall_intensity_mm_h)
    except (TypeError, ValueError):
        return {"status": "FAILED", "errors": ["SIMULATION_RAINFALL_INVALID"]}
    if not math.isfinite(intensity) or intensity <= 0:
        return {"status": "FAILED", "errors": ["SIMULATION_RAINFALL_INVALID"]}
    snapshot = deepcopy(synthetic_snapshot)
    scenario = {
        "contract": SIMULATION_CONTRACT_VERSION,
        "scenario_type": "SIMULATION_PREVIEW",
        "rainfall_intensity_mm_h": intensity,
        "source": "SYNTHETIC_TEST",
        "authoritative": False,
        "engineering_release_allowed": False,
        "publication_scope": "LOCAL_DISPOSABLE_PREVIEW_ONLY",
        "disclaimer_fa": SIMULATION_DISCLAIMER_FA,
    }
    snapshot["simulation"] = scenario
    snapshot.setdefault("project", {}).update({
        "project_identity": "ISOLATED-SYNTHETIC-SIMULATION",
        "revision_identity": "DISPOSABLE",
    })
    snapshot.setdefault("design_basis", {})["rainfall_intensity_mm_h"] = intensity
    generated = execute_registered_generator(deliverable_type, snapshot)
    if generated.get("status") != "PASS":
        return {**generated, "simulation": scenario}
    if generated.get("format") == "JSON":
        envelope = json.loads(generated["content"].decode("utf-8"))
        envelope["simulation"] = scenario
        content = (json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("utf-8")
        generated.update({"content": content, "sha256": sha256(content).hexdigest(),
                          "filename": "SIMULATION-roof-rainwater-calculation.json"})
    else:
        generated["filename"] = "SIMULATION-roof-rainwater-plan.dxf"
    generated.update({
        "simulation": scenario,
        "release_level": "SIMULATION_PREVIEW_ONLY",
        "publication_state": "LOCAL_ONLY_NOT_PUBLISHABLE",
    })
    generated["provenance"] = {
        **(generated.get("provenance") or {}),
        "simulation_scenario_hash": stable_hash(scenario),
        "synthetic_geometry_hash": stable_hash(snapshot.get("roof") or {}),
    }
    return generated
