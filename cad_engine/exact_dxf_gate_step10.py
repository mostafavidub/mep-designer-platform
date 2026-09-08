"""Step 10 — exact DXF reopen, audit and read-only release health gate.

The release candidate is treated as immutable evidence. This validator reopens
the exact path, audits it without repair/save, proves the file hash is unchanged,
and reopens it a second time before the transactional release adapter may return
success.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import ezdxf

VERSION = "exact-dxf-step10/1"


def _digest(path: Path) -> str:
    h=sha256()
    with path.open("rb") as fh:
        while True:
            chunk=fh.read(1024*1024)
            if not chunk: break
            h.update(chunk)
    return h.hexdigest()


def validate_exact_dxf_health(path: Path | str) -> dict[str,Any]:
    path=Path(path); errors=[]
    base={
        "version":VERSION,
        "path":str(path),
        "errors":errors,
        "first_reopen":False,
        "second_reopen":False,
        "audit_error_count":None,
        "entity_count":None,
        "read_only_hash_preserved":False,
        "policy":"NO_REPAIR_NO_AUDIT_ERROR_TRANSACTIONAL_RELEASE",
    }
    if not path.exists() or not path.is_file():
        errors.append("generated_dxf_missing")
        return {**base,"status":"FAIL","file_size":0,"sha256":None}
    try:
        size=path.stat().st_size
    except Exception as exc:
        errors.append(f"generated_dxf_stat_failed:{type(exc).__name__}:{exc}")
        return {**base,"status":"FAIL","file_size":None,"sha256":None}
    if size<=0:
        errors.append("generated_dxf_empty")
        return {**base,"status":"FAIL","file_size":size,"sha256":None}
    try:
        before=_digest(path)
    except Exception as exc:
        errors.append(f"generated_dxf_hash_failed:{type(exc).__name__}:{exc}")
        return {**base,"status":"FAIL","file_size":size,"sha256":None}

    try:
        doc=ezdxf.readfile(path)
        base["first_reopen"]=True
        msp=doc.modelspace()
        entity_count=sum(1 for _ in msp)
        base["entity_count"]=entity_count
        if entity_count<=0:
            errors.append("generated_dxf_modelspace_empty")
        auditor=doc.audit()
        audit_errors=len(auditor.errors)
        base["audit_error_count"]=audit_errors
        if audit_errors:
            errors.append(f"dxf_audit_errors:{audit_errors}")
    except Exception as exc:
        errors.append(f"exact_dxf_reopen_failed:{type(exc).__name__}:{exc}")
        return {**base,"status":"FAIL","file_size":size,"sha256":before}

    try:
        after=_digest(path)
        base["read_only_hash_preserved"]=(before==after)
        if before!=after:
            errors.append("exact_dxf_gate_mutated_file")
    except Exception as exc:
        errors.append(f"generated_dxf_postaudit_hash_failed:{type(exc).__name__}:{exc}")
        after=None

    try:
        reopened=ezdxf.readfile(path)
        _=reopened.modelspace()
        base["second_reopen"]=True
    except Exception as exc:
        errors.append(f"exact_dxf_second_reopen_failed:{type(exc).__name__}:{exc}")

    return {
        **base,
        "status":"PASS" if not errors else "FAIL",
        "file_size":size,
        "sha256":before,
        "post_audit_sha256":after,
    }
