#!/usr/bin/env python3
"""Offline, deterministic closure diagnostics for canonical Mechanical Rulebook modules."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODULES_ROOT = REPO_ROOT / "data" / "rulebook" / "modules" / "mechanical"
DEFAULT_SCHEMA = REPO_ROOT / "data" / "rulebook" / "schema" / "executable_rule.schema.json"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(paths: list[Path]) -> str:
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def audit_module(module_root: Path, schema_path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    manifest_path = module_root / "module.json"
    manifest = _read(manifest_path)
    rules_path = module_root / manifest["rules_file"]
    coverage_path = module_root / manifest["source_coverage_file"]
    registry = _read(rules_path)
    coverage = _read(coverage_path)
    rules = registry.get("rules") or []
    entries = coverage.get("entries") or []
    schema = _read(schema_path)
    validator = Draft202012Validator(schema)

    errors: list[str] = []
    rule_ids = [row.get("rule_id") for row in rules]
    if len(rule_ids) != len(set(rule_ids)):
        errors.append("RULE_ID_DUPLICATE")
    schema_errors: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        for error in validator.iter_errors(rule):
            location = "/".join(str(part) for part in error.absolute_path)
            schema_errors.append({
                "rule_index": index,
                "rule_id": rule.get("rule_id"),
                "path": location,
                "validator": error.validator,
                "message": error.message,
            })
    if schema_errors:
        errors.append("STRICT_SCHEMA_INVALID")

    expected_entries = manifest.get("coverage", {}).get("source_entries")
    declared_entries = coverage.get("source_entry_count")
    entry_ids = [row.get("source_id") for row in entries]
    if expected_entries != declared_entries or declared_entries != len(entries):
        errors.append("SOURCE_COVERAGE_COUNT_INVALID")
    if len(entry_ids) != len(set(entry_ids)):
        errors.append("SOURCE_ID_DUPLICATE")
    if any(row.get("automatic_pass") is not False for row in entries):
        errors.append("AUTOMATIC_PASS_FORBIDDEN")

    known_rules = set(rule_ids)
    mapped_rules = {rule_id for row in entries for rule_id in row.get("rule_ids", [])}
    unknown_mappings = sorted(mapped_rules - known_rules)
    if unknown_mappings:
        errors.append("SOURCE_MAPPING_UNKNOWN_RULE")

    source_ids_from_rules = {
        source_id
        for rule in rules
        for source in rule.get("sources", [])
        for source_id in source.get("source_ids", [])
    }
    executable_entries = {
        row.get("source_id")
        for row in entries
        if row.get("disposition") == "EXECUTABLE_RULE"
    }
    reciprocal_missing = sorted(executable_entries - source_ids_from_rules)
    if reciprocal_missing:
        errors.append("EXECUTABLE_SOURCE_RECIPROCAL_LINK_MISSING")

    dispositions = Counter(row.get("disposition", "MISSING") for row in entries)
    complete_claim = manifest.get("coverage", {}).get("complete_statutory_coverage")
    unresolved_count = dispositions.get("UNRESOLVED_CONTROL", 0)
    bounded_integrity = not errors
    if complete_claim is True and unresolved_count:
        errors.append("COMPLETE_CLAIM_WITH_UNRESOLVED_CONTROLS")
        bounded_integrity = False

    return {
        "module_id": manifest.get("module_id"),
        "module_version": manifest.get("version"),
        "status": "PASS" if bounded_integrity else "FAIL",
        "coverage_scope": "COMPLETE_STATUTORY" if complete_claim is True else "BOUNDED_ONLY",
        "complete_statutory_coverage": complete_claim is True,
        "rule_count": len(rules),
        "source_entry_count": len(entries),
        "disposition_counts": dict(sorted(dispositions.items())),
        "unresolved_control_count": unresolved_count,
        "schema_error_count": len(schema_errors),
        "schema_errors": schema_errors,
        "unknown_rule_mappings": unknown_mappings,
        "reciprocal_link_missing_source_ids": reciprocal_missing,
        "dependency_identity": _digest([manifest_path, rules_path, coverage_path, schema_path]),
        "errors": sorted(set(errors)),
    }


def audit_all(modules_root: Path = DEFAULT_MODULES_ROOT, schema_path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    module_roots = sorted(path.parent for path in modules_root.glob("*/module.json"))
    modules = [audit_module(path, schema_path) for path in module_roots]
    failed = [row["module_id"] for row in modules if row["status"] != "PASS"]
    complete = [row["module_id"] for row in modules if row["complete_statutory_coverage"]]
    return {
        "schema": "planha-rulebook-closure-audit/1.0",
        "status": "PASS" if not failed else "FAIL",
        "meaning": "PASS proves registered-data integrity only; it is not a statutory-completeness, runtime-activation, permit, construction, or professional-approval claim.",
        "module_count": len(modules),
        "failed_modules": failed,
        "complete_statutory_modules": complete,
        "bounded_only_modules": [row["module_id"] for row in modules if not row["complete_statutory_coverage"]],
        "modules": modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modules-root", type=Path, default=DEFAULT_MODULES_ROOT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_all(args.modules_root, args.schema)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
