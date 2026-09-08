import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ezdxf

from cad_engine.exact_dxf_gate_step10 import validate_exact_dxf_health
from cad_engine.mechanical_authority_site_v19 import design_mechanical_authority_site
from cad_engine.version_manifest import active_version_manifest


def _write_valid(path: Path, x=1.0):
    doc=ezdxf.new("R2010")
    doc.modelspace().add_line((0,0),(x,0),dxfattribs={"layer":"ENGITOOLS-M-TEST"})
    doc.saveas(path)


class _FakeAudit:
    def __init__(self,count=0): self.errors=[object() for _ in range(count)]


class _FakeDoc:
    def __init__(self,audit_errors=0): self.audit_errors=audit_errors
    def modelspace(self): return [object()]
    def audit(self): return _FakeAudit(self.audit_errors)


class ExactDXFStep10Tests(unittest.TestCase):
    def test_valid_exact_dxf_reopens_twice_audits_clean_and_preserves_hash(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"valid.dxf"; _write_valid(p)
            before=p.read_bytes()
            result=validate_exact_dxf_health(p)
            self.assertEqual(result["status"],"PASS",result)
            self.assertTrue(result["first_reopen"])
            self.assertTrue(result["second_reopen"])
            self.assertEqual(result["audit_error_count"],0)
            self.assertGreater(result["entity_count"],0)
            self.assertTrue(result["read_only_hash_preserved"])
            self.assertEqual(before,p.read_bytes())

    def test_missing_exact_dxf_fails(self):
        result=validate_exact_dxf_health(Path("definitely-missing-step10.dxf"))
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("generated_dxf_missing",result["errors"])

    def test_empty_exact_dxf_fails_before_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"empty.dxf"; p.write_bytes(b"")
            result=validate_exact_dxf_health(p)
            self.assertEqual(result["status"],"FAIL")
            self.assertIn("generated_dxf_empty",result["errors"])
            self.assertFalse(result["first_reopen"])

    def test_exact_reopen_exception_is_release_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.dxf"; p.write_bytes(b"not-empty")
            with patch("cad_engine.exact_dxf_gate_step10.ezdxf.readfile",side_effect=ValueError("broken")):
                result=validate_exact_dxf_health(p)
            self.assertEqual(result["status"],"FAIL")
            self.assertTrue(any(x.startswith("exact_dxf_reopen_failed:ValueError") for x in result["errors"]))

    def test_audit_error_is_release_blocking_without_repairing_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"audit.dxf"; p.write_bytes(b"immutable-candidate")
            before=p.read_bytes(); fake=_FakeDoc(audit_errors=1)
            with patch("cad_engine.exact_dxf_gate_step10.ezdxf.readfile",return_value=fake):
                result=validate_exact_dxf_health(p)
            self.assertEqual(result["status"],"FAIL")
            self.assertIn("dxf_audit_errors:1",result["errors"])
            self.assertTrue(result["read_only_hash_preserved"])
            self.assertEqual(before,p.read_bytes())

    def test_second_reopen_failure_is_release_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"second.dxf"; p.write_bytes(b"immutable-candidate")
            with patch("cad_engine.exact_dxf_gate_step10.ezdxf.readfile",side_effect=[_FakeDoc(0),RuntimeError("second-open")]):
                result=validate_exact_dxf_health(p)
            self.assertEqual(result["status"],"FAIL")
            self.assertTrue(result["first_reopen"])
            self.assertFalse(result["second_reopen"])
            self.assertTrue(any(x.startswith("exact_dxf_second_reopen_failed:RuntimeError") for x in result["errors"]))

    @patch("cad_engine.mechanical_authority_site_v19.validate_exact_dxf_health")
    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_failed_step10_restores_previous_known_artifact(self,designer,integrity,health):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/"mechanical.dxf"; _write_valid(dst,1.0); safe=dst.read_bytes()
            def generate(src,dst,answers=None,plan_analysis=None):
                _write_valid(Path(dst),9.0)
                return {"status":"PASS"}
            designer.side_effect=generate
            integrity.return_value={"status":"PASS","errors":[],"warnings":[],"exact_file_reopened":True}
            health.return_value={"status":"FAIL","errors":["dxf_audit_errors:1"],"first_reopen":True,"second_reopen":True}
            answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
            result=design_mechanical_authority_site(Path(td)/"architecture.dxf",dst,answers=answers,plan_analysis={})
            self.assertEqual(result["status"],"FAIL")
            self.assertEqual(result["stage"],"exact_dxf_health_gate")
            self.assertEqual(result["submission_state"],"BLOCKED")
            self.assertEqual(dst.read_bytes(),safe)

    @patch("cad_engine.mechanical_authority_site_v19.validate_exact_dxf_health")
    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_failed_step10_removes_new_candidate_when_no_previous_artifact(self,designer,integrity,health):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/"mechanical.dxf"
            def generate(src,dst,answers=None,plan_analysis=None):
                _write_valid(Path(dst),9.0)
                return {"status":"PASS"}
            designer.side_effect=generate
            integrity.return_value={"status":"PASS","errors":[],"warnings":[],"exact_file_reopened":True}
            health.return_value={"status":"FAIL","errors":["exact_dxf_second_reopen_failed"],"first_reopen":True,"second_reopen":False}
            answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
            result=design_mechanical_authority_site(Path(td)/"architecture.dxf",dst,answers=answers,plan_analysis={})
            self.assertEqual(result["stage"],"exact_dxf_health_gate")
            self.assertFalse(dst.exists())

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_lower_layer_failure_also_restores_previous_artifact_transactionally(self,designer):
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/"mechanical.dxf"; _write_valid(dst,1.0); safe=dst.read_bytes()
            def generate_fail(src,dst,answers=None,plan_analysis=None):
                Path(dst).write_bytes(b"partial-bad-output")
                return {"status":"FAIL","stage":"legacy"}
            designer.side_effect=generate_fail
            answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
            result=design_mechanical_authority_site(Path(td)/"architecture.dxf",dst,answers=answers,plan_analysis={})
            self.assertEqual(result["status"],"FAIL")
            self.assertEqual(dst.read_bytes(),safe)


if __name__=="__main__":
    unittest.main()
