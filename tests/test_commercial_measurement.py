from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import json
import pytest
from cad_engine.architecture_contract import adapt_current_architecture, assign_canonical_model_hash
from cad_engine.architecture_separator_evidence import witness
from app.commercial_measurement import measure, digest, geometry, verify_measurement, BILLABLE
from app.commercial_shadow import pricing_snapshot, shadow_quote, staleness, persist_shadow

ENGINE={"commit_sha":"synthetic-test-build", "build_identity":"synthetic-test-build"}
SHA="a"*64


def bundle(titles=("Ground floor",), level_sets=None, scale=1, sha=SHA, rotation=False):
    levels=level_sets or [["L"+str(i)] for i in range(len(titles))]
    legacy={"schema":"canonical-architectural-model/1.0", "source":{"source_sha256":sha,
        "insunits":6 if scale==1 else 4,"metres_per_unit":scale,"declared_metres_per_unit":scale,
        "unit_calibration":{"status":"DECLARED","evidence":[],"effective_metres_per_unit":scale,"declared_unit_conflict":False}},
        "frames":[],"canonical_walls":[],"building_envelopes":[],"dimensions":[],"physical_spaces":[],
        "completeness":{"issues":[],"release_allowed":False,"downstream_engineering_allowed":False}}
    for i,title in enumerate(titles):
        fid="F"+str(i); x=i*30/scale; size=10/scale
        ring=[[x,0],[x+size,0],[x+size,size],[x,size],[x,0]]
        if rotation: ring=[[-y,x] for x,y in ring]
        legacy["frames"].append({"frame_id":fid,"level_candidate":levels[i][0] if levels[i] else None,
            "represented_levels":levels[i],"frame_type":"PLAN","bounds":[x,0,x+size,size],
            "title_text":[title],"title_source_handles":["TITLE"+str(i)],"status":"SUPPORTED"})
        wids=[]; handles=[]
        for j,(a,b) in enumerate(zip(ring,ring[1:])):
            wid=f"{fid}W{j}"; handle=f"{fid}H{j}"; wids.append(wid); handles.append(handle)
            legacy["canonical_walls"].append({"wall_id":wid,"frame_id":fid,"centerline":[a,b],
                "face_a":[a,b],"face_b":[a,b],"status":"VERIFIED","source_handles":[handle]})
        legacy["building_envelopes"].append({"building_envelope_id":fid+"ENV","frame_id":fid,
            "outer_ring":ring,"components":[{"outer_ring":ring}],"exterior_wall_ids":wids,"source_handles":handles,"status":"VERIFIED"})
        for j in (0,1):
            legacy["dimensions"].append({"handle":fid+"DIM"+str(j),"witness_points":ring[j:j+2],
                "measurement":size,"text_override":"","dimension_type":0})
    return rebind({"legacy":legacy})


def rebind(b):
    c=adapt_current_architecture(b["legacy"],ENGINE)
    c["source"]["source_type"]="CERTIFIED_DXF" # Explicit synthetic source role fixture, not real DXF truth.
    for w in c["walls"]:
        e=witness({"geometry":w["face_a"],"source_handle":w["source_handles"][0],"segment_id":w["wall_id"]},
            c["source"]["source_sha256"],w["frame_id"],"synthetic")
        p=e["payload"]; p["separator"]={"role":"PHYSICAL_SEPARATOR","status":"VERIFIED","origin":"STRUCTURED_INPUT",
            "assertion":{"source_sha256":p["source_sha256"],"evidence_fingerprint":p["evidence_fingerprint"],"profile_id":"SYNTHETIC-EXPLICIT"}}
        c["evidence_registry"].append(e)
    b["canonical"]=assign_canonical_model_hash(c); return b


def run(bundles,answers=()):
    return measure("P1",bundles,current_sources=[b["canonical"]["source"]["source_sha256"] for b in bundles],answers=answers,engine=ENGINE)


def confirm(bundles, grouping=None):
    initial=run(bundles); refs=sorted(r["record_id"] for r in initial["levels"])
    answers=[]
    for q in initial["review_items"]:
        value="CONFIRMED" if q["fact"] in {"gross_scope","inventory_complete"} else (grouping or {}).get(q["object_id"],refs[0]) if q["fact"]=="building" else "UNKNOWN"
        answers.append({"question_id":q["question_id"],"question_fingerprint":q["question_fingerprint"],
            "value":value,"reviewer":"synthetic-author","reviewed_at":"2026-10-05T00:00:00Z"})
    return run(bundles,answers)


def test_single_floor_and_gross_not_room_sum():
    b=bundle(); r=confirm([b]); assert r["commercial_status"]=="AUTO_VERIFIED",r["blockers"]
    assert r["totals"]["billable_area_m2"]==100
    assert b["legacy"]["physical_spaces"]==[]


@pytest.mark.parametrize("title",["Basement","Parking","Ground floor","Floor 1","Mezzanine","Balcony","Terrace"])
def test_locked_billable_classes(title):
    r=confirm([bundle((title,))]); assert r["totals"]["billable_area_m2"]==100,r["blockers"]


@pytest.mark.parametrize("title",["Roof","Yard","Site"])
def test_positive_exclusions(title):
    r=confirm([bundle((title,))]); assert r["totals"]["billable_area_m2"]==0
    assert r["levels"][0]["exclusion_reason"] in {"ROOF","YARD","SITE"}
    assert r["rules"]["engineering_exclusion"] is False


@pytest.mark.parametrize("title",["Section","Elevation","Detail","Title block"])
def test_non_level_no_billing(title):
    r=confirm([bundle((title,))]); assert r["totals"]["billable_area_m2"]==0


def test_multi_floor_basement_parking_mezzanine_balcony_terrace_not_omitted():
    r=confirm([bundle(("Basement","Parking","Mezzanine","Balcony","Terrace","Floor 1","Roof","Yard"))])
    assert r["totals"]["billable_area_m2"]==600


def test_explicit_typical_four_floors():
    r=confirm([bundle(("Floors 2 to 5",), [["L2","L3","L4","L5"]])])
    assert r["totals"]["billable_area_m2"]==400


def test_similarity_alone_never_multiplicity():
    r=confirm([bundle(("Typical plan",),[[]])]); assert r["totals"]["billable_area_m2"] is None
    assert "EXPLICIT_LEVEL_INVENTORY_REQUIRED" in {x["code"] for x in r["blockers"]}


def test_duplicate_level_presentation_cannot_double_bill():
    r=confirm([bundle(("Floor 1","Floor 1"),[["L1"],["L1"]])])
    assert r["commercial_status"]=="CONFLICT"; assert r["totals"]["billable_area_m2"] is None


def test_typical_overlapping_single_floor_conflict():
    r=confirm([bundle(("Floors 2 to 5","Floor 3"),[["L2","L3","L4","L5"],["L3"]])])
    assert r["commercial_status"]=="CONFLICT"


def test_multiple_buildings_same_level_ids():
    b=bundle(("Ground floor","Ground floor"),[["GROUND"],["GROUND"]])
    refs=[SHA+":F0",SHA+":F1"]
    r=confirm([b],dict(zip(refs,refs))); assert len(r["buildings"])==2
    assert r["totals"]["billable_area_m2"]==200


def test_building_grouping_required_not_one_file_assumption():
    r=run([bundle()]); assert r["commercial_status"]=="QUICK_CONFIRMATION_REQUIRED"


def test_one_source_per_level():
    a=bundle(("Ground floor",),[["GROUND"]]); b=bundle(("Floor 1",),[["L1"]],sha="b"*64)
    assert confirm([a,b])["totals"]["billable_area_m2"]==200


@pytest.mark.parametrize("rotation,scale",[(False,1),(True,1),(False,.001),(True,.001)])
def test_rotation_units(rotation,scale):
    assert confirm([bundle(scale=scale,rotation=rotation)])["totals"]["billable_area_m2"]==100


@pytest.mark.parametrize("mutation",["inferred","ambiguous","wrong"])
def test_scale_fail_closed(mutation):
    b=bundle(); s=b["legacy"]["source"]
    if mutation=="inferred": s["unit_calibration"]["status"]="INFERRED"
    if mutation=="ambiguous": s["insunits"]=0
    if mutation=="wrong": s["unit_calibration"]["declared_unit_conflict"]=True
    r=confirm([rebind(b)]); assert r["totals"]["billable_area_m2"] is None


def test_wrong_dimension_conflict():
    b=bundle(); b["legacy"]["dimensions"][0]["measurement"]=11
    assert confirm([rebind(b)])["commercial_status"]=="CONFLICT"


def test_disconnected_regions_not_silently_dropped():
    b=bundle(); env=b["legacy"]["building_envelopes"][0]
    env["components"].append({"outer_ring":[[20,0],[30,0],[30,10],[20,10],[20,0]]})
    r=confirm([rebind(b)]); assert r["levels"][0]["gross_area_m2"]==200
    assert r["totals"]["billable_area_m2"] is None


def test_balcony_yard_ambiguity():
    r=run([bundle(("Balcony Yard",))]); assert r["totals"]["billable_area_m2"] is None
    assert any(q["fact"]=="classification" for q in r["review_items"])


@pytest.mark.parametrize("key",["geometry_bounds","geometry_area_m2","titleblock_bounds","remote_detail_bounds"])
def test_whole_file_and_remote_geometry_never_area(key):
    b=bundle(); b["legacy"][key]=[0,0,1000000,1000000]
    assert confirm([rebind(b)])["totals"]["billable_area_m2"]==100


def test_physical_sum_disagreement_blocks():
    b=bundle(); b["legacy"]["physical_spaces"]=[{"physical_space_id":"S","frame_id":"F0","level_id":"L0",
        "polygon":[[0,0],[20,0],[20,20],[0,20]],"area_m2":400,"status":"INPUT_REQUIRED"}]
    r=confirm([rebind(b)]); assert r["commercial_status"]=="CONFLICT"
    assert any(i["code"]=="PHYSICAL_SPACE_EXCEEDS_GROSS" for i in r["blockers"])


def test_reupload_bound_source_rejected():
    with pytest.raises(ValueError,match="STALE_OR_INCOMPLETE"):
        measure("P1",[bundle()],current_sources=["b"*64],engine=ENGINE)


def test_deterministic_reordered_sources_and_replay():
    a=bundle(); b=bundle(("Floor 1",),[["L1"]],sha="b"*64)
    first=confirm([a,b]); assert first==confirm([b,a])
    assert first==run([a,b],first["review_registry"]*2)


@pytest.mark.parametrize("mutation",["source","project","build","geometry","scale","title"])
def test_stale_review_rejected(mutation):
    b=bundle(); answers=confirm([b])["review_registry"]; engine=ENGINE; project="P1"
    if mutation=="source": b["legacy"]["source"]["source_sha256"]="c"*64
    if mutation=="project": project="P2"
    if mutation=="build": engine={"build_identity":"different"}
    if mutation=="geometry": b["legacy"]["building_envelopes"][0]["outer_ring"][0][0]=1
    if mutation=="scale": b["legacy"]["source"]["insunits"]=4
    if mutation=="title": b["legacy"]["frames"][0]["title_text"]=["Roof"]
    rebind(b)
    with pytest.raises(ValueError,match="STALE_REVIEW"):
        measure(project,[b],current_sources=[b["canonical"]["source"]["source_sha256"]],answers=answers,engine=engine)


def price(rate=20):
    return pricing_snapshot(SimpleNamespace(id=99,discipline="mechanical",enabled=True,minimum_price=500,
        price_per_m2=rate,updated_at=datetime(2026,10,5)))


def quote(r,pricing=None,paid=False):
    return shadow_quote(r,pricing or price(),discipline="mechanical",created_at="fixed",
        current_quote={"amount":600,"paid":paid},current_area=500)


def test_shadow_uses_configured_rates_minimum_and_preserves_paid():
    r=confirm([bundle()]); before=deepcopy(r)
    assert quote(r)["final_amount"]==2000
    assert quote(r,price(1))["final_amount"]==500
    paid=quote(r,paid=True); assert paid["comparison"]["current_quote"]=={"amount":600,"paid":True}
    assert r==before


def test_blocked_measurement_cannot_force_minimum_quote():
    assert quote(run([bundle()]))["final_amount"] is None


def test_pricing_change_stale_and_paid_immutable():
    r=confirm([bundle()]); q=quote(r,paid=True); before=deepcopy(q)
    assert staleness(q,r,price(21))["status"]=="STALE"; assert q==before
    assert staleness(q,r,price())["status"]=="CURRENT"


def test_persistence_immutable_idempotent(tmp_path):
    r=confirm([bundle()]); p=persist_shadow(tmp_path,r)
    assert p==persist_shadow(tmp_path,r); assert json.loads(p.read_text())==r
    assert p.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("mutation",["centerline","unsupported_wall","missing_witness","vision","gross_rejection","holes"])
def test_unsupported_commercial_geometry_cannot_auto_verify(mutation):
    b=bundle()
    if mutation=="centerline": b["legacy"]["canonical_walls"][0]["face_a"]=[[0,1],[10,1]]; b["legacy"]["canonical_walls"][0]["face_b"]=[[0,2],[10,2]]
    if mutation=="unsupported_wall": b["legacy"]["canonical_walls"][0]["status"]="SUPPORTED"
    if mutation=="holes": b["legacy"]["building_envelopes"][0]["interior_voids"]=[[[1,1],[2,1],[2,2],[1,2],[1,1]]]
    rebind(b)
    if mutation=="missing_witness": b["canonical"]["evidence_registry"]=[]
    if mutation=="vision": b["canonical"]["walls"][0]["authority"]["origins"]=["VISION_SUPPORT_ONLY"]
    assign_canonical_model_hash(b["canonical"])
    r=confirm([b])
    if mutation=="gross_rejection":
        answers=deepcopy(r["review_registry"])
        gross_ids={q["question_id"] for q in run([b])["review_items"] if q["fact"]=="gross_scope"}
        for a in answers:
            if a["question_id"] in gross_ids: a["value"]="REJECTED"
        r=run([b],answers)
    assert r["commercial_status"]!="AUTO_VERIFIED"


def test_injected_review_numeric_area_rejected():
    r=confirm([bundle()]); answers=deepcopy(r["review_registry"]); answers[0]["area_m2"]=999
    with pytest.raises(ValueError,match="INVALID_REVIEW_FIELDS"): run([bundle()],answers)


def test_integrity_tampering():
    r=confirm([bundle()]); r["totals"]["billable_area_m2"]=999
    with pytest.raises(ValueError,match="INTEGRITY"): quote(r)


def test_unproven_multiple_levels_in_title_not_multiplicity():
    r=confirm([bundle(('Floor 1',),[['L1','L2','L3']])])
    assert r['totals']['billable_area_m2'] is None
    assert any(x['code']=='TYPICAL_RANGE_NOT_PROVEN' for x in r['blockers'])


def test_entire_inventory_must_be_confirmed_prevents_missed_basement_authority():
    b=bundle(); r=confirm([b]); inventory={q['question_id'] for q in run([b])['review_items'] if q['fact']=='inventory_complete'}
    answers=[a for a in r['review_registry'] if a['question_id'] not in inventory]
    assert run([b],answers)['totals']['billable_area_m2'] is None


def test_classification_answer_cannot_make_geometry_or_replace_dimension_proof():
    b=bundle(('Unknown plan',)); b['legacy']['dimensions']=[]; rebind(b)
    r=run([b]); answers=[]
    for q in r['review_items']:
        value='GROUND' if q['fact']=='classification' else SHA+':F0' if q['fact']=='building' else 'CONFIRMED'
        answers.append(dict(question_id=q['question_id'],question_fingerprint=q['question_fingerprint'],value=value,reviewer='test',reviewed_at='fixed'))
    assert run([b],answers)['totals']['billable_area_m2'] is None


def test_roof_headroom_not_silently_excluded():
    r=run([bundle(('پلان خرپشته',),[['ROOF_HEADROOM']])])
    assert r['levels'][0]['commercial_level_type']=='UNKNOWN'
    assert r['totals']['billable_area_m2'] is None


def test_unequal_side_errors_cannot_cancel_dimension_check():
    b=bundle(); b['legacy']['dimensions'][0]['measurement']=20;b['legacy']['dimensions'][1]['measurement']=5
    r=confirm([rebind(b)])
    assert r['commercial_status']=='CONFLICT'


def test_rehashed_bad_total_still_rejected_by_independent_accounting():
    r=confirm([bundle()]);r['totals']['billable_area_m2']=999
    r['measurement_hash']=digest({k:v for k,v in r.items() if k!='measurement_hash'})
    with pytest.raises(ValueError,match='TOTAL_MISMATCH'):quote(r)


def test_report_schema_validates_real_contract():
    from pathlib import Path
    import jsonschema
    root=Path(__file__).parents[1]/'standards/test-suites'
    r=confirm([bundle()]);q=quote(r)
    jsonschema.validate(r,json.loads((root/'commercial-measurement.schema.json').read_text()))
    jsonschema.validate(q,json.loads((root/'commercial-shadow.schema.json').read_text()))


def test_equal_area_nonrectangle_cannot_use_rectangular_dimension_formula():
    from app.commercial_measurement import _dimension_checks
    from decimal import Decimal
    b=bundle();env=b['legacy']['building_envelopes'][0]
    env['outer_ring']=[[0,0],[10,0],[10,10],[1,11],[0,0]]
    assert _dimension_checks(env,b['legacy'],Decimal(100),Decimal(1))==[]


def test_missing_declared_calibration_value_returns_input_required():
    b=bundle();b['legacy']['source']['unit_calibration'].pop('effective_metres_per_unit')
    r=confirm([rebind(b)])
    assert r['commercial_status']=='INPUT_REQUIRED'


def test_unknown_answer_terminates_bounded_review_without_inventing_authority():
    b=bundle();r=run([b]);answers=[]
    for q in r['review_items']:
        answers.append(dict(question_id=q['question_id'],question_fingerprint=q['question_fingerprint'],value='UNKNOWN',reviewer='test',reviewed_at='fixed'))
    after=run([b],answers)
    assert after['commercial_status']=='INPUT_REQUIRED'
    assert after['review_items']==[] and after['totals']['billable_area_m2'] is None


def test_floor_title_cannot_override_explicit_non_level_frame_scope():
    b=bundle();b['legacy']['frames'][0]['frame_type']='SECTION'
    r=confirm([rebind(b)])
    assert r['commercial_status']=='CONFLICT'
    assert any(i['code']=='NON_LEVEL_SOURCE_SCOPE_CONFLICT' for i in r['blockers'])
