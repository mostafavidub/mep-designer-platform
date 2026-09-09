#!/usr/bin/env python3
"""Materialize the active Mechanical runtime into unversioned canonical modules.

This one-time migration copies the exact active implementation closure into semantic
module names and rewrites both Python imports and dynamic capability imports. Historical
*_vNN files are not runtime dependencies after this migration; Git preserves their history.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAD = ROOT / "cad_engine"
VERSIONED = re.compile(r"_v\d+(?:_\d+)*$", re.I)
DYNAMIC_MODULE = re.compile(r"cad_engine\.([A-Za-z_][A-Za-z0-9_]*)")

SPECIAL = {
    "main_v15": "main_transport",
    "mechanical_authority_site_v19": "mechanical_authority",
    "mechanical_pipeline_v19": "mechanical_pipeline",
    "mechanical_release_contract_v19": "mechanical_release_contract",
    "mechanical_release_contract_v17": "mechanical_release_contract_reference",
    "mechanical_release_contract_v16": "mechanical_release_contract_preservation",
    "mechanical_release_contract_v15": "mechanical_release_contract_base",
    "mechanical_authority_site_v17": "mechanical_cad_shell",
    "mechanical_authority_site_v16": "mechanical_cad_preservation",
    "mechanical_authority_site_v15": "mechanical_cad_base",
    "mechanical_authority_v15": "mechanical_design_core",
    "coordination_v19": "mechanical_coordination",
    "manufacturer_selector_v19": "mechanical_manufacturer_selector",
    "parametric_documentation_v19": "mechanical_documentation",
    "submission_qa_v19": "mechanical_submission_qa",
    "reference_parity_engine_v17": "reference_parity_engine",
    "documentation_enhancer_v17": "documentation_enhancer",
    "final_delivery_gate_v17": "final_delivery_gate",
    "mechanical_release_hardening_v18": "mechanical_release_hardening",
    "architecture_preservation_gate_v16": "architecture_preservation_gate",
    "engineering_runner_v13": "engineering_runner",
    "acceptance_v13": "engineering_acceptance",
    "authority_architecture_v14": "authority_architecture",
    "equipment_representation_v14": "equipment_representation",
    # Both historical sizing/calculation generations are reachable for different
    # semantic capabilities. Give them distinct semantic names instead of hiding
    # their generation behind ambiguous aliases.
    "sizing_v14": "mechanical_execution_sizing",
    "mechanical_calculations_v14": "mechanical_calculation_traceability",
    "version_manifest": "runtime_contract",
}
ROOT_SOURCES = {
    "main_v15",
    "mechanical_authority_site_v19",
    "mechanical_pipeline_v19",
    "mechanical_release_contract_v19",
    "mechanical_authority_site_v17",
}


def source_path(module: str) -> Path:
    return CAD / f"{module}.py"


def target_module(source: str) -> str:
    if source in SPECIAL:
        return SPECIAL[source]
    if VERSIONED.search(source):
        return VERSIONED.sub("", source)
    return source


def referenced_modules(text: str) -> set[str]:
    tree = ast.parse(text)
    out: set[str] = set(DYNAMIC_MODULE.findall(text))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module:
            out.add(node.module.split(".", 1)[0])
        else:
            for alias in node.names:
                out.add(alias.name.split(".", 1)[0])
    return out


def build_closure() -> tuple[set[str], dict[str, str]]:
    queue = list(ROOT_SOURCES)
    seen: set[str] = set()
    mapping: dict[str, str] = {"version_manifest": "runtime_contract"}
    owners: dict[str, str] = {}
    while queue:
        source = queue.pop()
        if source in seen:
            continue
        path = source_path(source)
        if not path.is_file():
            raise SystemExit(f"active runtime source missing: {source}")
        seen.add(source)
        target = target_module(source)
        prior = owners.get(target)
        if prior and prior != source:
            raise SystemExit(f"canonical module collision: {prior}, {source} -> {target}")
        owners[target] = source
        mapping[source] = target
        for dep in referenced_modules(path.read_text(encoding="utf-8")):
            dep_path = source_path(dep)
            if dep == "version_manifest":
                mapping[dep] = "runtime_contract"
                continue
            if dep_path.is_file() and VERSIONED.search(dep):
                queue.append(dep)
    return seen, mapping


def rewrite_imports(text: str, mapping: dict[str, str]) -> str:
    for source, target in sorted(mapping.items(), key=lambda item: -len(item[0])):
        if source == target:
            continue
        text = re.sub(rf"(?m)(from\s+\.){re.escape(source)}(?=\s+import\b)", rf"\1{target}", text)
        text = re.sub(
            rf"(?m)(from\s+\.\s+import\s+[^\n]*\b){re.escape(source)}\b",
            lambda m: m.group(0).replace(source, target),
            text,
        )
        text = text.replace(f"cad_engine.{source}", f"cad_engine.{target}")
    return text


def semantic_runtime_cleanup(target: str, text: str) -> str:
    replacements = {
        "run_v19_pipeline": "run_pipeline",
        "_v19_payload": "_authority_payload",
        "_design_v17": "_design_shell",
        "v19_runtime_contract_gate": "runtime_contract_gate",
        "v19_network_authority_gate": "network_authority_gate",
        "v19_authority_input_gate": "authority_input_gate",
        "v19_authority_release_gate": "authority_release_gate",
        "v19_network_materialization_gate": "network_materialization_gate",
        "v19_preflight_gate": "authority_preflight_gate",
        "v19_materialization_qa": "materialization_qa",
        "v19_traceability_preflight": "traceability_preflight",
        "v19_qa": "authority_pipeline_qa",
        "V19_RELEASE_GOLDEN_PASS": "MECHANICAL_RELEASE_GOLDEN_PASS",
        "MECHANICAL_V19_GOLDEN_STATUS": "MECHANICAL_GOLDEN_STATUS",
        "mechanical-v19-authoritative": "mechanical-authoritative",
        "mechanical-v19": "mechanical",
        "PMM_V3_V19": "PMM_V3",
        "legacy-v17-shell+graph-native-v19-network": "canonical-cad-shell+graph-native-network",
        "legacy-v17-shell": "canonical-cad-shell",
        "legacy_renderer_role": "cad_shell_role",
        "executed_versions": "runtime_contract",
        "active_version_manifest": "runtime_contract",
        "engitools-v19-authority-": "engitools-mechanical-authority-",
        "engitools-v19-network-": "engitools-mechanical-network-",
        "ENGITOOLS_V19": "ENGITOOLS_MECHANICAL",
        "DXF_XDATA_EDGE_ID_EQUALS_V19_NETWORK_EDGE_ID": "DXF_XDATA_EDGE_ID_EQUALS_NETWORK_EDGE_ID",
        "production_v19_version_locked_adapter": "production_canonical_authority_adapter",
        "four v19 phases": "the canonical Mechanical phases",
        "v19 network": "canonical network",
        "v19 graph": "canonical graph",
        "v19.1 Pre-Submission profile": "canonical Pre-Submission profile",
        "v19.1": "canonical",
        "v19": "canonical",
        "v17.6": "canonical",
        "v17": "canonical",
        "v16": "canonical",
        "v15": "canonical",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    if target == "main_transport":
        text = re.sub(
            r"from \.mechanical_cad_base import design_mechanical_authority_site",
            "from .mechanical_authority import design_mechanical_authority_site",
            text,
        )
        text = text.replace(
            "from .runtime_contract import CAD_API_VERSION, MECHANICAL_PIPELINE_VERSION, runtime_contract",
            "from .runtime_contract import runtime_contract\nfrom .build_identity import build_identity",
        )
        text = text.replace(
            'app = FastAPI(title="EngiTools CAD Designer", version=CAD_API_VERSION)',
            'app = FastAPI(title="EngiTools CAD Designer")',
        )
        text = text.replace(
            '"version": CAD_API_VERSION,\n        "mechanical_pipeline_version": MECHANICAL_PIPELINE_VERSION,',
            '"build": build_identity(),\n        "mechanical_runtime": "mechanical",',
        )
        text = text.replace('"active_versions":runtime_contract(),', '"runtime_contract":runtime_contract(),')
        text = text.replace('"active_versions": runtime_contract(),', '"runtime_contract": runtime_contract(),')
        text = text.replace('"engine_version":CAD_API_VERSION,', '"build":build_identity(),')
        text = text.replace('"engine_version": CAD_API_VERSION,', '"build": build_identity(),')

    if target.startswith("mechanical_release_contract"):
        text = re.sub(r"(?m)^RELEASE_VERSION\s*=.*\n", "", text)
        text = text.replace('"version": RELEASE_VERSION,\n', '')
        text = text.replace("'version':RELEASE_VERSION,", "")
        text = text.replace('{"version":RELEASE_VERSION,', '{')
        text = text.replace("V16_CAPABILITIES", "PRIOR_CAPABILITIES")
        text = text.replace("V15_CAPABILITIES", "PRIOR_CAPABILITIES")
    return text


def runtime_contract_text() -> str:
    return '''"""Canonical Mechanical runtime contract.

Build identity and schema/contract revisions are metadata. They are not engine
versions and never select between parallel Mechanical implementations.
"""
from __future__ import annotations
from .build_identity import build_identity

PRODUCTION_CAD_ENTRYPOINT = "cad_engine.main:app"
RUNTIME_IDENTITY = "mechanical"
PMM_SCHEMA = "project-mechanical-model/v3"
TRACEABILITY_POLICY = "NO_ORPHAN_ENGINEERING_OUTPUT"


def runtime_contract() -> dict:
    return {
        "runtime_identity": RUNTIME_IDENTITY,
        "production_cad_entrypoint": PRODUCTION_CAD_ENTRYPOINT,
        "pmm_schema": PMM_SCHEMA,
        "traceability_policy": TRACEABILITY_POLICY,
        "build_identity": build_identity(),
    }
'''


def write_migration() -> dict:
    sources, mapping = build_closure()
    written: list[str] = []
    for source in sorted(sources):
        target = mapping[source]
        text = source_path(source).read_text(encoding="utf-8")
        text = semantic_runtime_cleanup(target, rewrite_imports(text, mapping))
        path = source_path(target)
        path.write_text(text, encoding="utf-8")
        written.append(path.name)

    (CAD / "runtime_contract.py").write_text(runtime_contract_text(), encoding="utf-8")
    written.append("runtime_contract.py")

    materializer = CAD / "mechanical_network_materializer.py"
    materializer.write_text(
        semantic_runtime_cleanup("mechanical_network_materializer", materializer.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    # main.py is hand-maintained as the tiny deployment boundary. Do not regenerate it.
    start = ROOT / "start_services.sh"
    stext = start.read_text(encoding="utf-8")
    stext = re.sub(
        r"# CAD designer: mechanical requests use the version-locked v19\.1 authority\n# adapter and remain PRE_SUBMISSION/NOT_COORDINATED without Structural/RCP\.\n",
        "# CAD designer: mechanical requests use the single canonical fail-closed authority.\n",
        stext,
    )
    start.write_text(stext, encoding="utf-8")

    return {"source_count": len(sources), "written": sorted(set(written)), "mapping": dict(sorted(mapping.items()))}


if __name__ == "__main__":
    report = write_migration()
    print(f"canonicalized {report['source_count']} active versioned modules")
    for source, target in report["mapping"].items():
        if source != target:
            print(f"{source} -> {target}")
