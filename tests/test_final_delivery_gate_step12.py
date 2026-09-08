import hashlib
import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.final_delivery_gate_step12 import validate_non_destructive_final_delivery
from cad_engine.mechanical_release_contract_v19 import REQUIRED_CAPABILITIES


class FinalDeliveryGateStep12Tests(unittest.TestCase):
    def _dxf(self, root: str, outside: bool = False) -> Path:
        path = Path(root) / "candidate.dxf"
        doc = ezdxf.new("R2013")
        msp = doc.modelspace()
        msp.add_line((10, 10), (20, 10), dxfattribs={"layer": "ENGITOOLS-M-WATER"})
        if outside:
            msp.add_line((200, 200), (220, 200), dxfattribs={"layer": "SI"})
        doc.saveas(path)
        return path

    def _report(self, before=1, after=1, removed=0, removed_layouts=None):
        return {
            "composition": {"boards": {"B-1": {"bounds": (0, 0, 100, 100)}}},
            "final_delivery_isolation_qa": {
                "status": "PASS",
                "entities_before": before,
                "entities_after": after,
                "entities_removed": removed,
                "empty_layouts_removed": list(removed_layouts or []),
            },
            "architecture_preservation_qa_after_v17": {"status": "PASS"},
            "exact_file_final_delivery_qa": {"status": "PASS"},
            "montage_exact_reopen_qa": {"status": "PASS"},
        }

    def test_clean_candidate_passes_and_step12_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._dxf(td)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            qa = validate_non_destructive_final_delivery(path, self._report())
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(qa["status"], "PASS", qa)
            self.assertTrue(qa["hash_unchanged"])
            self.assertEqual(before, after)
            self.assertEqual(qa["entities_removed"], 0)

    def test_sanitized_candidate_is_blocked_even_when_exact_file_is_now_clean(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._dxf(td)
            qa = validate_non_destructive_final_delivery(path, self._report(before=3, after=1, removed=2))
            self.assertEqual(qa["status"], "FAIL")
            self.assertIn("POST_HOC_ENTITY_DELETION_REQUIRED", qa["errors"])
            self.assertIn("FINAL_ENTITY_COUNT_CHANGED_BY_SANITIZER", qa["errors"])

    def test_layout_deletion_is_release_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._dxf(td)
            qa = validate_non_destructive_final_delivery(path, self._report(removed_layouts=["M-101"]))
            self.assertEqual(qa["status"], "FAIL")
            self.assertIn("POST_HOC_LAYOUT_DELETION_REQUIRED", qa["errors"])

    def test_missing_sanitizer_evidence_is_input_required(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._dxf(td)
            report = self._report()
            report.pop("final_delivery_isolation_qa")
            qa = validate_non_destructive_final_delivery(path, report)
            self.assertEqual(qa["status"], "INPUT_REQUIRED")
            self.assertIn("FINAL_DELIVERY_ISOLATION_QA", qa["missing_inputs"])

    def test_outside_geometry_fails_without_being_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._dxf(td, outside=True)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            qa = validate_non_destructive_final_delivery(path, self._report(before=2, after=2))
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(qa["status"], "FAIL")
            self.assertIn("EXACT_FINAL_DELIVERY_RECHECK_FAILED", qa["errors"])
            self.assertEqual(before, after)
            reopened = ezdxf.readfile(path)
            self.assertTrue(any(str(getattr(e.dxf, "layer", "")) == "SI" for e in reopened.modelspace()))

    def test_release_contract_requires_step12_capability(self):
        self.assertEqual(
            REQUIRED_CAPABILITIES.get("non_destructive_final_delivery_acceptance"),
            "cad_engine.final_delivery_gate_step12",
        )


if __name__ == "__main__":
    unittest.main()
