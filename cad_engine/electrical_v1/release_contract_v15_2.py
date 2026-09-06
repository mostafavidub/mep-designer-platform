from __future__ import annotations

from importlib import import_module

from .authority_qa import release_contract_status as base_release_contract_status

EXTRA_REQUIRED_CAPABILITIES = {
    "preservation_first_cleanup": "cad_engine.electrical_v1.cleanup_policy",
    "north_inherited_from_architecture": "cad_engine.electrical_v1.orientation",
    "safe_drawing_area_zero_title_overlap": "cad_engine.electrical_v1.strict_pipeline_v15",
    "authority_parity_orchestration": "cad_engine.electrical_v1.strict_pipeline_v15_2",
}


def release_contract_status() -> dict:
    base = base_release_contract_status()
    checks = dict(base.get("checks") or {})
    for capability, module_name in EXTRA_REQUIRED_CAPABILITIES.items():
        try:
            import_module(module_name)
            checks[capability] = True
        except Exception:
            checks[capability] = False
    return {
        "version": "electrical-authority-parity-v15.2.0",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(checks),
        "passed_count": sum(1 for value in checks.values() if value),
        "checks": checks,
    }
