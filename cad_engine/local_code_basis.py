"""Offline local-jurisdiction and project-code-basis contracts.

This module is intentionally absent from production entrypoints.  It validates
traceable regulatory inputs and provides a bounded convex-parcel envelope
derivation without granting legal, professional, runtime, or Generator authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Protocol

from shapely.geometry import Polygon


LOCAL_PROFILE_SCHEMA = "architecture-local-rule-profile/1.0"
PROJECT_BASIS_SCHEMA = "architecture-project-code-basis/1.0"
MARKERS = {"NON_GOLDEN", "NON_REGULATORY_TEST_DATA", "NOT_PROFESSIONALLY_APPROVED"}
HEX = frozenset("0123456789abcdef")
SOURCE_STATES = {"UNVERIFIED", "AUTHORITY_REVIEW_REQUIRED", "AUTHORITY_QUALIFIED", "STALE"}
RULE_STATES = {"UNVERIFIED", "AUTHORITY_REVIEW_REQUIRED", "AUTHORITY_QUALIFIED", "STALE"}
FINAL_PROFILE_STATES = {"STRUCTURALLY_VALID", "AUTHORITY_REVIEW_REQUIRED", "AUTHORITY_QUALIFIED", "STALE_BINDING"}
FINAL_BASIS_STATES = {
    "INPUT_REQUIRED", "LOCAL_RULE_REQUIRED", "STALE_BINDING", "CONFLICT_REVIEW_REQUIRED",
    "STRUCTURALLY_VALID", "AUTHORITY_REVIEW_REQUIRED", "AUTHORITY_QUALIFIED",
}
AUTHORITIES = {"NATIONAL_CODE", "LOCAL_CODE", "SITE_EVIDENCE", "OWNER_REQUIREMENT", "HUMAN_DECISION"}
TOPICS = {
    "SETBACK", "BUILDING_LINE", "SITE_COVERAGE", "FAR_DENSITY", "MAX_HEIGHT", "PARKING",
    "VEHICLE_ACCESS", "PEDESTRIAN_ACCESS", "SPECIAL_DISTRICT", "PARCEL_EXCEPTION",
    "ELEVATOR", "LOCAL_FIRE", "ACCESSIBILITY",
}

# Conservative result precedence, highest first. Malformed or missing inputs are
# never hidden by a later conflict/review finding.
STATUS_PRECEDENCE = (
    "INPUT_REQUIRED", "LOCAL_RULE_REQUIRED", "STALE_BINDING",
    "CONFLICT_REVIEW_REQUIRED", "AUTHORITY_REVIEW_REQUIRED", "STRUCTURALLY_VALID",
)


class AuthorityEvidenceResolver(Protocol):
    """Future trust boundary; no production implementation exists in this PR.

    Implementations must resolve records from independently governed source and
    reviewer registries. Merely implementing this protocol never grants authority;
    a separately approved qualification entrypoint is still required.
    """

    def resolve_source(self, source_id: str) -> Mapping[str, Any] | None: ...
    def resolve_reviewer(self, reviewer_id: str) -> Mapping[str, Any] | None: ...
    def resolve_review_decision(self, decision_id: str) -> Mapping[str, Any] | None: ...


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def _finding(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _load_schema(filename: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "standards/test-suites/residential" / filename).read_text())


def load_schema(name: str) -> dict[str, Any]:
    names = {
        "local-rule-profile": "local-rule-profile-v1.schema.json",
        "project-code-basis": "project-code-basis-v1.schema.json",
    }
    if name not in names:
        raise ValueError("Unknown local code-basis schema")
    return _load_schema(names[name])


def _structural_findings(payload: Any, filename: str) -> list[dict[str, str]]:
    try:
        from jsonschema import Draft202012Validator
        errors = sorted(Draft202012Validator(_load_schema(filename)).iter_errors(payload), key=lambda e: tuple(str(part) for part in e.path))
        return [
            _finding("SCHEMA_VALIDATION", "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in e.path), e.message)
            for e in errors
        ]
    except ImportError as exc:
        return [_finding("SCHEMA_UNAVAILABLE", "$", f"Required JSON Schema validator unavailable: {exc}")]
    except (OSError, ValueError) as exc:
        return [_finding("SCHEMA_UNAVAILABLE", "$", str(exc))]


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _review_valid(review: Any, *, source_id: str | None = None, source_revision: str | None = None,
                  project_id: str | None = None) -> bool:
    if not isinstance(review, Mapping):
        return False
    required = ("reviewer_id", "reviewer_role", "qualification_reference", "review_date",
                "source_reference", "source_revision", "project_scope", "decision", "decision_evidence")
    if any(not isinstance(review.get(key), str) or not review[key] for key in required):
        return False
    if source_id is not None and review["source_reference"] != source_id:
        return False
    if source_revision is not None and review["source_revision"] != source_revision:
        return False
    if project_id is not None and review["project_scope"] not in {project_id, "JURISDICTION_PROFILE"}:
        return False
    return _date(review["review_date"]) is not None


def profile_content(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in profile.items() if k not in {"profile_hash", "status"}}


def validate_local_rule_profile(profile: Any, *, current_sources: Mapping[str, Mapping[str, Any]] | None = None,
                                as_of: str | None = None) -> dict[str, Any]:
    findings = _structural_findings(profile, "local-rule-profile-v1.schema.json")
    if not isinstance(profile, Mapping):
        return {"status": "INPUT_REQUIRED", "findings": findings or [_finding("INVALID_PAYLOAD", "$", "Object required")]}
    if profile.get("schema_version") != LOCAL_PROFILE_SCHEMA:
        findings.append(_finding("SCHEMA_VERSION", "schema_version", "LocalRuleProfile 1.0 required"))
    if profile.get("runtime_enabled") is not False:
        findings.append(_finding("RUNTIME_ACTIVATION_FORBIDDEN", "runtime_enabled", "Offline contract only"))
    if findings:
        return {"status": "INPUT_REQUIRED", "findings": findings, "content_hash": None, "runtime_enabled": False}
    if current_sources is not None and not isinstance(current_sources, Mapping):
        return {"status": "INPUT_REQUIRED", "findings": [_finding("INVALID_CURRENT_SOURCES", "current_sources", "Source snapshot must be an object")], "content_hash": None, "runtime_enabled": False}
    for field in ("country", "province", "city", "municipality"):
        if not profile.get(field):
            findings.append(_finding("MISSING_JURISDICTION", field, f"{field} is required"))
    if profile.get("country") not in {None, "IR"}:
        findings.append(_finding("UNSUPPORTED_COUNTRY", "country", "This contract currently supports Iran only"))
    effective_from, effective_until = _date(profile.get("effective_from")), _date(profile.get("effective_until"))
    if effective_from is None:
        findings.append(_finding("MISSING_EFFECTIVE_DATE", "effective_from", "Valid effective_from is required"))
    if effective_until and effective_from and effective_until < effective_from:
        findings.append(_finding("INVALID_TEMPORAL_SCOPE", "effective_until", "End precedes start"))
    evaluation_date = _date(as_of) if as_of else None
    if as_of and evaluation_date is None:
        findings.append(_finding("INVALID_EFFECTIVE_DATE", "as_of", "Valid project date is required"))
    if evaluation_date and effective_from and evaluation_date < effective_from:
        findings.append(_finding("OUTSIDE_EFFECTIVE_PERIOD", "effective_from", "Profile is not yet effective"))
    if evaluation_date and effective_until and evaluation_date > effective_until:
        findings.append(_finding("OUTSIDE_EFFECTIVE_PERIOD", "effective_until", "Profile expired"))

    documents = profile.get("source_documents") if isinstance(profile.get("source_documents"), list) else []
    docs: dict[str, Mapping[str, Any]] = {}
    for index, document in enumerate(documents):
        path = f"source_documents[{index}]"
        if not isinstance(document, Mapping) or not document.get("source_id"):
            continue
        source_id = document["source_id"]
        if source_id in docs:
            findings.append(_finding("DUPLICATE_SOURCE", path, "Source identity is duplicated"))
        docs[source_id] = document
        if not _is_hash(document.get("content_hash")):
            findings.append(_finding("INVALID_SOURCE_HASH", f"{path}.content_hash", "SHA-256 required"))
        if document.get("verification_status") == "AUTHORITY_QUALIFIED" and not _review_valid(
            document.get("review"), source_id=source_id, source_revision=document.get("document_revision")
        ):
            findings.append(_finding("UNSUPPORTED_VERIFIED_SOURCE", path, "Qualified source requires scoped review"))
        if document.get("superseded_by"):
            findings.append(_finding("SUPERSEDED_SOURCE", path, "Source declares a superseding document"))
        if current_sources is not None:
            current = current_sources.get(source_id)
            if not isinstance(current, Mapping) or not current:
                findings.append(_finding("CURRENT_SOURCE_REQUIRED", path, "Independent current source record missing or malformed"))
            elif any(current.get(k) != document.get(k) for k in ("source_id", "document_revision", "content_hash")):
                findings.append(_finding("STALE_SOURCE", path, "Source identity, revision, or hash changed"))

    rules = profile.get("rules") if isinstance(profile.get("rules"), list) else []
    rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if not isinstance(rule, Mapping) or not rule.get("rule_id"):
            continue
        if rule["rule_id"] in rule_ids:
            findings.append(_finding("DUPLICATE_RULE", path, "Rule identity is duplicated"))
        rule_ids.add(rule["rule_id"])
        if rule.get("authority_type") != "LOCAL_CODE":
            findings.append(_finding("INVALID_RULE_AUTHORITY", f"{path}.authority_type", "Local rules require LOCAL_CODE"))
        if rule.get("topic") not in TOPICS:
            findings.append(_finding("UNSUPPORTED_RULE_TOPIC", f"{path}.topic", "Unsupported topic"))
        source = docs.get(rule.get("source_id"))
        if source is None:
            findings.append(_finding("MISSING_RULE_SOURCE", f"{path}.source_id", "Rule source missing"))
        if rule.get("verification_status") == "AUTHORITY_QUALIFIED":
            if source is None or source.get("verification_status") != "AUTHORITY_QUALIFIED":
                findings.append(_finding("RULE_EXCEEDS_SOURCE_AUTHORITY", path, "Rule authority exceeds its source"))
            if not _review_valid(rule.get("review"), source_id=rule.get("source_id"),
                                 source_revision=source.get("document_revision") if source else None):
                findings.append(_finding("UNSUPPORTED_VERIFIED_RULE", path, "Qualified rule requires scoped review"))
        scope = rule.get("jurisdiction_scope") if isinstance(rule.get("jurisdiction_scope"), Mapping) else {}
        for field in ("country", "province", "city", "municipality", "municipal_district", "planning_zone"):
            if field in scope and scope[field] != profile.get(field):
                findings.append(_finding("RULE_JURISDICTION_MISMATCH", f"{path}.jurisdiction_scope.{field}", "Rule scope differs from profile jurisdiction"))
        temporal = rule.get("temporal_scope") if isinstance(rule.get("temporal_scope"), Mapping) else {}
        rule_from, rule_until = _date(temporal.get("effective_from")), _date(temporal.get("effective_until"))
        if temporal.get("effective_from") is not None and rule_from is None:
            findings.append(_finding("INVALID_RULE_TEMPORAL_SCOPE", f"{path}.temporal_scope.effective_from", "Valid date required"))
        if temporal.get("effective_until") is not None and rule_until is None:
            findings.append(_finding("INVALID_RULE_TEMPORAL_SCOPE", f"{path}.temporal_scope.effective_until", "Valid date required"))
        if rule_from and rule_until and rule_until < rule_from:
            findings.append(_finding("INVALID_RULE_TEMPORAL_SCOPE", f"{path}.temporal_scope", "Rule end precedes start"))
        if evaluation_date and rule_from and evaluation_date < rule_from:
            findings.append(_finding("RULE_OUTSIDE_EFFECTIVE_PERIOD", path, "Rule is not yet effective"))
        if evaluation_date and rule_until and evaluation_date > rule_until:
            findings.append(_finding("RULE_OUTSIDE_EFFECTIVE_PERIOD", path, "Rule expired"))
    try:
        expected_hash = stable_hash(profile_content(profile))
    except (TypeError, ValueError):
        expected_hash = None
    if profile.get("profile_hash") != expected_hash:
        findings.append(_finding("INVALID_PROFILE_HASH", "profile_hash", "Profile content hash mismatch"))

    codes = {f["code"] for f in findings}
    if codes & {"STALE_SOURCE", "SUPERSEDED_SOURCE", "OUTSIDE_EFFECTIVE_PERIOD", "RULE_OUTSIDE_EFFECTIVE_PERIOD", "INVALID_PROFILE_HASH"}:
        status = "STALE_BINDING"
    elif findings:
        status = "INPUT_REQUIRED"
    elif set(profile.get("markers", [])) == MARKERS:
        status = "STRUCTURALLY_VALID"
    else:
        # Marker-free records represent real-like authority claims. Embedded
        # reviews and caller-provided snapshots cannot prove independent source
        # authenticity or professional qualification, regardless of the
        # caller-supplied verification_status.
        status = "AUTHORITY_REVIEW_REQUIRED"
    return {"status": status, "findings": findings, "content_hash": expected_hash, "runtime_enabled": False}


def profile_hash(profile: Mapping[str, Any]) -> str:
    return stable_hash(profile_content(profile))


def dependency_fingerprint(*, project_id: str, parcel_id: str, site_model_hash: str, survey_hash: str,
                           local_profile_hash: str, national_profile_hash: str, effective_date: str,
                           rule_ids: list[str], building_line_source: str | None,
                           exception_ids: list[str], relevant_program_inputs: Mapping[str, Any]) -> str:
    return stable_hash({
        "project_id": project_id, "parcel_id": parcel_id, "site_model_hash": site_model_hash,
        "survey_hash": survey_hash, "local_profile_hash": local_profile_hash,
        "national_profile_hash": national_profile_hash, "effective_date": effective_date,
        "rule_ids": sorted(rule_ids), "building_line_source": building_line_source,
        "exception_ids": sorted(exception_ids), "relevant_program_inputs": relevant_program_inputs,
    })


def _signed_area(points: list[list[float]]) -> float:
    return sum(points[i][0] * points[i + 1][1] - points[i + 1][0] * points[i][1] for i in range(len(points) - 1)) / 2


def _clip(points: list[tuple[float, float]], a: tuple[float, float], b: tuple[float, float], distance: float,
          orientation: float) -> list[tuple[float, float]]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    nx, ny = orientation * -dy / length, orientation * dx / length
    c = nx * a[0] + ny * a[1] + distance
    inside = lambda p: nx * p[0] + ny * p[1] >= c - 1e-9
    output: list[tuple[float, float]] = []
    for current, previous in zip(points, points[-1:] + points[:-1]):
        ci, pi = inside(current), inside(previous)
        if ci != pi:
            vx, vy = current[0] - previous[0], current[1] - previous[1]
            denom = nx * vx + ny * vy
            if abs(denom) > 1e-12:
                t = (c - nx * previous[0] - ny * previous[1]) / denom
                output.append((previous[0] + t * vx, previous[1] + t * vy))
        if ci:
            output.append(current)
    return output


def derive_buildable_envelope(site_model: Mapping[str, Any], *, edge_constraints: list[Mapping[str, Any]],
                              dependency_id: str) -> dict[str, Any]:
    """Derive an envelope only for a valid convex polygon with explicit edge setbacks."""
    findings: list[dict[str, str]] = []
    if not isinstance(site_model, Mapping):
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": [_finding("INVALID_SITE_MODEL", "site_model", "Object required")]}
    boundary = site_model.get("parcel_boundary")
    if not isinstance(boundary, list) or len(boundary) < 4 or boundary[0] != boundary[-1]:
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": [_finding("INVALID_PARCEL", "parcel_boundary", "Closed polygon required")]}
    if site_model.get("units") != "m" or not site_model.get("coordinate_reference_system"):
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": [_finding("UNITS_OR_CRS_REQUIRED", "site_model", "Metres and CRS required")]}
    if not _is_hash(dependency_id):
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": [_finding("INVALID_DEPENDENCY_FINGERPRINT", "dependency_id", "Lowercase SHA-256 required")]}
    for index, point in enumerate(boundary):
        if not isinstance(point, (list, tuple)) or len(point) != 2 or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in point
        ):
            findings.append(_finding("NONFINITE_OR_INVALID_COORDINATE", f"parcel_boundary[{index}]", "Two finite real coordinates required"))
    if findings:
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": findings}
    for index in range(len(boundary) - 1):
        if boundary[index] == boundary[index + 1]:
            findings.append(_finding("ZERO_LENGTH_PARCEL_EDGE", f"parcel_boundary[{index}]", "Consecutive duplicate vertices are forbidden"))
    if findings:
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": findings}
    try:
        polygon = Polygon(boundary)
    except (TypeError, ValueError):
        polygon = Polygon()
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": [_finding("INVALID_PARCEL", "parcel_boundary", "Valid parcel polygon required")]}
    vertices = boundary[:-1]
    signs = []
    for i in range(len(vertices)):
        p0, p1, p2 = vertices[i - 1], vertices[i], vertices[(i + 1) % len(vertices)]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if abs(cross) > 1e-9:
            signs.append(math.copysign(1, cross))
    if signs and len(set(signs)) > 1:
        return {"status": "AUTHORITY_REVIEW_REQUIRED", "geometry": None, "findings": [_finding("COMPLEX_PARCEL_REVIEW_REQUIRED", "parcel_boundary", "Concave parcel requires bounded professional geometry review")]}
    if not isinstance(edge_constraints, list):
        return {"status": "INPUT_REQUIRED", "geometry": None, "findings": [_finding("INVALID_EDGE_CONSTRAINTS", "edge_constraints", "Array required")]}
    by_edge: dict[int, Mapping[str, Any]] = {}
    for i, item in enumerate(edge_constraints):
        if not isinstance(item, Mapping):
            findings.append(_finding("INVALID_EDGE_BINDING", f"edge_constraints[{i}]", "Object required"))
            continue
        edge = item.get("edge_index")
        if type(edge) is not int or edge < 0 or edge >= len(vertices) or edge in by_edge:
            findings.append(_finding("INVALID_EDGE_BINDING", f"edge_constraints[{i}]", "Unique parcel edge required"))
        elif not isinstance(item.get("distance_m"), (int, float)) or isinstance(item.get("distance_m"), bool) or not math.isfinite(item["distance_m"]) or item["distance_m"] < 0:
            findings.append(_finding("INVALID_SETBACK", f"edge_constraints[{i}].distance_m", "Nonnegative metres required"))
        elif not isinstance(item.get("source_references"), list) or not item["source_references"] or not all(
            isinstance(value, str) and value for value in item["source_references"]
        ) or not isinstance(item.get("rule_ids"), list) or not item["rule_ids"] or not all(
            isinstance(value, str) and value for value in item["rule_ids"]
        ):
            findings.append(_finding("UNTRACEABLE_SETBACK", f"edge_constraints[{i}]", "Source and rule references required"))
        else:
            by_edge[edge] = item
    if len(by_edge) != len(vertices):
        findings.append(_finding("MISSING_EDGE_CONSTRAINT", "edge_constraints", "Every parcel edge requires an explicit applicable setback"))
    if findings:
        malformed = {"INVALID_EDGE_BINDING", "INVALID_SETBACK"}
        status = "INPUT_REQUIRED" if {finding["code"] for finding in findings} & malformed else "LOCAL_RULE_REQUIRED"
        return {"status": status, "geometry": None, "findings": findings}
    orientation = 1.0 if _signed_area(boundary) > 0 else -1.0
    output = [(float(x), float(y)) for x, y in vertices]
    for edge in range(len(vertices)):
        output = _clip(output, tuple(vertices[edge]), tuple(vertices[(edge + 1) % len(vertices)]), float(by_edge[edge]["distance_m"]), orientation)
        if len(output) < 3:
            return {"status": "CONFLICT_REVIEW_REQUIRED", "geometry": None, "findings": [_finding("IMPOSSIBLE_ENVELOPE", "edge_constraints", "Setbacks eliminate the buildable area")]}
    ring = [[round(x, 9), round(y, 9)] for x, y in output]
    ring.append(ring[0])
    envelope = Polygon(ring)
    if not envelope.is_valid or envelope.is_empty or not polygon.covers(envelope):
        return {"status": "CONFLICT_REVIEW_REQUIRED", "geometry": None, "findings": [_finding("INVALID_DERIVED_ENVELOPE", "geometry", "Envelope failed independent polygon validation")]}
    geometry_hash = stable_hash({"crs": site_model["coordinate_reference_system"], "units": "m", "ring": ring})
    source_references = sorted({source for item in edge_constraints for source in item["source_references"]})
    rule_ids = sorted({rule_id for item in edge_constraints for rule_id in item["rule_ids"]})
    derived_constraint = {
        "constraint_id": f"buildable-envelope-{geometry_hash[:20]}",
        "constraint_type": "BUILDABLE_ENVELOPE",
        "input_references": [site_model.get("id"), site_model.get("survey_id")],
        "source_references": source_references,
        "applicability": {"parcel_id": site_model.get("parcel_id"), "edge_count": len(vertices)},
        "rule_or_formula": {"method": "INWARD_EDGE_HALF_PLANE_INTERSECTION", "rule_ids": rule_ids},
        "calculated_value": {"area_m2": envelope.area, "geometry_hash": geometry_hash},
        "unit": "m2", "geometry_reference": geometry_hash, "verification_status": "CALCULATED",
        "review_reference": None, "dependency_fingerprint": dependency_id,
    }
    return {
        "status": "STRUCTURALLY_VALID", "geometry": ring, "area_m2": envelope.area,
        "geometry_hash": geometry_hash, "derived_constraint": derived_constraint,
        "dependency_fingerprint": dependency_id, "verification_status": "CALCULATED_NOT_PROFESSIONALLY_APPROVED",
        "findings": [],
    }


def basis_content(basis: Mapping[str, Any]) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in basis.items() if k not in {"basis_hash", "status"}}


def validate_project_code_basis(basis: Any, *, current_site: Mapping[str, Any] | None = None,
                                current_local_profile: Mapping[str, Any] | None = None,
                                current_national_binding: Mapping[str, Any] | None = None,
                                current_owner_program: Mapping[str, Any] | None = None) -> dict[str, Any]:
    findings = _structural_findings(basis, "project-code-basis-v1.schema.json")
    if not isinstance(basis, Mapping):
        return {"status": "INPUT_REQUIRED", "findings": findings or [_finding("INVALID_PAYLOAD", "$", "Object required")]}
    if basis.get("runtime_enabled") is not False:
        findings.append(_finding("RUNTIME_ACTIVATION_FORBIDDEN", "runtime_enabled", "Offline contract only"))
    if findings:
        return {"status": "INPUT_REQUIRED", "findings": findings, "content_hash": None, "runtime_enabled": False}
    parcel = basis.get("parcel_identity") if isinstance(basis.get("parcel_identity"), Mapping) else {}
    if not basis.get("project_id") or not parcel.get("parcel_id"):
        findings.append(_finding("MISSING_PROJECT_OR_PARCEL", "parcel_identity", "Exact project and parcel required"))
    resolved_bindings = (
        ("site_model_binding", current_site, ("id", "revision", "source_hash")),
        ("local_rule_profile_binding", current_local_profile, ("profile_id", "profile_revision", "profile_hash")),
        ("national_ruleset_binding", current_national_binding, ("id", "revision", "source_hash")),
        ("owner_program_binding", current_owner_program, ("program_id", "program_revision", "content_hash")),
    )
    for binding_name, current, current_keys in resolved_bindings:
        binding = basis.get(binding_name)
        if not isinstance(binding, Mapping) or not all(binding.get(k) for k in ("id", "revision", "source_hash")):
            findings.append(_finding("MISSING_BINDING", binding_name, "Identity, revision and source hash required"))
        elif not isinstance(current, Mapping):
            findings.append(_finding("CURRENT_BINDING_REQUIRED", binding_name, "Independent current binding record required"))
        elif binding_name in {"local_rule_profile_binding", "owner_program_binding"} and any(
            (str(current.get(current_key)) if current_key in {"profile_revision", "program_revision"} else current.get(current_key)) != binding.get(binding_key)
            for current_key, binding_key in zip(current_keys, ("id", "revision", "source_hash"))
        ):
            findings.append(_finding("STALE_BINDING", binding_name, "Current binding differs"))
        elif binding_name not in {"local_rule_profile_binding", "owner_program_binding"} and any(current.get(k) != binding.get(k) for k in current_keys):
            findings.append(_finding("STALE_BINDING", binding_name, "Current binding differs"))
    if isinstance(current_site, Mapping):
        required_site_fields = ("survey_id", "survey_revision", "survey_hash", "coordinate_reference_system", "units", "parcel_boundary")
        if any(not current_site.get(field) for field in required_site_fields):
            findings.append(_finding("SITE_SURVEY_REQUIRED", "site_model_binding", "Current survey identity and geometry are required"))
        if current_site.get("parcel_id") != parcel.get("parcel_id"):
            findings.append(_finding("PARCEL_BINDING_MISMATCH", "site_model_binding", "Site belongs to another parcel"))
        if current_site.get("project_id") != basis.get("project_id"):
            findings.append(_finding("PROJECT_BINDING_MISMATCH", "site_model_binding", "Site belongs to another project"))
    if isinstance(current_owner_program, Mapping) and current_owner_program.get("project_id") != basis.get("project_id"):
        findings.append(_finding("PROJECT_BINDING_MISMATCH", "owner_program_binding", "Owner Program belongs to another project"))
    project_date = _date(basis.get("permit_or_design_effective_date"))
    if project_date is None:
        findings.append(_finding("EFFECTIVE_DATE_REQUIRED", "permit_or_design_effective_date", "Project date required"))
    if isinstance(current_local_profile, Mapping):
        profile_validation = validate_local_rule_profile(current_local_profile, as_of=basis.get("permit_or_design_effective_date"))
        if profile_validation["status"] == "STALE_BINDING":
            findings.append(_finding("STALE_BINDING", "local_rule_profile_binding", "Local profile is outside its current source or temporal scope"))
        elif profile_validation["status"] == "INPUT_REQUIRED":
            findings.append(_finding("LOCAL_PROFILE_INVALID", "local_rule_profile_binding", "Current LocalRuleProfile is incomplete"))
            return {"status": "INPUT_REQUIRED", "findings": findings + [
                _finding(f["code"], f"local_rule_profile_binding.{f['path']}", f["message"])
                for f in profile_validation["findings"]
            ], "content_hash": None, "runtime_enabled": False}
        jurisdiction_pairs = (
            ("country", parcel.get("country"), current_local_profile.get("country")),
            ("province", parcel.get("province"), current_local_profile.get("province")),
            ("city", parcel.get("city"), current_local_profile.get("city")),
            ("municipality", parcel.get("municipality"), current_local_profile.get("municipality")),
        )
        for field, parcel_value, profile_value in jurisdiction_pairs:
            if not parcel_value or not profile_value:
                findings.append(_finding("JURISDICTION_INPUT_REQUIRED", f"parcel_identity.{field}", "Material jurisdiction value required"))
            elif parcel_value != profile_value:
                findings.append(_finding("JURISDICTION_CONFLICT", f"parcel_identity.{field}", "Parcel and LocalRuleProfile disagree"))
        for field in ("municipal_district", "planning_zone"):
            parcel_value, profile_value = parcel.get(field), current_local_profile.get(field)
            material = any(field in rule.get("required_inputs", []) for rule in current_local_profile.get("rules", []) if isinstance(rule, Mapping))
            if material and (parcel_value is None or profile_value is None):
                findings.append(_finding("JURISDICTION_INPUT_REQUIRED", f"parcel_identity.{field}", "Rule applicability requires this jurisdiction value"))
            elif parcel_value is not None and profile_value is not None and parcel_value != profile_value:
                findings.append(_finding("JURISDICTION_CONFLICT", f"parcel_identity.{field}", "Parcel and LocalRuleProfile disagree"))
    accessibility = [d for d in basis.get("applicability_decisions", []) if isinstance(d, Mapping) and d.get("topic") == "ACCESSIBILITY"]
    if not accessibility or any(d.get("decision") == "UNKNOWN" for d in accessibility):
        findings.append(_finding("ACCESSIBILITY_APPLICABILITY_REQUIRED", "applicability_decisions", "Code 246 applicability must be independently established"))
    parking = [d for d in basis.get("applicability_decisions", []) if isinstance(d, Mapping) and d.get("topic") == "PARKING"]
    if parking and any(d.get("decision") == "UNKNOWN" or not d.get("source_references") for d in parking):
        findings.append(_finding("PARKING_AUTHORITY_REQUIRED", "applicability_decisions", "Applicable parking authority is unresolved"))
    for index, decision in enumerate(basis.get("applicability_decisions", [])):
        if not isinstance(decision, Mapping):
            continue
        if decision.get("authority_type") == "OWNER_REQUIREMENT" and decision.get("topic") in TOPICS:
            findings.append(_finding("OWNER_CANNOT_ASSERT_CODE", f"applicability_decisions[{index}]", "Owner requirements cannot establish regulatory applicability"))
        if decision.get("decision") in {"APPLICABLE", "NOT_APPLICABLE"} and decision.get("authority_type") not in {"NATIONAL_CODE", "LOCAL_CODE", "HUMAN_DECISION"}:
            findings.append(_finding("INVALID_APPLICABILITY_AUTHORITY", f"applicability_decisions[{index}]", "Independent code or scoped review required"))
        references = decision.get("source_references") if isinstance(decision.get("source_references"), list) else []
        if decision.get("authority_type") == "LOCAL_CODE" and isinstance(current_local_profile, Mapping):
            known = {d.get("source_id") for d in current_local_profile.get("source_documents", []) if isinstance(d, Mapping)} | {
                r.get("rule_id") for r in current_local_profile.get("rules", []) if isinstance(r, Mapping)
            }
            if not references or any(reference not in known for reference in references):
                findings.append(_finding("UNRESOLVED_APPLICABILITY_REFERENCE", f"applicability_decisions[{index}]", "Local source/rule reference is not current"))
        if decision.get("authority_type") == "NATIONAL_CODE":
            source_ids = current_national_binding.get("source_ids") if isinstance(current_national_binding, Mapping) else None
            known = set(source_ids) if isinstance(source_ids, list) and all(isinstance(value, str) for value in source_ids) else set()
            if not references or not known or any(reference not in known for reference in references):
                findings.append(_finding("UNRESOLVED_APPLICABILITY_REFERENCE", f"applicability_decisions[{index}]", "National source reference is not current"))
    conflicts = basis.get("conflicts") if isinstance(basis.get("conflicts"), list) else []
    if any(c.get("resolution") in {None, "UNRESOLVED"} for c in conflicts if isinstance(c, Mapping)):
        findings.append(_finding("UNRESOLVED_REGULATORY_CONFLICT", "conflicts", "Professional conflict review required"))
    try:
        expected_hash = stable_hash(basis_content(basis))
    except (TypeError, ValueError):
        expected_hash = None
    if basis.get("basis_hash") != expected_hash:
        findings.append(_finding("INVALID_BASIS_HASH", "basis_hash", "Basis content hash mismatch"))
    codes = {f["code"] for f in findings}
    binding_input = any(
        finding["code"] in {"MISSING_BINDING", "CURRENT_BINDING_REQUIRED"}
        and "local_rule_profile" not in finding["path"]
        for finding in findings
    )
    local_input = any(
        finding["code"] in {"MISSING_BINDING", "CURRENT_BINDING_REQUIRED"}
        and "local_rule_profile" in finding["path"]
        for finding in findings
    )
    if binding_input or codes & {"MISSING_PROJECT_OR_PARCEL", "SITE_SURVEY_REQUIRED", "JURISDICTION_INPUT_REQUIRED", "EFFECTIVE_DATE_REQUIRED", "ACCESSIBILITY_APPLICABILITY_REQUIRED", "PARKING_AUTHORITY_REQUIRED", "UNRESOLVED_APPLICABILITY_REFERENCE"}:
        status = "INPUT_REQUIRED"
    elif local_input:
        status = "LOCAL_RULE_REQUIRED"
    elif codes & {"STALE_BINDING", "INVALID_BASIS_HASH", "PARCEL_BINDING_MISMATCH", "PROJECT_BINDING_MISMATCH"}:
        status = "STALE_BINDING"
    elif codes & {"UNRESOLVED_REGULATORY_CONFLICT", "JURISDICTION_CONFLICT"}:
        status = "CONFLICT_REVIEW_REQUIRED"
    elif findings:
        status = "INPUT_REQUIRED"
    elif set(basis.get("markers", [])) == MARKERS:
        status = "STRUCTURALLY_VALID"
    else:
        status = "AUTHORITY_REVIEW_REQUIRED"
    return {"status": status, "findings": findings, "content_hash": expected_hash, "runtime_enabled": False}
