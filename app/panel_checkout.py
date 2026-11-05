"""Durable assistant handoff and transactional customer checkout.

Phone-only sign-in is deliberately retained; it is NOT proof of phone ownership.
Only the trusted panel bridge may mint the short-lived customer session.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Integer, String, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from . import mechanical_workflow
from .design_progress import set_project_progress, stage_payload


def _draft_domain_contract(deliverable_type, overlay, answers):
    """Derive one project-bound aggregate edge through canonical calculators.

    The edge is a DRAFT calculation transport, not a final routed network. Its
    source IDs are the exact reversible endpoints in the overlay.
    """
    from cad_engine.mechanical_execution_sizing import (
        design_water_network, design_heating_network, design_gas_network,
    )
    from cad_engine.hvac_calculations import size_round_duct
    calculation = dict(overlay.get("deterministic_calculation") or {})
    totals = dict(calculation.get("totals") or {})
    endpoints = list(overlay.get("fixture_endpoints") or [])
    source_ids = [str(row.get("id")) for row in endpoints if row.get("id")]
    if not source_ids or not totals:
        return None
    edge_id = "DRAFT-" + deliverable_type.replace("MECH_", "").replace("_PACKAGE", "") + "-E1"
    if deliverable_type == "MECH_WATER_SUPPLY_PACKAGE":
        fu=float(totals.get("water_fu") or 0); flow=float(totals.get("preliminary_water_lps") or 0)
        segment_inputs=[]
        for system in ("cold_water","hot_water"):
            segment_inputs.append({"id":edge_id+"-"+system.upper(),"system":system,
                "downstream_fixture_ids":source_ids,"length_m":20,
                "fittings_equivalent_length_m":5})
        result=design_water_network(
            segment_inputs,
            [{"id":source_id,"fixture_units":fu/len(source_ids)} for source_id in source_ids],
            {"probable_flow_curve":[{"max_fixture_units":fu,"flow_lps":flow}],
             "candidate_diameters_mm":[20,25,32,40,50],"max_velocity_m_s":2,
             "max_pressure_drop_pa_m":5000,"hazen_williams_c":150})
        if result.get("status")!="PASS": return None
        endpoint=next(row for row in endpoints if row.get("id") in source_ids)
        point=[float(value) for value in endpoint["point"]]
        design_room=next((row for row in overlay.get("design_rooms") or []
                          if str(row.get("room_id"))==str(endpoint.get("room_id"))),{})
        level_id=str(design_room.get("level_id") or "DRAFT-L1")
        nodes=[{"id":"DRAFT-WATER-SOURCE-COLD","kind":"water_source","point":[point[0]-1,point[1]],
                "level":level_id,"ports":["cold_water"],"authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION","release_allowed":False},
               {"id":"DRAFT-WATER-SOURCE-HOT","kind":"water_heater","point":[point[0]-1,point[1]+.5],
                "level":level_id,"ports":["hot_water"],"authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION","release_allowed":False},
               {"id":"DRAFT-WATER-ENDPOINT","kind":"fixture","point":point,
                "level":level_id,"ports":["cold_water","hot_water"],"source_detection_ids":source_ids,
                "authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION","release_allowed":False}]
        edges=[];rows=[]
        for sized in result["segments"]:
            system=sized["system"];source_node=("DRAFT-WATER-SOURCE-COLD" if system=="cold_water"
                                                 else "DRAFT-WATER-SOURCE-HOT")
            start=next(row["point"] for row in nodes if row["id"]==source_node)
            edge={"id":sized["segment_id"],"system":system,"from":source_node,
                  "to":"DRAFT-WATER-ENDPOINT","material":"PPR","calc_id":sized["calc_id"],
                  "flow_lps":sized["probable_flow_lps"],
                  "pressure_drop_pa":round(sized["pressure_drop_pa_m"]*25,2),
                  "size":sized["selected_dn_mm"],"plan_path":[start,[point[0],start[1]],point],
                  "draw_on_plan":True,"levels":[level_id],
                  "release_allowed":False}
            edges.append(edge);rows.append({**edge,"calculation_engine":"design_water_network",
                "source_input_ids":source_ids,"formula_inputs":{"fixture_units":fu,"length_m":25,
                "basis_status":"PROVISIONAL_DRAFT"}})
        graph_id="DRAFT-WATER-"+hashlib.sha256(json.dumps({"nodes":nodes,"edges":edges},
            sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16].upper()
        return {"network_graph_canonical":{"schema":"mechanical-network-graph/1","graph_id":graph_id,
                    "design_mode":"provisional-interpretation-draft","release_allowed":False,
                    "levels":[{"id":level_id,"name":level_id,"type":"GROUND"}],
                    "nodes":nodes,"edges":edges},"calculation_rows_canonical":rows}
    elif deliverable_type == "MECH_SANITARY_VENT_PACKAGE":
        from cad_engine.mechanical_execution_sizing import size_networks
        plumbing = [row for row in endpoints if str(row.get("type") or "").lower() in {
            "wc", "toilet", "basin", "sink", "shower", "floor_drain", "bath"}]
        shafts = list(overlay.get("shafts") or [])
        if not plumbing or not shafts: return None
        endpoint = plumbing[0]; point = [float(value) for value in endpoint["point"]]
        shaft = min((row for row in shafts if len(row.get("centroid") or []) == 2),
                    key=lambda row: math.dist(point, row["centroid"]), default=None)
        if shaft is None: return None
        start = [float(value) for value in shaft["centroid"]]
        design_room = next((row for row in overlay.get("design_rooms") or []
                            if str(row.get("room_id")) == str(endpoint.get("room_id"))), {})
        level_id = str(design_room.get("level_id") or "DRAFT-L1")
        detections = [{"id": str(row["id"]), "category": "fixture",
                       "type": "wc" if row.get("type") == "toilet" else row.get("type"),
                       "room_id": row.get("room_id")} for row in plumbing]
        topology = {"edges": [{"id": edge_id + "-" + system.upper(),
                     "from": "DRAFT-SANITARY-SHAFT", "endpoint_ids": [row["id"] for row in plumbing]}
                    for system in ("sanitary", "vent")]}
        routing = {"routes": [{"id": "ROUTE-" + row["id"], "edge_id": row["id"],
                    "system": row["id"].rsplit("-", 1)[-1].lower(),
                    "endpoint_ids": row["endpoint_ids"]} for row in topology["edges"]]}
        sized = size_networks(topology, routing, {"detections": detections},
                              calculation, design_basis={"sanitary_slope_percent": 2.0})
        if sized.get("quality", {}).get("unsized_routes"): return None
        nodes = [{"id": "DRAFT-SANITARY-SHAFT", "kind": "shaft", "point": start,
                  "level": level_id, "source": "ARCHITECTURAL_SHAFT_GEOMETRY",
                  "release_allowed": False},
                 {"id": "DRAFT-SANITARY-FIXTURES", "kind": "fixture_group", "point": point,
                  "level": level_id, "source_detection_ids": [row["id"] for row in plumbing],
                  "release_allowed": False}]
        edges=[]; rows=[]
        for segment in sized["segments"]:
            system=segment["system"]
            calc_id="CALC-DRAFT-%s-" % system.upper() + hashlib.sha256(json.dumps(
                {"load":segment["downstream_load"],"sources":source_ids,"system":system},
                sort_keys=True).encode()).hexdigest()[:12].upper()
            edge={"id":segment["edge_id"],"system":system,"material":"UPVC","calc_id":calc_id,
                  "fixture_units":segment["downstream_load"],"slope_percent":2.0,
                  "size":segment["size_mm"],"from":"DRAFT-SANITARY-FIXTURES",
                  "to":"DRAFT-SANITARY-SHAFT","plan_path":[point,[start[0],point[1]],start],
                  "draw_on_plan":True,"levels":[level_id],"release_allowed":False}
            edges.append(edge); rows.append({**edge,"calculation_engine":"size_networks",
                "source_input_ids":source_ids,"formula_inputs":{"fixture_units":segment["downstream_load"],
                    "sanitary_slope_percent":2.0,"basis_status":"PROVISIONAL_DRAFT"}})
        graph_id="DRAFT-SANITARY-"+hashlib.sha256(json.dumps({"nodes":nodes,"edges":edges},
            sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16].upper()
        return {"network_graph_canonical":{"schema":"mechanical-network-graph/1","graph_id":graph_id,
                    "design_mode":"provisional-interpretation-draft","release_allowed":False,
                    "levels":[{"id":level_id,"name":level_id,"type":"GROUND"}],
                    "nodes":nodes,"edges":edges},"calculation_rows_canonical":rows}
    elif deliverable_type == "MECH_HEATING_PACKAGE":
        load_kw=float(totals.get("heating_w") or 0)/1000
        result=design_heating_network(
            [{"id":edge_id,"system":"heating_supply","downstream_radiator_ids":["DRAFT-RADIATOR-AGG"]}],
            [{"radiator_id":"DRAFT-RADIATOR-AGG","selected_output_w":load_kw*1000}],
            {"design_delta_t_k":20,"fluid_density_kg_m3":998,"fluid_specific_heat_j_kgk":4180,
             "candidate_diameters_mm":[16,20,25,32,40],"max_velocity_m_s":1.5})
        if result.get("status")!="PASS": return None
        sized=result["segments"][0]; calc_id=sized["calc_id"]
        edge={"id":edge_id,"system":"heating_supply","material":"PEX","calc_id":calc_id,
              "load_kw":load_kw,"delta_t_c":20,"size":sized["selected_dn_mm"]}
        row={**edge,"calculation_engine":"design_heating_network","source_input_ids":source_ids,
             "formula_inputs":{"heat_loss_w":totals["heating_w"],"delta_t_k":20,
                               "basis_status":"PROVISIONAL_DRAFT"}}
    elif deliverable_type == "MECH_COOLING_PACKAGE":
        load_btu=round(float(totals.get("cooling_w") or 0)*3.412142); calc_id="CALC-DRAFT-COOL-"+hashlib.sha256(
            json.dumps({"load_btu_h":load_btu,"sources":source_ids},sort_keys=True).encode()).hexdigest()[:12].upper()
        edge={"id":edge_id,"system":"cooling","material":"COPPER","calc_id":calc_id,
              "load_btu_h":load_btu,"line_type":"DESIGN_LOAD_ONLY_UNSIZED",
              "size":None,"manufacturer_selection":"INPUT_REQUIRED_FOR_RELEASE"}
        row={**edge,"calculation_engine":"calculate_cooling_design","source_input_ids":source_ids,
             "formula_inputs":{"calculated_load_w":totals["cooling_w"],
                               "refrigerant_size_status":"UNSIZED_NO_MANUFACTURER",
                               "basis_status":"PROVISIONAL_DRAFT"}}
    elif deliverable_type == "MECH_GAS_PACKAGE":
        load_kw=float(totals.get("gas_kw") or 0); flow=round(load_kw/10.5,3)
        appliances=[{"id":"DRAFT-GAS-AGG","pmm_id":"DRAFT-GAS-AGG","manufacturer":"UNSELECTED",
          "model":"DRAFT","thermal_input_kw":load_kw,"gas_consumption_m3h":flow,
          "datasheet":{"official_url":"INPUT_REQUIRED","revision":"DRAFT","sha256":"0"*64},
          "appliance_valve":"required","flue":"required","combustion_air":"required"}]
        result=design_gas_network(
            [{"id":edge_id,"downstream_appliance_ids":["DRAFT-GAS-AGG"],"equivalent_length_m":25}],appliances,
            {"capacity_table":[{"max_equivalent_length_m":30,"max_flow_m3h":8,"dn_mm":32}],
             "service_pressure_mbar":float(mechanical_workflow._numeric(
                 answers.get("gas_pressure")) or 20),"allowable_pressure_drop_mbar":1,
             "meter":"DRAFT_UNSELECTED","regulator":"DRAFT_UNSELECTED","service_shutoff":"required",
             "riser":"DRAFT","fittings":"DRAFT","sleeves":"required"})
        if result.get("status")!="PASS": return None
        sized=result["segments"][0]; calc_id=sized["calc_id"]
        edge={"id":edge_id,"system":"gas","material":"BLACK_STEEL","calc_id":calc_id,
              "flow_m3_h":sized["flow_m3h"],"inlet_pressure_mbar":sized["service_pressure_mbar"],
              "size":sized["selected_dn_mm"]}
        row={**edge,"calculation_engine":"design_gas_network","source_input_ids":source_ids,
             "formula_inputs":{"thermal_input_kw":load_kw,"gas_consumption_m3h":flow,
                               "equivalent_length_m":25,"basis_status":"PROVISIONAL_DRAFT"}}
    else:
        airflow=round(float(totals.get("exhaust_cfm") or 0)*0.47194745,3)
        sized=size_round_duct(airflow,6,[200,250,315,355,400])
        if sized.get("status")!="PASS": return None
        calc_id=sized["calc_id"]
        edge={"id":edge_id,"system":"exhaust_ventilation","material":"GI","calc_id":calc_id,
              "airflow_lps":airflow,"velocity_m_s":sized["selected"]["velocity_m_s"],
              "size":sized["selected"]["diameter_mm"]}
        row={**edge,"calculation_engine":"duct_velocity_sizing","source_input_ids":source_ids,
             "formula_inputs":{"required_cfm":totals["exhaust_cfm"],"max_velocity_m_s":6,
                               "basis_status":"PROVISIONAL_DRAFT"}}
    return {"network_graph_canonical":{"nodes":[],"edges":[edge]},
            "calculation_rows_canonical":[row]}


def _system_deliverable_definitions(legacy, project, revision):
    """Materialize source-bound per-system DRAFT snapshots without inventing inputs."""
    from cad_engine.independent_deliverables import SYSTEM_PACKAGES
    analysis = dict(project.analysis or {})
    draft = dict(analysis.get("independent_draft_scope") or {})
    drawing_set = dict(draft.get("drawing_set_proposal") or analysis.get("drawing_set") or {})
    manifest = dict(drawing_set.get("approved_manifest") or drawing_set.get("drawing_manifest") or {})
    architecture = dict((analysis.get("architectural_auto") or {}).get("architecture_model") or {})
    derived = dict(architecture.get("llm_derived_canonical") or {})
    provisional = dict(derived.get("provisional_completeness") or {})
    source_sha = str(draft.get("source_sha256") or
                     (architecture.get("source_identity") or {}).get("sha256") or "")
    if provisional.get("status") != "PROVISIONAL_READY" or not source_sha:
        return []
    project_dir = Path(legacy.DATA_DIR) / "projects" / str(project.id)
    archive_path, dxf_path = project_dir / "architecture.zip", project_dir / "architecture.dxf"
    if archive_path.exists():
        archive_bytes = archive_path.read_bytes()
    elif dxf_path.exists():
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(dxf_path.name, dxf_path.read_bytes())
        archive_bytes = stream.getvalue()
    else:
        return []
    answers = dict(project.answers or {})
    from app.project_mechanical_model import build_project_mechanical_model
    scope = mechanical_workflow.build_scope(project)
    draft_pmm = build_project_mechanical_model(analysis, answers, scope, drawing_set)
    # This authority increase is confined to reversible DRAFT tasks.  The
    # canonical project PMM and every execution/release gate remain unchanged.
    draft_pmm["mode"] = "provisional-interpretation-draft"
    draft_pmm["architecture_completeness"] = {
        "status":"PROVISIONAL_READY", "downstream_engineering_allowed":True,
        "release_allowed":False, "authority":"MODEL_PROPOSED_REVERSIBLE",
        "source_sha256":source_sha,
    }
    draft_pmm["canonical_architecture_authority"] = {
        **dict(draft_pmm.get("canonical_architecture_authority") or {}),
        "downstream_engineering_allowed":True, "release_allowed":False,
        "policy":"PROVISIONAL_DRAFT_ONLY_NO_RELEASE_AUTHORITY",
    }
    draft_pmm["diagnostics"] = [row for row in draft_pmm.get("diagnostics") or []
                                if row not in {"architecture_completeness_input_required",
                                               "canonical_architecture_authority_input_required"}]
    draft_pmm["valid"] = not any(row in {"planner_total_does_not_match_manifest_count",
        "no_architecture_levels_in_pmm","duplicate_pmm_entity_id"} for row in draft_pmm["diagnostics"])
    fixture_text = str(answers.get("fixture_schedule") or "")
    number = lambda value: mechanical_workflow._numeric(value) is not None
    fixture_rows = list(((analysis.get("architectural_auto") or {})
                         .get("fixture_detections") or []))
    design_overlay = dict(analysis.get("draft_design_overlay") or {})
    overlay_fixtures = [row for row in design_overlay.get("fixture_endpoints") or []
                        if isinstance(row, dict)]
    plumbing_kinds = {"wc", "toilet", "basin", "sink", "shower", "floor_drain", "bath"}
    wet_room_types = {"bathroom", "toilet", "wc", "kitchen", "laundry", "wet_room"}
    has_located_plumbing = any(
        str(row.get("type") or row.get("kind") or "").lower() in plumbing_kinds
        and (row.get("point") or (row.get("x") is not None and row.get("y") is not None))
        and (row.get("wet_core_id") or str(row.get("room_type") or "").lower() in wet_room_types)
        and str(row.get("source_sha256") or "") == source_sha
        for row in fixture_rows if isinstance(row,dict))
    has_located_plumbing = has_located_plumbing or any(
        str(row.get("type") or "").lower() in plumbing_kinds
        and row.get("point") and row.get("authority") == "MODEL_PROPOSED_DESIGN_ASSUMPTION"
        and row.get("source_sha256") == source_sha and row.get("release_allowed") is False
        for row in overlay_fixtures)
    has_real_shaft = bool(architecture.get("shafts") or architecture.get("vertical_cores")
                          or design_overlay.get("shafts"))
    # Readiness is evidence, not intent.  In particular a selected system is
    # not proof that its engineering loads exist.  Keep these checks tied to
    # values already recorded on this project so an independent package cannot
    # enter the queue on a synthetic True flag.
    ventilation_basis = answers.get("ventilation_design_basis")
    ventilation_loads = (answers.get("ventilation_airflow_lps") or
                         answers.get("ventilation_airflow_m3_h") or
                         answers.get("airflow_schedule"))
    load_provenance = dict(answers.get("_engineering_input_provenance") or {})
    overlay_basis = dict(design_overlay.get("engineering_basis") or {})
    calculation_basis = dict((design_overlay.get("deterministic_calculation") or {}).get("design_basis") or {})
    typed_ventilation_spaces = list(calculation_basis.get("ventilation_spaces") or [])
    def traceable_load(key):
        record = dict(load_provenance.get(key) or {})
        basis_name = {"heating_load_kw": "heating_design_basis",
                      "cooling_load_kw": "cooling_design_basis"}.get(key)
        basis = dict(overlay_basis.get(basis_name) or {}) if basis_name else {}
        if (not record and basis.get("authority") == "OWNER_DECLARED_PROJECT_FACT"
                and basis.get(key) == answers.get(key)):
            record = {"authority": "OWNER_DECLARED_PROJECT_FACT",
                      "source_sha256": source_sha}
        return (number(answers.get(key)) and record.get("authority") in {
            "USER_CONFIRMED", "ENGINEERING_CALCULATION", "SOURCE_DOCUMENT",
            "MODEL_PROPOSED_DRAFT_CALCULATION", "OWNER_DECLARED_PROJECT_FACT",
        } and (not record.get("source_sha256") or record.get("source_sha256") == source_sha))
    evidence_by_type = {
        "MECH_WATER_SUPPLY_PACKAGE":{"water_pressure_basis":number(answers.get("water_inlet_pressure") or answers.get("water_pressure")),"fixture_schedule":bool(re.search(r"\d", fixture_text)) and has_located_plumbing},
        "MECH_SANITARY_VENT_PACKAGE":{"fixture_schedule":bool(re.search(r"\d", fixture_text)) and has_located_plumbing,"shaft_coordination":bool(mechanical_workflow.shaft_approval(answers)) and has_real_shaft},
        "MECH_HEATING_PACKAGE":{"heating_basis":bool(mechanical_workflow.canonical_heating_system(answers)),"heating_loads":traceable_load("heating_load_kw")},
        "MECH_COOLING_PACKAGE":{"cooling_basis":bool(mechanical_workflow.canonical_cooling_system(answers)),"cooling_loads":traceable_load("cooling_load_kw")},
        "MECH_GAS_PACKAGE":{"gas_pressure_basis":number(answers.get("gas_pressure")) and number(answers.get("gas_relative_density")),"gas_appliance_loads":number(answers.get("gas_appliance_load_kw")) or number(answers.get("gas_appliance_load_m3_h"))},
        "MECH_VENTILATION_PACKAGE":{"ventilation_basis":bool(str(ventilation_basis or "").strip()) or bool(typed_ventilation_spaces),"airflow_loads":number(ventilation_loads) or bool(typed_ventilation_spaces)},
    }
    definitions=[]
    for deliverable_type, system in SYSTEM_PACKAGES.items():
        sheets=[dict(row) for row in manifest.get("sheets") or [] if row.get("family")==system["family"]]
        if not sheets: continue
        filtered={k:v for k,v in manifest.items() if k not in {"sheets","total_sheets","manifest_id"}}
        filtered.update({"sheets":sheets,"total_sheets":len(sheets)})
        pmm_for_system = deepcopy(draft_pmm)
        task_analysis={**analysis,"project_mechanical_model":pmm_for_system}
        domain_contract=_draft_domain_contract(deliverable_type,design_overlay,answers)
        if domain_contract: task_analysis.update(domain_contract)
        if deliverable_type in {"MECH_HEATING_PACKAGE", "MECH_COOLING_PACKAGE",
                                "MECH_GAS_PACKAGE", "MECH_VENTILATION_PACKAGE"}:
            from cad_engine.independent_deliverables import _draft_domain_routed_graph
            routed = _draft_domain_routed_graph(
                deliverable_type, pmm_for_system, architecture, design_overlay, answers)
            if routed and routed.get("status") == "PASS":
                task_analysis["network_graph_canonical"] = routed["network_graph"]
                task_analysis["calculation_rows_canonical"] = routed["calculation_rows"]
        enabled = set(system["runtime_systems"])
        pmm_systems = dict(pmm_for_system.get("systems") or {})
        family_keys = {
            "conditioned_levels":{"cooling","condensate"}, "heated_levels":{"heating_supply","heating_return"},
            "wet_fixture_levels":{"cold_water","hot_water"}, "sanitary_fixture_levels":{"sanitary","vent"},
            "ventilation_required_levels":{"exhaust_ventilation"}, "gas_consumer_levels":{"gas"},
        }
        for key, owners in family_keys.items():
            if not (enabled & owners): pmm_systems[key]=[]
        pmm_systems["roof_exists"]=False
        pmm_for_system["systems"]=pmm_systems
        snapshot={"source_sha256":source_sha,"architecture_archive_b64":base64.b64encode(archive_bytes).decode(),
            "provisional_architecture":{"status":"PROVISIONAL_READY","draft_engineering_allowed":True,
                "release_allowed":False,"source_sha256":source_sha,"lineage":derived.get("counts") or {}},
            "draft_design_overlay":design_overlay,
            "approved_draft_manifest":filtered,"answers":answers,"plan_analysis":task_analysis,
            "revision":revision.revision_no}
        evidence={"source_geometry":True,"draft_architecture_interpretation":True,"system_scope":True,
                  "cross_system_coordination":False,**evidence_by_type[deliverable_type]}
        definitions.append({"deliverable_type":deliverable_type,"scope_key":system["family"].upper(),
                            "evidence":evidence,"input_snapshot":snapshot})
    return definitions


def _select_independent_definitions(persisted, fresh_system, *, refresh_system_definitions=False):
    persisted = list(persisted or [])
    if not refresh_system_definitions:
        return persisted or list(fresh_system or [])
    from cad_engine.independent_deliverables import SYSTEM_PACKAGES
    # Retain separately produced/custom deliverables, but a stale system
    # snapshot must never hide evidence materialized later in the same paid
    # workflow.  Fresh rows remain source/revision bound by their builder.
    retained = [row for row in persisted if isinstance(row, dict)
                and row.get("deliverable_type") not in SYSTEM_PACKAGES]
    return retained + list(fresh_system or [])


def _schedule_paid_independent_deliverables(
        db, legacy, project, revision, order, *, refresh_system_definitions=False):
    """Atomically bridge a paid order to source-qualified independent outputs.

    The architecture/analysis producer owns these snapshots. Checkout neither
    invents missing evidence nor promotes blocked definitions.
    """
    if os.environ.get("INDEPENDENT_DELIVERABLES_ENABLED", "0") != "1":
        return []
    if not all(hasattr(legacy, name) for name in (
        "EngineeringDeliverable", "DeliverableTask",
    )):
        return []
    persisted = (project.analysis or {}).get("independent_deliverables")
    fresh_system = (_system_deliverable_definitions(legacy, project, revision)
                    if refresh_system_definitions or not persisted else [])
    definitions = _select_independent_definitions(
        persisted, fresh_system,
        refresh_system_definitions=refresh_system_definitions,
    )
    diagnostic_preview = _source_bound_rainwater_preview_definition(legacy, project)
    if diagnostic_preview and not any(
            isinstance(row, dict) and row.get("deliverable_type") ==
            "MECH_ROOF_RAINWATER_SOURCE_PREVIEW" for row in definitions):
        definitions.append(diagnostic_preview)
    diagnostic_types = {
        "MECH_HEATING_PACKAGE": "MECH_HEATING_SOURCE_DIAGNOSTIC_PREVIEW",
        "MECH_COOLING_PACKAGE": "MECH_COOLING_SOURCE_DIAGNOSTIC_PREVIEW",
    }
    for definition in list(definitions):
        if not isinstance(definition, dict):
            continue
        diagnostic_type = diagnostic_types.get(definition.get("deliverable_type"))
        if not diagnostic_type or any(
                isinstance(row, dict) and row.get("deliverable_type") == diagnostic_type
                for row in definitions):
            continue
        evidence = dict(definition.get("evidence") or {})
        required = ({"source_geometry", "draft_architecture_interpretation", "system_scope",
                     "heating_basis", "heating_loads"}
                    if definition.get("deliverable_type") == "MECH_HEATING_PACKAGE" else
                    {"source_geometry", "draft_architecture_interpretation", "system_scope",
                     "cooling_basis", "cooling_loads"})
        # A diagnostic may display only a graph the normal typed producer can
        # actually derive.  Missing system evidence stays fail-closed and does
        # not gain a preview merely from payment or a source file.
        definitions.append({
            "deliverable_type": diagnostic_type,
            "scope_key": (str(definition.get("scope_key") or "PROJECT") +
                          "-SOURCE-DIAGNOSTIC")[:150],
            "evidence": {"source_geometry": bool(evidence.get("source_geometry")),
                         "draft_network_evidence": all(bool(evidence.get(key)) for key in required)},
            "input_snapshot": definition.get("input_snapshot"),
        })
    rainwater_snapshot = (project.analysis or {}).get("roof_rainwater_draft_snapshot")
    if not isinstance(rainwater_snapshot, dict):
        rainwater_snapshot = _source_bound_rainwater_snapshot(
            project.analysis or {}, project.answers or {})
    if isinstance(rainwater_snapshot, dict):
        from cad_engine.independent_deliverables import derive_rainwater_readiness_evidence
        evidence = derive_rainwater_readiness_evidence(rainwater_snapshot)
        for deliverable_type in ("MECH_ROOF_RAINWATER_CALC", "MECH_ROOF_RAINWATER_PLAN"):
            definitions.append({
                "deliverable_type": deliverable_type,
                "scope_key": "PLAN06-ROOF",
                "evidence": evidence,
                "input_snapshot": rainwater_snapshot,
            })
    if not isinstance(definitions, list):
        raise RuntimeError("INDEPENDENT_DELIVERABLE_DEFINITIONS_INVALID")
    from cad_engine.independent_deliverables import REGISTRY
    from .independent_deliverable_worker import schedule_deliverable
    scheduled = []
    for definition in definitions:
        if not isinstance(definition, dict):
            raise RuntimeError("INDEPENDENT_DELIVERABLE_DEFINITION_INVALID")
        deliverable_type = str(definition.get("deliverable_type") or "")
        if deliverable_type not in REGISTRY:
            raise RuntimeError("INDEPENDENT_DELIVERABLE_TYPE_NOT_REGISTERED")
        evidence = definition.get("evidence")
        snapshot = definition.get("input_snapshot")
        if not isinstance(evidence, dict) or not isinstance(snapshot, dict):
            raise RuntimeError("INDEPENDENT_DELIVERABLE_EVIDENCE_INVALID")
        # This bridge runs only inside the transaction that has just marked the
        # server-owned checkout as paid.  Entitlement is therefore authoritative
        # here and must not depend on a stale producer snapshot.
        evidence = {**evidence, "paid_order": True}
        deliverable, task, created = schedule_deliverable(
            db, legacy.EngineeringDeliverable, legacy.DeliverableTask,
            project_id=project.id, revision_id=revision.id,
            order_identity=order.external_id,
            deliverable_type=deliverable_type,
            scope_key=str(definition.get("scope_key") or "PROJECT")[:150],
            evidence=evidence, input_snapshot=snapshot, commit=False,
        )
        scheduled.append({"deliverable_id": deliverable.id,
                          "task_id": task.id if task else None,
                          "created": created,
                          "status": deliverable.processing_state})
    from .architecture_autopilot import record_generation_phase
    rows=db.query(legacy.EngineeringDeliverable).filter(
        legacy.EngineeringDeliverable.project_id==project.id).all()
    record_generation_phase(project,rows)
    return scheduled


def schedule_independent_deliverables_after_analysis(db, legacy, project, revision, order):
    """Re-evaluate independent families after their real producers have run.

    Payment-time scheduling is intentionally retained for evidence already
    available then.  Architecture interpretation, the project-bound resolver
    and typed engineering overlays finish later, however.  This second,
    idempotent pass uses the same order identity and snapshot hash, allowing a
    ready family (for example Heating) to proceed without weakening blockers
    on Plumbing, Gas, Cooling, Ventilation or Rainwater.
    """
    if not order or not getattr(order, "paid", False):
        return []
    if not revision or revision.project_id != project.id:
        raise RuntimeError("INDEPENDENT_DELIVERABLE_REVISION_MISMATCH")
    scheduled = _schedule_paid_independent_deliverables(
        db, legacy, project, revision, order,
        refresh_system_definitions=True,
    )
    analysis = deepcopy(project.analysis or {})
    architecture_fingerprint = str(
        (analysis.get("architecture_autopilot") or {}).get("checkpoint_fingerprint") or "")
    status_rows = sorted(
        ({"deliverable_id": int(row.get("deliverable_id") or 0),
          "status": str(row.get("status") or "UNKNOWN"),
          "task_id": int(row["task_id"]) if row.get("task_id") is not None else None,
          "created": bool(row.get("created"))} for row in scheduled),
        key=lambda row: (row["deliverable_id"], row["status"]),
    )
    identity_basis = {
        "project_id": project.id,
        "revision_id": revision.id,
        "revision_no": revision.revision_no,
        "architecture_checkpoint_fingerprint": architecture_fingerprint,
        "systems": status_rows,
    }
    fingerprint = hashlib.sha256(json.dumps(
        identity_basis, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    prior = dict(analysis.get("post_analysis_system_reevaluation") or {})
    checkpoint = {
        "schema": "planha-post-analysis-system-reevaluation/1.0",
        **identity_basis,
        "fingerprint": fingerprint,
        "ready_or_queued": sum(row["status"] in {"READY", "QUEUED", "RUNNING", "AVAILABLE"}
                               for row in status_rows),
        "blocked": sum(row["status"] in {"BLOCKED_INPUT", "INPUT_REQUIRED"}
                       for row in status_rows),
        "evaluated_at": (prior.get("evaluated_at") if prior.get("fingerprint") == fingerprint
                         else datetime.utcnow().isoformat()+"Z"),
        "fresh_current_revision": True,
        "independent_failures_do_not_block_siblings": True,
    }
    analysis["post_analysis_system_reevaluation"] = checkpoint
    project.analysis = analysis
    return scheduled


def _source_bound_rainwater_snapshot(analysis, answers):
    """Build a DRAFT roof contract only from one qualified source assembly.

    Boundary/drain/capacity values must all be authored in the uploaded DXF.
    Stack, catchment partition, route and overflow remain reversible proposals;
    rainfall is an explicit user input and is never promoted to official data.
    """
    auto=dict((analysis or {}).get("architectural_auto") or {})
    candidates=[row for row in auto.get("roof_rainwater_evidence_candidates") or []
                if row.get("source_plan_type")=="ROOF_PLAN"
                and row.get("source_plan_role")=="ROOF_SUPPORT"
                and row.get("source_symbol_semantic_role")=="ROOF_FLOOR_DRAIN"
                and len(row.get("source_plan_bounds") or [])==4
                and row.get("source_plan_boundary_handle")
                and row.get("symbol_handle") and row.get("source_capacity_lps")]
    if len(candidates)!=1: return None
    candidate=candidates[0]
    rainfall=mechanical_workflow._numeric(
        answers.get("rainfall_intensity_mm_h") or answers.get("rainfall_intensity"))
    if rainfall is None or float(rainfall)<=0: return None
    bounds=list(map(float,candidate["source_plan_bounds"])); x1,y1,x2,y2=bounds
    boundary=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
    drain=list(map(float,candidate["point"])); stack=[drain[0],y1]
    slopes=[]
    for value in candidate.get("slope_annotations") or []:
        number=mechanical_workflow._numeric(value)
        if number is not None: slopes.append(float(number))
    if not slopes or min(slopes)<=0: return None
    capacity=float(candidate["source_capacity_lps"]); dn=float(candidate["nominal_diameter_mm"])
    source_sha=str(candidate.get("source_sha256") or "")
    if len(source_sha)!=64: return None
    catchment_id="CATCHMENT-"+hashlib.sha256((source_sha+str(candidate["candidate_id"])).encode()).hexdigest()[:12].upper()
    return {"roof":{"roof_id":"ROOF-"+source_sha[:12].upper(),"boundary":boundary,
        "stacks":[{"id":"RW-STACK-1","point":stack,"authority":"NEW_PROPOSED_DRAFT",
                   "release_allowed":False}],
        "catchments":[{"id":catchment_id,"polygon":boundary,"low_point":drain,
            "drain":{"id":"RW-DRAIN-1","point":drain,
                     "source_handle":candidate["symbol_handle"],
                     "semantic_role":"ROOF_FLOOR_DRAIN",
                     "semantic_role_authority":candidate.get("semantic_role_authority"),
                     "connection_authority":"SOURCE_BOUND_DRAFT"},
            "stack_id":"RW-STACK-1","slope_percent":min(slopes),
            "route":([drain,stack] if drain[0]==stack[0] or drain[1]==stack[1]
                     else [drain,[stack[0],drain[1]],stack]),
            "emergency_overflow":{"type":"scupper","point":[x2,drain[1]],
                                  "authority":"NEW_PROPOSED_DRAFT"}}]},
        "design_basis":{"rainfall_intensity_mm_h":float(rainfall),"runoff_coefficient":1.0,
            "minimum_slope_percent":min(slopes),
            "drain_capacity_table":[{"dn_mm":dn,"max_flow_lps":capacity}],
            "downpipe_capacity_table":[{"dn_mm":dn,"max_flow_lps":capacity}]},
        "geometry_provenance":{"source_sha256":source_sha,
            "roof_boundary_source_handles":[candidate["source_plan_boundary_handle"]],
            "drain_source_handles":[candidate["symbol_handle"]],
            "capacity_source_handles":[candidate["pipe_note_handle"]]},
        "draft_assumption_basis":{"assumption_origin":"SOURCE_BOUND_DETERMINISTIC_DRAFT",
            "rainfall_authority":"USER_CONFIRMED_UNVERIFIED","capacity_authority":"SOURCE_DOCUMENT_UNVERIFIED",
            "release_allowed":False}}


def _source_bound_rainwater_preview_definition(legacy, project):
    """Build a publishable diagnostic-only source overlay contract.

    This never supplies hydraulic readiness. It only packages exact current
    source entities plus unresolved source-bound markers for customer review.
    """
    analysis = dict(project.analysis or {})
    candidates = [row for row in ((analysis.get("architectural_auto") or {})
                                  .get("roof_rainwater_evidence_candidates") or [])
                  if row.get("source_plan_type") in {"SLOPE_PLAN", "ROOF_PLAN"}
                  and row.get("source_plan_id") and row.get("symbol_handle")
                  and len(row.get("source_plan_bounds") or []) == 4
                  and len(row.get("point") or []) == 2
                  and len(str(row.get("source_sha256") or "")) == 64]
    if not candidates:
        return None
    source_shas = {str(row["source_sha256"]) for row in candidates}
    if len(source_shas) != 1:
        return None
    project_dir = Path(legacy.DATA_DIR) / "projects" / str(project.id)
    archive_path = project_dir / "architecture.zip"
    dxf_paths = list(project_dir.glob("*.dxf"))
    if archive_path.exists():
        archive_bytes = archive_path.read_bytes()
    elif len(dxf_paths) == 1:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(dxf_paths[0].name, dxf_paths[0].read_bytes())
        archive_bytes = stream.getvalue()
    else:
        return None
    plans = {}
    evidence = []
    for index, row in enumerate(candidates, 1):
        plan_id = str(row["source_plan_id"])
        plan = {"plan_id": plan_id, "drawing_type": row["source_plan_type"],
                "bounds": list(row["source_plan_bounds"])}
        if plan_id in plans and plans[plan_id] != plan:
            return None
        plans[plan_id] = plan
        evidence.append({"label":"RW-DIAG-%02d" % index,
            "symbol_handle":str(row["symbol_handle"]), "point":list(row["point"]),
            "source_plan_id":plan_id, "source_sha256":str(row["source_sha256"]),
            "nominal_diameter_mm":row.get("nominal_diameter_mm"),
            "source_symbol_semantic_role":row.get("source_symbol_semantic_role"),
            "semantic_role_authority":row.get("semantic_role_authority"),
            "connection_authority":row.get("connection_authority") or "UNRESOLVED",
            "evidence_status":"UNRESOLVED", "owner_attestation":"UNRESOLVED",
            "roof_tier":row.get("roof_tier") or "UNRESOLVED",
            "source_elevation_text":row.get("source_elevation_text") or "UNRESOLVED"})
    snapshot = {"source_sha256":next(iter(source_shas)),
        "architecture_archive_b64":base64.b64encode(archive_bytes).decode(),
        "source_plans":[plans[key] for key in sorted(plans)],
        "source_evidence":evidence,
        "diagnostic_contract":{"engineering_release_allowed":False,
            "review_required":True, "hydraulic_authority":False}}
    return {"deliverable_type":"MECH_ROOF_RAINWATER_SOURCE_PREVIEW",
            "scope_key":"PLAN05-ROOF-DIAGNOSTIC", "input_snapshot":snapshot,
            "evidence":{"paid_order":True,"source_geometry":True,
                        "source_diagnostic_points":True}}


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def sign(value):
    secret = os.environ.get("PANEL_BRIDGE_TOKEN", "")
    if not secret:
        raise HTTPException(503, "ارتباط پنل تنظیم نشده است.")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def authorize_bridge(request):
    supplied = request.headers.get("x-panel-token", "")
    secret = os.environ.get("PANEL_BRIDGE_TOKEN", "")
    if not secret or not secrets.compare_digest(secret, supplied):
        raise HTTPException(404)


def session_user(request):
    authorize_bridge(request)
    token = request.headers.get("x-customer-session", "")
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "دوباره وارد پنل شوید.")
    uid, expiry, signature = parts
    if not uid.isdigit() or not expiry.isdigit() or int(expiry) <= time.time() or not secrets.compare_digest(signature, sign(f"customer:{uid}.{expiry}")):
        raise HTTPException(401, "نشست ورود منقضی شده است.")
    return int(uid)


def unresolved_questions(project):
    """Same key, presentation and numeric validation for every entry point."""
    from .main_auto import _present_question
    answers = dict(project.answers or {})
    if answers.get("discipline") == "mechanical":
        answers = mechanical_workflow.normalize_answers(answers)
    project.answers = answers
    questions = {q["key"]: q for q in project.questions or [] if isinstance(q, dict) and q.get("key")}
    if answers.get("discipline") == "mechanical":
        for key in mechanical_workflow.required_basis_questions(project):
            questions[key] = mechanical_workflow._question_payload(key)
    missing = []
    for key, question in questions.items():
        if key == 'gas_pressure' and mechanical_workflow._negative(answers.get('gas')):
            continue
        value = answers.get(key)
        if value is None or not str(value).strip() or mechanical_workflow._basis_answer_error(key, str(value)):
            missing.append(_present_question(question))
    return missing


def register_panel_checkout(app, legacy, Job, Link, status_payload, project_token):
    class Handoff(legacy.Base):
        __tablename__ = "panel_handoffs"
        token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
        expires: Mapped[int] = mapped_column(Integer)
        claimed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    class Checkout(legacy.Base):
        __tablename__ = "panel_checkouts"
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        external_id: Mapped[str] = mapped_column(String(80), unique=True)
        amount: Mapped[int] = mapped_column(Integer, default=0)
        quote_token: Mapped[str] = mapped_column(String(64), default="")
        paid: Mapped[int] = mapped_column(Integer, default=0)
        area: Mapped[str] = mapped_column(String(40), default="")

    class Ledger(legacy.Base):
        __tablename__ = "panel_wallet_ledger"
        id: Mapped[str] = mapped_column(String(80), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
        amount: Mapped[int] = mapped_column(Integer)
        balance_after: Mapped[int] = mapped_column(Integer)
        created_at: Mapped[str] = mapped_column(String(40))

    class Profile(legacy.Base):
        __tablename__ = "panel_customer_profiles"
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
        phone: Mapped[str] = mapped_column(String(20))

    class Activity(legacy.Base):
        __tablename__ = "panel_account_activity"
        id: Mapped[str] = mapped_column(String(120), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        request_hash: Mapped[str] = mapped_column(String(64))
        kind: Mapped[str] = mapped_column(String(40))
        amount: Mapped[int] = mapped_column(Integer)
        balance_after: Mapped[int] = mapped_column(Integer)
        description: Mapped[str] = mapped_column(String(500))
        actor: Mapped[str] = mapped_column(String(100))
        created_at: Mapped[str] = mapped_column(String(40))

    class PanelProject(legacy.Base):
        __tablename__ = "panel_customer_projects"
        id: Mapped[str] = mapped_column(String(80), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        payload: Mapped[str] = mapped_column(Text)
        created_at: Mapped[str] = mapped_column(String(40))
        updated_at: Mapped[str] = mapped_column(String(40))

    for model in (Handoff, Checkout, Ledger, Profile, Activity, PanelProject):
        model.__table__.create(bind=legacy.engine, checkfirst=True)
    Wallet = app.state.commercial["Wallet"]
    pricing_for = app.state.commercial["service_pricing"]

    def apply_account_reconciliations():
        """Apply audited, idempotent wallet reconciliations configured for production."""
        raw = os.environ.get("PANEL_ACCOUNT_RECONCILIATIONS", "").strip()
        if not raw:
            return
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise RuntimeError("PANEL_ACCOUNT_RECONCILIATIONS must be a JSON list")
        with legacy.Session() as db:
            for entry in entries:
                uid = int(entry["user_id"])
                phone = re.sub(r"\D", "", str(entry["phone"]))
                amount = int(entry["amount"])
                request_id = str(entry["request_id"])
                if amount <= 0 or not re.fullmatch(r"[A-Za-z0-9-]{16,80}", request_id):
                    raise RuntimeError("Invalid account reconciliation entry")
                profile = db.get(Profile, uid)
                wallet = db.query(Wallet).filter(Wallet.user_id == uid).first()
                if not profile or re.sub(r"\D", "", profile.phone) != phone or not wallet:
                    raise RuntimeError(f"Account reconciliation target CUST-{uid} did not match")
                key = f"RECON-{uid}-{request_id}"
                if db.get(Activity, key):
                    continue
                wallet.balance += amount
                db.add(Activity(id=key, user_id=uid, request_hash=digest(json.dumps(entry, sort_keys=True)),
                                kind="account_reconciliation", amount=amount, balance_after=wallet.balance,
                                description=str(entry.get("reason", "Account reconciliation"))[:500],
                                actor="system-reconciliation", created_at=datetime.utcnow().isoformat()+'Z'))
            db.commit()

    apply_account_reconciliations()

    @app.middleware('http')
    async def freeze_claimed_drafts(request, call_next):
        match = re.fullmatch(r'/projects/(\d+)(?:/.*)?', request.url.path)
        if match and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            with legacy.Session() as db:
                if db.get(Checkout, int(match.group(1))):
                    return JSONResponse({'detail': 'این پروژه به پنل منتقل شده است؛ از پنل ادامه دهید.'}, status_code=409)
        return await call_next(request)

    def begin(db):
        # SQLite serializes before any reads; PostgreSQL locks the account below.
        if db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

    def account_id(uid):
        return f"CUST-{uid}"

    def require_account(db, uid):
        user = db.query(legacy.User).filter(legacy.User.id == uid).with_for_update().first()
        if not user or not db.get(Profile, uid):
            raise HTTPException(401)
        return user

    def account_history_score(db, uid):
        """Identify the established owner without treating an empty shell as history."""
        wallet = db.query(Wallet).filter(Wallet.user_id == uid).first()
        return sum((
            db.query(legacy.Project).filter(legacy.Project.user_id == uid).count(),
            db.query(Checkout).filter(Checkout.user_id == uid).count(),
            db.query(Ledger).filter(Ledger.user_id == uid).count(),
            db.query(Activity).filter(Activity.user_id == uid).count(),
            int(bool(wallet and wallet.balance)),
        ))

    def user_for_phone(db, phone):
        """Resolve a returning phone to its profile-backed account before creating one."""
        profiles = db.query(Profile).filter(Profile.phone == phone).order_by(Profile.user_id).all()
        if profiles:
            established = [p for p in profiles if account_history_score(db, p.user_id)]
            if len(established) > 1:
                raise HTTPException(409, "این شماره به چند حساب فعال متصل است؛ برای یکپارچه‌سازی حساب‌ها با پشتیبانی تماس بگیرید.")
            if established:
                return db.get(legacy.User, established[0].user_id)
            generated_email = f"phone-{digest(phone)}@panel.local"
            generated = db.query(legacy.User).filter(legacy.User.email == generated_email).first()
            if generated and any(p.user_id == generated.id for p in profiles):
                return generated
            return db.get(legacy.User, profiles[0].user_id)
        return db.query(legacy.User).filter(legacy.User.email == f"phone-{digest(phone)}@panel.local").first()

    def order_payload(db, order):
        project = db.get(legacy.Project, order.project_id)
        link = db.query(Link).filter(Link.project_id == project.id).first()
        data = authoritative_engine_state(db, project, link)
        return {"id": order.external_id, "owner": account_id(order.user_id), "title": project.name,
                "service": "طراحی برق" if (project.answers or {}).get("discipline") == "electrical" else "طراحی مکانیک",
                "area": float(order.area or 0), "amount": order.amount, "paid": bool(order.paid),
                "quoteToken": order.quote_token, "answers": {k: v for k, v in (project.answers or {}).items() if isinstance(v, (str, int, float, bool))}, "engine": data}

    def authoritative_engine_state(db, project, link):
        """Return one revisioned snapshot shared by customer and admin views."""
        data = status_payload(project)
        latest = (db.query(legacy.Revision)
                  .filter(legacy.Revision.project_id == project.id)
                  .order_by(legacy.Revision.revision_no.desc())
                  .first())
        state_revision = latest.revision_no if latest else (project.current_revision or 0)
        updated_at = ((data.get("design_progress") or {}).get("updated_at")
                      or (latest.created_at.isoformat() + "Z" if latest and latest.created_at else project.created_at.isoformat() + "Z"))
        data.update(
            engine_project_id=project.id,
            project_token=project_token(link.external_project_id, link.external_user_hash),
            state_revision=state_revision,
            state_updated_at=updated_at,
        )
        if data.get("output_ready") or project.status == "ready":
            data["output_ready"] = True
            data["progress"] = 100
            if data.get("design_progress"):
                data["design_progress"]["percent"] = 100
        return data

    def state(db, uid):
        require_account(db, uid)
        wallet = db.query(Wallet).filter(Wallet.user_id == uid).first()
        entries = db.query(Ledger).filter(Ledger.user_id == uid).order_by(Ledger.created_at.desc()).all()
        orders = db.query(Checkout).filter(Checkout.user_id == uid).all()
        by_project = {o.project_id: o.external_id for o in orders}
        activities = db.query(Activity).filter(Activity.user_id == uid).all()
        transactions = [{"id": e.id, "owner": account_id(uid), "project": by_project.get(e.project_id, ""),
                         "title": "پرداخت پروژه از کیف پول", "amount": -e.amount,
                         "date": e.created_at, "status": "موفق", "category": "پروژه", "balanceAfter": e.balance_after} for e in entries]
        transactions.extend({"id": e.id, "owner": account_id(uid), "project": "",
                             "title": e.description, "amount": e.amount, "balanceAfter": e.balance_after,
                             "date": e.created_at, "status": "آزمایشی" if e.kind.startswith('demo_') else "موفق",
                             "category": e.kind, "actor": e.actor} for e in activities)
        durable_projects = []
        order_ids = {o.external_id for o in orders}
        for row in db.query(PanelProject).filter(PanelProject.user_id == uid).order_by(PanelProject.created_at.desc()).all():
            if row.id in order_ids:
                continue
            try:
                project = json.loads(row.payload)
            except (TypeError, ValueError):
                continue
            project.update(id=row.id, owner=account_id(uid))
            # Imported projects used to carry a browser snapshot forever. When
            # they reference an engine project owned by this account, replace
            # that snapshot with the same authoritative state used by checkout
            # projects so account polling can never restore stale progress.
            try:
                engine_id = int(project.get("engineProjectId") or 0)
            except (TypeError, ValueError):
                engine_id = 0
            supplied_token = str(project.get("engineProjectToken") or "")
            if engine_id and supplied_token:
                engine_project = db.get(legacy.Project, engine_id)
                link = db.query(Link).filter(Link.project_id == engine_id).first()
                if (engine_project and link
                        and link.external_user_hash == digest(account_id(uid))
                        and secrets.compare_digest(
                            supplied_token,
                            project_token(link.external_project_id, link.external_user_hash),
                        )):
                    project["engine"] = authoritative_engine_state(db, engine_project, link)
            durable_projects.append(project)
        return {"userId": account_id(uid), "balance": wallet.balance if wallet else 0,
                "demoPayments": os.environ.get('PANEL_DEMO_PAYMENTS') == '1',
                "projects": [order_payload(db, o) for o in orders] + durable_projects,
                "transactions": sorted(transactions, key=lambda e: e['date'], reverse=True)}

    def import_projects(db, uid, rows):
        if not isinstance(rows, list) or len(rows) > 100:
            raise HTTPException(400, "فهرست پروژه‌ها معتبر نیست.")
        now = datetime.utcnow().isoformat() + "Z"
        allowed = {"title", "service", "area", "amount", "status", "progress", "date", "answers",
                   "engineProjectId", "engineProjectToken", "quoteToken", "paid", "designStage",
                   "designLabel", "designDetail", "designTimeline", "outputReady", "lastError"}
        for item in rows:
            if not isinstance(item, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", str(item.get("id", ""))):
                raise HTTPException(400, "یکی از پروژه‌ها معتبر نیست.")
            project_id = str(item["id"])
            payload = {key: item[key] for key in allowed if key in item}
            encoded = json.dumps(payload, ensure_ascii=False)
            if len(encoded.encode()) > 20000:
                raise HTTPException(400, "حجم اطلاعات پروژه بیش از حد مجاز است.")
            row = db.get(PanelProject, project_id)
            if row and row.user_id != uid:
                raise HTTPException(409, "این پروژه متعلق به حساب دیگری است.")
            if row:
                row.payload = encoded
                row.updated_at = now
            else:
                db.add(PanelProject(id=project_id, user_id=uid, payload=encoded, created_at=now, updated_at=now))

    def adjust(db, uid, body, *, demo=False):
        request_id = str(body.get('requestId', ''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,80}', request_id):
            raise HTTPException(400, 'شناسه درخواست معتبر نیست.')
        amount = body.get('amount')
        reason = str(body.get('reason', '')).strip()
        kind = body.get('kind', 'credit')
        if type(amount) is not int or not 0 < amount <= 100000000 or kind not in ('credit', 'debit') or not 1 <= len(reason) <= 500:
            raise HTTPException(400, 'مبلغ و دلیل تغییر موجودی را صحیح وارد کنید.')
        if demo and (os.environ.get('PANEL_DEMO_PAYMENTS') != '1' or kind != 'credit'):
            raise HTTPException(409, 'پرداخت آزمایشی فعال نیست.')
        delta = -amount if kind == 'debit' else amount
        fingerprint = digest(json.dumps([delta, reason, demo], ensure_ascii=False))
        key = f"{'DEMO' if demo else 'ADJ'}-{uid}-{request_id}"
        previous = db.get(Activity, key)
        if previous:
            if previous.request_hash != fingerprint:
                raise HTTPException(409, 'این شناسه قبلاً برای درخواست دیگری استفاده شده است.')
            return
        wallet = db.query(Wallet).filter(Wallet.user_id == uid).with_for_update().one()
        if wallet.balance + delta < 0:
            raise HTTPException(409, 'موجودی کیف پول کافی نیست.')
        wallet.balance += delta
        db.add(Activity(id=key, user_id=uid, request_hash=fingerprint, kind='demo_topup' if demo else 'admin_adjustment',
                        amount=delta, balance_after=wallet.balance, description=reason,
                        actor=account_id(uid) if demo else 'panel-admin', created_at=datetime.utcnow().isoformat()+'Z'))

    @app.post('/internal/panel/admin/accounts')
    async def admin_accounts(request: Request):
        # Only the server-side admin proxy can reach this route with the bridge secret.
        authorize_bridge(request)
        body = await request.json()
        with legacy.Session() as db:
            begin(db)
            if body.get('action') == 'wallet_adjustment':
                match = re.fullmatch(r'CUST-(\d+)', str(body.get('userId', '')))
                if not match:
                    raise HTTPException(400, 'شناسه حساب معتبر نیست.')
                uid = int(match.group(1))
                require_account(db, uid)
                adjust(db, uid, body)
                db.commit()
            elif body.get('action') != 'state':
                raise HTTPException(400)
            profiles = []
            for phone, in db.query(Profile.phone).distinct().order_by(Profile.phone).all():
                try:
                    profiles.append(db.get(Profile, user_for_phone(db, phone).id))
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    # Keep genuinely active duplicates visible to administrators
                    # so they can be reconciled; only empty shells are collapsed.
                    profiles.extend(db.query(Profile).filter(Profile.phone == phone).order_by(Profile.user_id).all())
            accounts = [state(db, p.user_id) for p in profiles]
            return {'users': [{'id': account_id(p.user_id), 'mobile': p.phone, 'name': p.phone,
                               'wallet': a['balance'], 'active': True, 'admin': False, 'email': ''}
                              for p, a in zip(profiles, accounts)],
                    # Administration is an inventory view, not a payment report.
                    # Keep durable legacy/draft projects visible even when they
                    # do not have a paid checkout record.
                    'projects': [p for a in accounts for p in a['projects']],
                    'transactions': [t for a in accounts for t in a['transactions']]}

    @app.post("/internal/panel/customer/session")
    async def login(request: Request):
        authorize_bridge(request)
        body = await request.json()
        phone = str(body.get("phone", "")).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if not re.fullmatch(r"09\d{9}", phone, flags=re.ASCII):
            raise HTTPException(400, "شماره موبایل معتبر وارد کنید.")
        with legacy.Session() as db:
            begin(db)
            email = f"phone-{digest(phone)}@panel.local"
            user = user_for_phone(db, phone)
            if not user:
                user = legacy.User(email=email)
                db.add(user); db.flush()
            if not db.query(Wallet).filter(Wallet.user_id == user.id).first():
                db.add(Wallet(user_id=user.id, balance=0))
            if not db.get(Profile, user.id):
                db.add(Profile(user_id=user.id, phone=phone))
            db.commit()
            expiry = int(time.time()) + 86400
            token = f"{user.id}.{expiry}"
            return {**state(db, user.id), "session": f"{token}.{sign('customer:' + token)}"}

    @app.post("/projects/{pid}/panel-handoff")
    def handoff(pid: int, request: Request):
        user = legacy.current_user(request)
        db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        try:
            if project.status not in ("asking", "ready_to_design", "drawing_set_review"):
                raise HTTPException(409, "تحلیل فایل هنوز کامل نشده است.")
            missing = unresolved_questions(project)
            if missing:
                project.questions = missing
                project.current_question = 0
                project.status = "asking"
                db.commit()
                return JSONResponse(legacy.flow_payload(project), status_code=409)
            token = secrets.token_urlsafe(32)
            db.add(Handoff(token_hash=digest(token), project_id=pid, expires=int(time.time()) + 86400))
            db.commit()
            origin = os.environ.get("PANEL_PUBLIC_URL", "https://engitools-admin.finodex-2798.chatgpt.site").rstrip("/")
            return {"url": f"{origin}/panel/projects/new#handoff={token}"}
        finally:
            db.close()

    @app.post("/internal/panel/customer/{action}")
    async def customer(action: str, request: Request):
        uid = session_user(request)
        body = await request.json()
        if action not in ("state", "import", "claim", "quote", "pay", "topup"):
            raise HTTPException(404)
        with legacy.Session() as db:
            begin(db)
            require_account(db, uid)
            if action == "state":
                return state(db, uid)
            if action == "import":
                import_projects(db, uid, body.get("projects"))
                db.commit()
                return state(db, uid)
            if action == 'topup':
                adjust(db, uid, {**body, 'kind': 'credit', 'reason': 'افزایش موجودی آزمایشی — بدون برداشت بانکی'}, demo=True)
                db.commit()
                return state(db, uid)
            if action == "claim":
                row = db.get(Handoff, digest(body.get("token", "")))
                if not row or row.expires < time.time() or row.claimed_by not in (None, uid):
                    raise HTTPException(404, "پیوند انتقال معتبر نیست یا منقضی شده است.")
                row.claimed_by = uid
                project = db.get(legacy.Project, row.project_id)
                order = db.get(Checkout, project.id)
                if order and order.user_id != uid:
                    raise HTTPException(404)
                if not order:
                    external_id = f"PRJ-{secrets.token_hex(8)}"
                    user_hash = digest(account_id(uid))
                    db.add(Link(external_project_id=external_id, external_user_hash=user_hash, project_id=project.id,
                                access_token_hash=digest(project_token(external_id, user_hash))))
                    order = Checkout(project_id=project.id, user_id=uid, external_id=external_id)
                    db.add(order)
                db.commit()
                from .main_auto import panel_analysis_payload, QUESTIONNAIRE_VERSION
                payload = order_payload(db, order)
                payload["analysis"] = {**panel_analysis_payload((project.analysis or {}).get("architectural_auto") or {}),
                                       "questions": [], "inferredAnswers": payload['answers'], "questionnaireVersion": QUESTIONNAIRE_VERSION}
                return payload
            try:
                pid = int(body.get("engineProjectId", 0))
            except (TypeError, ValueError):
                raise HTTPException(400)
            link = db.query(Link).filter(Link.project_id == pid).first()
            if not link or link.external_user_hash != digest(account_id(uid)):
                raise HTTPException(404)
            project = db.get(legacy.Project, pid)
            order = db.get(Checkout, pid)
            if not order:
                order = Checkout(project_id=pid, user_id=uid, external_id=link.external_project_id)
                db.add(order); db.flush()
            if order.paid:
                return {"project": order_payload(db, order), **state(db, uid)}
            if action == "quote":
                supplied = body.get("answers") or {}
                if not isinstance(supplied, dict):
                    raise HTTPException(400)
                # Do not let a client change discipline or inject internal fields.
                allowed = {q.get("key") for q in project.questions or [] if isinstance(q, dict)}
                if (project.answers or {}).get("discipline") == "mechanical":
                    allowed.update(mechanical_workflow.required_basis_questions(project))
                answers = dict(project.answers or {})
                answers.update({k: v for k, v in supplied.items() if k in allowed and isinstance(v, (str, int, float))})
                project.answers = answers
                missing = unresolved_questions(project)
                if missing:
                    db.commit()
                    return JSONResponse({"status": "asking", "questions": missing, "question_count": len(missing), "error": "اطلاعات پروژه را تکمیل کنید."}, status_code=409)
                try:
                    area = float(body.get("area", 0))
                except (ValueError, TypeError):
                    area = 0
                if not math.isfinite(area) or not 0 < area <= 100000:
                    raise HTTPException(400, "مساحت پروژه را تأیید کنید.")
                # Pricing is read from the server, never from the browser's amount.
                db.commit()
                pricing = pricing_for(answers.get("discipline", "mechanical"))
                begin(db)
                require_account(db, uid)
                db.refresh(order)
                db.refresh(project)
                if order.paid:
                    return {"project": order_payload(db, order), **state(db, uid)}
                if not pricing["enabled"]:
                    raise HTTPException(409, "این خدمت فعال نیست.")
                order.amount = max(pricing["minimum_price"], int(round(area * pricing["price_per_m2"])))
                order.area = str(area)
                order.quote_token = digest(json.dumps([order.amount, project.answers, order.area], sort_keys=True, ensure_ascii=False))
                db.commit()
                return {"project": order_payload(db, order), **state(db, uid)}
            demo = body.get('method') == 'gateway' and os.environ.get('PANEL_DEMO_PAYMENTS') == '1'
            if body.get("method") != "wallet" and not demo:
                raise HTTPException(503, "درگاه بانکی هنوز متصل نیست؛ پرداختی انجام نشد.")
            if not order.quote_token or not secrets.compare_digest(str(body.get("quoteToken", "")), order.quote_token):
                raise HTTPException(409, "قیمت نهایی را دوباره دریافت و تأیید کنید.")
            current_quote = digest(json.dumps([order.amount, project.answers, order.area], sort_keys=True, ensure_ascii=False))
            if not secrets.compare_digest(current_quote, order.quote_token):
                raise HTTPException(409, "اطلاعات پروژه تغییر کرده است؛ دوباره قیمت را تأیید کنید.")
            missing = unresolved_questions(project)
            if missing:
                raise HTTPException(409, "اطلاعات پروژه تغییر کرده است؛ دوباره قیمت را تأیید کنید.")
            wallet = db.query(Wallet).filter(Wallet.user_id == uid).with_for_update().first()
            if not wallet or (not demo and wallet.balance < order.amount):
                raise HTTPException(409, "موجودی کیف پول کافی نیست؛ هیچ مبلغی کسر نشد.")
            if (project.answers or {}).get("discipline") == "mechanical":
                proposal = mechanical_workflow.create_proposal(project)
                analysis = dict(project.analysis or {})
                analysis["drawing_set"] = mechanical_workflow.approve_drawing_set(proposal)
                project.analysis = analysis
            if not demo:
                wallet.balance -= order.amount
            order.paid = 1
            if demo:
                db.add(Activity(id=f'DEMO-PAY-{pid}', user_id=uid, request_hash=order.quote_token, kind='demo_payment',
                                amount=-order.amount, balance_after=wallet.balance,
                                description=f'پرداخت آزمایشی پروژه {order.external_id} — بدون برداشت بانکی یا کیف پول',
                                actor=account_id(uid), created_at=datetime.utcnow().isoformat()+'Z'))
            else:
                db.add(Ledger(id=f"TXN-{secrets.token_hex(12)}", user_id=uid, project_id=pid, amount=order.amount,
                              balance_after=wallet.balance, created_at=datetime.utcnow().isoformat() + "Z"))
            revision = legacy.Revision(project_id=pid, revision_no=(project.current_revision or 0) + 1, status="queued")
            db.add(revision); db.flush()
            db.add(Job(job_type="design", project_id=pid, revision_id=revision.id, status="queued"))
            project.status = "queued"
            project.last_error = ""
            set_project_progress(project, "queued")
            # Debit, ledger, paid marker and queue job either all commit or all roll back.
            db.commit()
            return {"project": order_payload(db, order), **state(db, uid)}

    app.state.panel_checkout = SimpleNamespace(Handoff=Handoff, Checkout=Checkout, Ledger=Ledger, Activity=Activity, Profile=Profile, PanelProject=PanelProject,
                                               session_user=session_user, apply_account_reconciliations=apply_account_reconciliations)
