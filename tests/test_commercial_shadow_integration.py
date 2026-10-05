"""Actual registered SQL models and live quote path on an isolated local database."""
from datetime import datetime
from copy import deepcopy
from sqlalchemy import event
from fastapi.testclient import TestClient
from app.main_health import app
from app import main as legacy
from app.commercial_shadow import run_internal_shadow
from tests.test_commercial_measurement import bundle


def test_actual_database_shadow_reads_never_write_paid_quote_wallet_or_analysis(tmp_path):
    client=TestClient(app);client.get('/panel')
    pid=client.post('/api/upload/init/electrical',json={'name':'commercial-shadow-synthetic'}).json()['project_id']
    db=legacy.Session(); project=db.get(legacy.Project,pid)
    project.status='ready_to_design'; project.answers={'discipline':'electrical'}
    import hashlib
    source=b'synthetic-private-source'; b=bundle(sha=hashlib.sha256(source).hexdigest())
    project_directory=tmp_path/str(pid);project_directory.mkdir();(project_directory/'architecture.dxf').write_bytes(source)
    project.analysis={'discipline':'electrical','architectural_auto':{'geometry_area_m2':250},'files':[{'canonical_architecture_model':b['legacy']}]}
    db.commit()
    commercial=app.state.commercial
    config=commercial['service_pricing']('electrical',db)
    live=commercial['quote_for'](project)
    q=db.query(commercial['ProjectQuote']).filter_by(project_id=pid).first()
    q.paid=True;q.payment_method='synthetic';q.paid_at=datetime(2026,10,5);db.commit()
    before={col.name:getattr(q,col.name) for col in q.__table__.columns}
    analysis=deepcopy(project.analysis); wallet_before=commercial['wallet_for'](project.user_id)
    statements=[]
    def collect(conn,cursor,statement,parameters,context,executemany): statements.append(statement)
    event.listen(legacy.engine,'before_cursor_execute',collect)
    try:
        result=run_internal_shadow(project,db,commercial,bundles=[b],project_directory=project_directory,created_at='fixed')
    finally:
        event.remove(legacy.engine,'before_cursor_execute',collect)
    assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
    assert result['shadow_quote']['pricing']['price_per_m2']==config['price_per_m2']
    assert result['shadow_quote']['final_amount'] is None
    db.refresh(q); db.refresh(project)
    assert before=={col.name:getattr(q,col.name) for col in q.__table__.columns}
    assert project.analysis==analysis
    assert commercial['wallet_for'](project.user_id)==wallet_before
    assert commercial['quote_for'](project)['amount']==live['amount']
    (project_directory/'architecture.dxf').write_bytes(b'changed-source')
    import pytest
    with pytest.raises(ValueError,match='STALE_PROJECT_ANALYSIS'):
        run_internal_shadow(project,db,commercial,bundles=[b],project_directory=project_directory,created_at='fixed')
    db.close()


def test_actual_extent_heuristic_reproduces_root_cause(monkeypatch):
    from app import unit_sanity
    monkeypatch.setattr(unit_sanity,'_original_analyze_dxf_enhanced',lambda path:{'geometry_bounds':[0,0,10,20]})
    monkeypatch.setattr(unit_sanity.main_auto.legacy,'read_input_dxf',lambda path:(object(),None))
    monkeypatch.setattr(unit_sanity,'_infer_scale',lambda doc:{'effective_scale_to_m':1})
    result=unit_sanity.analyze_dxf_enhanced('synthetic-no-file')
    assert result['geometry_area_m2']==200
    assert result['geometry_scope']=='single-plan-plausible'
    assert 'levels' not in result and 'building_envelopes' not in result
