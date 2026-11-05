import json
import shutil
from pathlib import Path

from tools.rulebook_closure_diagnostics import DEFAULT_MODULES_ROOT, audit_all, audit_module


def test_current_mechanical_rulebooks_pass_bounded_integrity_without_false_completeness():
    report = audit_all()
    assert report["status"] == "PASS"
    assert report["module_count"] == 7
    assert report["complete_statutory_modules"] == []
    assert set(report["bounded_only_modules"]) == {
        "mechanical.cooling.iran", "mechanical.gas.iran", "mechanical.heating.iran",
        "mechanical.rainwater.iran", "mechanical.sanitary_vent.iran",
        "mechanical.ventilation.iran", "mechanical.water.iran",
    }
    rainwater = next(row for row in report["modules"] if row["module_id"] == "mechanical.rainwater.iran")
    assert rainwater["module_version"] == "2.85.1"
    assert rainwater["rule_count"] == 103
    assert rainwater["source_entry_count"] == 534
    assert rainwater["schema_error_count"] == 0
    assert rainwater["unresolved_control_count"] == 0
    assert rainwater["coverage_scope"] == "BOUNDED_ONLY"


def test_audit_fails_on_schema_extension_and_does_not_hide_error(tmp_path: Path):
    source = DEFAULT_MODULES_ROOT / "gas"
    target = tmp_path / "gas"
    shutil.copytree(source, target)
    manifest = json.loads((target / "module.json").read_text(encoding="utf-8"))
    rules_path = target / manifest["rules_file"]
    registry = json.loads(rules_path.read_text(encoding="utf-8"))
    registry["rules"][0]["unreviewed_hidden_field"] = True
    rules_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    result = audit_module(target)
    assert result["status"] == "FAIL"
    assert "STRICT_SCHEMA_INVALID" in result["errors"]
    assert result["schema_error_count"] >= 1
    assert result["schema_errors"][0]["rule_id"]


def test_audit_fails_when_executable_source_lacks_reciprocal_rule_source(tmp_path: Path):
    source = DEFAULT_MODULES_ROOT / "water"
    target = tmp_path / "water"
    shutil.copytree(source, target)
    coverage = json.loads((target / "source_coverage.json").read_text(encoding="utf-8"))
    coverage["entries"][0]["disposition"] = "EXECUTABLE_RULE"
    coverage["entries"][0]["source_id"] = "M16-DECOY-NOT-IN-RULE"
    (target / "source_coverage.json").write_text(json.dumps(coverage, ensure_ascii=False), encoding="utf-8")

    result = audit_module(target)
    assert result["status"] == "FAIL"
    assert "EXECUTABLE_SOURCE_RECIPROCAL_LINK_MISSING" in result["errors"]
    assert result["reciprocal_link_missing_source_ids"] == ["M16-DECOY-NOT-IN-RULE"]
