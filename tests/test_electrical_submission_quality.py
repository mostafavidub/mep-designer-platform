from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.electrical_v1.submission_quality import (
    apply_submission_titleblocks,
    cross_sheet_traceability_qa,
    submission_titleblock_qa,
)


class ElectricalSubmissionQualityTests(unittest.TestCase):
    def _manifest(self):
        return [
            {"sheet_id": "E-01", "family": "LIGHTING"},
            {"sheet_id": "E-02", "family": "POWER"},
            {"sheet_id": "E-10", "family": "DETAILS"},
        ]

    def _data(self):
        return {
            "project": {
                "project": {
                    "project_name": {"value": "QA Project", "status": "FINAL", "source": "explicit_user_input"},
                    "owner": {"value": "Owner", "status": "FINAL", "source": "explicit_user_input"},
                }
            },
            "manifest": self._manifest(),
            "topology": {
                "circuits": [
                    {"id": "L3/1", "panel_id": "P1", "load_ids": ["LD-1"]},
                    {"id": "L1/1", "panel_id": "P1", "load_ids": ["LD-2"]},
                ],
                "panels": [{"id": "P1", "circuit_ids": ["L3/1", "L1/1"]}],
            },
            "routing": {"routes": [{"circuit_id": "L3/1"}, {"circuit_id": "L1/1"}]},
            "schedules": {
                "P1": [
                    {"circuit_no": "L3/1"},
                    {"circuit_no": "L1/1"},
                ]
            },
            "details": [{"detail_id": "D-EL-LIGHT-MOUNT"}],
            "detail_links": [{"sheet_id": "E-01", "detail_id": "D-EL-LIGHT-MOUNT"}],
        }

    def test_submission_titleblock_is_materialized_and_detected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.dxf"
            doc = ezdxf.new("R2013")
            for sid in ("E-01", "E-02", "E-10"):
                doc.layouts.new(sid)
            doc.saveas(path)
            data = self._data()
            materialized = apply_submission_titleblocks(path, data)
            self.assertEqual(materialized["status"], "PASS")
            result = submission_titleblock_qa(path, data["manifest"])
            self.assertEqual(result["status"], "PASS", result)

    def test_cross_sheet_traceability_passes_for_consistent_graph(self):
        result = cross_sheet_traceability_qa(self._data())
        self.assertEqual(result["status"], "PASS", result)

    def test_cross_sheet_traceability_rejects_missing_panel_and_detail(self):
        data = self._data()
        data["topology"]["circuits"][0]["panel_id"] = "MISSING"
        data["detail_links"][0]["detail_id"] = "MISSING-DETAIL"
        result = cross_sheet_traceability_qa(data)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("circuit_panel_missing" in x for x in result["errors"]))
        self.assertTrue(any("detail_link_detail_missing" in x for x in result["errors"]))

    def test_cross_sheet_traceability_rejects_schedule_drift(self):
        data = self._data()
        data["schedules"]["P1"].append({"circuit_no": "UNKNOWN"})
        result = cross_sheet_traceability_qa(data)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("schedule_circuit_reference_missing" in x for x in result["errors"]))


if __name__ == "__main__":
    unittest.main()
