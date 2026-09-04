"""Fail-closed, allow-listed recovery policy for production design jobs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RecoveryDecision:
    recoverable: bool
    strategy: str
    resume_stage: str
    reason: str


INPUT_REQUIRED = (
    "unresolved engineering inputs", "input_required", "اطلاعات فنی لازم",
    "approved mechanical drawing manifest is missing", "مانیفست تأییدشده نامعتبر",
    "architectural_north_missing", "discipline must be", "output_scope",
    "design_basis_input_required", "provisional_shaft_not_authority_acceptable",
)
TRANSIENT = (
    "timeout", "timed out", "connection", "temporarily", "reset by peer",
    "502", "503", "504", "no space left on device",
)
INPUT_STORAGE = (
    "فایل معماری پروژه در فضای ذخیره‌سازی پیدا نشد", "هیچ فایل dxf معتبر پیدا نشد",
    "هیچ فایل dxf معتبر داخل zip پیدا نشد", "architecture_dir", "input dxf",
)
SAFE_REBUILD = (
    "exact-file", "exact_file", "reopen", "montage", "preview", "artifact",
    "فایل dxf تولیدشده پیدا نشد", "موتور cad هیچ فایل", "zip", "package",
    "no space left on device", "cad http 500",
)


def classify_recovery(error: str, *, attempt: int, max_attempts: int) -> RecoveryDecision:
    value=str(error or "").lower()
    if any(token in value for token in INPUT_STORAGE):
        if attempt >= max_attempts:
            return RecoveryDecision(False,"request_input_reupload","awaiting_upload","durable_input_missing")
        return RecoveryDecision(True,"restore_durable_input","preparing_inputs","input_restore_allowed")
    if attempt >= max_attempts:
        return RecoveryDecision(False,"stop","failed","retry_budget_exhausted")
    if any(token in value for token in INPUT_REQUIRED):
        return RecoveryDecision(False,"request_user_input","failed","engineering_input_required")
    if "no space left on device" in value:
        return RecoveryDecision(True,"reclaim_workspace","preparing_inputs","workspace_reclaim_allowed")
    if any(token in value for token in TRANSIENT):
        return RecoveryDecision(True,"retry_transport","engine_designing","transient_service_failure")
    if any(token in value for token in SAFE_REBUILD):
        return RecoveryDecision(True,"rebuild_clean_transaction","engine_designing","transactional_artifact_failure")
    return RecoveryDecision(False,"stop","failed","unrecognized_or_deterministic_failure")


def record_recovery(project, decision: RecoveryDecision, *, attempt: int, max_attempts: int, error: str):
    analysis=dict(project.analysis or {});recovery=dict(analysis.get("design_recovery") or {})
    history=list(recovery.get("history") or [])
    entry={**asdict(decision),"attempt":attempt,"max_attempts":max_attempts,"error":str(error or "")[:1200],"at":datetime.now(timezone.utc).isoformat()}
    history.append(entry)
    recovery={"active":decision.recoverable,"current":entry,"history":history[-20:]}
    analysis["design_recovery"]=recovery;project.analysis=analysis
    return recovery


def clear_active_recovery(project):
    analysis=dict(project.analysis or {});recovery=dict(analysis.get("design_recovery") or {})
    if recovery:
        recovery["active"]=False;recovery["current"]=None;analysis["design_recovery"]=recovery;project.analysis=analysis


def get_recovery(project):
    return dict((project.analysis or {}).get("design_recovery") or {})
