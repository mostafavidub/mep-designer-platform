from copy import deepcopy
import re

from fastapi.testclient import TestClient

from app.main_health import app
from app import main as legacy
from app.architecture_preflight_ui import PERSISTENCE_KEY, preflight_view_model
from cad_engine.architecture_contract import assign_canonical_model_hash, content_hash
from cad_engine.architecture_review_engine import empty_review_registry, plan_preflight


SHA = "d" * 64


def authority(status="SUPPORTED", **grants):
    return {"status": status, "origins": ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
            "material_geometry": grants.get("material_geometry", False),
            "wall": grants.get("wall", False), "portal": grants.get("portal", False),
            "access": grants.get("access", False), "routing": False, "release": False}


def rehash(row):
    return assign_canonical_model_hash(row)


def model(release=True):
    from tests.architecture_separator_fixtures import declare_structured_separators
    from tests.architecture_spatial_fixtures import declare_verified_spatial_authority
    return rehash(declare_verified_spatial_authority(declare_structured_separators({"schema": "planha-canonical-architecture/2.0", "contract_status": "EXPERIMENTAL_INTERNAL",
        "source": {"source_type": "RAW_DXF", "source_sha256": SHA, "source_revision_identity": SHA,
                   "units": "METERS", "effective_scale": 1.0, "coordinate_system": {"status": "SUPPORTED"},
                   "adapter": {"adapter_id": "ui-test", "adapter_version": "1"}},
        "levels": [{"level_id": "L1", "status": "SUPPORTED", "source_frame_ids": ["F1"]}],
        "frames": [{"frame_id": "F1", "level_id": "L1", "source_identity": SHA, "status": "SUPPORTED"}],
        "walls": [{"wall_id": "W1", "frame_id": "F1", "centerline": [[5, 0], [5, 10]],
                   "source_handles": ["10"], "authority": authority(wall=True, material_geometry=True)}],
        "physical_spaces": [{"physical_space_id": "S1", "level_id": "L1", "frame_id": "F1",
            "polygon": [[0, 0], [5, 0], [5, 10], [0, 10]], "interior_rings": [],
            "topology_status": "VERIFIED", "source_handles": ["20"],
            "authority": authority("VERIFIED", material_geometry=True)},
            {"physical_space_id": "S2", "level_id": "L1", "frame_id": "F1",
             "polygon": [[5, 0], [10, 0], [10, 10], [5, 10]], "interior_rings": [],
             "topology_status": "VERIFIED", "source_handles": ["21"],
             "authority": authority("VERIFIED", material_geometry=True)}],
        "functional_zones": [], "apertures": [{"aperture_id": "G1", "frame_id": "F1",
            "classification": "UNKNOWN", "status": "SUPPORTED", "geometry": [[5, 4], [5, 5]],
            "host_wall_ids": ["W1"], "source_handles": ["30"], "authority": authority()}],
        "portals": [], "voids": [], "dimensions": [],
        "graphs": {"adjacency": [], "enclosure": [["S1", "S2"]], "access": []},
        "unresolved_items": [], "evidence_registry": [], "review_registry": empty_review_registry(),
        "authority_model": {"dimensions": [], "allowed_origins": [], "vision_independent_grants": []},
        "traceability": {"source_sha256": SHA, "adapter_id": "ui-test", "adapter_version": "1",
                         "legacy_model_hash": "e" * 64},
        "release": {"status": "VERIFIED" if release else "INPUT_REQUIRED",
                    "downstream_engineering_allowed": release, "release_allowed": release}})))


def candidate(answers=None):
    answers = answers or ["LIVING", "TOILET", "UNKNOWN"]
    return {"question_type": "SPACE_CLASSIFICATION", "frame_or_level_id": "F1",
            "object_or_region_id": "S1", "geometry_fingerprint": "geo-S1",
            "evidence_fingerprint": "ev-S1", "review_scope": "BOUNDED_SOURCE_INTERPRETATION",
            "candidate_interpretations": answers, "allowed_answers": answers,
            "can_resolve_without_geometry_creation": True, "impact_classification": "REVIEW_CRITICAL",
            "root_cause_key": "ROOT-UI", "evidence_summary": {"source_handles": ["30"],
            "unsafe": "<script>alert(1)</script>"},
            "preview_spec": {"frame_id": "F1", "crop_bounds": [0, 0, 6, 10],
                "related_wall_ids": ["W1"], "related_gap_ids": ["G1"],
                "related_space_ids": ["S1", "S2"], "source_handles": ["30"],
                "overlay_layers_requested": ["SOURCE", "TOPOLOGY"],
                "highlight_geometry": [[5, 4], [5, 5]], "question_focus": "SPACE"}}


def add_review(model_row, answers=None):
    model_row["unresolved_items"] = [{"unresolved_item_id": "U1", "object_or_region_id": "S1",
        "issue_type": "SPACE_SEMANTICS_UNRESOLVED", "evidence": {"source": "synthetic"},
        "downstream_impact": "BLOCKS_RELEASE", "impact_classification": "REVIEW_CRITICAL",
        "review_candidate": candidate(answers)}]
    model_row["release"] = {"status": "INPUT_REQUIRED", "downstream_engineering_allowed": False,
                            "release_allowed": False}
    return rehash(model_row)


def add_source_required(model_row):
    model_row["apertures"] = []
    model_row["unresolved_items"] = [{"unresolved_item_id": "U-DOOR", "object_or_region_id": "MISSING-GAP",
        "issue_type": "PORTAL_TOPOLOGY_UNRESOLVED", "evidence": {"motif": "door-like"},
        "downstream_impact": "BLOCKS_RELEASE", "impact_classification": "DOWNSTREAM_CRITICAL",
        "review_candidate": {"question_type": "PORTAL_INTERPRETATION", "frame_or_level_id": "F1",
            "object_or_region_id": "MISSING-GAP", "geometry_fingerprint": "g", "evidence_fingerprint": "e",
            "review_scope": "BOUNDED_SOURCE_INTERPRETATION", "candidate_interpretations": ["DOOR", "UNKNOWN"],
            "allowed_answers": ["DOOR", "UNKNOWN"], "can_resolve_without_geometry_creation": True}}]
    model_row["release"] = {"status": "INPUT_REQUIRED", "downstream_engineering_allowed": False,
                            "release_allowed": False}
    return rehash(model_row)


def create_project(client, canonical):
    response = client.post("/api/upload/init/electrical", json={"name": "پروژه پیش‌پرواز"})
    assert response.status_code == 200
    pid = response.json()["project_id"]
    db = legacy.Session(); project = db.get(legacy.Project, pid)
    project.analysis = {"discipline": "electrical", PERSISTENCE_KEY: {
        "canonical_model": canonical, "review_registry": empty_review_registry(),
        "source_sha256": canonical["source"]["source_sha256"],
        "canonical_model_hash": canonical["canonical_model_hash"], "created_at": "2026-10-03T00:00:00Z"}}
    db.commit(); db.close()
    return pid


def page_token(html):
    return re.search(r'data-csrf="([^"]+)"', html).group(1)


def current_item(canonical):
    return plan_preflight(canonical)["review_items"][0]


def post_payload(item, decision="LIVING", request_id="request-1"):
    return {"review_item_id": item["review_item_id"], "decision": decision,
            "review_fingerprint": item["review_fingerprint"], "request_id": request_id}


def test_view_model_uses_backend_answers_and_persian_labels_without_changing_values():
    current = add_review(model(False), ["DOOR", "UNKNOWN"]); plan = plan_preflight(current)
    view = preflight_view_model(current, plan)
    assert view["state"] == "QUICK_REVIEW_REQUIRED"
    assert view["question"]["answers"] == [{"value": "DOOR", "label": "در"},
                                               {"value": "UNKNOWN", "label": "نامشخص"}]
    assert view["question"]["viewer"]["crop_bounds"] == [0.0, 0.0, 6.0, 10.0]


def test_auto_quick_input_and_conflict_states_render_with_safe_persian_copy():
    client = TestClient(app)
    auto_id = create_project(client, model())
    auto = client.get(f"/projects/{auto_id}/architecture-preflight")
    assert auto.status_code == 200 and "ورودی معماری تأیید شد" in auto.text
    quick_model = add_review(model(False)); quick_id = create_project(client, quick_model)
    quick = client.get(f"/projects/{quick_id}/architecture-preflight")
    assert "یک مورد نیاز به تأیید دارد" in quick.text and "نامشخص" in quick.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in quick.text and "<script>alert(1)</script>" not in quick.text
    source_id = create_project(client, add_source_required(model(False)))
    source = client.get(f"/projects/{source_id}/architecture-preflight")
    assert "اصلاح فایل معماری لازم است" in source.text and "بازشوی هندسی قابل‌اثبات" in source.text
    conflict_model = model(); conflict_model["apertures"][0]["host_wall_ids"] = ["NO-WALL"]; rehash(conflict_model)
    conflict_id = create_project(client, conflict_model); conflict = client.get(f"/projects/{conflict_id}/architecture-preflight")
    assert "ادامه طراحی مسدود است" in conflict.text and "بررسی سیستم" in conflict.text


def test_rendered_answers_are_only_backend_allowed_and_enum_is_submitted():
    client = TestClient(app); current = add_review(model(False), ["TOILET"]); pid = create_project(client, current)
    page = client.get(f"/projects/{pid}/architecture-preflight")
    assert 'value="TOILET"' in page.text and 'value="UNKNOWN"' not in page.text
    assert "سرویس بهداشتی" in page.text


def test_owner_binding_blocks_cross_project_get_and_post():
    owner = TestClient(app); stranger = TestClient(app); current = add_review(model(False)); pid = create_project(owner, current)
    foreign = create_project(stranger, add_review(model(False)))
    assert stranger.get(f"/projects/{pid}/architecture-preflight").status_code == 404
    page = owner.get(f"/projects/{pid}/architecture-preflight"); token = page_token(page.text); item = current_item(current)
    assert stranger.post(f"/projects/{pid}/architecture-preflight/review/{item['review_item_id']}",
                         json=post_payload(item), headers={"X-CSRF-Token": token}).status_code == 404
    other_item = current_item(add_review(model(False), ["TOILET"]))
    response = owner.post(f"/projects/{foreign}/architecture-preflight/review/{other_item['review_item_id']}",
                          json=post_payload(other_item), headers={"X-CSRF-Token": token})
    assert response.status_code == 404


def test_tampering_csrf_answer_item_fingerprint_and_extra_geometry_are_rejected():
    client = TestClient(app); current = add_review(model(False)); pid = create_project(client, current)
    page = client.get(f"/projects/{pid}/architecture-preflight"); token = page_token(page.text); item = current_item(current)
    url = f"/projects/{pid}/architecture-preflight/review/{item['review_item_id']}"
    assert client.post(url, json=post_payload(item), headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post(url, json=post_payload(item, "در"), headers={"X-CSRF-Token": token}).status_code == 422
    assert client.post(url + "-changed", json=post_payload(item), headers={"X-CSRF-Token": token}).status_code == 409
    stale = post_payload(item); stale["review_fingerprint"] = "stale"
    assert client.post(url, json=stale, headers={"X-CSRF-Token": token}).status_code == 409
    extra = post_payload(item); extra["geometry"] = [[0, 0], [1, 1]]; extra["authority"] = "VERIFIED"
    assert client.post(url, json=extra, headers={"X-CSRF-Token": token}).status_code == 422


def test_valid_review_revalidates_persists_snapshot_and_retry_is_idempotent():
    client = TestClient(app); current = add_review(model(False)); pid = create_project(client, current)
    page = client.get(f"/projects/{pid}/architecture-preflight"); token = page_token(page.text); item = current_item(current)
    url = f"/projects/{pid}/architecture-preflight/review/{item['review_item_id']}"; payload = post_payload(item)
    accepted = client.post(url, json=payload, headers={"X-CSRF-Token": token})
    assert accepted.status_code == 200 and accepted.json()["preflight"]["state"] == "AUTO_VALIDATED"
    retry = client.post(url, json=payload, headers={"X-CSRF-Token": token})
    assert retry.status_code == 200 and retry.json()["idempotent_replay"] is True
    db = legacy.Session(); stored = db.get(legacy.Project, pid).analysis[PERSISTENCE_KEY]; db.close()
    assert len(stored["review_registry"]["accepted_decisions"]) == 1
    assert stored["snapshot"]["validation_state"] == "VALIDATED"
    assert stored["last_validator_report_hash"]


def test_idempotency_key_cannot_be_reused_for_different_answer():
    client = TestClient(app); current = add_review(model(False)); pid = create_project(client, current)
    page = client.get(f"/projects/{pid}/architecture-preflight"); token = page_token(page.text); item = current_item(current)
    url = f"/projects/{pid}/architecture-preflight/review/{item['review_item_id']}"
    assert client.post(url, json=post_payload(item, "LIVING", "same"), headers={"X-CSRF-Token": token}).status_code == 200
    changed = post_payload(item, "TOILET", "same")
    assert client.post(url, json=changed, headers={"X-CSRF-Token": token}).status_code == 409


def test_unknown_is_safe_and_never_creates_geometry_or_snapshot():
    client = TestClient(app); current = add_review(model(False)); pid = create_project(client, current)
    page = client.get(f"/projects/{pid}/architecture-preflight"); token = page_token(page.text); item = current_item(current)
    before = content_hash({"walls": current["walls"], "spaces": current["physical_spaces"], "apertures": current["apertures"]})
    response = client.post(f"/projects/{pid}/architecture-preflight/review/{item['review_item_id']}",
                           json=post_payload(item, "UNKNOWN"), headers={"X-CSRF-Token": token})
    assert response.status_code == 200 and response.json()["preflight"]["state"] == "ARCHITECTURE_INPUT_REQUIRED"
    db = legacy.Session(); stored = db.get(legacy.Project, pid).analysis[PERSISTENCE_KEY]; db.close()
    after = content_hash({"walls": stored["canonical_model"]["walls"], "spaces": stored["canonical_model"]["physical_spaces"],
                          "apertures": stored["canonical_model"]["apertures"]})
    assert before == after and stored["snapshot"] is None


def test_project_page_links_preflight_without_mixing_generic_questions():
    client = TestClient(app); pid = create_project(client, add_review(model(False)))
    db = legacy.Session(); project = db.get(legacy.Project, pid); project.status = "asking"
    original_questions = deepcopy(project.questions); original_answers = deepcopy(project.answers); db.commit(); db.close()
    page = client.get(f"/projects/{pid}")
    assert f'/projects/{pid}/architecture-preflight' in page.text and "مشاهده بررسی معماری" in page.text
    db = legacy.Session(); project = db.get(legacy.Project, pid)
    assert project.questions == original_questions and project.answers == original_answers; db.close()


def test_critical_preflight_blocks_design_transport_and_hides_start_action():
    client = TestClient(app); pid = create_project(client, add_review(model(False)))
    db = legacy.Session(); project = db.get(legacy.Project, pid); project.status = "ready_to_design"; db.commit(); db.close()
    page = client.get(f"/projects/{pid}")
    assert "مشاهده بررسی معماری" in page.text and "شروع طراحی برق" not in page.text
    blocked = client.post(f"/projects/{pid}/design-json")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "architecture_preflight_required"


def test_static_assets_have_accessibility_retry_and_no_unsafe_svg_or_geometry_editing():
    template = open("app/templates/architecture_preflight.html", encoding="utf-8").read()
    script = open("app/static/architecture-preflight.js", encoding="utf-8").read()
    css = open("app/static/architecture-preflight.css", encoding="utf-8").read()
    assert "aria-live" in template and "fieldset" in template and 'dir="ltr"' in template
    assert "createElementNS" in script and "textContent" in script and "innerHTML" not in script
    assert "foreignObject" not in script and "javascript:" not in script and "location.assign" in script
    assert ":focus-visible" in css and "@media(max-width:900px)" in css
    forbidden = ("draw-wall", "draw-portal", "vertex-handle", "edit-polygon", "create-access")
    assert not any(token in (template + script).lower() for token in forbidden)


def test_stale_snapshot_is_never_current_in_server_view_or_html():
    from types import SimpleNamespace
    from app.architecture_preflight_ui import _load_state
    from cad_engine.architecture_snapshot import validate_snapshot
    current = model()
    old = {'snapshot_id': 'STALE-SNAPSHOT-MARKER', 'schema': 'old',
           'source_sha256': '0' * 64, 'validation_state': 'SUPERSEDED'}
    project = SimpleNamespace(analysis={PERSISTENCE_KEY: {
        'canonical_model': current, 'snapshot': old,
        'review_registry': empty_review_registry()}})
    _, _, _, result, view = _load_state(project)
    assert view['state'] == 'AUTO_VALIDATED'
    assert view['snapshot'] == result['snapshot']
    assert view['snapshot']['snapshot_id'] != old['snapshot_id']
    assert validate_snapshot(view['snapshot'], current, result['validator_report'])['current_authority']
    assert project.analysis[PERSISTENCE_KEY]['snapshot'] == old  # read-only GET
    client = TestClient(app)
    pid = create_project(client, current)
    db = legacy.Session(); saved = db.get(legacy.Project, pid)
    data = deepcopy(saved.analysis); data[PERSISTENCE_KEY]['snapshot'] = old
    saved.analysis = data; db.commit(); db.close()
    response = client.get(f'/projects/{pid}/architecture-preflight/state')
    assert response.status_code == 200
    assert response.json()['snapshot']['snapshot_id'] != old['snapshot_id']
    page = client.get(f'/projects/{pid}/architecture-preflight')
    assert page.status_code == 200 and 'STALE-SNAPSHOT-MARKER' not in page.text



def test_unresolved_and_old_contracts_cannot_expose_stored_snapshot():
    from types import SimpleNamespace
    from app.architecture_preflight_ui import _load_state
    for state in ('review', 'input', 'v2'):
        current = model()
        if state == 'review': current = add_review(current)
        elif state == 'input': current = add_source_required(current)
        else:
            current['schema'] = 'planha-canonical-architecture/2.0'
            current = rehash(current)
        project = SimpleNamespace(analysis={PERSISTENCE_KEY: {
            'canonical_model': current, 'snapshot': {'snapshot_id': 'STALE'},
            'review_registry': empty_review_registry()}})
        _, _, _, result, view = _load_state(project)
        assert view['state'] != 'AUTO_VALIDATED'
        assert view['snapshot'] is None
