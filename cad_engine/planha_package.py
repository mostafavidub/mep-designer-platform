"""Deterministic, non-production `.planha` package prototype."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import zipfile

from .architecture_contract import SCHEMA as ARCHITECTURE_SCHEMA, canonical_json, content_hash
from .architecture_snapshot import SNAPSHOT_SCHEMA


PACKAGE_SCHEMA = "planha-package-manifest/1.0"
PACKAGE_FILES = ("architecture.json", "review.json", "snapshot.json", "validation.json")
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _bytes(value):
    return canonical_json(value).encode("utf-8")


def pack_planha(*, architecture, snapshot, validation, review=None):
    """Return deterministic bytes. Raw source embedding is deliberately unsupported."""
    payloads = {"architecture.json": _bytes(architecture),
                "review.json": _bytes(review or {}),
                "snapshot.json": _bytes(snapshot),
                "validation.json": _bytes(validation)}
    manifest = {"schema": PACKAGE_SCHEMA, "package_status": "EXPERIMENTAL_INTERNAL",
                "source_embedding": "REFERENCE_BY_SHA256_ONLY",
                "source_sha256": architecture.get("source", {}).get("source_sha256"),
                "canonical_schema": architecture.get("schema"),
                "snapshot_schema": snapshot.get("schema"),
                "snapshot_id": snapshot.get("snapshot_id"),
                "files": {name: {"sha256": content_hash(json.loads(data.decode("utf-8"))),
                                  "size": len(data)}
                          for name, data in sorted(payloads.items())}}
    payloads["manifest.json"] = _bytes(manifest)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(payloads):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payloads[name])
    return output.getvalue()


def unpack_planha(package_bytes):
    try:
        with zipfile.ZipFile(BytesIO(package_bytes), "r") as archive:
            names = set(archive.namelist())
            expected = set(PACKAGE_FILES) | {"manifest.json"}
            if names != expected:
                raise ValueError("PLANHA_PACKAGE_FILE_SET_INVALID")
            documents = {name: json.loads(archive.read(name).decode("utf-8")) for name in expected}
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("PLANHA_PACKAGE_CORRUPT") from exc
    manifest = documents.pop("manifest.json")
    if manifest.get("schema") != PACKAGE_SCHEMA:
        raise ValueError("PLANHA_PACKAGE_SCHEMA_MISMATCH")
    if documents["architecture.json"].get("schema") != ARCHITECTURE_SCHEMA:
        raise ValueError("PLANHA_ARCHITECTURE_SCHEMA_MISMATCH")
    if documents["snapshot.json"].get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("PLANHA_SNAPSHOT_SCHEMA_MISMATCH")
    for name, document in documents.items():
        expected_hash = (manifest.get("files", {}).get(name) or {}).get("sha256")
        if expected_hash != content_hash(document):
            raise ValueError("PLANHA_PACKAGE_HASH_MISMATCH:%s" % name)
    if manifest.get("source_sha256") != documents["architecture.json"].get("source", {}).get("source_sha256"):
        raise ValueError("PLANHA_PACKAGE_SOURCE_IDENTITY_MISMATCH")
    return {"manifest": deepcopy(manifest),
            "architecture": documents["architecture.json"],
            "review": documents["review.json"],
            "snapshot": documents["snapshot.json"],
            "validation": documents["validation.json"]}
