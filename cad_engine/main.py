"""The only production CAD entrypoint.

History lives in Git. Transitional implementation modules remain internal until
their compatibility migration is complete; launchers must import only this path.
"""
import os

if os.getenv("CAD_ISOLATED_SERVICE", "").strip().lower() in {"1", "true", "yes"}:
    from .isolated_service import app
else:
    import ctypes
    import gc
    import ezdxf

    def install_ezdxf_memory_guard() -> None:
        current = ezdxf.readfile
        if getattr(current, "_engitools_memory_guard", False): return
        def guarded_readfile(*args, **kwargs):
            gc.collect()
            try: ctypes.CDLL(None).malloc_trim(0)
            except (AttributeError, OSError): pass
            return current(*args, **kwargs)
        guarded_readfile._engitools_memory_guard = True
        ezdxf.readfile = guarded_readfile

    install_ezdxf_memory_guard()
    from . import main_v15 as _base
    from .main_v18 import app
    from .build_identity import build_identity
    from .mechanical_release_contract_v19 import release_contract_status
    from .mechanical_authority_site_v19 import design_mechanical_authority_site
    from .runtime_core import design_dxf
    _base.design_mechanical_authority_site = design_mechanical_authority_site

    @app.get("/version")
    def version(): return build_identity()

    @app.get("/mechanical/status")
    def mechanical_status():
        status=release_contract_status();status["production_entrypoint"]="cad_engine.main:app";status["build"]=build_identity();return status
