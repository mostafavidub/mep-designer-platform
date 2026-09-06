from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import RedirectResponse

from app import dxf_output


class _Query:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return SimpleNamespace(status='ready', pdf_path='s3://bucket/projects/96/outputs/R001/mechanical/output.dxf')


class _Session:
    def get(self, model, pid):
        return SimpleNamespace(answers={'discipline': 'mechanical'}, analysis={})

    def query(self, model):
        return _Query()

    def close(self):
        pass


def test_maintenance_output_redirects_to_durable_artifact(monkeypatch):
    monkeypatch.setenv('INTERNAL_MAINTENANCE_TOKEN', 'test-token')
    monkeypatch.setattr(dxf_output.legacy, 'Session', lambda: _Session())
    monkeypatch.setattr(dxf_output.artifact_storage, 'configured', lambda: True)
    monkeypatch.setattr(dxf_output.artifact_storage, 'presigned_download', lambda uri, filename: f'https://download.invalid/{filename}')
    request=Request({'type':'http','method':'GET','path':'/','headers':[(b'x-maintenance-token',b'test-token')]})
    response=dxf_output.maintenance_get_cad_output(96,1,request)
    assert isinstance(response,RedirectResponse)
    assert response.status_code == 307
    assert response.headers['location'].endswith('EngiTools_mechanical_96_R1.dxf')
