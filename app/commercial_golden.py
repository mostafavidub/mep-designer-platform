"""Independent human Golden contract; algorithm results never become truth."""
from copy import deepcopy
from .commercial_measurement import digest, number, verify_measurement

SCHEMA="planha-commercial-golden/1.0"
METRICS=("building_count_accuracy","billable_level_count_accuracy","level_classification_accuracy",
    "typical_multiplicity_accuracy","per_level_gross_area_error_m2","total_billable_area_error_m2",
    "false_auto_verified_count","roof_false_inclusion_count","yard_site_false_inclusion_count","duplicate_billing_count")


def golden_request(project_id, sources, frames, build):
    """Skeleton is deliberately incomplete, not a Golden fixture with auto-filled truth."""
    return {"schema":SCHEMA,"project_id":str(project_id),"source_sha256s":sorted(sources),
        "status":"HUMAN_GOLDEN_REQUIRED","build_identity":deepcopy(build),
        "observed_frame_inventory_not_truth":deepcopy(frames),
        "building_count":None,"levels":[],"expected_total_billable_area_m2":None,
        "reviewer":None,"reviewed_at":None,"authority_source":None,
        "instructions_fa":"برای هر طبقهٔ واقعی، ساختمان، شناسهٔ پلان، نوع طبقه، تعداد تکرار و مساحت ناخالصِ مستقلاً اندازه‌گیری‌شده را ثبت کنید. بام و حیاط/سایت حذف تجاری دارند؛ بالکن و تراس حذف ندارند. مقادیر الگوریتم پاسخ صحیح محسوب نمی‌شوند. پلان‌های جاافتاده را نیز ثبت کنید."}


def validate_golden(truth):
    if truth.get("schema")!=SCHEMA or truth.get("status")!="HUMAN_VERIFIED":
        raise ValueError("HUMAN_GOLDEN_REQUIRED")
    if not all(truth.get(k) for k in ("reviewer","reviewed_at","authority_source","source_sha256s")):
        raise ValueError("INDEPENDENT_HUMAN_AUTHORITY_REQUIRED")
    if truth.get("authority_source") in {"PLANHA","ALGORITHM","SYNTHETIC"}:
        raise ValueError("ALGORITHM_IS_NOT_HUMAN_TRUTH")
    from .commercial_measurement import BILLABLE, EXCLUDED
    total=0; identities=set(); buildings=set()
    for row in truth.get("levels",[]):
        if row["source_sha256"] not in truth["source_sha256s"] or not row.get("authority_note"):
            raise ValueError("GOLDEN_LEVEL_PROVENANCE_REQUIRED")
        identities_here={(row["building_id"],level) for level in row["represented_level_ids"]}
        if identities & identities_here: raise ValueError("GOLDEN_DUPLICATE_LEVEL")
        identities |= identities_here; buildings.add(row["building_id"])
        if row["commercial_level_type"] not in BILLABLE|EXCLUDED:
            raise ValueError("GOLDEN_CLASSIFICATION_REQUIRED")
        if row["multiplicity"]!=len(row["represented_level_ids"]) or row["multiplicity"]<=0:
            raise ValueError("GOLDEN_MULTIPLICITY_REQUIRED")
        if row["billable"] != (row["commercial_level_type"] in BILLABLE):
            raise ValueError("GOLDEN_BILLABLE_RULE_CONFLICT")
        if row["billable"]:
            if number(row["gross_area_m2"])<=0: raise ValueError("GOLDEN_GROSS_AREA_REQUIRED")
            total+=number(row["gross_area_m2"])*row["multiplicity"]
    if not identities or len(buildings)!=truth["building_count"] or total!=number(truth["expected_total_billable_area_m2"]):
        raise ValueError("GOLDEN_TOTAL_OR_INVENTORY_CONFLICT")
    return True


def benchmark(measurements, truths=()):
    measurements=list(measurements)
    for report in measurements: verify_measurement(report)
    truth_map={t["project_id"]:t for t in truths}
    for truth in truths: validate_golden(truth)
    evaluated=[]; n=len(measurements)
    metrics={key:None for key in METRICS}
    for report in measurements:
        truth=truth_map.get(report["binding"]["project_id"])
        if truth is None: continue
        if sorted(truth["source_sha256s"])!=sorted(s["source_sha256"] for s in report["binding"]["sources"]):
            raise ValueError("STALE_GOLDEN_SOURCE")
        expected={r["source_sha256"]+":"+r["frame_id"]:r for r in truth["levels"]}
        actual={r["record_id"]:r for r in report["levels"] if r["exclusion_reason"]!="NOT_A_LEVEL"}
        rows=[]
        for ref,t in expected.items():
            a=actual.get(ref,{})
            rows.append({"record_id":ref,"classification_correct":a.get("commercial_level_type")==t["commercial_level_type"],
                "multiplicity_correct":a.get("multiplicity")==t["multiplicity"],
                "gross_area_error_m2":float(number(a["gross_area_m2"])-number(t["gross_area_m2"])) if a.get("gross_area_m2") is not None and t.get("gross_area_m2") is not None else None,
                "roof_false_inclusion":t["commercial_level_type"]=="ROOF" and a.get("billable") is True,
                "yard_site_false_inclusion":t["commercial_level_type"] in {"YARD","SITE"} and a.get("billable") is True})
        area=report["totals"]["billable_area_m2"]
        error=float(number(area)-number(truth["expected_total_billable_area_m2"])) if area is not None else None
        correct=all(r["classification_correct"] and r["multiplicity_correct"] and (r["gross_area_error_m2"]==0 or not expected[r["record_id"]]["billable"]) for r in rows)
        seen=set(); duplicate_count=0
        for row in actual.values():
            if row.get("billable_contribution_m2") is None or number(row["billable_contribution_m2"])<=0:
                continue
            for level in row["represented_level_ids"]:
                key=(row["building_id"],level)
                duplicate_count += key in seen
                seen.add(key)
        evaluated.append({"project_id":truth["project_id"],"duplicate_billing_count":duplicate_count,"building_count_correct":len(report["buildings"])==truth["building_count"],
            "billable_level_count_correct":report["totals"]["billable_level_count"]==sum(r["multiplicity"] for r in truth["levels"] if r["billable"]),
            "inventory_correct":set(expected)==set(actual),"levels":rows,"total_billable_area_error_m2":error,
            "false_auto_verified":report["commercial_status"]=="AUTO_VERIFIED" and (not correct or error!=0 or set(expected)!=set(actual) or len(report["buildings"])!=truth["building_count"])})
    if evaluated:
        all_rows=[r for e in evaluated for r in e["levels"]]
        metrics.update(building_count_accuracy=sum(e["building_count_correct"] for e in evaluated)/len(evaluated),
            billable_level_count_accuracy=sum(e["billable_level_count_correct"] for e in evaluated)/len(evaluated),
            level_classification_accuracy=sum(r["classification_correct"] for r in all_rows)/len(all_rows),
            typical_multiplicity_accuracy=sum(r["multiplicity_correct"] for r in all_rows)/len(all_rows),
            per_level_gross_area_error_m2=[r["gross_area_error_m2"] for r in all_rows],
            total_billable_area_error_m2=[e["total_billable_area_error_m2"] for e in evaluated],
            false_auto_verified_count=sum(e["false_auto_verified"] for e in evaluated),
            roof_false_inclusion_count=sum(r["roof_false_inclusion"] for r in all_rows),
            yard_site_false_inclusion_count=sum(r["yard_site_false_inclusion"] for r in all_rows),
            duplicate_billing_count=sum(e["duplicate_billing_count"] for e in evaluated))
    # Operational rates have a different denominator from truth accuracy.
    for state in ("AUTO_VERIFIED","QUICK_CONFIRMATION_REQUIRED","INPUT_REQUIRED","CONFLICT"):
        metrics[state.lower()+"_rate"]=sum(r["commercial_status"]==state for r in measurements)/n if n else None
    metrics["stale_measurement_detection_rate"]=None
    metrics["deterministic_replay_rate"]=None
    return {"schema":"planha-commercial-benchmark/1.0","build_identities":[r["build_identity"] for r in measurements],"status":"HUMAN_GOLDEN_REQUIRED" if not evaluated else "REVIEWED_BENCHMARK_NOT_RELEASE_AUTHORIZATION",
        "project_count":n,"human_verified_project_count":len(evaluated),"metrics":metrics,"comparisons":evaluated,
        "acceptance_threshold":"NOT_RELEASE_QUALIFIED","source_outputs_seal":digest(measurements)}
