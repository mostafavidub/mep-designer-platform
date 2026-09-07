"""One-shot CAD worker invoked by the low-memory production service."""
from __future__ import annotations
import json,sys
from pathlib import Path
from fastapi import HTTPException

def main(request_path:str,response_path:str)->int:
    from .main import install_ezdxf_memory_guard
    from . import main_v15 as base
    from .mechanical_authority_site_v19 import design_mechanical_authority_site
    from .runtime_core import DesignRequest
    install_ezdxf_memory_guard();base.design_mechanical_authority_site=design_mechanical_authority_site
    payload=json.loads(Path(request_path).read_text(encoding="utf-8"))
    try: envelope={"status_code":200,"body":base.design(DesignRequest(**payload))}
    except HTTPException as exc: envelope={"status_code":exc.status_code,"body":{"detail":exc.detail}}
    except Exception as exc: envelope={"status_code":500,"body":{"detail":{"message":"CAD worker failed","code":"CAD_WORKER_FAILURE","error":str(exc)}}}
    Path(response_path).write_text(json.dumps(envelope,ensure_ascii=False),encoding="utf-8");return 0

if __name__=="__main__": raise SystemExit(main(sys.argv[1],sys.argv[2]))
