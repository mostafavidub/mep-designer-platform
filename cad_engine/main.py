"""The only production CAD entrypoint.

History lives in Git. Production-facing mechanical imports and routes are
unversioned; historical implementation modules are compatibility debt only and
must never be configured as deployment entrypoints.
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
        if getattr(current, "_engitools_memory_guard", False):
            return
        def guarded_readfile(*args, **kwargs):
            gc.collect()
            try:
                ctypes.CDLL(None).malloc_trim(0)
            except (AttributeError, OSError):
                pass
            return current(*args, **kwargs)
        guarded_readfile._engitools_memory_guard = True
        ezdxf.readfile = guarded_readfile

    install_ezdxf_memory_guard()

    # The web/API transport is transitional compatibility code. Mechanical
    # engineering authority is injected only from the canonical unversioned
    # surface below. No versioned mechanical route is exposed here.
    from . import main_v15 as _cad_transport
    from .main_v18 import app
    from .build_identity import build_identity
    from .mechanical_release_contract import release_contract_status
    from .mechanical_authority import design_mechanical_authority_site
    from .runtime_core import design_dxf

    _cad_transport.design_mechanical_authority_site = design_mechanical_authority_site

    @app.get("/version")
    def version():
        return build_identity()

    @app.get("/mechanical/status")
    def mechanical_status():
        status = release_contract_status()
        status.pop("version", None)
        status.pop("release_version", None)
        status["runtime_identity"] = "mechanical"
        status["production_entrypoint"] = "cad_engine.main:app"
        status["build"] = build_identity()
        return status
