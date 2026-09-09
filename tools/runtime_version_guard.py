#!/usr/bin/env python3
"""Reject parallel runtime versions and versioned production-facing identities."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONED = re.compile(r"(?:^|/)(?:main|engine|rulebook)[_-]?v\d|(?:^|/)[^/]+_v\d+(?:[_.]|$)", re.I)
PRODUCTION_ROOTS = ("app/", "cad_engine/", "data/rulebook/")
EXEMPT_ROOTS = ("tests/fixtures/", "archived_compatibility/")
REFERENCE_FILES = ("README.md", "Dockerfile", "start_services.sh", "cad_engine/Dockerfile")
CANONICAL_MECHANICAL_WORKFLOWS = {
    ".github/workflows/mechanical-authority.yml": "Mechanical Authority",
    ".github/workflows/mechanical-network-authority.yml": "Mechanical Network Authority",
    ".github/workflows/mechanical-governance.yml": "Mechanical Governance",
    ".github/workflows/mechanical-coordination.yml": "Mechanical Coordination",
}
FORBIDDEN_VISIBLE_WORKFLOWS = (
    ".github/workflows/mechanical-authority-v15.yml",
    ".github/workflows/mechanical-network-authority-v19.yml",
    ".github/workflows/mechanical-coordination-v19.yml",
)
LEGACY_GOVERNANCE_SENTINEL = ".github/workflows/mechanical-governance-v1.yml"


def _lines(*args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line]


def audit(base: str) -> dict:
    tracked = _lines("ls-files")
    added = _lines("diff", "--diff-filter=A", "--name-only", f"{base}...HEAD")
    legacy = sorted(path for path in tracked if path.startswith(PRODUCTION_ROOTS) and VERSIONED.search(path))
    forbidden = sorted(path for path in added if path.startswith(PRODUCTION_ROOTS) and VERSIONED.search(path) and not path.startswith(EXEMPT_ROOTS))
    references = []
    for name in REFERENCE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        if "cad_engine.main_v" in text:
            references.append(f"versioned_production_reference:{name}")

    main_text = (ROOT / "cad_engine/main.py").read_text(encoding="utf-8")
    if re.search(r"from\s+\.[A-Za-z0-9_]*_v\d+|import\s+\.[A-Za-z0-9_]*_v\d+", main_text):
        references.append("versioned_import_in_canonical_entrypoint:cad_engine/main.py")
    if re.search(r"/mechanical[^\"']*v\d+", main_text, re.I):
        references.append("versioned_mechanical_route_in_canonical_entrypoint")

    workflow_errors = []
    tracked_set = set(tracked)
    for path in FORBIDDEN_VISIBLE_WORKFLOWS:
        if path in tracked_set:
            workflow_errors.append(f"versioned_visible_workflow:{path}")

    sentinel = ROOT / LEGACY_GOVERNANCE_SENTINEL
    if sentinel.is_file():
        text = sentinel.read_text(encoding="utf-8")
        if "compatibility_artifact: true" not in text or re.search(r"^\s*(name|on|jobs)\s*:", text, re.M):
            workflow_errors.append("legacy_governance_sentinel_must_be_non_runnable")

    for path, expected_name in CANONICAL_MECHANICAL_WORKFLOWS.items():
        file = ROOT / path
        if not file.is_file():
            workflow_errors.append(f"missing_canonical_workflow:{path}")
            continue
        first = file.read_text(encoding="utf-8").splitlines()[0].strip()
        if first != f"name: {expected_name}":
            workflow_errors.append(f"workflow_name_mismatch:{path}:{first}")

    status = "PASS" if not forbidden and not references and not workflow_errors else "FAIL"
    return {
        "status": status,
        "forbidden_added": forbidden,
        "reference_errors": references,
        "workflow_errors": workflow_errors,
        "legacy_runtime_files": legacy,
        "canonical_mechanical_runtime": "cad_engine.main:app",
        "canonical_mechanical_identity": "mechanical",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit(args.base)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
