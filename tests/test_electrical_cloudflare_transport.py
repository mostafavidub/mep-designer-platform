from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app import electrical_cad_transport


class _FakeResponse:
    def __init__(self, body=None, status_code=200):
        self._body=body or {"mode":"electrical-authoritative","pipeline_authority":"electrical-authority"}
        self.status_code=status_code
        self.ok=status_code < 400
    def json(self): return self._body


class _DxfOutput:
    def __init__(self):
        self.calls=[]
        def original(payload):
            self.calls.append(payload)
            return _FakeResponse({"delegated":True})
        self._post_to_compatible_cad=original


class ElectricalCloudflareTransportTests(unittest.TestCase):
    def test_mechanical_transport_is_untouched(self):
        module=_DxfOutput(); electrical_cad_transport.install(module)
        response=module._post_to_compatible_cad({"discipline":"mechanical","project_id":"M1"})
        self.assertEqual(response.json(),{"delegated":True})
        self.assertEqual(module.calls,[{"discipline":"mechanical","project_id":"M1"}])

    def test_remote_electrical_uses_dedicated_authenticated_endpoint(self):
        module=_DxfOutput(); electrical_cad_transport.install(module)
        captured={}
        def fake_post(url,**kwargs):
            captured.update({"url":url,**kwargs});return _FakeResponse()
        env={"COBUILT_CAD_DESIGNER_URL":"https://cad.example.test","COBUILT_CAD_SERVICE_TOKEN":"secret-token"}
        with patch.dict(os.environ,env,clear=False), patch.object(electrical_cad_transport.requests,"post",side_effect=fake_post):
            response=module._post_to_compatible_cad({"discipline":"electrical","project_id":"E1"})
        self.assertTrue(response.ok)
        self.assertEqual(captured["url"],"https://cad.example.test/design-electrical")
        self.assertEqual(captured["headers"],{"x-cad-service-token":"secret-token"})
        self.assertEqual(captured["json"]["discipline"],"electrical")

    def test_cloudflare_edge_protects_both_design_mutations(self):
        source=(Path(__file__).resolve().parents[1]/".github"/"cloudflare-cad"/"src"/"index.ts").read_text(encoding="utf-8")
        self.assertIn('"/design"',source)
        self.assertIn('"/design-electrical"',source)
        self.assertIn("protectedDesignPaths",source)
        self.assertIn("x-cad-service-token",source)


if __name__ == "__main__":
    unittest.main()
