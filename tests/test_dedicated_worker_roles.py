import importlib


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv('JOB_WORKER_TYPES', raising=False)
    else:
        monkeypatch.setenv('JOB_WORKER_TYPES', value)
    import app.job_queue as job_queue
    return importlib.reload(job_queue)


def test_unset_worker_roles_preserve_all_in_one_runtime(monkeypatch):
    queue = _reload(monkeypatch, None)
    assert queue.WORKER_TYPES == {'analysis', 'design'}
    assert queue.queue_health()['mode'] == 'worker'


def test_empty_worker_roles_make_web_process_http_only(monkeypatch):
    queue = _reload(monkeypatch, '')
    assert queue.WORKER_TYPES == set()
    assert queue.queue_health() == {
        'status': 'ok',
        'mode': 'http_only',
        'workers': queue._QUEUE_STATE,
    }


def test_worker_role_allowlist_ignores_unknown_values(monkeypatch):
    queue = _reload(monkeypatch, 'design,unknown,analysis')
    assert queue.WORKER_TYPES == {'analysis', 'design'}
    assert queue.queue_health()['worker_types'] == ['analysis', 'design']
