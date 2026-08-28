from pathlib import Path
import re
import tempfile

import ezdxf
from ezdxf import recover
from ezdxf.lldxf.const import DXFStructureError


def _read_with_final_endsec(path: Path):
    raw = path.read_bytes()
    matches = list(re.finditer(rb'(?m)^[ \t]*0\r?\nEOF[ \t]*(?:\r?\n)?', raw))
    if not matches:
        raise DXFStructureError('missing EOF tag; safe ENDSEC repair is not possible')
    eof = matches[-1]
    newline = b'\r\n' if b'\r\n' in raw[max(0, eof.start() - 100):eof.end()] else b'\n'
    repaired = raw[:eof.start()] + b'  0' + newline + b'ENDSEC' + newline + raw[eof.start():]
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as temp:
            temp.write(repaired)
            temp_name = temp.name
        return ezdxf.readfile(temp_name)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


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
        if 'ENDSEC' in str(strict_error).upper():
            try:
                doc = _read_with_final_endsec(source)
                entity_count = sum(1 for _ in doc.modelspace())
                if entity_count < 1:
                    raise DXFStructureError(
                        f'فایل DXF پس از ترمیم ENDSEC هیچ Entity قابل استفاده‌ای ندارد: {source.name}'
                    )
                return doc, {
                    'recovered': True,
                    'mode': 'final_endsec_repair',
                    'errors': 1,
                    'fixes': 1,
                    'original_error': str(strict_error),
                }
            except Exception as repair_error:
                raise DXFStructureError(f'ENDSEC repair failed: {repair_error}') from strict_error
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
            'mode': 'ezdxf_recover',
            'errors': len(auditor.errors),
            'fixes': len(auditor.fixes),
            'original_error': str(strict_error),
        }
