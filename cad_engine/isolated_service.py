"""Low-memory production HTTP shell for isolated CAD transactions."""
from __future__ import annotations
import asyncio,json,os,subprocess,sys,tempfile
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from .build_identity import build_identity
from .version_manifest import CAD_API_VERSION,MECHANICAL_PIPELINE_VERSION,active_version_manifest

app=FastAPI(title="EngiTools CAD Designer",version=CAD_API_VERSION)
_design_lock=asyncio.Lock()

@app.get("/health")
def health():
    return {"ok":True,"service":"cad-designer","version":CAD_API_VERSION,"mechanical_pipeline_version":MECHANICAL_PIPELINE_VERSION,"mechanical_mode":"authority-project-driven","electrical_mode":"authority-project-driven"}

@app.get("/version")
def version(): return active_version_manifest()

@app.get("/mechanical/status")
def mechanical_status():
    from .mechanical_release_contract_v19 import release_contract_status
    status=release_contract_status();status["production_entrypoint"]="cad_engine.main:app";status["build"]=build_identity();return status

@app.get("/electrical/status")
def electrical_status():
    # Keep the Electrical engineering stack out of the long-lived parent. The
    # status adapter itself performs its heavier imports lazily on demand.
    from .electrical_api import electrical_status_payload
    return electrical_status_payload()


def _run_worker(payload:dict,operation:str="design")->tuple[int,dict]:
    with tempfile.TemporaryDirectory(prefix="engitools-isolated-request-") as td:
        request_path=Path(td)/"request.json";response_path=Path(td)/"response.json"
        request_path.write_text(json.dumps({"operation":operation,"payload":payload},ensure_ascii=False),encoding="utf-8")
        env=dict(os.environ);env.pop("CAD_ISOLATED_SERVICE",None)
        completed=subprocess.run([sys.executable,"-m","cad_engine.isolated_worker",str(request_path),str(response_path)],env=env,timeout=900,check=False)
        if not response_path.is_file(): return 503,{"detail":{"message":"CAD worker stopped before returning a result","code":"CAD_WORKER_TERMINATED","exit_code":completed.returncode}}
        envelope=json.loads(response_path.read_text(encoding="utf-8"));return int(envelope.get("status_code",500)),envelope.get("body") or {}


async def _isolated_design(request:Request,operation:str):
    try: payload=await request.json()
    except Exception: return JSONResponse(status_code=400,content={"detail":"invalid JSON body"})
    async with _design_lock:
        try: status_code,body=await asyncio.to_thread(_run_worker,payload,operation)
        except subprocess.TimeoutExpired: status_code,body=504,{"detail":{"message":"CAD worker timed out","code":"CAD_WORKER_TIMEOUT"}}
        except Exception as exc: status_code,body=500,{"detail":{"message":"CAD worker failed","code":"CAD_WORKER_FAILURE","error":str(exc)}}
    return JSONResponse(status_code=status_code,content=body)


@app.post("/design")
async def design(request:Request):
    return await _isolated_design(request,"design")


@app.post("/design-electrical")
async def design_electrical(request:Request):
    return await _isolated_design(request,"design-electrical")
