#!/usr/bin/env python3
"""Fail-closed repository and per-change validator for SWCIS."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWCIS = ROOT / "standards" / "swcis"
FILES = {
    "graph": "system_dependency_graph.yaml",
    "trace": "rule_traceability_matrix.yaml",
    "impact": "change_impact_matrix.yaml",
    "release": "release_contract.yaml",
    "golden": "golden_regression_manifest.yaml",
    "version": "version_manifest.yaml",
}


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable_contract:{path.relative_to(ROOT)}:{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"contract_root_must_be_mapping:{path.relative_to(ROOT)}")
    return value


def contracts() -> dict[str, dict]:
    return {name: load(SWCIS / filename) for name, filename in FILES.items()}


def matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-2]))
    )


def transitive_dependents(modules: dict, seeds: set[str]) -> set[str]:
    affected = set(seeds)
    changed = True
    while changed:
        changed = False
        for name, config in modules.items():
            if name not in affected and affected.intersection(config["depends_on"]):
                affected.add(name)
                changed = True
    return affected


def repository_errors(data: dict[str, dict] | None = None) -> list[str]:
    data = data or contracts()
    errors: list[str] = []
    versions = {item.get("schema_version") for item in data.values()}
    if versions != {"1.0.0"}:
        errors.append(f"schema_version_mismatch:{sorted(str(v) for v in versions)}")
    if any(item.get("standard") != "SWCIS" for item in data.values()):
        errors.append("standard_name_mismatch")

    modules = data["graph"].get("modules", {})
    required_modules = {
        "rule_book", "pmm", "questionnaire", "planner", "cad_designer", "routing",
        "sizing", "equipment", "manufacturer_selector", "detail_riser", "qa",
        "manifest", "ui_api", "docs", "versioning", "migration", "governance", "deployment",
    }
    if set(modules) != required_modules:
        errors.append(f"module_inventory_mismatch:{sorted(required_modules - set(modules))}")
    for name, module in modules.items():
        if not module.get("owners") or not module.get("paths"):
            errors.append(f"module_metadata_missing:{name}")
        for dependency in module.get("depends_on", []):
            if dependency not in modules:
                errors.append(f"unknown_dependency:{name}:{dependency}")

    required_chain = set(data["trace"].get("required_chain", []))
    rule_ids: set[str] = set()
    for rule in data["trace"].get("rules", []):
        rule_id = rule.get("rule_id", "MISSING")
        if rule_id in rule_ids:
            errors.append(f"duplicate_rule_id:{rule_id}")
        rule_ids.add(rule_id)
        for field in required_chain:
            if not rule.get(field):
                errors.append(f"traceability_gap:{rule_id}:{field}")

    if {p.get("project_id") for p in data["golden"].get("real_projects", [])} != {"1", "3", "4", "6", "7", "8", "10"}:
        errors.append("golden_project_inventory_mismatch")
    if not data["golden"].get("synthetic_cases"):
        errors.append("synthetic_cases_missing")
    for artifact in data["version"].get("machine_contracts", []):
        if not (ROOT / artifact).is_file():
            errors.append(f"canonical_artifact_missing:{artifact}")
    if data["release"].get("status") != "LOCKED":
        errors.append("release_contract_not_locked")
    return errors


def classify(paths: list[str], data: dict[str, dict]) -> tuple[set[str], set[str], set[str]]:
    modules = data["graph"]["modules"]
    types = data["impact"]["change_types"]
    direct: set[str] = set()
    change_types: set[str] = set()
    unclassified: set[str] = set()
    for path in paths:
        path_modules = {name for name, cfg in modules.items() if any(matches(path, p) for p in cfg["paths"])}
        path_types = {name for name, cfg in types.items() if any(matches(path, p) for p in cfg["path_patterns"])}
        if not path_modules or not path_types:
            unclassified.add(path)
        direct.update(path_modules)
        change_types.update(path_types)
    return transitive_dependents(modules, direct), change_types, unclassified


def waiver_errors(waiver_path: str | None, release: dict) -> list[str]:
    if not waiver_path:
        return []
    waiver = load(ROOT / waiver_path)
    contract = release["waiver_contract"]
    errors = [f"waiver_field_missing:{f}" for f in contract["required_fields"] if not waiver.get(f)]
    try:
        approved = dt.date.fromisoformat(waiver["approved_at"])
        expires = dt.date.fromisoformat(waiver["expires_at"])
        if expires < dt.date.today():
            errors.append("waiver_expired")
        if (expires - approved).days > contract["maximum_days"]:
            errors.append("waiver_duration_exceeds_maximum")
    except (KeyError, TypeError, ValueError):
        errors.append("waiver_dates_invalid")
    if waiver.get("requester") == waiver.get("reviewer"):
        errors.append("waiver_self_approval")
    return errors


def impact_errors(paths: list[str], request_path: Path, data: dict[str, dict] | None = None) -> tuple[list[str], dict]:
    data = data or contracts()
    errors = repository_errors(data)
    request = load(request_path)
    affected, change_types, unclassified = classify(paths, data)
    if unclassified:
        errors.extend(f"unclassified_path:{path}" for path in sorted(unclassified))
    declared = set(request.get("impacted_modules", []))
    errors.extend(f"undeclared_impacted_module:{name}" for name in sorted(affected - declared))
    errors.extend(f"invalid_declared_module:{name}" for name in sorted(declared - set(data["graph"]["modules"])))
    declared_types = set(request.get("change_types", []))
    errors.extend(f"undeclared_change_type:{name}" for name in sorted(change_types - declared_types))

    required_evidence: set[str] = set()
    for name in change_types:
        required_evidence.update(data["impact"]["change_types"][name]["required_evidence"])
    evidence = request.get("evidence", {})
    for name in sorted(required_evidence):
        if not evidence.get(name):
            errors.append(f"required_evidence_missing:{name}")

    risk = request.get("risk", {})
    try:
        score = risk["likelihood"] * risk["severity"] * risk["detectability"]
        if any(not 1 <= risk[k] <= 5 for k in ("likelihood", "severity", "detectability")):
            errors.append("risk_factor_out_of_range")
        if risk.get("score") != score:
            errors.append(f"risk_score_mismatch:expected_{score}")
    except (KeyError, TypeError):
        score = None
        errors.append("risk_score_missing_or_invalid")
    errors.extend(waiver_errors(request.get("waiver"), data["release"]))
    report = {"status": "FAIL" if errors else "PASS", "changed_paths": paths, "change_types": sorted(change_types), "affected_modules": sorted(affected), "required_evidence": sorted(required_evidence), "risk_score": score, "errors": errors}
    return errors, report


def git_changed(base: str) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=ROOT, check=True, text=True, capture_output=True)
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="Git base ref used to discover changed paths")
    parser.add_argument("--change-request", type=Path)
    parser.add_argument("--paths", nargs="*")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        data = contracts()
        if args.change_request:
            paths = args.paths if args.paths is not None else git_changed(args.base or "HEAD^")
            errors, report = impact_errors(paths, ROOT / args.change_request, data)
        else:
            errors = repository_errors(data)
            report = {"status": "FAIL" if errors else "PASS", "errors": errors}
    except (ValueError, subprocess.CalledProcessError) as exc:
        errors = [str(exc)]
        report = {"status": "FAIL", "errors": errors}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
