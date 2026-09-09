"""Fail-closed Heating, Gas and Split AC design packages for target sheets."""
from __future__ import annotations

from .hvac_calculations import calculate_heating_design, calculate_cooling_design
from .mechanical_execution_sizing import design_heating_network, design_gas_network
from .mechanical_manufacturer_selector import select_radiators, select_package, select_split_system
from .mechanical_submission_qa import validate_target_design_packages


def _blocked(stage, result):
    return {"status":result.get("status","FAIL"),"blocked_at":stage,"result":result}


def build_heating_package(payload):
    heat=calculate_heating_design(payload.get("rooms") or [],payload.get("design_basis") or {})
    if heat["status"]!="PASS":return _blocked("room_heat_loss",heat)
    basis=payload["design_basis"]
    radiators=select_radiators(heat["rooms"],payload.get("radiator_catalogue") or [],
                               {"supply_c":basis["supply_c"],"return_c":basis["return_c"],
                                "room_c":basis["indoor_design_c"]})
    if radiators["status"]!="PASS":return _blocked("radiator_selection",radiators)
    network=design_heating_network(payload.get("segments") or [],radiators["radiators"],
                                   payload.get("network_basis") or {})
    if network["status"]!="PASS":return _blocked("heating_network",network)
    package=select_package(payload.get("package_requirements") or [],payload.get("package_catalogue") or [])
    if package["status"]!="PASS":return _blocked("package_selection",package)
    return {"status":"PASS","basis_status":"FINAL","sheets":["M-131","M-132"],
            "room_heat_loss":heat,"radiator_selection":radiators,"heating_network":network,
            "package_selection":package}


def build_gas_package(payload):
    gas=design_gas_network(payload.get("segments") or [],payload.get("appliances") or [],
                           payload.get("design_basis") or {})
    if gas["status"]!="PASS":return _blocked("gas_network",gas)
    return {"status":"PASS","basis_status":"FINAL","sheets":["M-141","M-142"],"gas_network":gas}


def build_split_ac_package(payload):
    cooling=calculate_cooling_design(payload.get("rooms") or [],payload.get("design_basis") or {})
    if cooling["status"]!="PASS":return _blocked("cooling_load",cooling)
    selection=select_split_system(cooling,payload.get("idu_catalogue") or [],payload.get("odu_catalogue") or [],
                                  payload.get("routes") or [],payload.get("odu_site"))
    if selection["status"]!="PASS":return _blocked("selection",selection)
    return {"status":"PASS","basis_status":"FINAL","sheets":["M-161","M-162"],
            "cooling_load":cooling,"selection":selection}


def build_target_design_packages(payload):
    packages={
        "heating":build_heating_package(payload.get("heating") or {}),
        "gas":build_gas_package(payload.get("gas") or {}),
        "split_ac":build_split_ac_package(payload.get("split_ac") or {}),
    }
    gate=validate_target_design_packages(packages)
    return {"status":gate["status"],"packages":packages,"gate":gate,
            "release_allowed":gate["status"]=="PASS"}
