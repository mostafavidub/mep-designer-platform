from unittest.mock import Mock, patch

from app import dxf_output


def response(status, payload):
    item = Mock(status_code=status, ok=status < 400)
    item.json.return_value = payload
    return item


@patch.object(dxf_output.legacy, "CAD_DESIGNER_URL", "https://external-cad.example")
@patch("app.dxf_output.requests.post")
def test_design_uses_only_canonical_cobuilt_runtime(post):
    post.return_value = response(200, {"status": "PASS"})

    result = dxf_output._post_to_compatible_cad({"project_id": "preserved"})

    assert result.ok
    post.assert_called_once()
    assert post.call_args.args[0] == "http://127.0.0.1:8081/design"
    assert post.call_args.kwargs["json"] == {"project_id": "preserved"}


@patch.object(dxf_output.legacy, "CAD_DESIGNER_URL", "https://external-cad.example")
@patch("app.dxf_output.requests.post")
def test_other_cad_failures_never_retry(post):
    post.return_value = response(422, {
        "detail": {
            "stage": "v19_preflight_gate",
            "v19_qa": {"errors": ["missing:STRUCTURAL_MODEL"]},
        }
    })

    result = dxf_output._post_to_compatible_cad({"project_id": "preserved"})

    assert not result.ok
    post.assert_called_once()


@patch.object(dxf_output.legacy, "CAD_DESIGNER_URL", "http://127.0.0.1:8081")
@patch("app.dxf_output.requests.post")
def test_local_runtime_mismatch_does_not_loop(post):
    post.return_value = response(422, {
        "detail": {
            "stage": "v19_runtime_contract_gate",
            "v19_qa": {"errors": ["runtime_contract_mismatch:build_identity"]},
        }
    })

    result = dxf_output._post_to_compatible_cad({"project_id": "preserved"})

    assert not result.ok
    post.assert_called_once()


def test_startup_requeues_only_exact_preserved_build_identity_failures():
    source = (dxf_output.Path(__file__).parents[1] / "app/job_queue.py").read_text()
    assert "runtime_contract_mismatch:build_identity" in source
    assert "Job.status == 'failed'" in source
    assert "failed_job.status = 'queued'" in source
    assert "failed_job.attempts = 0" in source
