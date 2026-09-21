"""Durable, owner-bound background jobs for architecture questionnaires."""
import asyncio
import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from .panel_checkout import session_user


_TASKS = {}
_RETENTION_SECONDS = 24 * 60 * 60


def _root():
    path = Path(os.getenv("DATA_DIR", "/data")) / "questionnaire-jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _cleanup_expired_jobs(now=None):
    """Remove completed/stale job workspaces after the documented retention window."""
    now = int(now or time.time())
    for workspace in _root().iterdir():
        if not workspace.is_dir() or workspace.name in _TASKS:
            continue
        metadata = workspace / "metadata.json"
        try:
            created_at = int(json.loads(metadata.read_text(encoding="utf-8")).get("created_at", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            created_at = 0
        if created_at and now - created_at > _RETENTION_SECONDS:
            shutil.rmtree(workspace, ignore_errors=True)


def _launch(job_id, workspace, saved, main_auto, legacy):
    """Start or resume one job once per process."""
    if job_id in _TASKS:
        return
    _write(workspace / "state.json", {"status": "processing", "started_at": int(time.time())})
    task = asyncio.create_task(_run(
        job_id, workspace, saved["name"], saved["discipline"],
        saved.get("occupancy", ""), main_auto, legacy))
    _TASKS[job_id] = task


def _analyze(workspace, name, discipline, occupancy, main_auto, legacy):
    source = workspace / name
    inputs = workspace / "inputs"
    if inputs.exists():
        shutil.rmtree(inputs)
    inputs.mkdir()
    if source.suffix.lower() == ".zip":
        legacy.safe_extract(source, inputs)
    else:
        shutil.copy2(source, inputs / name)
    files = sorted(path for path in inputs.rglob("*.dxf") if legacy.is_real_dxf_path(path))
    if not files or len(files) > 8:
        raise ValueError("No valid DXF found or package contains too many files")
    from .dxf_input import begin_input_read_cache, end_input_read_cache
    token = begin_input_read_cache()
    try:
        analysis = {
            "discipline": discipline,
            "architecture_analyzer_version": "3.5-project-evidence-gate",
            "file_count": len(files),
            "files": [main_auto.analyze_dxf_enhanced(path) for path in files],
            "inference_mode": "architecture-first-v2-spatial",
        }
        auto, answers, unresolved = main_auto.build_unified_questionnaire(
            analysis, discipline, {"occupancy": occupancy} if occupancy else {})
    finally:
        end_input_read_cache(token)
    from .mechanical_workflow import _question_payload
    return {
        "identity": main_auto.QUESTIONNAIRE_IDENTITY,
        "discipline": discipline,
        "source": "engi-design-engine",
        "questions": [main_auto._present_question(q) for q in legacy.qlist(unresolved)],
        "conditional_questions": ([dict(_question_payload("gas_pressure"), depends_on="gas")]
                                    if discipline == "mechanical" else []),
        "inferred_answers": {key: str(value) for key, value in answers.items()
                             if isinstance(value, (str, int, float, bool))},
        "auto_summary": main_auto.auto_summary(auto, discipline),
        "panel_analysis": main_auto.panel_analysis_payload(auto),
    }


async def _run(job_id, workspace, name, discipline, occupancy, main_auto, legacy):
    try:
        result = await asyncio.to_thread(
            _analyze, workspace, name, discipline, occupancy, main_auto, legacy)
        _write(workspace / "state.json", {"status": "ready", "result": result, "finished_at": int(time.time())})
    except Exception as exc:
        _write(workspace / "state.json", {"status": "failed", "error": str(exc), "finished_at": int(time.time())})
    finally:
        _TASKS.pop(job_id, None)


def register_questionnaire_jobs(app, main_auto, legacy):
    @app.post("/internal/panel/questionnaire/start")
    async def start(request: Request, file: UploadFile = File(...), discipline: str = "mechanical", occupancy: str = ""):
        owner = session_user(request)
        _cleanup_expired_jobs()
        if discipline not in {"mechanical", "electrical"}:
            raise HTTPException(400, "Unknown discipline")
        name = Path(file.filename or "").name
        if Path(name).suffix.lower() not in {".zip", ".dxf"}:
            raise HTTPException(415, "Only ZIP or DXF is accepted")
        content = await file.read(50_000_001)
        if not content or len(content) > 50_000_000:
            raise HTTPException(413, "File is empty or larger than 50 MB")
        digest = hashlib.sha256(
            f"{owner}:{discipline}:{occupancy}".encode() + content).hexdigest()
        job_id = digest[:32]
        workspace = _root() / job_id
        workspace.mkdir(exist_ok=True)
        metadata = workspace / "metadata.json"
        state = workspace / "state.json"
        if metadata.exists():
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved.get("owner") != owner:
                raise HTTPException(404)
        else:
            (workspace / name).write_bytes(content)
            saved = {"owner": owner, "name": name, "discipline": discipline,
                     "occupancy": occupancy, "created_at": int(time.time())}
            _write(metadata, saved)
        current = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
        if current.get("status") not in {"ready"} and job_id not in _TASKS:
            _launch(job_id, workspace, saved, main_auto, legacy)
        if current.get("status") == "ready":
            return {**current, "job_id": job_id}
        return JSONResponse({"status": "processing", "job_id": job_id}, status_code=202)

    @app.get("/internal/panel/questionnaire/{job_id}")
    async def status(job_id: str, request: Request):
        owner = session_user(request)
        if not (len(job_id) == 32 and all(char in "0123456789abcdef" for char in job_id)):
            raise HTTPException(404)
        workspace = _root() / job_id
        metadata = workspace / "metadata.json"
        state = workspace / "state.json"
        if not metadata.exists() or not state.exists():
            raise HTTPException(404)
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        if saved.get("owner") != owner:
            raise HTTPException(404)
        payload = json.loads(state.read_text(encoding="utf-8"))
        # A deploy may restart the process while durable state says processing.
        # Resume from the private stored source instead of leaving the UI stuck.
        if payload.get("status") == "processing" and job_id not in _TASKS:
            _launch(job_id, workspace, saved, main_auto, legacy)
            payload = {"status": "processing", "started_at": int(time.time())}
        return JSONResponse(payload, status_code=202 if payload.get("status") == "processing" else 200)
