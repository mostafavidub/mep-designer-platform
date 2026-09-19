from app.dxf_output import _cad_error_message


class _Response:
    def json(self):
        return {
            "detail": {
                "stage": "architecture_preservation_gate",
                "status": "FAIL",
                "architecture_preservation_qa": {
                    "critical_missing_count": 0,
                    "important_missing_count": 0,
                    "all_missing_count": 0,
                    "sheet_results": [{
                        "sheet": "M-111",
                        "status": "FAIL",
                        "preservation_match": {
                            "strategy": "conservative_spatial",
                            "protected_source_count": 10,
                            "matched_count": 10,
                            "extra_protected": [{"key": "extra"}],
                        },
                        "topology": {
                            "pass": False,
                            "wall_topology_before": {"wall_count": 4},
                            "wall_topology_after": {"wall_count": 5},
                            "critical_counts_before": {"DOOR": 1},
                            "critical_counts_after": {"DOOR": 2},
                        },
                    }],
                },
            }
        }

    @property
    def text(self):
        return ""


def test_topology_failure_includes_bounded_actionable_evidence():
    message = _cad_error_message(_Response())
    assert "TOPOLOGY_MISMATCH:M-111" in message
    assert "strategy=conservative_spatial" in message
    assert "protected=10/10/1" in message
    assert "walls=4/5" in message
    assert "'DOOR': 1" in message
