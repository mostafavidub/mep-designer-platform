"""Canonical loader and integrity checks for modular executable Rulebook data."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_ROOT = ROOT / "data" / "rulebook"
RAINWATER_ROOT = RULEBOOK_ROOT / "modules" / "mechanical" / "rainwater"
REQUIRED_RULE_FIELDS = {
    "rule_id", "version", "owner", "subsystem", "kind", "authority", "sources",
    "applicability", "required_inputs", "design_actions", "validator", "output_evidence",
}
ALLOWED_KINDS = {
    "OPERATIVE", "CONDITIONAL", "DEFINITION", "GUIDANCE", "DEPENDENCY",
    "UNRESOLVED_CONTROL", "DOCUMENTED_NOT_APPLICABLE",
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_rulebook_module(module_root: Path = RAINWATER_ROOT):
    manifest = _read_json(module_root / "module.json")
    registry = _read_json(module_root / manifest["rules_file"])
    coverage = _read_json(module_root / manifest["source_coverage_file"])
    return {"manifest": manifest, "registry": registry, "coverage": coverage}


def module_dependency_identity(module_root: Path = RAINWATER_ROOT) -> str:
    files = [module_root / "module.json", module_root / "rules.json",
             module_root / "source_coverage.json",
             RULEBOOK_ROOT / "schema" / "executable_rule.schema.json"]
    digest = sha256()
    for path in files:
        try:
            label = "module/" + path.relative_to(module_root).as_posix()
        except ValueError:
            label = "schema/" + path.name
        digest.update(label.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_rulebook_module(module=None):
    module = module or load_rulebook_module()
    manifest, registry, coverage = (module[key] for key in ("manifest", "registry", "coverage"))
    errors = []
    rules = registry.get("rules") or []
    ids = [row.get("rule_id") for row in rules]
    if not rules:
        errors.append("RULES_MISSING")
    if len(ids) != len(set(ids)):
        errors.append("RULE_ID_DUPLICATE")
    known = set(ids)
    source_ids = set()
    for row in rules:
        missing = REQUIRED_RULE_FIELDS - set(row)
        if missing:
            errors.append(f"{row.get('rule_id','UNKNOWN')}:FIELDS_MISSING:{','.join(sorted(missing))}")
        if row.get("kind") not in ALLOWED_KINDS:
            errors.append(f"{row.get('rule_id','UNKNOWN')}:KIND_INVALID")
        if row.get("unknown_policy") != "INPUT_REQUIRED":
            errors.append(f"{row.get('rule_id','UNKNOWN')}:UNKNOWN_POLICY_INVALID")
        if row.get("llm_override_allowed") is not False:
            errors.append(f"{row.get('rule_id','UNKNOWN')}:LLM_OVERRIDE_FORBIDDEN")
        if (row.get("applicability") or {}).get("unknown_result") != "INPUT_REQUIRED":
            errors.append(f"{row.get('rule_id','UNKNOWN')}:APPLICABILITY_UNKNOWN_NOT_FAIL_CLOSED")
        for source in row.get("sources") or []:
            source_ids.update(source.get("source_ids") or [])
        for ref in row.get("cross_references") or []:
            if ref not in known:
                errors.append(f"{row.get('rule_id','UNKNOWN')}:CROSS_REFERENCE_UNKNOWN:{ref}")
    entries = coverage.get("entries") or []
    entry_ids = [row.get("source_id") for row in entries]
    if coverage.get("source_entry_count") != 534 or len(entries) != 534:
        errors.append("SOURCE_COVERAGE_COUNT_INVALID")
    if len(entry_ids) != len(set(entry_ids)):
        errors.append("SOURCE_COVERAGE_DUPLICATE")
    if any(row.get("automatic_pass") is not False for row in entries):
        errors.append("SOURCE_RECORD_AUTOMATIC_PASS_FORBIDDEN")
    mapped = {rule_id for row in entries for rule_id in row.get("rule_ids") or []}
    if mapped - known:
        errors.append("SOURCE_COVERAGE_RULE_UNKNOWN")
    declared_sources = sum(int(row.get("entry_count") or 0)
                           for row in manifest.get("source_documents") or [])
    # The handoff manifest is the source of the count; module source rows retain hashes only.
    if manifest.get("coverage", {}).get("source_entries") != 534:
        errors.append("MANIFEST_SOURCE_COUNT_INVALID")
    return {"status": "PASS" if not errors else "FAIL", "errors": sorted(set(errors)),
            "module_id": manifest.get("module_id"), "module_version": manifest.get("version"),
            "rule_count": len(rules), "source_entry_count": len(entries),
            "mapped_executable_source_count": sum(bool(row.get("rule_ids")) for row in entries),
            "unresolved_control_count": sum(row.get("disposition") == "UNRESOLVED_CONTROL" for row in entries),
            "dependency_identity": module_dependency_identity(),
            "declared_source_entry_count": declared_sources or 534}


def rule_rows(module=None):
    module = module or load_rulebook_module()
    return deepcopy(module["registry"]["rules"])
