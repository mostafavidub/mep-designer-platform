"""Read-only commercial projection of bound Architecture evidence.

No DXF parsing, recognition, customer quote writes, or provider calls. Review
may qualify existing interpretation; it cannot supply geometry or numeric area.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from cad_engine.architecture_contract import (SCHEMA as ARCH_SCHEMA,
    canonical_model_hash, content_hash, legacy_semantic_projection)
from cad_engine.build_identity import build_identity
from cad_engine.architecture_validator import validate_architecture
from cad_engine.architecture_separator_validator import separator_errors

SCHEMA = "planha-commercial-measurement/1.0"
VERSION = "1.0.0"
RULE_VERSION = "commercial-gross/1.0"
BILLABLE = frozenset({"BASEMENT", "PARKING", "GROUND", "ORDINARY_FLOOR",
    "MEZZANINE", "TYPICAL_FLOOR", "BALCONY", "TERRACE", "OTHER_BUILDING_FLOOR"})
EXCLUDED = frozenset({"ROOF", "YARD", "SITE"})
NON_LEVEL = frozenset({"SECTION", "ELEVATION", "DETAIL", "REFERENCE_ONLY"})
STATUSES = ("AUTO_VERIFIED", "QUICK_CONFIRMATION_REQUIRED", "INPUT_REQUIRED", "CONFLICT")
RULES = {"version": RULE_VERSION, "billable": sorted(BILLABLE),
         "excluded": sorted(EXCLUDED), "non_levels": sorted(NON_LEVEL),
         "numeric_acceptance": "EXACT_DECIMAL_ONLY_PENDING_HUMAN_GOLDEN",
         "engineering_exclusion": False, "live_activation": False}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("FINITE_NUMBER_REQUIRED")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("FINITE_NUMBER_REQUIRED") from exc
    if not result.is_finite():
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return result


def numeric(value):
    return float(value) if value is not None else None


def status(issues):
    return max((i["status"] for i in issues), key=STATUSES.index, default="AUTO_VERIFIED")


def _ring_area(ring):
    points = [(number(p[0]), number(p[1])) for p in ring]
    if len(points) < 4 or points[0] != points[-1]:
        raise ValueError("CLOSED_RING_REQUIRED")
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points, points[1:]))) / 2


def geometry(envelope):
    """Use every existing component, retain gross internal shafts/stairs/voids.

    Interior holes need separate scope evidence, so they block qualification;
    never silently subtract them as unrecognized rooms or as courtyard space.
    """
    components = envelope.get("components") or [{"outer_ring": envelope.get("outer_ring")}]
    polygons, area = [], Decimal(0)
    for component in components:
        ring = component.get("outer_ring") or []
        a = _ring_area(ring)
        poly = Polygon(ring)
        if not poly.is_valid or poly.is_empty or a <= 0:
            raise ValueError("INVALID_GROSS_GEOMETRY")
        polygons.append(poly); area += a
    for index, left in enumerate(polygons):
        if any(left.intersection(right).area > 0 for right in polygons[index+1:]):
            raise ValueError("OVERLAPPING_GROSS_COMPONENTS")
    return unary_union(polygons), area


def _source_binding(bundle):
    canonical, legacy = bundle["canonical"], bundle["legacy"]
    sha = (canonical.get("source") or {}).get("source_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("SOURCE_IDENTITY_REQUIRED")
    if canonical.get("schema") != ARCH_SCHEMA:
        raise ValueError("CURRENT_ARCHITECTURE_SCHEMA_REQUIRED")
    if sha != (legacy.get("source") or {}).get("source_sha256"):
        raise ValueError("SOURCE_MISMATCH")
    if canonical.get("canonical_model_hash") != canonical_model_hash(canonical):
        raise ValueError("ARCHITECTURE_HASH_MISMATCH")
    if (canonical.get("traceability") or {}).get("legacy_model_hash") != content_hash(legacy_semantic_projection(legacy)):
        raise ValueError("ARCHITECTURE_EVIDENCE_MISMATCH")
    return {"source_sha256": sha, "canonical_model_hash": canonical["canonical_model_hash"],
            "legacy_model_hash": content_hash(legacy_semantic_projection(legacy)),
            # Includes calibration/reconciliation evidence not currently in the semantic projection.
            "commercial_evidence_hash": digest({k: legacy.get(k) for k in
                ("source", "building_envelopes", "plan_regions", "dimensions", "dimension_reconciliation")})}


def binding(project_id, bundles, current_sources, engine):
    if not str(project_id).strip() or not bundles:
        raise ValueError("PROJECT_AND_SOURCES_REQUIRED")
    records = sorted((_source_binding(b) for b in bundles), key=lambda r:r["source_sha256"])
    shas = [r["source_sha256"] for r in records]
    if len(set(shas)) != len(shas):
        raise ValueError("DUPLICATE_SOURCE")
    if sorted(current_sources) != shas:
        raise ValueError("STALE_OR_INCOMPLETE_SOURCE_SET")
    return {"project_id": str(project_id), "sources": records, "build_identity": engine,
            "measurement_version": VERSION, "rules_hash": digest(RULES)}


def question(scope, object_id, fact, choices, prompt, evidence):
    q = {"object_id": object_id, "fact": fact, "choices": deepcopy(choices),
         "prompt_fa": prompt, "evidence": deepcopy(evidence), "binding_hash": digest(scope)}
    q["question_id"] = "CM-" + digest(q)[:24]
    q["question_fingerprint"] = digest(q)
    return q


def _answer_map(questions, answers):
    available = {q["question_id"]: q for q in questions}
    accepted = {}
    for answer in answers or []:
        if set(answer) != {"question_id", "question_fingerprint", "value", "reviewer", "reviewed_at"}:
            raise ValueError("INVALID_REVIEW_FIELDS")
        q = available.get(answer["question_id"])
        if not q or q["question_fingerprint"] != answer["question_fingerprint"]:
            raise ValueError("STALE_REVIEW")
        if answer["value"] not in q["choices"] or not answer["reviewer"] or not answer["reviewed_at"]:
            raise ValueError("INVALID_BOUNDED_ANSWER")
        if q["question_id"] in accepted and accepted[q["question_id"]] != answer:
            raise ValueError("CONFLICTING_REVIEW_REPLAY")
        accepted[q["question_id"]] = deepcopy(answer)
    return accepted


def _title_type(frame):
    evidence = frame.get("title_evidence") or {}
    raw = evidence.get("raw_text") or []
    text = " ".join(raw) if isinstance(raw, list) else str(raw)
    if not evidence.get("source_handles") or evidence.get("provenance") != "DXF_TEXT_WITHIN_FRAME":
        return "UNKNOWN"
    patterns = (("SECTION", r"\bsection\b|برش|مقطع"), ("ELEVATION", r"\belevation\b|^نما"),
        ("DETAIL", r"\bdetail\b|جزئیات|دیتیل"), ("REFERENCE_ONLY", r"title\s*block|کادر اطلاعات"),
        ("ROOF", r"\broof\b|بام"), ("YARD", r"\byard\b|حیاط"), ("SITE", r"\bsite\b|سایت"),
        ("BASEMENT", r"\bbasement\b|زیرزمین"), ("PARKING", r"\bparking\b|پارکینگ"),
        ("MEZZANINE", r"\bmezzanine\b|نیم[ ‌]طبقه"), ("BALCONY", r"\bbalcony\b|بالکن"),
        ("TERRACE", r"\bterrace\b|تراس"), ("GROUND", r"\bground\b|همکف"))
    hits = [kind for kind, pattern in patterns if re.search(pattern, text, re.I)]
    if re.search(r"خرپشته|roof headroom",text,re.I):
        return "UNKNOWN"  # Billable enclosed rooftop storey vs excluded roof requires bounded classification.
    if len(hits) == 1:
        return hits[0]
    if hits:
        return "UNKNOWN"  # e.g. roof view also showing yard cannot exclude whole frame.
    if frame.get("represented_level_ids") and re.search(r"طبقه|طبقات|\bfloors?\b|\blevels?\b", text, re.I):
        return "TYPICAL_FLOOR" if len(frame["represented_level_ids"]) > 1 else "ORDINARY_FLOOR"
    return "UNKNOWN"


def _explicit_typical(frame, represented):
    from cad_engine.plan_segmentation import _levels
    raw = (frame.get("title_evidence") or {}).get("raw_text") or []
    text = " ".join(raw) if isinstance(raw,list) else str(raw)
    parsed = _levels(text)
    if len(parsed)>1 and sorted(parsed)==represented:
        return True
    match = re.search(r"(?:floors?|levels?)\s+(\d+)\s*(?:to|[-–])\s*(\d+)",text,re.I)
    if not match:
        return False
    first,last=map(int,match.groups())
    numbers=[]
    for level in represented:
        number_match=re.fullmatch(r"(?:LEVEL-|L)(\d+)",level)
        if not number_match: return False
        numbers.append(int(number_match.group(1)))
    return first<=last and sorted(numbers)==list(range(first,last+1))


def _questions(scope, bundles):
    questions = [question(scope,scope["project_id"],"inventory_complete",["CONFIRMED","INCOMPLETE","UNKNOWN"],
        "آیا فهرست فعلی تمام پلان‌های طبقات، زیرزمین، پارکینگ، نیم‌طبقه، بالکن/تراس، بام و سایتِ این پروژه را پوشش می‌دهد؟ اگر پلانی جا افتاده یا فایل دیگری لازم است، ناقص را انتخاب کنید.",
        {"sources":scope["sources"],"frame_inventory":[{"source_sha256":b["canonical"]["source"]["source_sha256"],
            "frames":[{"frame_id":f["frame_id"],"title_evidence":f.get("title_evidence")} for f in b["canonical"].get("frames",[])]} for b in bundles]})]
    # Membership choices reference existing source/frame IDs, not inferred buildings.
    refs = sorted(b["canonical"]["source"]["source_sha256"] + ":" + f["frame_id"]
                  for b in bundles for f in b["canonical"].get("frames", []))
    for b in bundles:
        sha = b["canonical"]["source"]["source_sha256"]
        envs = {e["frame_id"]: e for e in b["legacy"].get("building_envelopes", [])}
        for f in b["canonical"].get("frames", []):
            ref = sha + ":" + f["frame_id"]
            ev = {"frame_id": f["frame_id"], "source_sha256": sha,
                  "title_evidence": f.get("title_evidence"), "represented_level_ids": f.get("represented_level_ids")}
            if _title_type(f) == "UNKNOWN":
                questions.append(question(scope, ref, "classification", sorted(BILLABLE | EXCLUDED | NON_LEVEL) + ["UNKNOWN"],
                    "این نمای نقشه چه نوع فضایی یا چه نوع ترسیمی را نشان می‌دهد؟ در صورت ابهام «نامشخص» را انتخاب کنید.", ev))
            if _title_type(f) not in NON_LEVEL:
                questions.append(question(scope, ref, "building", refs + ["UNKNOWN"],
                    "این پلان به کدام ساختمان تعلق دارد؟ برای تمام پلان‌های یک ساختمان، شناسهٔ یک پلان نمایندهٔ ثابت را انتخاب کنید.", ev))
            env = envs.get(f["frame_id"])
            if env and env.get("outer_ring") and _title_type(f) not in NON_LEVEL | EXCLUDED:
                questions.append(question(scope, ref, "gross_scope", ["CONFIRMED", "REJECTED", "UNKNOWN"],
                    "آیا مرز موجود، تمام مساحت ناخالص این تراز شامل دیوارها، راه‌پله، شفت و بالکن/تراس را پوشش می‌دهد و حیاط یا سایت را شامل نمی‌شود؟ این پاسخ فقط همین مرز موجود را بررسی می‌کند.",
                    {**ev, "envelope_id": env.get("building_envelope_id"), "geometry_fingerprint": digest(env)}))
    return sorted(questions, key=lambda q:q["question_id"])


def _scale(legacy, canonical):
    source = legacy.get("source") or {}; cal = source.get("unit_calibration") or {}
    if cal.get("declared_unit_conflict"):
        return None, "CONFLICT"
    # Magnitude voting in current _calibrate_scale is not unit authority.
    if cal.get("status") != "DECLARED" or cal.get("evidence"):
        return None, "INPUT_REQUIRED"
    known = {1:Decimal("0.0254"), 2:Decimal("0.3048"), 4:Decimal("0.001"), 5:Decimal("0.01"), 6:Decimal("1")}
    scale = known.get(source.get("insunits"))
    if scale is None:
        return None, "INPUT_REQUIRED"
    values=(source.get("metres_per_unit"), source.get("declared_metres_per_unit"),
            cal.get("effective_metres_per_unit"), canonical["source"].get("effective_scale"))
    try:
        converted=[number(value) for value in values]
    except ValueError:
        return None, "INPUT_REQUIRED"
    if any(value != scale for value in converted):
        return None, "CONFLICT"
    return scale, "AUTO_VERIFIED"


def _face_support(poly, envelope, canonical, frame_id):
    ids = envelope.get("exterior_wall_ids") or []
    walls = {w["wall_id"]:w for w in canonical.get("walls", []) if w.get("frame_id") == frame_id}
    if not ids or any(i not in walls for i in ids):
        return False
    faces = []
    for wid in ids:
        wall = walls[wid]; authority = wall.get("authority") or {}
        if not authority.get("material_geometry") or authority.get("status") != "VERIFIED" or not wall.get("source_handles"):
            return False
        for key in ("face_a", "face_b"):
            if wall.get(key):
                faces.append(LineString(wall[key]))
    # Exact native wall faces only. Centerline, frame box and offsets cannot qualify.
    witnesses = []
    if separator_errors(canonical):
        return False
    for entry in canonical.get("evidence_registry", []):
        payload = entry.get("payload") or {}
        role = payload.get("separator") or {}
        if entry.get("kind") == "SOURCE_BOUNDARY_SUPPORT" and payload.get("frame_id") == frame_id and role.get("status") == "VERIFIED" and role.get("role") == "PHYSICAL_SEPARATOR":
            from shapely.ops import substring
            lo, hi = payload["interval"]
            witnesses.append(substring(LineString(payload["geometry"]),lo,hi,normalized=True))
    return (bool(faces) and bool(witnesses) and poly.boundary.difference(unary_union(faces)).is_empty
            and poly.boundary.difference(unary_union(witnesses)).is_empty)


def measure(project_id, bundles, *, current_sources, answers=(), engine=None):
    """Pure replay. current_sources must come from current stored upload identities.

    This internal API is not a client authority endpoint. Invalid source/model or
    review bindings raise; missing architectural facts produce fail-closed reports.
    """
    bundles = sorted(deepcopy(bundles),key=lambda b:b["canonical"]["source"]["source_sha256"])
    engine = deepcopy(engine if engine is not None else build_identity())
    scope = binding(project_id, bundles, current_sources, engine)
    questions = _questions(scope, bundles)
    accepted = _answer_map(questions, answers)
    facts = {(q["object_id"], q["fact"]): accepted[q["question_id"]]["value"]
             for q in questions if q["question_id"] in accepted}
    rows, blockers = [], []
    if facts.get((str(project_id),"inventory_complete")) != "CONFIRMED":
        blockers.append({"code":"COMPLETE_LEVEL_INVENTORY_REVIEW_REQUIRED","status":"INPUT_REQUIRED" if (str(project_id),"inventory_complete") in facts else "QUICK_CONFIRMATION_REQUIRED","object_id":str(project_id)})
    def issue(row, code, state="INPUT_REQUIRED"):
        entry = {"code": code, "status": state, "object_id": row["record_id"]}
        row["conflicts"].append(entry); blockers.append(entry)
    for bundle in sorted(bundles, key=lambda b:b["canonical"]["source"]["source_sha256"]):
        c, legacy = bundle["canonical"], bundle["legacy"]
        sha = c["source"]["source_sha256"]
        validation = validate_architecture(c)
        scale, scale_status = _scale(legacy, c)
        envs = {}
        for env in legacy.get("building_envelopes", []):
            envs.setdefault(env.get("frame_id"), []).append(env)
        for f in sorted(c.get("frames", []), key=lambda f:f["frame_id"]):
            ref = sha + ":" + f["frame_id"]; kind = _title_type(f)
            kind = facts.get((ref,"classification"),kind)
            represented = sorted(set(f.get("represented_level_ids") or []))
            building = facts.get((ref,"building"))
            row = {"record_id": ref, "source_sha256": sha, "frame_id": f["frame_id"],
                "building_id": "BUILDING-"+digest(building)[:20] if building and building != "UNKNOWN" else None,
                "level_id": f.get("primary_level_id"), "represented_level_ids": represented,
                "canonical_level_name": f.get("level_id"), "commercial_level_type": kind,
                "source_evidence": deepcopy(f.get("title_evidence")),
                "source_handles": (f.get("title_evidence") or {}).get("source_handles", []),
                "geometry_fingerprint": None, "gross_area_m2": None,
                "scale_evidence": deepcopy((legacy.get("source") or {}).get("unit_calibration")),
                "metres_per_unit": numeric(scale), "area_authority_source": "CANONICAL_NATIVE_WALL_FACES",
                "envelope_status": "INPUT_REQUIRED", "level_confidence": "SOURCE_EXPLICIT" if kind != "UNKNOWN" else "UNRESOLVED",
                "billable": kind in BILLABLE if kind != "UNKNOWN" else None,
                "exclusion_reason": kind if kind in EXCLUDED else "NOT_A_LEVEL" if kind in NON_LEVEL else None,
                "multiplicity": len(represented) if represented else None,
                "multiplicity_authority": "EXPLICIT_TITLE_LEVEL_SET" if represented else "NONE",
                "billable_contribution_m2": None, "cross_checks": [], "conflicts": [],
                "human_confirmed_facts": [a for q in questions if q["object_id"]==ref and (a:=accepted.get(q["question_id"]))]}
            rows.append(row)
            if validation["hard_errors"]:
                issue(row,"ARCHITECTURE_VALIDATION_FAILED","CONFLICT")
            source_role=str(f.get("frame_type") or "").upper()
            if kind in BILLABLE and source_role in NON_LEVEL | {"DETAIL_REFERENCE","DETAIL_REFERENCE_ONLY","TITLE_BLOCK"}:
                issue(row,"NON_LEVEL_SOURCE_SCOPE_CONFLICT","CONFLICT")
            if kind in NON_LEVEL:
                row.update(multiplicity=0,billable=False,billable_contribution_m2=0,commercial_status=status(row["conflicts"]))
                continue
            if kind == "UNKNOWN": issue(row,"LEVEL_CLASSIFICATION_REQUIRED","INPUT_REQUIRED" if (ref,"classification") in facts else "QUICK_CONFIRMATION_REQUIRED")
            if not row["building_id"]: issue(row,"BUILDING_MEMBERSHIP_REQUIRED","INPUT_REQUIRED" if (ref,"building") in facts else "QUICK_CONFIRMATION_REQUIRED")
            if not represented or not (f.get("title_evidence") or {}).get("source_handles"):
                issue(row,"EXPLICIT_LEVEL_INVENTORY_REQUIRED")
            if len(represented) > 1 and not _explicit_typical(f, represented):
                issue(row,"TYPICAL_RANGE_NOT_PROVEN")
            if represented != sorted(set((f.get("title_evidence") or {}).get("represented_level_ids") or [])):
                issue(row,"LEVEL_TITLE_DISAGREEMENT","CONFLICT")
            if kind in EXCLUDED:
                row.update(billable_contribution_m2=0,commercial_status=status(row["conflicts"]))
                continue
            if scale_status != "AUTO_VERIFIED": issue(row,"SCALE_AUTHORITY_REQUIRED",scale_status)
            candidates = envs.get(f["frame_id"], [])
            if len(candidates) != 1:
                issue(row,"ONE_QUALIFIED_ENVELOPE_REQUIRED")
                row["commercial_status"] = status(row["conflicts"]); continue
            env = candidates[0]; row["geometry_fingerprint"] = digest(env)
            row["source_handles"] = sorted(set(row["source_handles"] + (env.get("source_handles") or [])))
            row["envelope_status"] = env.get("status")
            try:
                poly, area = geometry(env)
                if scale is not None: row["gross_area_m2"] = numeric(area * scale * scale)
                if not _face_support(poly,env,c,f["frame_id"]): issue(row,"GROSS_OUTER_FACE_NOT_PROVEN")
                if env.get("status") not in {"VERIFIED","HIGH_CONFIDENCE"}: issue(row,"ENVELOPE_NOT_QUALIFIED")
                if env.get("interior_voids") or any(p.get("interior_voids") for p in env.get("components", [])):
                    issue(row,"GROSS_HOLE_SCOPE_REQUIRED")
                if facts.get((ref,"gross_scope")) != "CONFIRMED":
                    issue(row,"GROSS_SCOPE_REVIEW_REQUIRED","INPUT_REQUIRED" if (ref,"gross_scope") in facts else "QUICK_CONFIRMATION_REQUIRED")
                # Existing region/space union is correlated: report, never call it independent.
                spaces = [s for s in c.get("physical_spaces", []) if s.get("frame_id")==f["frame_id"]]
                row["cross_checks"].append({"method":"PHYSICAL_SPACE_ACCOUNTING", "independent":False,
                    "status":"DIAGNOSTIC_ONLY", "recognized_space_count":len(spaces),
                    "reason":"Room net areas omit walls; cannot replace gross or authorize tolerance."})
                net = sum((number(s["area_m2"]) for s in spaces if s.get("area_m2") is not None), Decimal(0))
                if row["gross_area_m2"] is not None:
                    row["cross_checks"][-1].update(comparison_m2=numeric(net),
                        delta_m2=numeric(net-number(row["gross_area_m2"])),
                        delta_percent=numeric((net-number(row["gross_area_m2"]))/number(row["gross_area_m2"])*100))
                    if net > number(row["gross_area_m2"]):
                        issue(row,"PHYSICAL_SPACE_EXCEEDS_GROSS","CONFLICT")
                reconciliation = legacy.get("dimension_reconciliation") or {}
                if reconciliation.get("conflicts") or reconciliation.get("status") in {"CONFLICT","FAIL"}:
                    issue(row,"SOURCE_DIMENSION_CONFLICT","CONFLICT")
                # No existing architecture export proves independent overall gross-area dimensions.
                # Read explicitly associated native source dimension pairs only; arbitrary area inputs forbidden.
                checks = _dimension_checks(env, legacy, area, scale)
                row["cross_checks"].extend(checks)
                if not checks: issue(row,"INDEPENDENT_GROSS_CHECK_REQUIRED")
                if any(check["status"] == "CONFLICT" for check in checks): issue(row,"AREA_RECONCILIATION_CONFLICT","CONFLICT")
            except (ValueError, TypeError, KeyError, IndexError):
                issue(row,"INVALID_GROSS_GEOMETRY")
            row["commercial_status"] = status(row["conflicts"])
            if row["commercial_status"] == "AUTO_VERIFIED":
                row["billable_contribution_m2"] = numeric(number(row["gross_area_m2"])*row["multiplicity"])
    # A confirmed representative must itself belong to that building (no split aliases).
    by_ref = {row["record_id"]:row for row in rows}
    for row in rows:
        representative = facts.get((row["record_id"],"building"))
        if representative and representative != "UNKNOWN" and (representative not in by_ref or
                by_ref[representative]["building_id"] != row["building_id"] or by_ref[representative]["commercial_level_type"] in NON_LEVEL):
            issue(row,"BUILDING_GROUP_CONFLICT","CONFLICT")
    occupied = {}
    for row in rows:
        if row["commercial_level_type"] in NON_LEVEL or not row["building_id"]: continue
        for level in row["represented_level_ids"]:
            key = (row["building_id"],level)
            if key in occupied:
                # Same identity in different views is unresolved, never sum or similarity-dedup.
                issue(row,"DUPLICATE_LEVEL_PRESENTATION","CONFLICT")
                issue(occupied[key],"DUPLICATE_LEVEL_PRESENTATION","CONFLICT")
            occupied[key] = row
    if not rows:
        blockers.append({"code":"LEVEL_INVENTORY_REQUIRED","status":"INPUT_REQUIRED","object_id":str(project_id)})
    for row in rows:
        row["commercial_status"] = status(row["conflicts"])
        if row["conflicts"]: row["billable_contribution_m2"] = None
    overall = status(blockers)
    total = sum(number(r["billable_contribution_m2"]) for r in rows if r["billable_contribution_m2"] is not None)
    buildings = [{"building_id":bid,"record_ids":[r["record_id"] for r in rows if r["building_id"]==bid],
        "billable_area_m2": numeric(sum(number(r["billable_contribution_m2"]) for r in rows if r["building_id"]==bid))
            if overall=="AUTO_VERIFIED" else None} for bid in sorted({r["building_id"] for r in rows if r["building_id"]})]
    result = {"schema":SCHEMA,"measurement_version":VERSION,"build_identity":engine,"binding":scope,
        "source":{"sources":scope["sources"]},"rules":RULES,"buildings":buildings,"levels":rows,
        "totals":{"detected_frame_count":len(rows),
            "detected_level_count":len(occupied) if all(r["building_id"] and r["represented_level_ids"] for r in rows if r["commercial_level_type"] not in NON_LEVEL) else None,
            "billable_level_count":sum(r["multiplicity"] or 0 for r in rows if r["billable"]) if overall=="AUTO_VERIFIED" else None,
            "gross_detected_area_m2":numeric(sum(number(r["gross_area_m2"])*(r["multiplicity"] or 0) for r in rows if r["commercial_level_type"] not in NON_LEVEL)) if all(r["gross_area_m2"] is not None for r in rows if r["commercial_level_type"] not in NON_LEVEL) else None,
            "excluded_area_m2":0 if not any(r["commercial_level_type"] in EXCLUDED for r in rows) else None,
            "billable_area_m2":numeric(total) if overall=="AUTO_VERIFIED" else None},
        "reconciliation":{"acceptance_policy":RULES["numeric_acceptance"],"status":overall},
        "commercial_status":overall,"blockers":sorted(blockers,key=lambda i:(i["object_id"],i["code"])),
        "review_items":[q for q in questions if q["question_id"] not in accepted],
        "review_registry":sorted(accepted.values(),key=lambda a:a["question_id"]),
        "provider_calls":0,"mode":"SHADOW","release_qualification":"HUMAN_GOLDEN_REQUIRED"}
    result["measurement_hash"] = digest(result)
    return result


def _dimension_checks(envelope, legacy, area, scale):
    """Reconcile a native overall rectangle only if source witness geometry proves it.

    No inferred tolerance or synthetic independence: pair handles must be actual
    DIMENSION records; endpoints must be adjacent existing gross polygon corners.
    More complex boundaries remain input-required until an independent method exists.
    """
    ring = envelope.get("outer_ring") or []
    if len(ring)!=5 or len(envelope.get("components") or [])>1 or scale is None:
        return []
    sides = [LineString([ring[i],ring[i+1]]) for i in range(4)]
    vectors = [(number(ring[i+1][0])-number(ring[i][0]),number(ring[i+1][1])-number(ring[i][1])) for i in range(4)]
    if any(vectors[i][0]*vectors[(i+1)%4][0]+vectors[i][1]*vectors[(i+1)%4][1] != 0 for i in range(4)):
        return []
    dims = []
    for side in sides[:2]:
        matches = [d for d in legacy.get("dimensions",[]) if d.get("handle") and
                   d.get("witness_points") and LineString(d["witness_points"]).equals(side) and
                   d.get("text_override") in (None,"","<>") and number(d.get("measurement"))>0]
        if len(matches)!=1: return []
        dims.append(matches[0])
    if dims[0]["handle"] == dims[1]["handle"]: return []
    lengths_match = all(number(d["measurement"])**2 == vectors[i][0]**2 + vectors[i][1]**2 for i,d in enumerate(dims))
    compared = number(dims[0]["measurement"])*number(dims[1]["measurement"])
    delta = (compared-area)*scale*scale
    return [{"method":"NATIVE_OVERALL_DIMENSIONS","independent":True,
        "source_handles":[d["handle"] for d in dims], "primary_m2":numeric(area*scale*scale),
        "comparison_m2":numeric(compared*scale*scale),"delta_m2":numeric(delta),
        "delta_percent":numeric((compared-area)/area*100),
        "status":"PASS" if compared==area and lengths_match else "CONFLICT", "tolerance":0,
        "individual_dimension_lengths_match":lengths_match,
        "acceptance_basis":"Exact arithmetic synthetic characterization; no real-project tolerance authorized."}]


def verify_measurement(report):
    if report.get("schema") != SCHEMA or report.get("measurement_hash") != digest({k:v for k,v in report.items() if k!="measurement_hash"}):
        raise ValueError("MEASUREMENT_INTEGRITY_FAILED")


def validate_measurement_accounting(report):
    """Independent result arithmetic/control audit; source replay still required at service boundary."""
    verify_measurement(report)
    if report.get("mode") != "SHADOW" or report.get("rules") != RULES:
        raise ValueError("COMMERCIAL_RULE_MISMATCH")
    if report["commercial_status"] != "AUTO_VERIFIED":
        if report["totals"]["billable_area_m2"] is not None:
            raise ValueError("BLOCKED_TOTAL_FORBIDDEN")
        return
    if report["blockers"] or not report["levels"]:
        raise ValueError("FALSE_COMMERCIAL_AUTHORITY")
    seen=set(); total=Decimal(0)
    for row in report["levels"]:
        if row["commercial_status"]!="AUTO_VERIFIED" or row["conflicts"]:
            raise ValueError("UNRESOLVED_LEVEL_AUTHORITY")
        if row["commercial_level_type"] in NON_LEVEL:
            if row["billable"] or number(row["billable_contribution_m2"])!=0:
                raise ValueError("NON_LEVEL_BILLING_FORBIDDEN")
            continue
        if not row["building_id"] or not row["represented_level_ids"]:
            raise ValueError("LEVEL_IDENTITY_REQUIRED")
        for level in row["represented_level_ids"]:
            key=(row["building_id"],level)
            if key in seen: raise ValueError("DUPLICATE_LEVEL_BILLING")
            seen.add(key)
        if row["commercial_level_type"] in EXCLUDED:
            if row["billable"] or number(row["billable_contribution_m2"])!=0:
                raise ValueError("EXCLUDED_LEVEL_BILLING")
            continue
        if row["commercial_level_type"] not in BILLABLE or row["billable"] is not True:
            raise ValueError("UNSUPPORTED_LEVEL_BILLING")
        if row["multiplicity"]!=len(row["represented_level_ids"]) or not any(c.get("independent") and c.get("status")=="PASS" for c in row["cross_checks"]):
            raise ValueError("COMMERCIAL_PROOF_REQUIRED")
        contribution=number(row["gross_area_m2"])*row["multiplicity"]
        if contribution<=0 or contribution!=number(row["billable_contribution_m2"]):
            raise ValueError("CONTRIBUTION_MISMATCH")
        total+=contribution
    if total!=number(report["totals"]["billable_area_m2"]):
        raise ValueError("COMMERCIAL_TOTAL_MISMATCH")
