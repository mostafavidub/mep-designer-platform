"""Discipline-safe CAD transport for the active Electrical workflow.

Mechanical continues through the shared transport unchanged. Electrical is sent
to its dedicated authority endpoint with the same co-built token contract used
by the Cloudflare CAD edge. In-process development executes the same Electrical
request adapter directly without routing through Mechanical.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import requests
from fastapi import HTTPException


def install(dxf_output):
    if getattr(dxf_output, "_electrical_cad_transport_installed", False):
        return
    original_post = dxf_output._post_to_compatible_cad

    class LocalResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self.ok = status_code < 400
            self._body = body

        def json(self):
            return self._body

    def post_to_compatible_cad(payload):
        if str((payload or {}).get("discipline") or "").lower() != "electrical":
            return original_post(payload)

        if os.getenv("COBUILT_CAD_IN_PROCESS", "").strip() == "1":
            from cad_engine.electrical_api import design_electrical_request
            local_payload = {"architecture_archive_b64": None, **payload}
            try:
                body = design_electrical_request(SimpleNamespace(**local_payload))
                return LocalResponse(200, body)
            except HTTPException as exc:
                return LocalResponse(exc.status_code, {"detail": exc.detail})

        cobuilt = os.getenv("COBUILT_CAD_DESIGNER_URL", "http://127.0.0.1:8081").rstrip("/")
        token = os.getenv("COBUILT_CAD_SERVICE_TOKEN", "").strip()
        headers = {"x-cad-service-token": token} if token else None
        response = requests.post(
            cobuilt + "/design-electrical",
            json=payload,
            headers=headers,
            timeout=3600,
        )
        if response.ok:
            data = response.json()
            if data.get("mode") != "electrical-authoritative" or data.get("pipeline_authority") != "electrical-authority":
                raise RuntimeError("مسیر تولید برق با قرارداد فعال سیستم تطابق ندارد.")
        return response

    dxf_output._post_to_compatible_cad = post_to_compatible_cad
    dxf_output._electrical_cad_transport_installed = True
