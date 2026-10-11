"""Independent offline residential symbol placement and clearance validation.

The producer is deliberately separate from this read-only validator.  It does
not repair geometry, infer hosts, qualify sources, or grant professional,
regulatory, Generator, CAD, snapshot, or runtime authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Protocol

from shapely.affinity import affine_transform
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union


CLEARANCE_TYPES = {
    "OBJECT_FOOTPRINT", "USAGE_CLEARANCE", "ACCESS_CLEARANCE",
    "MAINTENANCE_CLEARANCE", "CODE_REQUIRED_CLEARANCE",
}
SOURCE_TYPES = {
    "NATIONAL_CODE", "LOCAL_CODE", "MANUFACTURER_DATA", "ERGONOMIC_REFERENCE",
    "OWNER_REQUIREMENT", "HUMAN_DECISION",
}
VERIFICATION_STATES = {"UNVERIFIED", "SOURCE_VERIFIED", "AUTHORITY_QUALIFIED", "STALE", "SYNTHETIC"}
MARKERS = {"NON_GOLDEN", "NON_REGULATORY_TEST_DATA", "NOT_PROFESSIONALLY_APPROVED"}
HEX = frozenset("0123456789abcdef")


class ClearanceAuthorityResolver(Protocol):
    """Future independent trust boundary; no production provider is supplied here."""

    def resolve_source(self, source_id: str) -> Mapping[str, Any] | None: ...
    def resolve_rule(self, rule_reference: str) -> Mapping[str, Any] | None: ...


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finding(code: str, path: str, message: str, dimension: str = "STRUCTURAL_GEOMETRY_VALIDITY",
             outcome: str = "INPUT_REQUIRED") -> dict[str, str]:
    return {"code": code, "path": path, "message": message, "dimension": dimension, "outcome": outcome}


def _schema_findings(payload: Any, filename: str) -> list[dict[str, str]]:
    try:
        from jsonschema import Draft202012Validator
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "standards/test-suites/residential" / filename).read_text())
        errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda e: tuple(map(str, e.path)))
        return [_finding("SCHEMA_VALIDATION", "$" + "".join(
            f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.path), e.message) for e in errors]
    except (ImportError, OSError, ValueError) as exc:
        return [_finding("SCHEMA_UNAVAILABLE", "$", str(exc))]


def _polygon(points: Any, path: str, findings: list[dict[str, str]]) -> Polygon | None:
    if not isinstance(points, list) or len(points) < 4 or points[0] != points[-1]:
        findings.append(_finding("INVALID_POLYGON", path, "Closed polygon with at least three vertices required"))
        return None
    if any(not isinstance(p, list) or len(p) != 2 or any(not _finite(v) for v in p) for p in points):
        findings.append(_finding("NON_FINITE_GEOMETRY", path, "Finite two-dimensional coordinates required"))
        return None
    poly = Polygon(points)
    if not poly.is_valid or poly.area <= 0:
        findings.append(_finding("INVALID_POLYGON", path, "Simple nonzero-area polygon required"))
        return None
    return poly


def profile_content(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in profile.items() if key != "dependency_fingerprint"}


def validate_clearance_profile(profile: Any, *, authority_resolver: ClearanceAuthorityResolver | None = None
                               ) -> dict[str, Any]:
    findings = _schema_findings(profile, "clearance-profile.schema.json")
    if not isinstance(profile, Mapping) or findings:
        return {"status": "INPUT_REQUIRED", "findings": findings or [_finding("INVALID_PROFILE", "$", "Object required")]}
    markers = set(profile.get("markers", []))
    synthetic = markers == MARKERS
    if markers and not synthetic:
        findings.append(_finding("INVALID_SYNTHETIC_MARKERS", "markers", "All three fixture disclaimers are required"))
    mandatory = profile["mandatory_or_heuristic"] == "MANDATORY"
    if mandatory and profile["clearance_type"] not in {"ACCESS_CLEARANCE", "CODE_REQUIRED_CLEARANCE"}:
        findings.append(_finding("MANDATORY_TYPE_MISMATCH", "clearance_type", "Mandatory clearance must use an authority-bearing type",
                                 "REGULATORY_COMPLIANCE"))
    if mandatory and profile["source_type"] not in {"NATIONAL_CODE", "LOCAL_CODE"}:
        findings.append(_finding("MANDATORY_SOURCE_REQUIRED", "source_type", "Mandatory clearance requires national or local code evidence",
                                 "REGULATORY_COMPLIANCE"))
    if mandatory and (profile["verification_status"] != "AUTHORITY_QUALIFIED" or not profile.get("rule_or_clause_reference")):
        findings.append(_finding("MANDATORY_AUTHORITY_REQUIRED", "verification_status", "Qualified applicable rule evidence required",
                                 "REGULATORY_COMPLIANCE"))
    if synthetic and profile["verification_status"] == "AUTHORITY_QUALIFIED":
        findings.append(_finding("SYNTHETIC_AUTHORITY_FORBIDDEN", "verification_status", "Synthetic data cannot grant authority",
                                 "REGULATORY_COMPLIANCE"))
    source_hash = profile.get("source_hash")
    if profile["verification_status"] in {"SOURCE_VERIFIED", "AUTHORITY_QUALIFIED"} and not _is_hash(source_hash):
        findings.append(_finding("SOURCE_HASH_REQUIRED", "source_hash", "Verified evidence requires SHA-256"))
    if profile["verification_status"] in {"SOURCE_VERIFIED", "AUTHORITY_QUALIFIED"}:
        current = authority_resolver.resolve_source(profile["source_id"]) if authority_resolver is not None else None
        if not isinstance(current, Mapping):
            findings.append(_finding("INDEPENDENT_SOURCE_REQUIRED", "source_id", "Independent current source record is required",
                                     "REGULATORY_COMPLIANCE"))
        elif any(current.get(k) != profile.get(k) for k in ("source_id", "source_revision", "source_hash")):
            findings.append(_finding("STALE_SOURCE", "source_id", "Source identity, revision, or hash changed",
                                     "REGULATORY_COMPLIANCE"))
        if mandatory:
            rule = authority_resolver.resolve_rule(profile["rule_or_clause_reference"]) if authority_resolver is not None else None
            if not isinstance(rule, Mapping) or rule.get("source_id") != profile["source_id"] or rule.get("verification_status") != "AUTHORITY_QUALIFIED":
                findings.append(_finding("INDEPENDENT_RULE_REQUIRED", "rule_or_clause_reference",
                                         "Independently resolved applicable rule is required", "REGULATORY_COMPLIANCE"))
    for i, points in enumerate(profile["local_geometry"]["polygons"]):
        _polygon(points, f"local_geometry.polygons[{i}]", findings)
    expected = stable_hash(profile_content(profile))
    if profile["dependency_fingerprint"] != expected:
        findings.append(_finding("STALE_PROFILE", "dependency_fingerprint", "Clearance profile content changed"))
    if any(f["code"] in {"STALE_SOURCE", "STALE_PROFILE"} for f in findings):
        status = "STALE_BINDING"
    elif findings:
        status = "INPUT_REQUIRED"
    elif synthetic:
        status = "STRUCTURALLY_VALID"
    elif profile["verification_status"] == "AUTHORITY_QUALIFIED":
        status = "AUTHORITY_REVIEW_REQUIRED"  # embedded data is not independent professional approval
    else:
        status = "REVIEW_REQUIRED"
    return {"status": status, "findings": findings, "profile_hash": expected,
            "regulatory_authority": False, "professional_approval": False}


def placement_content(instance: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in instance.items() if key != "dependency_fingerprint"}


def create_placement_instance(symbol: Mapping[str, Any], *, placement_id: str, project_id: str,
                              physical_space_id: str, physical_space_fingerprint: str,
                              coordinate_frame: str, position: list[float], rotation_deg: float,
                              clearance_profile_references: list[str], host_id: str | None = None,
                              host_fingerprint: str | None = None, code_basis_hash: str | None = None,
                              relevant_program_hash: str | None = None,
                              applicable_operating_state: str = "DEFAULT") -> dict[str, Any]:
    if not all(isinstance(v, str) and v for v in (placement_id, project_id, physical_space_id, coordinate_frame)):
        raise ValueError("Stable placement, project, space and frame identity required")
    if not isinstance(position, list) or len(position) != 2 or any(not _finite(v) for v in position) or not _finite(rotation_deg):
        raise ValueError("Finite placement transform required")
    if not _is_hash(symbol.get("parameter_hash")) or not _is_hash(symbol.get("geometry_fingerprint")) or not _is_hash(physical_space_fingerprint):
        raise ValueError("Current symbol and physical-space fingerprints required")
    if host_id is not None and (not isinstance(host_id, str) or not host_id or not _is_hash(host_fingerprint)):
        raise ValueError("Hosted placement requires exact host identity and fingerprint")
    if code_basis_hash is not None and not _is_hash(code_basis_hash):
        raise ValueError("Invalid code-basis hash")
    if relevant_program_hash is not None and not _is_hash(relevant_program_hash):
        raise ValueError("Invalid relevant-program hash")
    angle = math.radians(rotation_deg % 360)
    transform = [round(math.cos(angle), 15), round(-math.sin(angle), 15),
                 round(math.sin(angle), 15), round(math.cos(angle), 15), position[0], position[1]]
    instance = {
        "schema_version": "architecture-symbol-placement/1.0", "placement_id": placement_id,
        "symbol_id": symbol["symbol_id"], "symbol_category": symbol["category"],
        "parameter_hash": symbol["parameter_hash"],
        "symbol_geometry_fingerprint": symbol["geometry_fingerprint"], "project_id": project_id,
        "physical_space_id": physical_space_id, "physical_space_fingerprint": physical_space_fingerprint,
        "host_id": host_id, "host_fingerprint": host_fingerprint, "coordinate_frame": coordinate_frame,
        "position": position, "rotation_deg": rotation_deg % 360, "transformation": transform,
        "clearance_profile_references": sorted(set(clearance_profile_references)),
        "applicable_operating_state": applicable_operating_state,
        "source_bindings": {"code_basis_hash": code_basis_hash, "relevant_program_hash": relevant_program_hash},
        "local_footprint": copy.deepcopy(symbol.get("local_footprint", symbol["footprint"])),
        "local_operating_envelope": copy.deepcopy(symbol.get("local_operating_envelope", symbol.get("operating_envelope"))),
    }
    instance["dependency_fingerprint"] = stable_hash(placement_content(instance))
    return instance


def _transform(poly: Polygon, matrix: list[float]) -> Polygon:
    # Shapely uses [a,b,d,e,xoff,yoff]. Our stored matrix uses that exact order.
    return affine_transform(poly, matrix)


def _dimension_states(findings: list[dict[str, str]]) -> dict[str, str]:
    dimensions = {name: "PASS" for name in (
        "STRUCTURAL_GEOMETRY_VALIDITY", "PLACEMENT_VALIDITY", "FUNCTIONAL_USABILITY",
        "REGULATORY_COMPLIANCE", "PROFESSIONAL_REVIEW")}
    dimensions["PROFESSIONAL_REVIEW"] = "NOT_REVIEWED"
    rank = {"PASS": 0, "NOT_REVIEWED": 1, "HUMAN_REVIEW_REQUIRED": 2, "INPUT_REQUIRED": 3, "FAIL": 4}
    for finding in findings:
        dim, outcome = finding["dimension"], finding["outcome"]
        if rank[outcome] > rank.get(dimensions.get(dim, "PASS"), 0):
            dimensions[dim] = outcome
    return dimensions


def validate_placement_scene(scene: Any, *, authority_resolver: ClearanceAuthorityResolver | None = None,
                             current_dependencies: Mapping[str, str] | None = None,
                             current_symbols: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    findings = _schema_findings(scene, "placement-scene.schema.json")
    if not isinstance(scene, Mapping) or findings:
        return {"status": "INPUT_REQUIRED", "findings": findings or [_finding("INVALID_SCENE", "$", "Object required")],
                "dimensions": _dimension_states(findings), "input_hash": None}
    try:
        original_hash = stable_hash(scene)
    except (TypeError, ValueError):
        findings.append(_finding("NON_FINITE_OR_NON_JSON_INPUT", "$", "Scene must contain finite JSON values"))
        return {"status": "INPUT_REQUIRED", "findings": findings,
                "dimensions": _dimension_states(findings), "input_hash": None,
                "input_unchanged": True, "whole_building_compliance": False,
                "professional_approval": False, "runtime_enabled": False}
    room = scene["physical_space"]
    room_poly = _polygon(room["polygon"], "physical_space.polygon", findings)
    if room["project_id"] != scene["project_id"] or room["authority_status"] != "VERIFIED" or room["material_geometry"] is not True:
        findings.append(_finding("AUTHORITATIVE_SPACE_REQUIRED", "physical_space", "Verified material Physical Space is required"))
    if room["geometry_fingerprint"] != stable_hash({"polygon": room["polygon"], "coordinate_frame": room["coordinate_frame"]}):
        findings.append(_finding("STALE_SPACE_GEOMETRY", "physical_space.geometry_fingerprint", "Physical-space geometry changed"))
    profiles = {p["clearance_id"]: p for p in scene["clearance_profiles"]
                if isinstance(p, Mapping) and isinstance(p.get("clearance_id"), str)}
    if len(profiles) != len(scene["clearance_profiles"]):
        findings.append(_finding("DUPLICATE_CLEARANCE_PROFILE", "clearance_profiles", "Unique identities required"))
    profile_polys: dict[str, list[Polygon]] = {}
    for index, profile in enumerate(scene["clearance_profiles"]):
        if not isinstance(profile, Mapping) or not isinstance(profile.get("clearance_id"), str):
            findings.append(_finding("INVALID_CLEARANCE_PROFILE", f"clearance_profiles[{index}]", "Typed clearance profile required"))
            continue
        result = validate_clearance_profile(profile, authority_resolver=authority_resolver)
        if result["status"] in {"INPUT_REQUIRED", "STALE_BINDING"}:
            findings.extend({**f, "path": f"clearance_profiles[{index}].{f['path']}"} for f in result["findings"])
        profile_polys[profile["clearance_id"]] = [Polygon(points) for points in profile["local_geometry"]["polygons"]]
    hosts = {h["host_id"]: h for h in scene["hosts"]}
    if len(hosts) != len(scene["hosts"]):
        findings.append(_finding("DUPLICATE_HOST", "hosts", "Unique current host identities required"))
    host_lines: dict[str, LineString] = {}
    for index, host in enumerate(scene["hosts"]):
        geometry = host.get("geometry")
        if (not isinstance(geometry, list) or len(geometry) < 2
                or any(not isinstance(point, list) or len(point) != 2 or any(not _finite(v) for v in point)
                       for point in geometry)):
            findings.append(_finding("INVALID_HOST_GEOMETRY", f"hosts[{index}].geometry", "Finite host polyline required"))
            continue
        line = LineString(geometry)
        if not line.is_valid or line.length <= 0:
            findings.append(_finding("INVALID_HOST_GEOMETRY", f"hosts[{index}].geometry", "Nonzero valid host polyline required"))
            continue
        expected_host = stable_hash({"coordinate_frame": host["coordinate_frame"], "geometry": geometry})
        if host["geometry_fingerprint"] != expected_host:
            findings.append(_finding("STALE_HOST_GEOMETRY", f"hosts[{index}].geometry_fingerprint", "Host geometry changed"))
        host_lines[host["host_id"]] = line
    placed: list[tuple[Mapping[str, Any], Polygon, Polygon | None, dict[str, list[Polygon]]]] = []
    placement_ids: set[str] = set()
    for index, instance in enumerate(scene["placements"]):
        path = f"placements[{index}]"
        if instance["placement_id"] in placement_ids:
            findings.append(_finding("DUPLICATE_PLACEMENT", path, "Unique placement identities required"))
        placement_ids.add(instance["placement_id"])
        current_symbol = current_symbols.get(instance["symbol_id"]) if isinstance(current_symbols, Mapping) else None
        if not isinstance(current_symbol, Mapping):
            findings.append(_finding("CURRENT_SYMBOL_REQUIRED", f"{path}.symbol_id", "Independent current symbol record is required"))
        elif (current_symbol.get("parameter_hash") != instance["parameter_hash"]
              or current_symbol.get("geometry_fingerprint") != instance["symbol_geometry_fingerprint"]
              or current_symbol.get("footprint") != instance["local_footprint"]):
            findings.append(_finding("STALE_SYMBOL_BINDING", path, "Symbol parameters or geometry changed"))
        if instance["project_id"] != scene["project_id"] or instance["physical_space_id"] != room["physical_space_id"]:
            findings.append(_finding("CROSS_PROJECT_OR_SPACE_BINDING", path, "Placement identity does not match scene"))
        if instance["coordinate_frame"] != room["coordinate_frame"]:
            findings.append(_finding("COORDINATE_FRAME_MISMATCH", path, "Placement and Physical Space frames differ"))
        if instance["physical_space_fingerprint"] != room["geometry_fingerprint"]:
            findings.append(_finding("STALE_SPACE_BINDING", path, "Placement uses stale Physical Space geometry"))
        if instance["dependency_fingerprint"] != stable_hash(placement_content(instance)):
            findings.append(_finding("STALE_PLACEMENT", path, "Placement material dependency changed"))
        angle = math.radians(instance["rotation_deg"] % 360)
        expected_transform = [round(math.cos(angle), 15), round(-math.sin(angle), 15),
                              round(math.sin(angle), 15), round(math.cos(angle), 15),
                              instance["position"][0], instance["position"][1]]
        if instance["transformation"] != expected_transform:
            findings.append(_finding("INVALID_TRANSFORMATION", f"{path}.transformation",
                                     "Transformation must exactly represent position and rotation"))
        bindings = instance.get("source_bindings", {})
        if any(value is not None for value in bindings.values()) and current_dependencies is None:
            findings.append(_finding("CURRENT_DEPENDENCIES_REQUIRED", f"{path}.source_bindings",
                                     "Current material dependency snapshot is required"))
        if current_dependencies is not None:
            for key, bound in bindings.items():
                if bound is not None and key not in current_dependencies:
                    findings.append(_finding("CURRENT_DEPENDENCY_REQUIRED", f"{path}.source_bindings.{key}",
                                             "Current material dependency is missing"))
            for key, expected in current_dependencies.items():
                if expected is not None and bindings.get(key) != expected:
                    findings.append(_finding("STALE_DEPENDENCY", f"{path}.source_bindings.{key}", "Current material dependency changed"))
        host_id = instance.get("host_id")
        if host_id is not None:
            host = hosts.get(host_id)
            if not host or host["project_id"] != scene["project_id"] or host["coordinate_frame"] != room["coordinate_frame"]:
                findings.append(_finding("MISSING_HOST_EVIDENCE", f"{path}.host_id", "Exact current host is required"))
            elif instance.get("host_fingerprint") != host["geometry_fingerprint"]:
                findings.append(_finding("STALE_HOST_BINDING", f"{path}.host_fingerprint", "Host geometry changed"))
        local = _polygon(instance["local_footprint"], f"{path}.local_footprint", findings)
        operating = None
        if instance.get("local_operating_envelope") is not None:
            operating = _polygon(instance["local_operating_envelope"], f"{path}.local_operating_envelope", findings)
            if host_id is None:
                findings.append(_finding("MISSING_DOOR_HOST", path, "Operating door placement requires host evidence",
                                         "PLACEMENT_VALIDITY"))
            elif host_id in host_lines and host_lines[host_id].distance(Point(instance["position"])) > 1e-9:
                findings.append(_finding("DOOR_HOST_GEOMETRY_MISMATCH", path,
                                         "Door hinge point is not on the exact supplied host geometry",
                                         "PLACEMENT_VALIDITY", "FAIL"))
        if local is None:
            continue
        world = _transform(local, instance["transformation"])
        world_operating = _transform(operating, instance["transformation"]) if operating else None
        if room_poly and not room_poly.covers(world):
            findings.append(_finding("FOOTPRINT_OUTSIDE_SPACE", path, "Object footprint is outside Physical Space",
                                     "PLACEMENT_VALIDITY", "FAIL"))
        regions: dict[str, list[Polygon]] = {}
        for ref in instance["clearance_profile_references"]:
            profile = profiles.get(ref)
            if profile is None:
                findings.append(_finding("MISSING_CLEARANCE_PROFILE", path, f"Unknown clearance profile {ref}",
                                         "FUNCTIONAL_USABILITY"))
                continue
            if profile["symbol_id"] != instance["symbol_id"] or profile["symbol_category"] != instance["symbol_category"]:
                findings.append(_finding("CLEARANCE_SYMBOL_MISMATCH", path, "Clearance profile belongs to another symbol",
                                         "FUNCTIONAL_USABILITY"))
            if profile["applicable_configuration"] not in {"ANY", instance["applicable_operating_state"]}:
                findings.append(_finding("CLEARANCE_CONFIGURATION_MISMATCH", path, "Profile does not cover operating state",
                                         "FUNCTIONAL_USABILITY"))
            world_regions = [_transform(poly, instance["transformation"]) for poly in profile_polys.get(ref, [])]
            regions[ref] = world_regions
            for poly in world_regions:
                if room_poly and not room_poly.covers(poly):
                    dim = "REGULATORY_COMPLIANCE" if profile["mandatory_or_heuristic"] == "MANDATORY" else "FUNCTIONAL_USABILITY"
                    findings.append(_finding("CLEARANCE_OUTSIDE_SPACE", path, f"{ref} is outside Physical Space", dim, "FAIL"))
        placed.append((instance, world, world_operating, regions))
    for i, (left, left_poly, left_operating, left_regions) in enumerate(placed):
        for right, right_poly, right_operating, right_regions in placed[i + 1:]:
            if left_poly.intersection(right_poly).area > 1e-10:
                findings.append(_finding("OBJECT_COLLISION", f"placements[{left['placement_id']}:{right['placement_id']}]",
                                         "Object footprints collide", "PLACEMENT_VALIDITY", "FAIL"))
            for door, operating, other in ((left, left_operating, right_poly), (right, right_operating, left_poly)):
                if operating is not None and operating.intersection(other).area > 1e-10:
                    findings.append(_finding("DOOR_SWING_COLLISION", f"placements[{door['placement_id']}]",
                                             "Operating envelope intersects another object", "PLACEMENT_VALIDITY", "FAIL"))
            for owner, regions, other in ((left, left_regions, right_poly), (right, right_regions, left_poly)):
                for ref, polygons in regions.items():
                    profile = profiles[ref]
                    if not any(poly.intersection(other).area > 1e-10 for poly in polygons):
                        continue
                    policy = profile["coexistence_policy"]
                    dim = "REGULATORY_COMPLIANCE" if profile["mandatory_or_heuristic"] == "MANDATORY" else "FUNCTIONAL_USABILITY"
                    if policy == "PROHIBITED":
                        findings.append(_finding("CLEARANCE_OBSTRUCTED", f"placements[{owner['placement_id']}]", f"{ref} is obstructed", dim, "FAIL"))
                    elif policy == "CONDITIONAL_REVIEW":
                        findings.append(_finding("CLEARANCE_OVERLAP_REVIEW", f"placements[{owner['placement_id']}]",
                                                 f"{ref} overlap lacks a simultaneous-use decision", dim, "HUMAN_REVIEW_REQUIRED"))
    obstacles = []
    for index, points in enumerate(scene["obstacles"]):
        obstacle = _polygon(points, f"obstacles[{index}]", findings)
        if obstacle is not None:
            obstacles.append(obstacle)
    obstacle_union = unary_union(obstacles + [item[1] for item in placed]) if obstacles or placed else None
    for index, check in enumerate(scene["access_path_checks"]):
        ref = profiles.get(check["clearance_profile_id"])
        if ref is None or ref["clearance_type"] not in {"ACCESS_CLEARANCE", "CODE_REQUIRED_CLEARANCE"}:
            findings.append(_finding("ACCESS_PROFILE_REQUIRED", f"access_path_checks[{index}]", "Typed access profile required",
                                     "FUNCTIONAL_USABILITY"))
            continue
        width = check["required_width_m"]
        if not _finite(width) or width <= 0:
            findings.append(_finding("INVALID_ACCESS_WIDTH", f"access_path_checks[{index}]", "Positive finite width required",
                                     "FUNCTIONAL_USABILITY"))
            continue
        if ref["mandatory_or_heuristic"] == "MANDATORY" and ref["verification_status"] != "AUTHORITY_QUALIFIED":
            findings.append(_finding("ACCESS_AUTHORITY_REQUIRED", f"access_path_checks[{index}]", "Mandatory path width lacks authority",
                                     "REGULATORY_COMPLIANCE"))
            continue
        if room_poly is None:
            continue
        free = room_poly.buffer(-width / 2)
        if obstacle_union is not None:
            free = free.difference(obstacle_union.buffer(width / 2))
        start, goal = Point(check["start"]), Point(check["goal"])
        components = list(free.geoms) if hasattr(free, "geoms") else [free]
        if not any(component.covers(start) and component.covers(goal) for component in components):
            dim = "REGULATORY_COMPLIANCE" if ref["mandatory_or_heuristic"] == "MANDATORY" else "FUNCTIONAL_USABILITY"
            findings.append(_finding("ACCESS_PATH_BLOCKED", f"access_path_checks[{index}]", "No bounded clear path connects endpoints",
                                     dim, "FAIL"))
    dimensions = _dimension_states(findings)
    if "FAIL" in dimensions.values():
        status = "FAIL"
    elif "INPUT_REQUIRED" in dimensions.values():
        status = "INPUT_REQUIRED"
    elif "HUMAN_REVIEW_REQUIRED" in dimensions.values():
        status = "HUMAN_REVIEW_REQUIRED"
    else:
        status = "REVIEW_REQUIRED"  # geometry success is never professional approval
    return {"status": status, "dimensions": dimensions, "findings": findings, "input_hash": original_hash,
            "input_unchanged": stable_hash(scene) == original_hash, "whole_building_compliance": False,
            "professional_approval": False, "runtime_enabled": False}
