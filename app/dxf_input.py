from pathlib import Path
import re
import tempfile

import ezdxf
from ezdxf import recover
from ezdxf.lldxf.const import DXFStructureError


_TAG_ZERO = re.compile(rb"^[ \t]*0[ \t]*$")


def _entity_count(doc) -> int:
    return sum(1 for _ in doc.modelspace())


def _structural_tags(raw: bytes):
    """Read group-code 0 structure with CRLF/LF and indented values."""
    lines = raw.splitlines()
    tags = []
    for index in range(len(lines) - 1):
        if _TAG_ZERO.match(lines[index]):
            value = lines[index + 1].strip().upper()
            if value in {b"SECTION", b"ENDSEC", b"EOF"}:
                tags.append(value)
    return tags


def _tail_repair_candidates(raw: bytes):
    """Yield repairs at the semantic section boundary, never blindly at EOF."""
    if not raw or raw.count(b"\x00") > max(8, len(raw) // 100):
        raise DXFStructureError("unsupported binary or empty DXF input")

    newline = b"\r\n" if raw.count(b"\r\n") > raw.count(b"\n") // 2 else b"\n"
    event_pattern = re.compile(
        rb"(?im)^[ \t]*0[ \t]*\r?\n[ \t]*(SECTION|ENDSEC|EOF)[ \t]*(?:\r?\n)?"
    )
    events = list(event_pattern.finditer(raw))
    depth = 0
    yielded_offsets = set()

    # A SECTION encountered while another section is still open pinpoints the
    # missing ENDSEC: insert it immediately before the new SECTION.
    for event in events:
        value = event.group(1).upper()
        if value == b"SECTION":
            if depth == 1 and event.start() not in yielded_offsets:
                yielded_offsets.add(event.start())
                yield (
                    raw[:event.start()] + b"  0" + newline + b"ENDSEC" + newline +
                    raw[event.start():],
                    "inter_section_endsec_repair",
                )
            depth += 1
        elif value == b"ENDSEC":
            depth = max(0, depth - 1)
        elif value == b"EOF":
            if depth == 1 and event.start() not in yielded_offsets:
                yielded_offsets.add(event.start())
                yield (
                    raw[:event.start()] + b"  0" + newline + b"ENDSEC" + newline +
                    raw[event.start():],
                    "final_endsec_repair",
                )
            return

    # Interrupted exports may omit EOF while all entity bytes remain intact.
    if depth not in (0, 1):
        raise DXFStructureError(f"unsafe DXF section depth: {depth}")
    base = raw.rstrip(b"\r\n") + newline
    if depth == 1:
        yield (base + b"  0" + newline + b"ENDSEC" + newline +
               b"  0" + newline + b"EOF" + newline, "truncated_tail_repair")
    else:
        yield base + b"  0" + newline + b"EOF" + newline, "missing_eof_repair"


def _read_candidate(raw: bytes):
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as temp:
            temp.write(raw)
            temp_name = temp.name
        try:
            return ezdxf.readfile(temp_name), None
        except Exception:
            return recover.readfile(temp_name)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def _recover_document(source: Path):
    doc, auditor = recover.readfile(source)
    if _entity_count(doc) < 1:
        raise DXFStructureError(
            f"فایل DXF پس از بازیابی هیچ Entity قابل استفاده‌ای ندارد: {source.name}"
        )
    return doc, auditor


def _read_repaired_tail(source: Path):
    errors = []
    for repaired, mode in _tail_repair_candidates(source.read_bytes()):
        try:
            doc, auditor = _read_candidate(repaired)
            if _entity_count(doc) < 1:
                raise DXFStructureError("repaired DXF has no usable entities")
            return doc, auditor, mode
        except Exception as exc:
            errors.append(str(exc))
    raise DXFStructureError("DXF tail repair failed: " + "; ".join(errors))


def normalize_input_copy(path: Path):
    """Validate the extracted working copy while preserving the upload."""
    source = Path(path)
    try:
        ezdxf.readfile(source)
        return {"recovered": False, "errors": 0, "fixes": 0}
    except Exception as strict_error:
        try:
            doc, auditor = _recover_document(source)
            mode = "ezdxf_recover_normalized"
        except Exception as recovery_error:
            try:
                doc, auditor, mode = _read_repaired_tail(source)
            except Exception as repair_error:
                raise DXFStructureError(
                    f"DXF parse failed: strict={strict_error}; "
                    f"recovery={recovery_error}; repair={repair_error}"
                ) from strict_error
        # Persist the normalized extracted working copy for strict downstream readers.
        # The user's original upload remains untouched.
        doc.saveas(source)
        return {
            "recovered": True,
            "mode": mode,
            "errors": len(auditor.errors) if auditor is not None else 1,
            "fixes": len(auditor.fixes) if auditor is not None else 1,
            "original_error": str(strict_error),
        }


def read_input_dxf(path: Path):
    """Read uploaded DXF, recovering intact geometry from malformed tails."""
    source = Path(path)
    try:
        doc = ezdxf.readfile(source)
        return doc, {"recovered": False, "errors": 0, "fixes": 0}
    except Exception as strict_error:
        recovery_error = None
        try:
            doc, auditor = _recover_document(source)
            return doc, {
                "recovered": True, "mode": "ezdxf_recover",
                "errors": len(auditor.errors), "fixes": len(auditor.fixes),
                "original_error": str(strict_error),
            }
        except Exception as exc:
            recovery_error = exc

        try:
            doc, auditor, mode = _read_repaired_tail(source)
            return doc, {
                "recovered": True, "mode": mode,
                "errors": len(auditor.errors) if auditor is not None else 1,
                "fixes": len(auditor.fixes) if auditor is not None else 1,
                "original_error": str(strict_error),
                "recovery_error": str(recovery_error),
            }
        except Exception as repair_error:
            raise DXFStructureError(
                f"ترمیم امن DXF ممکن نشد: {repair_error}; recovery: {recovery_error}"
            ) from strict_error
