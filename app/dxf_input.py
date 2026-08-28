from pathlib import Path

import ezdxf
from ezdxf import recover
from ezdxf.lldxf.const import DXFStructureError


def read_input_dxf(path: Path):
    """Read an architectural DXF, recovering only structurally damaged inputs.

    Output artifacts remain subject to the strict validator. Recovery is limited
    to uploaded source drawings and is accepted only when modelspace geometry is
    still present, preventing a truncated file from becoming an empty design.
    """
    source = Path(path)
    try:
        doc = ezdxf.readfile(source)
        return doc, {'recovered': False, 'errors': 0, 'fixes': 0}
    except DXFStructureError as strict_error:
        try:
            doc, auditor = recover.readfile(source)
        except Exception:
            raise strict_error

        entity_count = sum(1 for _ in doc.modelspace())
        if entity_count < 1:
            raise DXFStructureError(
                f'فایل DXF پس از بازیابی هیچ Entity قابل استفاده‌ای ندارد: {source.name}'
            ) from strict_error

        return doc, {
            'recovered': True,
            'errors': len(auditor.errors),
            'fixes': len(auditor.fixes),
            'original_error': str(strict_error),
        }
