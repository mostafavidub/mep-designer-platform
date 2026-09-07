"""One-shot CAD worker invoked by the low-memory production service."""
from __future__ import annotations
import ctypes,gc,json,sys
from pathlib import Path
from fastapi import HTTPException


def _install_ezdxf_memory_guard() -> None:
    """Install the canonical pre-read memory trim without importing main.py.

    Importing the non-isolated canonical app would eagerly load the Mechanical
    stack before an Electrical transaction. The disposable worker needs only
    the same ezdxf guard, then it can lazily load the requested discipline.
    """
    import ezdxf
    current=ezdxf.readfile
    if getattr(current,"_engitools_memory_guard",False): return
    def guarded_readfile(*args,**kwargs):
        gc.collect()
        try: ctypes.CDLL(None).malloc_trim(0)
        except (AttributeError,OSError): pass
        return current(*args,**kwargs)
    guarded_readfile._engitools_memory_guard=True
    ezdxf.readfile=guarded_readfile


def main(request_path:str,response_path:str)->int:
    from .runtime_core import DesignRequest

    _install_ezdxf_memory_guard()
    request_data=json.loads(Path(request_path).read_text(encoding="utf-8"))
    # Accept the legacy raw-payload shape for local/backward compatibility while
    # the isolated shell uses an explicit operation envelope.
    if isinstance(request_data,dict) and "operation" in request_data and "payload" in request_data:
        operation=str(request_data.get("operation") or "design")
        payload=request_data.get("payload") or {}
    else:
        operation="design"
        payload=request_data

    try:
        req=DesignRequest(**payload)
        if operation == "design-electrical":
            from .electrical_api import design_electrical_request
            body=design_electrical_request(req)
        elif operation == "design":
            from . import main_v15 as base
            from .mechanical_authority_site_v19 import design_mechanical_authority_site
            base.design_mechanical_authority_site=design_mechanical_authority_site
            body=base.design(req)
        else:
            envelope={"status_code":400,"body":{"detail":{"message":"Unknown CAD worker operation","code":"CAD_WORKER_OPERATION_INVALID","operation":operation}}}
            Path(response_path).write_text(json.dumps(envelope,ensure_ascii=False),encoding="utf-8")
            return 0
        envelope={"status_code":200,"body":body}
    except HTTPException as exc:
        envelope={"status_code":exc.status_code,"body":{"detail":exc.detail}}
    except Exception as exc:
        envelope={"status_code":500,"body":{"detail":{"message":"CAD worker failed","code":"CAD_WORKER_FAILURE","error":str(exc)}}}
    Path(response_path).write_text(json.dumps(envelope,ensure_ascii=False),encoding="utf-8");return 0


if __name__=="__main__": raise SystemExit(main(sys.argv[1],sys.argv[2]))
