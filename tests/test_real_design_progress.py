from pathlib import Path


def test_customer_progress_is_detailed_and_unversioned():
    from app.design_progress import STAGES

    expected = [
        "architecture_interpretation", "scope_mapping", "network_topology",
        "network_sizing", "system_coordination", "equipment_placement",
        "documentation_composition", "drawing_composition",
        "network_materialization", "exact_output_review",
    ]
    assert all(stage in STAGES for stage in expected)
    percents = [STAGES[stage][0] for stage in STAGES]
    assert percents == sorted(percents)
    assert all("v19" not in stage.lower() for stage in STAGES)
    assert all("v19" not in label.lower() for _, label in STAGES.values())


def test_progress_is_wired_to_real_engine_boundaries():
    source = Path("cad_engine/mechanical_authority.py").read_text()
    for stage in (
        "architecture_interpretation", "scope_mapping", "network_topology",
        "network_sizing", "system_coordination", "equipment_placement",
        "documentation_composition", "drawing_composition",
        "network_materialization", "exact_output_review",
    ):
        assert f'_emit_progress(answers, "{stage}")' in source
    assert "sleep(" not in source


def test_customer_templates_do_not_expose_engine_versions():
    project = Path("app/templates/project.html").read_text()
    progress = Path("app/design_progress.py").read_text()
    assert "v19" not in project.lower()
    assert "19.1.0" not in project
    assert "v19" not in progress.lower()

