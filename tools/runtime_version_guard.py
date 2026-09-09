#!/usr/bin/env python3
"""Reject release-numbered identities anywhere in the active Mechanical runtime.

Historical files may remain in Git while they are being deleted, but the canonical
production closure reachable from cad_engine.main:app must not import, dynamically
load, expose, or stamp a release-numbered Mechanical implementation.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAD = ROOT / "cad_engine"
VERSIONED_PATH = re.compile(r"(?:^|/)(?:main|engine|rulebook)[_-]?v\d|(?:^|/)[^/]+_v\d+(?:[_.]|$)", re.I)
VERSIONED_MODULE = re.compile(r"_v\d+(?:_\d+)*$", re.I)
PRODUCTION_ROOTS = ("app/", "cad_engine/", "data/rulebook/")
EXEMPT_ROOTS = ("tests/fixtures/", "archived_compatibility/")
REFERENCE_FILES = ("README.md", "Dockerfile", "start_services.sh", "cad_engine/Dockerfile")
CANONICAL_ROOT_MODULES = (
    "main",
    "main_transport",
    "mechanical_authority",
    "mechanical_pipeline",
    "mechanical_release_contract",
)
CANONICAL_MECHANICAL_WORKFLOWS = {
    ".github/workflows/mechanical-authority.yml": "Mechanical Authority",
    ".github/workflows/mechanical-network-authority.yml": "Mechanical Network Authority",
    ".github/workflows/mechanical-governance.yml": "Mechanical Governance",
    ".github/workflows/mechanical-coordination.yml": "Mechanical Coordination",
}
FORBIDDEN_VISIBLE_WORKFLOWS = (
    ".github/workflows/mechanical-authority-v15.yml",
    ".github/workflows/mechanical-network-authority-v19.yml",
    ".github/workflows/mechanical-governance-v1.yml",
    ".github/workflows/mechanical-coordination-v19.yml",
)
FORBIDDEN_RUNTIME_LITERAL = re.compile(
    r"(?:mechanical[-_]v\d+|legacy[-_]v\d+|ENGITOOLS_V\d+|(?:pipeline|authority|renderer)[-_]v\d+|version[-_ ]locked\s*v\d+)",
    re.I,
)
DYNAMIC_MODULE = re.compile(r"cad_engine\.([A-Za-z_][A-Za-z0-9_]*)")


def _lines(*args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line]


def _module_file(module: str) -> Path:
    return CAD / (module.replace(".", "/") + ".py")


def _relative_imports(module: str, text: str) -> set[str]:
    tree = ast.parse(text, filename=str(_module_file(module)))
    imports: set[str] = set()
    package = module.rsplit(".", 1)[0] if "." in module else ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module:
            dep = node.module
            imports.add(dep if not package else f"{package}.{dep}")
        else:
            for alias in node.names:
                dep = alias.name
                imports.add(dep if not package else f"{package}.{dep}")
    for found in DYNAMIC_MODULE.findall(text):
        imports.add(found)
    return imports


def active_runtime_closure() -> dict:
    queue = list(CANONICAL_ROOT_MODULES)
    seen: set[str] = set()
    versioned_modules: list[str] = []
    missing_modules: list[str] = []
    literal_errors: list[str] = []
    import_errors: list[str] = []

    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_file(module)
        if not path.is_file():
            missing_modules.append(module)
            continue
        if VERSIONED_MODULE.search(module):
            versioned_modules.append(module)
        text = path.read_text(encoding="utf-8")
        try:
            deps = _relative_imports(module, text)
        except SyntaxError as exc:
            import_errors.append(f"syntax_error:{module}:{exc.lineno}:{exc.msg}")
            continue
        for match in FORBIDDEN_RUNTIME_LITERAL.finditer(text):
            literal_errors.append(f"versioned_runtime_literal:{module}:{match.group(0)}")
        for dep in deps:
            dep_path = _module_file(dep)
            if not dep_path.is_file():
                continue
            if VERSIONED_MODULE.search(dep):
                import_errors.append(f"versioned_reachable_import:{module}->{dep}")
            queue.append(dep)

    materializer = CAD / "mechanical_network_materializer.py"
    if materializer.is_file():
        text = materializer.read_text(encoding="utf-8")
        if 'APPID = "ENGITOOLS_MECHANICAL"' not in text:
            literal_errors.append("canonical_mechanical_xdata_appid_missing")

    return {
        "modules": sorted(seen),
        "versioned_modules": sorted(set(versioned_modules)),
        "missing_modules": sorted(set(missing_modules)),
        "import_errors": sorted(set(import_errors)),
        "literal_errors": sorted(set(literal_errors)),
    }


def audit(base: str) -> dict:
    tracked = _lines("ls-files")
    added = _lines("diff", "--diff-filter=A", "--name-only", f"{base}...HEAD")
    historical = sorted(path for path in tracked if path.startswith(PRODUCTION_ROOTS) and VERSIONED_PATH.search(path))
    forbidden_added = sorted(
        path for path in added
        if path.startswith(PRODUCTION_ROOTS) and VERSIONED_PATH.search(path) and not path.startswith(EXEMPT_ROOTS)
    )

    reference_errors = []
    for name in REFERENCE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        if "cad_engine.main_v" in text:
            reference_errors.append(f"versioned_production_reference:{name}")
        if "version-locked v" in text.lower():
            reference_errors.append(f"version_locked_runtime_comment:{name}")

    main_text = (CAD / "main.py").read_text(encoding="utf-8")
    if re.search(r"/mechanical[^\"']*v\d+", main_text, re.I):
        reference_errors.append("versioned_mechanical_route_in_canonical_entrypoint")
    if "cad_engine.main:app" not in main_text:
        reference_errors.append("canonical_production_entrypoint_not_declared")

    workflow_errors = []
    tracked_set = set(tracked)
    for path in FORBIDDEN_VISIBLE_WORKFLOWS:
        if path in tracked_set:
            workflow_errors.append(f"versioned_visible_workflow:{path}")
    for path, expected_name in CANONICAL_MECHANICAL_WORKFLOWS.items():
        file = ROOT / path
        if not file.is_file():
            workflow_errors.append(f"missing_canonical_workflow:{path}")
            continue
        first = file.read_text(encoding="utf-8").splitlines()[0].strip()
        if first != f"name: {expected_name}":
            workflow_errors.append(f"workflow_name_mismatch:{path}:{first}")

    closure = active_runtime_closure()
    closure_errors = (
        closure["versioned_modules"]
        + closure["missing_modules"]
        + closure["import_errors"]
        + closure["literal_errors"]
    )
    status = "PASS" if not forbidden_added and not reference_errors and not workflow_errors and not closure_errors else "FAIL"
    return {
        "status": status,
        "forbidden_added": forbidden_added,
        "reference_errors": reference_errors,
        "workflow_errors": workflow_errors,
        "runtime_closure": closure,
        "historical_versioned_files": historical,
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
