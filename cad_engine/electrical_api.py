"""Active production HTTP adapter for Electrical.

The module stays lightweight so the isolated CAD HTTP shell can import route
metadata without loading the Electrical engineering stack into the long-lived
parent process. Heavy runtime imports happen only inside a status/design call.
"""
from __future__ import annotations

import base64
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException

PIPELINE_AUTHORITY = "electrical-authority"


def _missing_inputs(report):
    """Return stable, user-actionable evidence keys for late recovery.

    Raw authority diagnostics contain internal requirement IDs (``REQ-0001``),
    system-family names and every unresolved design-basis field.  Those are useful
    for engineering QA but are not a recovery contract.  This adapter collapses
    them into the smallest semantic inputs that can actually change the next run.
    Exact construction-detail ``detail-id.parameter`` tokens remain preserved.
    """
    missing = []
    data = report.get("data") or {}
    gates = report.get("gates") or {}

    def add(key):
        key = str(key or "").strip()
        if key and key not in missing:
            missing.append(key)

    # Only project facts that have a direct user recovery path are read from the
    # design basis.  Do not dump all optional/unused basis fields to the customer.
    basis = (data.get("basis") or {}).get("values") or {}

    def basis_unresolved(key):
        value = basis.get(key) or {}
        return isinstance(value, dict) and value.get("status") in {"INPUT_REQUIRED", "UNKNOWN"}
    for key in ("city", "building_type", "number_of_units", "earthing_system"):
        value = basis.get(key) or {}
        if isinstance(value, dict) and value.get("status") in {"INPUT_REQUIRED", "UNKNOWN"}:
            add("earthing_final_basis" if key == "earthing_system" else key)
    voltage = basis.get("supply_voltage_v") or {}
    if isinstance(voltage, dict) and voltage.get("status") in {"INPUT_REQUIRED", "UNKNOWN"}:
        add("supply_voltage_v")
    for key in ("phase_configuration", "utility_service"):
        value = basis.get(key) or {}
        if isinstance(value, dict) and value.get("status") in {"INPUT_REQUIRED", "UNKNOWN"}:
            add("supply_configuration")

    system_recovery = {
        "HVAC_POWER": "hvac_electrical_loads",
        "EMERGENCY_LIGHTING": "emergency_lighting",
        "FIRE_ALARM": "fire_alarm_requirement",
        "LIGHTNING_PROTECTION": "lightning_protection",
        "GENERATOR": "generator",
        "UPS": "ups",
        "EV_CHARGING": "ev_charging",
        "SOLAR_PV": "solar_pv",
        "ELEVATOR_POWER": "elevator",
        "PUMP_POWER": "pump",
        "TELECOM": "low_current_systems",
        "DATA": "low_current_systems",
        "TV": "low_current_systems",
        "INTERCOM": "low_current_systems",
        "CCTV": "low_current_systems",
        "ACCESS_CONTROL": "low_current_systems",
    }
    equipment_recovery = {
        "LIGHT_FIXTURE": ("lighting_basis_values", "luminaire_schedule"),
        "LIGHT_SWITCH": ("switch_control_requirements",),
        "GENERAL_SOCKET": ("socket_power_requirements",),
        "DEDICATED_APPLIANCE_OUTLET": ("dedicated_appliance_requirements",),
    }
    equipment_by_id = {
        str(row.get("id")): str(row.get("equipment_type") or "")
        for row in (data.get("equipment") or []) if isinstance(row, dict) and row.get("id")
    }

    for gate_name, gate in gates.items():
        for warning in gate.get("warnings") or []:
            text = str(warning).strip()
            detail_match = re.search(r"detail_parameters_input_required:([^:]+):([^|;]+)", text)
            if detail_match:
                detail_id = detail_match.group(1).strip()
                for parameter in detail_match.group(2).split(","):
                    parameter = parameter.strip()
                    if parameter:
                        add(f"{detail_id}.{parameter}")
                continue
            if text.startswith("detail_not_final:") or text.startswith("plan_detail_reference_required:"):
                # These are downstream document-state symptoms.  Exact missing
                # detail parameters are emitted by CONSTRUCTION_DETAIL_AUTHORITY.
                continue
            if text.startswith("scope_input_required:"):
                add(system_recovery.get(text.split(":", 1)[1].strip()))
                continue
            if text.startswith(("quantity_not_final:", "design_not_final:")):
                req_id = text.rsplit(":", 1)[-1].strip()
                for key in equipment_recovery.get(equipment_by_id.get(req_id), ()):
                    add(key)
                continue
            if text == "opening_clearance_rule_missing":
                add("opening_clearance_m"); continue
            if text == "wall_host_tolerance_missing":
                add("wall_host_tolerance_m"); continue
            if text == "ceiling_layout_basis_missing":
                add("ceiling_layout_basis_confirmed"); continue
            if text.startswith("switch_door_side_not_confirmed:"):
                add("switch_door_relation_confirmed"); continue
            if text == "supply_voltage_or_phase_configuration_missing":
                # This calculation warning is intentionally coarse. Reopen only
                # the basis fields that are still unresolved so a finalized
                # voltage is not asked again merely because phase is missing.
                if basis_unresolved("phase_configuration") or basis_unresolved("utility_service"):
                    add("supply_configuration")
                if basis_unresolved("supply_voltage_v"):
                    add("supply_voltage_v")
                continue
            if text == "power_factor_missing":
                add("power_factor"); continue
            if text.startswith("service_or_feeder_input_required:"):
                add(text.rsplit(":", 1)[-1].strip()); continue
            if text.startswith("riser_input_required:"):
                add("riser_feeder_schedule"); continue
            if text.startswith("grounding_input_required:"):
                item = text.rsplit(":", 1)[-1].strip()
                add({
                    "earth_electrode": "grounding_earth_electrode",
                    "main_earth_bar": "grounding_main_earth_bar",
                    "protective_conductors": "grounding_protective_conductors",
                    "panel_grounding": "grounding_panel_grounding",
                }.get(item))
                continue
            if text.startswith("optional_system_design_input_required:"):
                system = text.rsplit(":", 1)[-1].strip()
                add("fire_alarm_design_inputs" if system == "FIRE_ALARM" else "low_current_design_inputs")
                continue
            if text.startswith("panel_location_missing:"):
                add("panel_locations"); continue
            if text.startswith("load_unresolved:"):
                # Demand calculation becomes actionable through the project
                # circuit/demand rules rather than through an internal C-xxxx ID.
                add("circuit_demand_rules"); continue
            if text.startswith("cable_basis_missing:"):
                add("installation_method"); add("conductor_material"); continue
            if text.startswith("voltage_drop_inputs_missing:"):
                add("voltage_drop_rules"); add("voltage_drop_limits"); continue
            if text.startswith("voltage_drop_limit_missing:"):
                add("voltage_drop_limits"); continue
            if text.startswith("phase_balance_threshold_missing"):
                add("phase_balance_threshold_pct"); continue
            if text.startswith("panel_") and "_missing:" in text:
                add("panel_design_rules"); continue

    return missing


def _aggregate_release_state(reports):
    """Never promote the HTTP response beyond the authority reports it contains."""
    if not reports:
        return {
            "submission_state": "PRE_SUBMISSION",
            "preliminary": True,
            "real_project_acceptance": False,
            "production_release_allowed": False,
        }
    states = [str(r.get("submission_state") or "PRE_SUBMISSION") for r in reports]
    accepted = [bool((r.get("acceptance") or {}).get("real_project_acceptance")) for r in reports]
    release = [bool((r.get("acceptance") or {}).get("production_release_allowed")) for r in reports]
    review_ready = all(state == "EXECUTION_REVIEW_READY" for state in states)
    return {
        "submission_state": "EXECUTION_REVIEW_READY" if review_ready else "PRE_SUBMISSION",
        "preliminary": not review_ready,
        "real_project_acceptance": all(accepted),
        "production_release_allowed": all(release),
    }


def electrical_status_payload():
    """Build the Electrical status lazily so isolated parent memory stays small."""
    from .build_identity import build_identity
    from .electrical_v1.release_contract import release_contract_status

    return {
        **release_contract_status(),
        "production_entrypoint": "cad_engine.main:app",
        "pipeline_authority": PIPELINE_AUTHORITY,
        "build": build_identity(),
    }


def design_electrical_request(req):
    """Execute one validated Electrical request in the current process.

    Isolated production calls this only from a disposable worker. Non-isolated
    deployments use the same function through the FastAPI wrapper below.
    """
    from .build_identity import build_identity
    from .electrical_v1.production import design_electrical_authority_site
    from .runtime_core import OUTPUT_ROOT, source_files, zip_outputs

    if str(req.discipline or "").lower() != "electrical":
        raise HTTPException(400, "Electrical endpoint accepts electrical discipline only")
    scope = req.output_scope or {}
    if scope.get("discipline") != "electrical" or scope.get("only_this_discipline") is not True or scope.get("include_other_disciplines") is not False:
        raise HTTPException(400, "discipline isolation flags are required")
    project_out = OUTPUT_ROOT / str(req.project_id) / f"R{req.revision:03d}" / "electrical"
    shutil.rmtree(project_out, ignore_errors=True)
    project_out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engitools-electrical-") as td:
        input_dir = Path(td) / "input"; input_dir.mkdir()
        try:
            sources = source_files(req, input_dir)
        except Exception as exc:
            shutil.rmtree(project_out, ignore_errors=True)
            raise HTTPException(400, str(exc))
        generated = []; reports = []
        for index, src in enumerate(sources, 1):
            safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)[:80] or f"plan_{index}"
            dst = project_out / f"{index:02d}_{safe_stem}_electrical.dxf"
            report = design_electrical_authority_site(src, dst, answers=req.answers, plan_analysis=req.plan_analysis)
            if report.get("status") != "PASS":
                missing = _missing_inputs(report)
                shutil.rmtree(project_out, ignore_errors=True)
                raise HTTPException(422, {
                    "message": "Electrical authority pipeline requires additional evidence",
                    "code": "ELECTRICAL_INPUT_REQUIRED" if missing else "ELECTRICAL_QA_FAILED",
                    "status": "INPUT_REQUIRED" if missing else "FAIL",
                    "missing_inputs": missing,
                    "acceptance": report.get("acceptance"),
                    "execution_readiness": report.get("execution_readiness"),
                    "gates": {k:v for k,v in (report.get("gates") or {}).items() if v.get("status") not in {"PASS","NOT_REQUIRED"}},
                    "pipeline_authority": PIPELINE_AUTHORITY,
                })
            reports.append({"source": src.name, **report})
            generated.append(dst)

        package = project_out / f"EngiTools_{req.project_id}_electrical_R{req.revision}_DXF.zip"
        # Always create a transfer envelope. A remote Cloudflare CAD container's
        # filesystem is not visible to the web service, even for a single DXF.
        if generated:
            zip_outputs(generated, package)
        if len(generated) > 1:
            for path in generated:
                path.unlink(missing_ok=True)

        release_state = _aggregate_release_state(reports)
        return {
            "ok": True, "project_id": req.project_id, "discipline": "electrical",
            "engine_identity": build_identity(),
            "mode": "electrical-authoritative",
            "pipeline_authority": PIPELINE_AUTHORITY,
            **release_state,
            "requires_professional_review": True,
            "systems": scope.get("systems") or [],
            "design_reports": reports,
            "generated_files": [p.name for p in generated],
            "pdf_path": "",
            "zip_path": str(package),
            "pdf_base64": "",
            "zip_base64": base64.b64encode(package.read_bytes()).decode("ascii") if package.exists() else "",
        }


def register_electrical(app):
    # Import the request model only when routes are installed in a non-isolated
    # process; the isolated parent owns its own Request-based wrappers.
    from .runtime_core import DesignRequest

    @app.get("/electrical/status")
    def electrical_status():
        return electrical_status_payload()

    @app.post("/design-electrical")
    def design_electrical(req: DesignRequest):
        return design_electrical_request(req)
