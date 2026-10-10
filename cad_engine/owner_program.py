"""Offline Owner Program 2.0 contracts, migration, and deterministic validation.

This module is intentionally not imported by the production runtime.  It prepares
versioned architectural inputs without granting geometry, code, or generation
authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from cad_engine.residential_foundation import branch_state, load_catalog, questionnaire_state, stable_hash, unit_program_errors


SCHEMA_VERSION_DRAFT = "architecture-owner-program-draft/2.0"
SCHEMA_VERSION_RESOLVED = "architecture-resolved-generation-input/2.0"
AUTHORITY_TYPES = {
    "OWNER_REQUIREMENT",
    "OWNER_PREFERENCE",
    "SITE_EVIDENCE",
    "NATIONAL_CODE",
    "LOCAL_CODE",
    "DERIVED_GEOMETRY",
    "SYSTEM_CALCULATION",
    "HUMAN_DECISION",
    "UNKNOWN_LEGACY_SOURCE",
}
VERIFICATION_STATUSES = {"VERIFIED", "UNVERIFIED", "INPUT_REQUIRED", "STALE", "UNKNOWN"}
HEX_DIGITS = frozenset("0123456789abcdef")
DRAFT_MATERIAL_FIELDS = {
    "project_requirements.building_use",
    "project_requirements.floor_count",
    "project_requirements.typical_floor_constraints",
    "unit_program.units_per_floor",
    "unit_program.unit_types",
    "spaces.required",
    "spaces.optional",
    "spaces.prohibited",
    "spaces.minimum_counts",
    "spaces.preferred_counts",
    "relationships.required_adjacencies",
    "relationships.preferred_adjacencies",
    "relationships.preferred_avoid_adjacencies",
    "relationships.prohibited_adjacencies",
    "preferences.privacy_tiers",
    "preferences.zoning.day_night",
    "preferences.zoning.guest_family",
    "preferences.zoning.service",
    "preferences.furniture_requirements",
    "preferences.accessibility.owner_preference",
    "preferences.accessibility.regulatory_obligation",
    "preferences.accessibility.needs",
    "preferences.priorities",
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX_DIGITS


def _finding(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _matches_schema_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": _finite(value),
        "null": value is None,
        "boolean": type(value) is bool,
    }.get(expected, True)


def _schema_errors(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[dict[str, str]]:
    """Validate the JSON-Schema subset used by the two offline v2 contracts."""
    findings: list[dict[str, str]] = []
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected] if isinstance(expected, str) else []
    if types and not any(_matches_schema_type(value, item) for item in types):
        return [_finding("SCHEMA_VALIDATION", path, f"Expected schema type {expected}")]
    if "const" in schema and value != schema["const"]:
        findings.append(_finding("SCHEMA_VALIDATION", path, "Value does not match the contract constant"))
    if "enum" in schema and value not in schema["enum"]:
        findings.append(_finding("SCHEMA_VALIDATION", path, "Value is outside the contract enumeration"))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            findings.append(_finding("SCHEMA_VALIDATION", path, "String is shorter than the contract minimum"))
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            findings.append(_finding("SCHEMA_VALIDATION", path, "String does not match the contract pattern"))
    if _finite(value):
        if "minimum" in schema and value < schema["minimum"]:
            findings.append(_finding("SCHEMA_VALIDATION", path, "Number is below the contract minimum"))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            findings.append(_finding("SCHEMA_VALIDATION", path, "Number is not above the exclusive minimum"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            findings.append(_finding("SCHEMA_VALIDATION", path, "Array is shorter than the contract minimum"))
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) for item in value]
            if len(encoded) != len(set(encoded)):
                findings.append(_finding("SCHEMA_VALIDATION", path, "Array items must be unique"))
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                findings.extend(_schema_errors(item, item_schema, f"{path}[{index}]"))
    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                findings.append(_finding("SCHEMA_VALIDATION", f"{path}.{key}", "Required contract field is missing"))
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                findings.extend(_schema_errors(child, properties[key], child_path))
            elif schema.get("additionalProperties") is False:
                findings.append(_finding("SCHEMA_VALIDATION", child_path, "Unexpected contract field"))
            elif isinstance(schema.get("additionalProperties"), Mapping):
                findings.extend(_schema_errors(child, schema["additionalProperties"], child_path))
    return findings


def _contract_schema_findings(payload: Any, filename: str) -> list[dict[str, str]]:
    root = Path(__file__).resolve().parents[1]
    try:
        schema = json.loads((root / "standards/test-suites/residential" / filename).read_text())
    except (OSError, ValueError) as exc:
        return [_finding("SCHEMA_UNAVAILABLE", "$", f"Contract schema could not be loaded: {exc}")]
    return _schema_errors(payload, schema)


def _relation_key(relation: Any) -> tuple[str, str] | None:
    if not isinstance(relation, Mapping):
        return None
    left, right = relation.get("from"), relation.get("to")
    if not isinstance(left, str) or not left or not isinstance(right, str) or not right:
        return None
    return tuple(sorted((left, right)))


def _value_at_path(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _status(findings: list[dict[str, str]], *, draft: bool) -> str:
    codes = {finding["code"] for finding in findings}
    if codes & {
        "INVALID_COUNT",
        "UNIT_TOTAL_MISMATCH",
        "REQUIRED_PROHIBITED_SPACE_CONFLICT",
        "REQUIRED_PROHIBITED_ADJACENCY_CONFLICT",
        "ACCESSIBILITY_AUTHORITY_CONFLICT",
        "CONDITIONAL_ANSWER_OUT_OF_SCOPE",
    }:
        return "DEFINITELY_INVALID"
    if findings:
        return "INPUT_REQUIRED"
    return "DRAFT_VALID" if draft else "NEEDS_GEOMETRIC_FEASIBILITY_CHECK"


def _provenance_map(draft: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, str]]]:
    result: dict[str, Mapping[str, Any]] = {}
    findings: list[dict[str, str]] = []
    entries = draft.get("provenance")
    if not isinstance(entries, list):
        return result, [_finding("MISSING_PROVENANCE", "provenance", "Per-field provenance is required")]
    for index, entry in enumerate(entries):
        path = f"provenance[{index}]"
        if not isinstance(entry, Mapping) or not isinstance(entry.get("field_id"), str):
            findings.append(_finding("INVALID_PROVENANCE", path, "A stable field_id is required"))
            continue
        field_id = entry["field_id"]
        if field_id in result:
            findings.append(_finding("DUPLICATE_PROVENANCE", path, f"Duplicate provenance for {field_id}"))
            continue
        if entry.get("authority_type") not in AUTHORITY_TYPES:
            findings.append(_finding("INVALID_PROVENANCE", path, "Unknown authority_type"))
        if entry.get("verification_status") not in VERIFICATION_STATUSES:
            findings.append(_finding("INVALID_PROVENANCE", path, "Unknown verification_status"))
        for key in ("source_type", "source_reference"):
            if not isinstance(entry.get(key), str) or not entry.get(key):
                findings.append(_finding("INVALID_PROVENANCE", f"{path}.{key}", f"{key} is required"))
        if not _is_sha256(entry.get("source_hash")):
            findings.append(_finding("INVALID_PROVENANCE", f"{path}.source_hash", "A lowercase SHA-256 is required"))
        if type(entry.get("revision")) is not int or entry["revision"] < 1:
            findings.append(_finding("INVALID_PROVENANCE", f"{path}.revision", "A positive source revision is required"))
        if not isinstance(entry.get("dependencies"), list) or any(
            not isinstance(value, str) or not value for value in entry.get("dependencies", [])
        ):
            findings.append(_finding("INVALID_PROVENANCE", f"{path}.dependencies", "Dependencies must be stable IDs"))
        result[field_id] = entry
    return result, findings


def _allowed_authorities(field_id: str) -> set[str]:
    if field_id == "preferences.accessibility.regulatory_obligation":
        return {"NATIONAL_CODE", "LOCAL_CODE"}
    if field_id in {
        "preferences.accessibility.owner_preference",
        "preferences.accessibility.needs",
    }:
        return {"OWNER_PREFERENCE", "OWNER_REQUIREMENT", "HUMAN_DECISION"}
    if field_id.startswith("preferences."):
        allowed = {"OWNER_PREFERENCE", "OWNER_REQUIREMENT", "HUMAN_DECISION"}
        return allowed
    if field_id.startswith("project_requirements."):
        return {"OWNER_REQUIREMENT", "SITE_EVIDENCE", "HUMAN_DECISION", "NATIONAL_CODE", "LOCAL_CODE"}
    return {"OWNER_REQUIREMENT", "HUMAN_DECISION", "NATIONAL_CODE", "LOCAL_CODE"}


def _resolution_readiness_findings(draft: Mapping[str, Any]) -> list[dict[str, str]]:
    """Checks required for authority promotion, deliberately stricter than draft save."""
    findings: list[dict[str, str]] = []
    unit_program = draft.get("unit_program")
    if not isinstance(unit_program, Mapping):
        return [_finding("INCOMPLETE_UNIT_PROGRAM", "unit_program", "A canonical unit program is required for resolution")]
    units_per_floor = unit_program.get("units_per_floor")
    unit_types = unit_program.get("unit_types")
    if type(units_per_floor) is not int or units_per_floor < 1 or not isinstance(unit_types, list) or not unit_types:
        findings.append(_finding("INCOMPLETE_UNIT_PROGRAM", "unit_program", "Unit count and at least one unit type are required for resolution"))
    else:
        try:
            errors = unit_program_errors(unit_types, units_per_floor)
        except (TypeError, ValueError, KeyError):
            errors = ["INVALID_UNIT_PROGRAM"]
        for code in errors:
            findings.append(_finding(code, "unit_program", "Canonical unit program is inconsistent"))

    provenance, provenance_findings = _provenance_map(draft)
    findings.extend(provenance_findings)
    for field_id in sorted(DRAFT_MATERIAL_FIELDS):
        entry = provenance.get(field_id)
        if entry is None:
            findings.append(_finding("MISSING_PROVENANCE", field_id, "Material field requires explicit provenance"))
            continue
        if entry.get("verification_status") != "VERIFIED":
            findings.append(_finding("UNVERIFIED_MATERIAL_PROVENANCE", field_id, "Material provenance must be independently verified"))
        if entry.get("authority_type") not in _allowed_authorities(field_id):
            findings.append(_finding("INVALID_FIELD_AUTHORITY", field_id, "Authority type cannot authorize this material field"))
        if entry.get("value") != _value_at_path(draft, field_id):
            findings.append(_finding("PROVENANCE_VALUE_MISMATCH", field_id, "Provenance value must equal the canonical field value"))
    applicability = _value_at_path(draft, "preferences.accessibility.regulatory_obligation")
    if applicability == "UNKNOWN":
        findings.append(_finding(
            "ACCESSIBILITY_APPLICABILITY_REQUIRED",
            "preferences.accessibility.regulatory_obligation",
            "Regulatory applicability requires independently supported national or local code evidence",
        ))
    return findings


def evidence_input_identity(
    draft: Mapping[str, Any],
    *,
    site_binding: Mapping[str, Any] | None,
    national_ruleset_binding: Mapping[str, Any] | None,
    local_profile_binding: Mapping[str, Any] | None,
) -> str | None:
    """Fingerprint the exact inputs a geometry evidence artifact evaluates."""
    if not isinstance(draft, Mapping):
        return None
    try:
        basis = {
            "project_id": draft.get("project_id"),
            "program_id": draft.get("program_id"),
            "program_revision": draft.get("program_revision"),
            "owner_program_hash": _json_hash(draft),
            "canonical_unit_program_hash": _json_hash(draft.get("unit_program")),
            "site_binding": site_binding,
            "national_ruleset_binding": national_ruleset_binding,
            "local_profile_binding": local_profile_binding,
        }
        return f"evidence-input-{stable_hash(basis)}"
    except (TypeError, ValueError):
        return None


def _binding_findings(
    resolved: Mapping[str, Any],
    current_bindings: Mapping[str, Mapping[str, Any]] | None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    names = (
        ("site_binding", "MISSING_SITE_MODEL"),
        ("national_ruleset_binding", "MISSING_NATIONAL_RULESET"),
        ("local_profile_binding", "MISSING_LOCAL_PROFILE"),
    )
    for name, missing_code in names:
        binding = resolved.get(name)
        if not isinstance(binding, Mapping):
            findings.append(_finding(missing_code, name, "A complete immutable binding is required"))
            continue
        if binding.get("verification_status") != "VERIFIED":
            findings.append(_finding(missing_code, name, "A verified immutable binding is required"))
        for key in ("id", "version", "source_reference"):
            if not isinstance(binding.get(key), str) or not binding.get(key):
                findings.append(_finding(missing_code, f"{name}.{key}", "Binding identity is incomplete"))
        if not _is_sha256(binding.get("source_hash")):
            findings.append(_finding(missing_code, f"{name}.source_hash", "Binding requires a lowercase SHA-256"))

    if current_bindings is None:
        findings.append(_finding("CURRENT_BINDINGS_REQUIRED", "current_bindings", "Current authoritative bindings must be independently supplied"))
        return findings
    for name, _ in names:
        expected = current_bindings.get(name) if isinstance(current_bindings, Mapping) else None
        actual = resolved.get(name)
        if not isinstance(expected, Mapping) or expected.get("verification_status") != "VERIFIED":
            findings.append(_finding("CURRENT_BINDING_UNVERIFIED", name, "Current authority registry did not verify this binding"))
            continue
        if not isinstance(actual, Mapping) or any(
            actual.get(key) != expected.get(key)
            for key in ("id", "version", "source_reference", "source_hash")
        ):
            findings.append(_finding("STALE_BINDING", name, "Binding no longer matches the current authoritative revision"))
    return findings


def _derived_fact_findings(
    resolved: Mapping[str, Any],
    current_geometry_evidence: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    facts = resolved.get("derived_project_facts")
    if not isinstance(facts, list):
        return [_finding("INVALID_DERIVED_FACT", "derived_project_facts", "Derived facts must be an array")]
    geometry_proof: Mapping[str, Any] | None = None
    seen: set[str] = set()
    for index, fact in enumerate(facts):
        path = f"derived_project_facts[{index}]"
        if not isinstance(fact, Mapping):
            findings.append(_finding("INVALID_DERIVED_FACT", path, "Derived fact must be an object"))
            continue
        field_id = fact.get("field_id")
        if not isinstance(field_id, str) or not field_id or field_id in seen:
            findings.append(_finding("INVALID_DERIVED_FACT", f"{path}.field_id", "Derived fact identity is missing or duplicated"))
        else:
            seen.add(field_id)
        for key in ("source_type", "source_reference"):
            if not isinstance(fact.get(key), str) or not fact.get(key):
                findings.append(_finding("INVALID_DERIVED_FACT", f"{path}.{key}", f"{key} is required"))
        if not _is_sha256(fact.get("source_hash")):
            findings.append(_finding("INVALID_DERIVED_FACT", f"{path}.source_hash", "A lowercase SHA-256 is required"))
        if type(fact.get("revision")) is not int or fact["revision"] < 1:
            findings.append(_finding("INVALID_DERIVED_FACT", f"{path}.revision", "A positive source revision is required"))
        if fact.get("verification_status") != "VERIFIED":
            findings.append(_finding("UNVERIFIED_DERIVED_FACT", path, "Derived fact must be independently verified"))
        if fact.get("authority_type") not in {
            "DERIVED_GEOMETRY", "SYSTEM_CALCULATION", "SITE_EVIDENCE", "NATIONAL_CODE", "LOCAL_CODE", "HUMAN_DECISION"
        }:
            findings.append(_finding("INVALID_DERIVED_AUTHORITY", path, "Authority type cannot authorize a derived fact"))
        if (
            field_id == "geometry_feasibility"
            and fact.get("value") == "VERIFIED"
            and fact.get("authority_type") == "DERIVED_GEOMETRY"
            and fact.get("verification_status") == "VERIFIED"
            and _is_sha256(fact.get("source_hash"))
            and fact.get("dependencies") == [resolved.get("evidence_input_id")]
        ):
            geometry_proof = fact
    if resolved.get("geometry_feasibility") == "VERIFIED":
        if geometry_proof is None:
            findings.append(_finding(
                "GEOMETRY_PROOF_REQUIRED",
                "geometry_feasibility",
                "Geometry evidence must depend on the exact evidence-input identity",
            ))
        elif not isinstance(current_geometry_evidence, Mapping):
            findings.append(_finding(
                "GEOMETRY_EVIDENCE_UNRESOLVED",
                "current_geometry_evidence",
                "Independent current geometry evidence is required",
            ))
        elif current_geometry_evidence.get("verification_status") != "VERIFIED" or any(
            current_geometry_evidence.get(key) != geometry_proof.get(key)
            for key in (
                "field_id", "value", "source_type", "source_reference", "source_hash",
                "authority_type", "revision", "dependencies",
            )
        ):
            findings.append(_finding(
                "STALE_GEOMETRY_EVIDENCE",
                "current_geometry_evidence",
                "Geometry evidence does not match the current independently verified artifact",
            ))
    return findings


def validate_owner_program_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a v2 draft without requiring site or regulatory bindings."""
    findings: list[dict[str, str]] = []
    if not isinstance(draft, Mapping) or draft.get("schema_version") != SCHEMA_VERSION_DRAFT:
        findings.append(_finding("SCHEMA_VERSION", "schema_version", "OwnerProgramDraft 2.0 is required"))
        return _validation_result("INPUT_REQUIRED", findings, draft)
    findings.extend(_contract_schema_findings(draft, "owner-program-draft-v2.schema.json"))
    if draft.get("runtime_enabled") is not False:
        findings.append(_finding("RUNTIME_ACTIVATION_FORBIDDEN", "runtime_enabled", "Owner Program 2.0 is offline-only"))
    for field in ("program_id", "project_id", "program_revision", "questionnaire_version", "answers_hash"):
        if draft.get(field) in (None, ""):
            findings.append(_finding("MISSING_REQUIRED_FIELD", field, "Required draft identity is missing"))
    if not isinstance(draft.get("program_revision"), int) or isinstance(draft.get("program_revision"), bool) or draft.get("program_revision", 0) < 1:
        findings.append(_finding("INVALID_COUNT", "program_revision", "Revision must be a positive integer"))

    unit_program = draft.get("unit_program", {})
    units_per_floor = unit_program.get("units_per_floor") if isinstance(unit_program, Mapping) else None
    unit_types = unit_program.get("unit_types") if isinstance(unit_program, Mapping) else None
    unit_known = units_per_floor is not None or bool(unit_types)
    if unit_known:
        try:
            unit_errors = unit_program_errors(unit_types, units_per_floor)
        except (TypeError, ValueError, KeyError):
            unit_errors = ["INVALID_UNIT_PROGRAM"]
        for code in unit_errors:
            findings.append(_finding(code, "unit_program", "Canonical unit program is inconsistent"))

    spaces = draft.get("spaces", {})
    if not isinstance(spaces, Mapping):
        findings.append(_finding("MISSING_REQUIRED_FIELD", "spaces", "Space requirements are required"))
        spaces = {}
    required = spaces.get("required", [])
    prohibited = spaces.get("prohibited", [])
    if not isinstance(required, list) or not isinstance(prohibited, list):
        findings.append(_finding("MISSING_REQUIRED_FIELD", "spaces", "Space sets must be arrays"))
    else:
        try:
            overlap = set(required) & set(prohibited)
        except TypeError:
            findings.append(_finding("INVALID_SPACE", "spaces", "Space IDs must be hashable strings"))
        else:
            if overlap:
                findings.append(_finding("REQUIRED_PROHIBITED_SPACE_CONFLICT", "spaces", "A space cannot be required and prohibited"))
    minimum_counts = spaces.get("minimum_counts", {})
    if not isinstance(minimum_counts, Mapping) or any(type(v) is not int or v < 0 for v in minimum_counts.values()):
        findings.append(_finding("INVALID_COUNT", "spaces.minimum_counts", "Minimum counts must be non-negative integers"))

    relationships = draft.get("relationships", {})
    required_relations = relationships.get("required_adjacencies", []) if isinstance(relationships, Mapping) else []
    prohibited_relations = relationships.get("prohibited_adjacencies", []) if isinstance(relationships, Mapping) else []
    required_keys = {_relation_key(value) for value in required_relations}
    prohibited_keys = {_relation_key(value) for value in prohibited_relations}
    if None in required_keys | prohibited_keys:
        findings.append(_finding("INVALID_RELATION", "relationships", "Adjacency endpoints must be stable semantic IDs"))
    elif required_keys & prohibited_keys:
        findings.append(_finding("REQUIRED_PROHIBITED_ADJACENCY_CONFLICT", "relationships", "An adjacency cannot be required and prohibited"))

    preferences = draft.get("preferences", {})
    accessibility = preferences.get("accessibility", {}) if isinstance(preferences, Mapping) else {}
    if not isinstance(accessibility, Mapping):
        findings.append(_finding("MISSING_REQUIRED_FIELD", "preferences.accessibility", "Accessibility preferences must be an object"))
        accessibility = {}
    if accessibility.get("regulatory_obligation") == "REQUIRED" and accessibility.get("owner_preference") == "PROHIBIT":
        findings.append(_finding("ACCESSIBILITY_AUTHORITY_CONFLICT", "preferences.accessibility", "Owner preference cannot negate a mandatory obligation"))
    priorities = preferences.get("priorities") if isinstance(preferences, Mapping) else None
    if priorities is not None and (
        not isinstance(priorities, Mapping)
        or any(not _finite(value) or value < 0 for value in priorities.values())
        or not priorities
    ):
        findings.append(_finding("INVALID_PRIORITY", "preferences.priorities", "Priorities must be explicit finite non-negative values"))

    answers = draft.get("questionnaire_answers")
    if answers is not None:
        if not isinstance(answers, Mapping):
            findings.append(_finding("INVALID_QUESTIONNAIRE", "questionnaire_answers", "Questionnaire answers must be an object"))
            answers = {}
        if draft.get("answers_hash") != _json_hash(answers):
            findings.append(_finding("STALE_QUESTIONNAIRE_ANSWERS", "answers_hash", "Questionnaire answers do not match their recorded content hash"))
        try:
            questionnaire = questionnaire_state(answers)
        except ValueError as exc:
            findings.append(_finding("INVALID_QUESTIONNAIRE", "questionnaire_answers", str(exc)))
        else:
            for field in questionnaire["invalid"]:
                findings.append(_finding("INVALID_QUESTIONNAIRE", f"questionnaire_answers.{field}", "Questionnaire answer is invalid"))
            for field in questionnaire["missing"]:
                findings.append(_finding("MISSING_REQUIRED_FIELD", f"questionnaire_answers.{field}", "Mandatory questionnaire answer is missing"))
            for question in load_catalog("owner-questionnaire")["questions"]:
                field = question["field"]
                if field in answers and branch_state(question["condition"], answers) == "INACTIVE":
                    findings.append(_finding("CONDITIONAL_ANSWER_OUT_OF_SCOPE", f"questionnaire_answers.{field}", "Conditional answer is outside its applicability"))

    provenance, provenance_findings = _provenance_map(draft)
    findings.extend(provenance_findings)
    for field_id in sorted(DRAFT_MATERIAL_FIELDS - set(provenance)):
        findings.append(_finding("MISSING_PROVENANCE", field_id, "Material field requires explicit provenance"))
    for field_id in sorted(DRAFT_MATERIAL_FIELDS & set(provenance)):
        if provenance[field_id].get("value") != _value_at_path(draft, field_id):
            findings.append(_finding("PROVENANCE_VALUE_MISMATCH", field_id, "Provenance value must equal the canonical field value"))

    status = _status(findings, draft=True)
    return _validation_result(status, findings, draft)


def _validation_result(status: str, findings: list[dict[str, str]], payload: Any) -> dict[str, Any]:
    try:
        content_hash = _json_hash(payload)
    except (TypeError, ValueError):
        content_hash = None
        findings = [*findings, _finding("NON_JSON_VALUE", "$", "Payload must serialize deterministically")]
        status = "INPUT_REQUIRED"
    return {
        "status": status,
        "findings": sorted(findings, key=lambda item: (item["path"], item["code"], item["message"])),
        "content_hash": content_hash,
        "runtime_enabled": False,
        "construction_authority": False,
        "geometry_feasibility_proven": status == "VALIDATED_INPUT",
    }


def migrate_v1_owner_program(
    legacy: Mapping[str, Any],
    *,
    project_id: str,
    program_revision: int = 1,
    legacy_generation_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a non-destructive draft and explicit loss report from v1 data."""
    legacy_copy = copy.deepcopy(dict(legacy))
    findings: list[dict[str, str]] = []
    generation_program = None
    if legacy_generation_input is not None:
        generation_program = legacy_generation_input.get("program") if isinstance(legacy_generation_input, Mapping) else None
    if isinstance(generation_program, Mapping):
        units_per_floor = generation_program.get("units_per_floor")
        unit_types = copy.deepcopy(generation_program.get("unit_types", []))
        unit_source = "LEGACY_GENERATION_INPUT"
        unit_hash = _json_hash(legacy_generation_input)
    else:
        units_per_floor = None
        unit_types = []
        unit_source = "LEGACY_OWNER_PROGRAM"
        unit_hash = _json_hash(legacy_copy)
        findings.append(_finding("MATERIAL_INPUT_NOT_PRESENT", "unit_program", "v1 Owner Program does not contain canonical unit types"))

    legacy_adjacencies = legacy_copy.get("adjacency_preferences", [])
    legacy_avoid = legacy_copy.get("avoid_adjacency", [])
    def relations(values: Any, strength: str | None = None) -> list[dict[str, str]]:
        if not isinstance(values, list):
            return []
        return [
            {"from": value["from"], "to": value["to"]}
            for value in values
            if isinstance(value, Mapping)
            and isinstance(value.get("from"), str)
            and isinstance(value.get("to"), str)
            and (strength is None or value.get("strength") == strength)
        ]
    field_values = {
        "project_requirements.building_use": None,
        "project_requirements.floor_count": None,
        "project_requirements.typical_floor_constraints": {},
        "unit_program.units_per_floor": units_per_floor,
        "unit_program.unit_types": unit_types,
        "spaces.required": copy.deepcopy(legacy_copy.get("required_spaces", [])),
        "spaces.optional": copy.deepcopy(legacy_copy.get("optional_spaces", [])),
        "spaces.prohibited": [],
        "spaces.minimum_counts": copy.deepcopy(legacy_copy.get("minimum_counts", {})),
        "spaces.preferred_counts": copy.deepcopy(legacy_copy.get("preferred_counts", {})),
        "relationships.required_adjacencies": relations(legacy_adjacencies, "MANDATORY"),
        "relationships.preferred_adjacencies": relations(legacy_adjacencies, "PREFERRED"),
        "relationships.preferred_avoid_adjacencies": relations(legacy_avoid, "PREFERRED"),
        "relationships.prohibited_adjacencies": relations(legacy_avoid, "MANDATORY"),
        "preferences.privacy_tiers": copy.deepcopy(legacy_copy.get("privacy_tiers", {})),
        "preferences.zoning.day_night": copy.deepcopy(legacy_copy.get("day_night_zoning", {})),
        "preferences.zoning.guest_family": copy.deepcopy(legacy_copy.get("guest_family_zoning", {})),
        "preferences.zoning.service": copy.deepcopy(legacy_copy.get("service_zoning", {})),
        "preferences.furniture_requirements": copy.deepcopy(legacy_copy.get("furniture_expectations", [])),
        "preferences.accessibility.owner_preference": "LEGACY_UNSTRUCTURED" if legacy_copy.get("accessibility_needs") else "UNKNOWN",
        "preferences.accessibility.regulatory_obligation": "UNKNOWN",
        "preferences.accessibility.needs": copy.deepcopy(legacy_copy.get("accessibility_needs", [])),
        "preferences.priorities": copy.deepcopy(legacy_copy.get("priority_weights", {})),
    }
    provenance = []
    for field_id, value in sorted(field_values.items()):
        provenance.append({
            "field_id": field_id,
            "value": copy.deepcopy(value),
            "unit": None,
            "source_type": unit_source if field_id.startswith("unit_program.") else "LEGACY_OWNER_PROGRAM",
            "source_reference": legacy_copy.get("program_id", "UNKNOWN_LEGACY_PROGRAM"),
            "source_hash": unit_hash if field_id.startswith("unit_program.") else _json_hash(legacy_copy),
            "authority_type": "UNKNOWN_LEGACY_SOURCE",
            "verification_status": "UNKNOWN",
            "revision": program_revision,
            "dependencies": [],
        })
    draft = {
        "schema_version": SCHEMA_VERSION_DRAFT,
        "program_id": legacy_copy.get("program_id", f"legacy-{_json_hash(legacy_copy)[:16]}"),
        "project_id": project_id,
        "program_revision": program_revision,
        "questionnaire_version": legacy_copy.get("questionnaire_version", "UNKNOWN_LEGACY_VERSION"),
        "answers_hash": legacy_copy.get("answers_hash", _json_hash(legacy_copy)),
        "project_requirements": {
            "building_use": field_values["project_requirements.building_use"],
            "floor_count": field_values["project_requirements.floor_count"],
            "typical_floor_constraints": field_values["project_requirements.typical_floor_constraints"],
        },
        "unit_program": {"units_per_floor": units_per_floor, "unit_types": unit_types},
        "spaces": {
            "required": field_values["spaces.required"],
            "optional": field_values["spaces.optional"],
            "prohibited": [],
            "minimum_counts": field_values["spaces.minimum_counts"],
            "preferred_counts": field_values["spaces.preferred_counts"],
        },
        "relationships": {
            "required_adjacencies": field_values["relationships.required_adjacencies"],
            "preferred_adjacencies": field_values["relationships.preferred_adjacencies"],
            "preferred_avoid_adjacencies": field_values["relationships.preferred_avoid_adjacencies"],
            "prohibited_adjacencies": field_values["relationships.prohibited_adjacencies"],
        },
        "preferences": {
            "privacy_tiers": field_values["preferences.privacy_tiers"],
            "zoning": {
                "day_night": field_values["preferences.zoning.day_night"],
                "guest_family": field_values["preferences.zoning.guest_family"],
                "service": field_values["preferences.zoning.service"],
            },
            "furniture_requirements": field_values["preferences.furniture_requirements"],
            "accessibility": {
                "owner_preference": field_values["preferences.accessibility.owner_preference"],
                "regulatory_obligation": field_values["preferences.accessibility.regulatory_obligation"],
                "needs": field_values["preferences.accessibility.needs"],
            },
            "priorities": field_values["preferences.priorities"],
        },
        "questionnaire_answers": None,
        "provenance": provenance,
        "legacy": {
            "source_schema_version": "architecture-owner-program/1.0",
            "source_hash": _json_hash(legacy_copy),
            "preserved_payload": legacy_copy,
            "migration_findings": findings,
        },
        "runtime_enabled": False,
    }
    validation = validate_owner_program_draft(draft)
    return {
        "draft": draft,
        "validation": validation,
        "migration_findings": findings,
        "lossless_preservation": draft["legacy"]["preserved_payload"] == legacy_copy,
        "source_hash": draft["legacy"]["source_hash"],
        "draft_hash": _json_hash(draft),
    }


def resolve_generation_input(
    draft: Mapping[str, Any],
    *,
    site_binding: Mapping[str, Any] | None,
    national_ruleset_binding: Mapping[str, Any] | None,
    local_profile_binding: Mapping[str, Any] | None,
    derived_project_facts: list[Mapping[str, Any]] | None = None,
    geometry_feasibility: str = "NOT_EXECUTED",
    current_bindings: Mapping[str, Mapping[str, Any]] | None = None,
    current_geometry_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a valid draft to authority snapshots without activating generation."""
    if not isinstance(draft, Mapping):
        validation = validate_owner_program_draft(draft)
        return {"resolved_input": None, "validation": validation}
    draft_validation = validate_owner_program_draft(draft)
    owner_program_hash = draft_validation["content_hash"]
    try:
        canonical_unit_program_hash = _json_hash(draft.get("unit_program"))
    except (TypeError, ValueError):
        canonical_unit_program_hash = None
    evidence_input_id = evidence_input_identity(
        draft,
        site_binding=site_binding,
        national_ruleset_binding=national_ruleset_binding,
        local_profile_binding=local_profile_binding,
    )
    snapshot_basis = {
        "project_id": draft.get("project_id"),
        "program_id": draft.get("program_id"),
        "program_revision": draft.get("program_revision"),
        "owner_program_hash": owner_program_hash,
        "canonical_unit_program_hash": canonical_unit_program_hash,
        "evidence_input_id": evidence_input_id,
        "site_binding": site_binding,
        "national_ruleset_binding": national_ruleset_binding,
        "local_profile_binding": local_profile_binding,
        "derived_project_facts": derived_project_facts or [],
        "geometry_feasibility": geometry_feasibility,
    }
    try:
        resolved_id = f"resolved-{stable_hash(snapshot_basis)[:20]}"
    except (TypeError, ValueError):
        resolved_id = None
    payload = {
        "schema_version": SCHEMA_VERSION_RESOLVED,
        "resolved_id": resolved_id,
        "project_id": draft.get("project_id"),
        "program_id": draft.get("program_id"),
        "program_revision": draft.get("program_revision"),
        "owner_program_hash": owner_program_hash,
        "canonical_unit_program_hash": canonical_unit_program_hash,
        "evidence_input_id": evidence_input_id,
        "site_binding": copy.deepcopy(site_binding),
        "national_ruleset_binding": copy.deepcopy(national_ruleset_binding),
        "local_profile_binding": copy.deepcopy(local_profile_binding),
        "derived_project_facts": copy.deepcopy(derived_project_facts or []),
        "geometry_feasibility": geometry_feasibility,
        "runtime_enabled": False,
    }
    validation = validate_resolved_generation_input(
        payload,
        draft=draft,
        current_bindings=current_bindings,
        current_geometry_evidence=current_geometry_evidence,
    )
    payload["resolution_status"] = validation["status"]
    try:
        payload["resolution_hash"] = _json_hash(payload)
    except (TypeError, ValueError):
        payload["resolution_hash"] = None
    return {"resolved_input": payload, "validation": validation}


def validate_resolved_generation_input(
    resolved: Mapping[str, Any],
    *,
    draft: Mapping[str, Any],
    current_bindings: Mapping[str, Mapping[str, Any]] | None = None,
    current_geometry_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if not isinstance(resolved, Mapping):
        return _validation_result(
            "INPUT_REQUIRED",
            [_finding("INVALID_PAYLOAD", "$", "ResolvedGenerationInput must be an object")],
            resolved,
        )
    if not isinstance(draft, Mapping):
        return _validation_result(
            "INPUT_REQUIRED",
            [_finding("INVALID_PAYLOAD", "draft", "OwnerProgramDraft must be an object")],
            resolved,
        )
    schema_findings = _contract_schema_findings(resolved, "resolved-generation-input-v2.schema.json")
    if "resolution_status" not in resolved and "resolution_hash" not in resolved:
        schema_findings = [
            item for item in schema_findings
            if item["path"] not in {"$.resolution_status", "$.resolution_hash"}
        ]
    findings.extend(schema_findings)
    if resolved.get("schema_version") != SCHEMA_VERSION_RESOLVED:
        findings.append(_finding("SCHEMA_VERSION", "schema_version", "ResolvedGenerationInput 2.0 is required"))
    if resolved.get("runtime_enabled") is not False:
        findings.append(_finding("RUNTIME_ACTIVATION_FORBIDDEN", "runtime_enabled", "ResolvedGenerationInput 2.0 is offline-only"))
    draft_validation = validate_owner_program_draft(draft)
    if draft_validation["status"] != "DRAFT_VALID":
        findings.append(_finding("DRAFT_NOT_VALID", "owner_program_hash", "OwnerProgramDraft must be DRAFT_VALID"))
    if resolved.get("owner_program_hash") != draft_validation.get("content_hash"):
        findings.append(_finding("STALE_OWNER_PROGRAM", "owner_program_hash", "Draft content hash changed"))
    try:
        unit_program_hash = _json_hash(draft.get("unit_program"))
    except (TypeError, ValueError):
        unit_program_hash = None
    if resolved.get("canonical_unit_program_hash") != unit_program_hash:
        findings.append(_finding("STALE_UNIT_PROGRAM", "canonical_unit_program_hash", "Canonical unit program changed"))
    expected_evidence_input_id = evidence_input_identity(
        draft,
        site_binding=resolved.get("site_binding"),
        national_ruleset_binding=resolved.get("national_ruleset_binding"),
        local_profile_binding=resolved.get("local_profile_binding"),
    )
    if resolved.get("evidence_input_id") != expected_evidence_input_id:
        findings.append(_finding("STALE_EVIDENCE_INPUT", "evidence_input_id", "Evidence input identity no longer matches resolved sources"))
    for field in ("project_id", "program_id", "program_revision"):
        if resolved.get(field) != draft.get(field):
            findings.append(_finding("SOURCE_DRAFT_IDENTITY_MISMATCH", field, "Resolved identity must match its source draft"))
    expected_identity_basis = {
        "project_id": resolved.get("project_id"),
        "program_id": resolved.get("program_id"),
        "program_revision": resolved.get("program_revision"),
        "owner_program_hash": resolved.get("owner_program_hash"),
        "canonical_unit_program_hash": resolved.get("canonical_unit_program_hash"),
        "evidence_input_id": resolved.get("evidence_input_id"),
        "site_binding": resolved.get("site_binding"),
        "national_ruleset_binding": resolved.get("national_ruleset_binding"),
        "local_profile_binding": resolved.get("local_profile_binding"),
        "derived_project_facts": resolved.get("derived_project_facts", []),
        "geometry_feasibility": resolved.get("geometry_feasibility"),
    }
    try:
        expected_resolved_id = f"resolved-{stable_hash(expected_identity_basis)[:20]}"
    except (TypeError, ValueError):
        expected_resolved_id = None
        findings.append(_finding("INVALID_PAYLOAD", "$", "Resolved identity inputs must serialize deterministically"))
    if resolved.get("resolved_id") != expected_resolved_id:
        findings.append(_finding("INVALID_RESOLVED_ID", "resolved_id", "Resolved identity does not match its bound inputs"))
    if "resolution_hash" in resolved:
        hash_payload = dict(resolved)
        supplied_hash = hash_payload.pop("resolution_hash")
        try:
            expected_resolution_hash = _json_hash(hash_payload)
        except (TypeError, ValueError):
            expected_resolution_hash = None
        if supplied_hash != expected_resolution_hash:
            findings.append(_finding("INVALID_RESOLUTION_HASH", "resolution_hash", "Resolved payload changed after hashing"))
    findings.extend(_resolution_readiness_findings(draft))
    findings.extend(_derived_fact_findings(resolved, current_geometry_evidence))
    findings.extend(_binding_findings(resolved, current_bindings))

    codes = {finding["code"] for finding in findings}
    if draft_validation["status"] == "DEFINITELY_INVALID":
        status = "DEFINITELY_INVALID"
    elif codes & {
        "STALE_BINDING",
        "STALE_OWNER_PROGRAM",
        "STALE_UNIT_PROGRAM",
        "INVALID_RESOLVED_ID",
        "INVALID_RESOLUTION_HASH",
        "SOURCE_DRAFT_IDENTITY_MISMATCH",
        "STALE_EVIDENCE_INPUT",
        "STALE_GEOMETRY_EVIDENCE",
    }:
        status = "STALE_BINDING"
    elif draft_validation["status"] != "DRAFT_VALID":
        status = "INPUT_REQUIRED"
    elif "MISSING_LOCAL_PROFILE" in codes:
        status = "LOCAL_RULE_REQUIRED"
    elif findings:
        status = "INPUT_REQUIRED"
    elif resolved.get("geometry_feasibility") == "VERIFIED":
        status = "VALIDATED_INPUT"
    else:
        status = "NEEDS_GEOMETRIC_FEASIBILITY_CHECK"
    supplied_status = resolved.get("resolution_status")
    if supplied_status is not None and supplied_status != status:
        findings.append(_finding("RESOLUTION_STATUS_MISMATCH", "resolution_status", "Stored status exceeds independently computed validation"))
        status = "STALE_BINDING"
    return _validation_result(status, findings, resolved)


def load_schema(name: str) -> dict[str, Any]:
    """Load only the two additive v2 schemas; no runtime schema negotiation."""
    filenames = {
        "owner-program-draft-v2": "owner-program-draft-v2.schema.json",
        "resolved-generation-input-v2": "resolved-generation-input-v2.schema.json",
    }
    if name not in filenames:
        raise ValueError("Unknown Owner Program v2 schema")
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "standards/test-suites/residential" / filenames[name]).read_text())
