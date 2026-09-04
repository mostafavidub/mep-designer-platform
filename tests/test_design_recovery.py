from types import SimpleNamespace

from app.design_recovery import classify_recovery, clear_active_recovery, get_recovery, record_recovery


def test_transient_and_transactional_failures_are_retried_with_allowlisted_actions():
    network=classify_recovery("CAD connection timeout",attempt=1,max_attempts=3)
    artifact=classify_recovery("exact-file reopen failed",attempt=1,max_attempts=3)
    missing=classify_recovery("هیچ فایل dxf معتبر پیدا نشد",attempt=1,max_attempts=3)
    assert network.recoverable and network.strategy=="retry_transport"
    assert artifact.recoverable and artifact.strategy=="rebuild_clean_transaction"
    assert missing.recoverable and missing.strategy=="restore_durable_input"


def test_engineering_input_and_retry_budget_fail_closed():
    required=classify_recovery("unresolved engineering inputs: north",attempt=1,max_attempts=3)
    exhausted=classify_recovery("connection timeout",attempt=3,max_attempts=3)
    unknown=classify_recovery("pipe sizing rule contradiction",attempt=1,max_attempts=3)
    assert not required.recoverable and required.strategy=="request_user_input"
    assert not exhausted.recoverable and exhausted.reason=="retry_budget_exhausted"
    assert not unknown.recoverable


def test_missing_durable_input_requests_reupload_after_retry_budget():
    decision=classify_recovery('فایل معماری پروژه در فضای ذخیره‌سازی پیدا نشد.',attempt=3,max_attempts=3)
    assert not decision.recoverable
    assert decision.strategy == 'request_input_reupload'
    assert decision.resume_stage == 'awaiting_upload'


def test_recovery_history_is_durable_and_clears_only_active_marker():
    project=SimpleNamespace(analysis={"drawing_set":{"approved":True}})
    decision=classify_recovery("montage render failed",attempt=1,max_attempts=3)
    record_recovery(project,decision,attempt=1,max_attempts=3,error="montage render failed")
    recovery=get_recovery(project)
    assert recovery["active"] is True and len(recovery["history"])==1
    assert project.analysis["drawing_set"]["approved"] is True
    clear_active_recovery(project)
    recovery=get_recovery(project)
    assert recovery["active"] is False and len(recovery["history"])==1


def test_site_and_queue_expose_controlled_retry_state():
    queue=open("app/job_queue.py",encoding="utf-8").read()
    modal=open("app/static/resumable-upload.js",encoding="utf-8").read()
    project=open("app/templates/project.html",encoding="utf-8").read()
    assert "MAX_ATTEMPTS = int(os.getenv('JOB_MAX_ATTEMPTS', '3'))" in queue
    assert "classify_recovery" in queue and "design_recovery" in queue
    assert "اصلاح خودکار در حال اجراست" in modal
    assert "data-design-recovery" in project and "اصلاح خودکار در حال اجراست" in project
