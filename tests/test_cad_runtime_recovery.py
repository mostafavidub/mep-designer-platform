from unittest.mock import Mock, patch

from app import dxf_output


def response(status, payload):
    item = Mock(status_code=status, ok=status < 400)
    item.json.return_value = payload
    return item


@patch.object(dxf_output.legacy, "CAD_DESIGNER_URL", "https://external-cad.example")
@patch("app.dxf_output.requests.post")
def test_exact_build_identity_mismatch_retries_once_against_cobuilt_runtime(post):
    post.side_effect = [
        response(422, {
            "detail": {
                "stage": "v19_runtime_contract_gate",
                "v19_qa": {"errors": ["runtime_contract_mismatch:build_identity"]},
            }
        }),
        response(200, {"status": "PASS"}),
    ]

    result = dxf_output._post_to_compatible_cad({"project_id": "preserved"})

    assert result.ok
    assert [call.args[0] for call in post.call_args_list] == [
        "https://external-cad.example/design",
        "http://127.0.0.1:8081/design",
    ]
    assert post.call_args_list[0].kwargs["json"] == post.call_args_list[1].kwargs["json"]


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
