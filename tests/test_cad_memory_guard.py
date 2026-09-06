import ezdxf

from cad_engine.main import install_ezdxf_memory_guard


def test_memory_guard_wraps_ezdxf_readfile_once():
    install_ezdxf_memory_guard()
    first = ezdxf.readfile
    assert getattr(first, "_engitools_memory_guard", False) is True
    install_ezdxf_memory_guard()
    assert ezdxf.readfile is first
