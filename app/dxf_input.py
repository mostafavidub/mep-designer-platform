from pathlib import Path
import re
import tempfile

import ezdxf
from ezdxf import recover
from ezdxf.lldxf.const import DXFStructureError


_EOF_PATTERN = re.compile(rb'(?m)^[ \t]*0\r?\nEOF[ \t]*(?:\r?\n)?')
_ENDSEC_BEFORE_EOF_PATTERN = re.compile(
    rb'(?ms)^[ \t]*0\r?\nENDSEC[ \t]*\r?\n[ \t]*$'
)


def _last_eof(raw: bytes):
    matches = list(_EOF_PATTERN.finditer(raw))
    if not matches:
        raise DXFStructureError('missing EOF tag; safe ENDSEC repair is not possible')
    return matches[-1]


def _has_terminal_endsec(raw: bytes, eof) -> bool:
    # ENDSEC must be the final DXF tag immediately before EOF. Restrict the
    # search to a small tail window so an ENDSEC from an earlier section does
    # not produce a false positive.
    tail = raw[max(0, eof.start() - 256):eof.start()]
    return bool(_ENDSEC_BEFORE_EOF_PATTERN.search(tail))


def _entity_count(doc) -> int:
    return sum(1 for _ in doc.modelspace())


def _read_with_final_endsec(path: Path):
    raw = path.read_bytes()
    eof = _last_eof(raw)
    if _has_terminal_endsec(raw, eof):
        raise DXFStructureError(
            'terminal ENDSEC already exists; duplicate insertion is unsafe'
        )
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


def _recover_document(source: Path):
    doc, auditor = recover.readfile(source)
    if _entity_count(doc) < 1:
        raise DXFStructureError(
            f'فایل DXF پس از بازیابی هیچ Entity قابل استفاده‌ای ندارد: {source.name}'
        )
    return doc, auditor


def normalize_input_copy(path: Path):
    """Normalize only the extracted working copy; preserve the original upload."""
    source = Path(path)
    try:
        doc = ezdxf.readfile(source)
        return {'recovered': False, 'errors': 0, 'fixes': 0}
    except Exception as strict_error:
        raw = source.read_bytes()
        eof = _last_eof(raw)
        recovery_error = None

        # A parser may report "missing ENDSEC" for an earlier malformed section
        # even when the terminal ENDSEC is present. Recovery must run before any
        # byte-level repair; otherwise a duplicate ENDSEC corrupts a valid tail.
        try:
            doc, auditor = _recover_document(source)
            mode = 'ezdxf_recover_normalized'
        except Exception as exc:
            recovery_error = exc
            if _has_terminal_endsec(raw, eof):
                raise DXFStructureError(
                    f'ترمیم ساختار داخلی DXF ممکن نشد: {exc}'
                ) from strict_error
            doc = _read_with_final_endsec(source)
            if _entity_count(doc) < 1:
                raise DXFStructureError(
                    f'فایل DXF پس از ترمیم ENDSEC هیچ Entity قابل استفاده‌ای ندارد: {source.name}'
                )
            auditor = None
            mode = 'final_endsec_repair'

        candidate = source.with_name(source.name + '.repairing')
        try:
            # Re-serialize the recovered document so every subsequent analyzer
            # and the CAD engine receive one strict, canonical DXF structure.
            doc.saveas(candidate)
            verified = ezdxf.readfile(candidate)
            if _entity_count(verified) < 1:
                raise DXFStructureError(
                    f'فایل DXF نرمال‌شده هیچ Entity قابل استفاده‌ای ندارد: {source.name}'
                )
            candidate.replace(source)
        finally:
            candidate.unlink(missing_ok=True)

        return {
            'recovered': True,
            'mode': mode,
            'errors': len(auditor.errors) if auditor is not None else 1,
            'fixes': len(auditor.fixes) if auditor is not None else 1,
            'original_error': str(strict_error),
            'recovery_error': str(recovery_error) if recovery_error else '',
        }


def read_input_dxf(path: Path):
    """Read an architectural DXF without ever inserting duplicate section tags."""
    source = Path(path)
    try:
        doc = ezdxf.readfile(source)
        return doc, {'recovered': False, 'errors': 0, 'fixes': 0}
    except Exception as strict_error:
        recovery_error = None
        try:
            doc, auditor = _recover_document(source)
            return doc, {
                'recovered': True,
                'mode': 'ezdxf_recover',
                'errors': len(auditor.errors),
                'fixes': len(auditor.fixes),
                'original_error': str(strict_error),
            }
        except Exception as exc:
            recovery_error = exc

        raw = source.read_bytes()
        eof = _last_eof(raw)
        if _has_terminal_endsec(raw, eof):
            raise DXFStructureError(
                f'ترمیم ساختار داخلی DXF ممکن نشد: {recovery_error}'
            ) from strict_error

        try:
            doc = _read_with_final_endsec(source)
            if _entity_count(doc) < 1:
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
            raise DXFStructureError(
                f'ترمیم امن DXF ممکن نشد: {repair_error}; recovery: {recovery_error}'
            ) from strict_error
