#!/usr/bin/env python3
"""Reject new parallel runtime versions and non-canonical production references."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONED = re.compile(r"(?:^|/)(?:main|engine|rulebook)[_-]?v\d|(?:^|/)[^/]+_v\d+(?:[_.]|$)", re.I)
PRODUCTION_ROOTS = ("app/", "cad_engine/", "data/rulebook/")
EXEMPT_ROOTS = ("tests/fixtures/", "archived_compatibility/")
REFERENCE_FILES = ("README.md", "Dockerfile", "start_services.sh", "cad_engine/Dockerfile")

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
    return {"status": "PASS" if not forbidden and not references else "FAIL", "forbidden_added": forbidden, "reference_errors": references, "legacy_runtime_files": legacy}

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--base", default="origin/main"); parser.add_argument("--report", type=Path)
    args = parser.parse_args(); report = audit(args.base); rendered = json.dumps(report, indent=2, sort_keys=True); print(rendered)
    if args.report: args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    sys.exit(main())
