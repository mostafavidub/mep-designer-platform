"""Opt-in internal shadow service. SELECT-only database access, no live imports."""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_EVEN
import json
import hashlib
import zipfile
import os
from pathlib import Path

from .commercial_measurement import digest, measure, number, verify_measurement, validate_measurement_accounting

SCHEMA = "planha-commercial-shadow-quote/1.0"
PRICING_RULE = "existing-max-minimum-metered/1.0"


def pricing_snapshot(row):
    if row is None:
        raise ValueError("CONFIGURED_SERVICE_PRICING_REQUIRED")
    data = {key:getattr(row,key) for key in ("id","discipline","enabled","price_per_m2","minimum_price")}
    updated = getattr(row,"updated_at",None)
    if updated is None: raise ValueError("PRICING_VERSION_REQUIRED")
    data["updated_at"] = updated.isoformat()
    for key in ("price_per_m2","minimum_price"):
        if number(data[key]) < 0: raise ValueError("INVALID_PRICING")
    data["pricing_identity"] = digest(data)
    return data


def shadow_quote(measurement, pricing, *, discipline, created_at, current_quote=None, current_area=None):
    validate_measurement_accounting(measurement)
    if pricing.get("discipline") != discipline or pricing.get("pricing_identity") != digest({k:v for k,v in pricing.items() if k!="pricing_identity"}):
        raise ValueError("PRICING_IDENTITY_MISMATCH")
    if not created_at: raise ValueError("TIMESTAMP_REQUIRED")
    for key in ("price_per_m2","minimum_price"):
        if number(pricing[key]) < 0: raise ValueError("INVALID_PRICING")
    area = measurement["totals"]["billable_area_m2"]
    ready = measurement["commercial_status"] == "AUTO_VERIFIED" and pricing.get("enabled") is True and area is not None
    amount = None
    if ready:
        # Match existing integer round semantics explicitly, without binary float money arithmetic.
        metered = (number(area)*number(pricing["price_per_m2"])).quantize(Decimal(1),rounding=ROUND_HALF_EVEN)
        amount = int(max(number(pricing["minimum_price"]),metered))
    current_quote = deepcopy(current_quote or {})
    result = {"schema":SCHEMA,"mode":"SHADOW","status":"PROPOSED" if ready else "BLOCKED",
        "binding":{"measurement_hash":measurement["measurement_hash"],
            "measurement_version":measurement["measurement_version"],"measurement_binding":measurement["binding"],
            "pricing_rule_version":PRICING_RULE,"pricing_identity":pricing["pricing_identity"],"discipline":discipline},
        "pricing":deepcopy(pricing),"billable_area_m2":area,"final_amount":amount,"created_at":created_at,
        "comparison":{"current_live_area_m2":current_area,"current_quote":current_quote,
            "area_delta_m2":float(number(area)-number(current_area)) if area is not None and current_area is not None else None,
            "amount_delta":amount-current_quote["amount"] if amount is not None and current_quote.get("amount") is not None else None,
            "reason":"Evidence-qualified gross measurement" if ready else "Commercial evidence or enabled pricing missing"},
        "live_quote_unchanged":True,"paid_records_immutable":True,"customer_activation_allowed":False,
        "release_qualification":measurement["release_qualification"]}
    result["shadow_quote_hash"] = digest(result)
    return result


def staleness(shadow, measurement, pricing):
    validate_measurement_accounting(measurement)
    if shadow.get("shadow_quote_hash") != digest({k:v for k,v in shadow.items() if k!="shadow_quote_hash"}):
        raise ValueError("SHADOW_INTEGRITY_FAILED")
    if pricing.get("pricing_identity") != digest({k:v for k,v in pricing.items() if k!="pricing_identity"}):
        raise ValueError("PRICING_IDENTITY_MISMATCH")
    old=shadow["binding"]
    stale = old["measurement_hash"] != measurement["measurement_hash"] or old["pricing_identity"] != pricing["pricing_identity"] or old["pricing_rule_version"] != PRICING_RULE
    return {"status":"STALE" if stale else "CURRENT", "regeneration_required":stale,
        "paid_record_action":"PRESERVE_IMMUTABLE", "post_payment_policy":"SEPARATE_ADJUSTMENT_REQUIRED"}


def current_upload_sources(project_directory, project_id):
    directory=Path(project_directory)
    if directory.name != str(project_id):
        raise ValueError("PROJECT_DIRECTORY_BINDING_REQUIRED")
    archive=directory/'architecture.zip'; drawing=directory/'architecture.dxf'
    hashes=[]
    if archive.is_file():
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                path=Path(member.filename)
                if path.suffix.lower()=='.dxf' and '__MACOSX' not in path.parts and not path.name.startswith('._'):
                    with source.open(member) as stream:
                        hashes.append(hashlib.file_digest(stream,'sha256').hexdigest())
    elif drawing.is_file():
        with drawing.open('rb') as stream:
            hashes.append(hashlib.file_digest(stream,'sha256').hexdigest())
    if not hashes: raise ValueError("CURRENT_UPLOAD_REQUIRED")
    if len(set(hashes))!=len(hashes): raise ValueError("DUPLICATE_SOURCE")
    return sorted(hashes)


def run_internal_shadow(project, db, commercial, *, bundles, project_directory, answers=(), created_at):
    """Read actual ServicePricing WITHOUT service_pricing()/quote_for() write-on-read.

    Caller owns transaction, authenticates internal operator, resolves current source
    identities from stored uploads. No route or background/live pricing registration.
    """
    current_sources=current_upload_sources(project_directory,project.id)
    stored_models=[item.get("canonical_architecture_model") or {} for item in (project.analysis or {}).get("files",[])]
    stored_sources=sorted((model.get("source") or {}).get("source_sha256") or "" for model in stored_models)
    if stored_sources != current_sources:
        raise ValueError("STALE_PROJECT_ANALYSIS")
    supplied={b["legacy"]["source"]["source_sha256"]:b["legacy"] for b in bundles}
    from cad_engine.architecture_contract import content_hash, legacy_semantic_projection
    if any(content_hash(legacy_semantic_projection(m))!=content_hash(legacy_semantic_projection(supplied.get(m["source"]["source_sha256"],{}))) for m in stored_models):
        raise ValueError("PROJECT_MODEL_BINDING_MISMATCH")
    discipline = (project.answers or {}).get("discipline",(project.analysis or {}).get("discipline","mechanical"))
    with db.no_autoflush:
        pricing_row=db.query(commercial["ServicePricing"]).filter(commercial["ServicePricing"].discipline==discipline).first()
        quote=db.query(commercial["ProjectQuote"]).filter(commercial["ProjectQuote"].project_id==project.id).first()
        pricing=pricing_snapshot(pricing_row)
        measurement=measure(project.id,bundles,current_sources=current_sources,answers=answers)
        current={"id":quote.id,"amount":quote.amount,"paid":quote.paid,"currency":quote.currency} if quote else {}
        shadow=shadow_quote(measurement,pricing,discipline=discipline,created_at=created_at,current_quote=current,
            current_area=commercial["project_area_m2"](project))
    return {"measurement":measurement,"shadow_quote":shadow}


def persist_shadow(directory, artifact):
    """Immutable private sidecar; explicit operator-selected storage, no Project writes.

    Content addressing makes repeated identical writes idempotent. Permissions are
    restrictive; no customer DXF/geometry is copied, only evidence references.
    """
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=digest(artifact); path=directory/(key+".json")
    payload=json.dumps(artifact,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+"\n"
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if path.read_text()!=payload: raise ValueError("IMMUTABLE_ARTIFACT_COLLISION")
        return path
    with os.fdopen(fd,"w") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    return path
