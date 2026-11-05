"""Offline, NON-REGULATORY contract PoC for Planha Architecture MVP.

This file intentionally lives under tests/. It is not a production resolver,
not a code/permit authority, and must never be imported by the served runtime.
All rules here are synthetic fixtures, never Iranian statutory values.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import math
import unittest


REQUIRED_BRIEF = frozenset({
    "project_id", "city_id", "width_ns_m", "length_ew_m",
    "site_type", "unit_count", "revision",
})
SITE_TYPES = frozenset({"NORTHERN", "SOUTHERN"})
FIXTURE_MARKER = "NON_REGULATORY_TEST_DATA"


def digest(payload):
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return sha256(raw.encode("utf-8")).hexdigest()


def validate_brief(payload):
    """Public input is not allowed to claim parcel, bedrooms or regulations."""
    if not isinstance(payload, dict):
        return {"status": "INPUT_REQUIRED", "findings": ["BRIEF_OBJECT_REQUIRED"]}
    missing = sorted(REQUIRED_BRIEF - set(payload))
    extra = sorted(set(payload) - REQUIRED_BRIEF)
    errors = (["MISSING_FIELDS:" + ",".join(missing)] if missing else []) + (
        ["UNAUTHORIZED_FIELDS:" + ",".join(extra)] if extra else [])
    if errors:
        return {"status": "INPUT_REQUIRED", "findings": errors}
    if not all(isinstance(payload[k], str) and payload[k].strip()
               for k in ("project_id", "city_id")):
        errors.append("INVALID_IDENTITY")
    for key in ("width_ns_m", "length_ew_m"):
        value = payload[key]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value <= 0):
            errors.append("INVALID_DIMENSION:" + key)
    if payload["site_type"] not in SITE_TYPES:
        errors.append("INVALID_SITE_TYPE")
    if type(payload["unit_count"]) is not int or not 1 <= payload["unit_count"] <= 4:
        errors.append("INVALID_UNIT_COUNT")
    if type(payload["revision"]) is not int or payload["revision"] <= 0:
        errors.append("INVALID_REVISION")
    if errors:
        return {"status": "INPUT_REQUIRED", "findings": errors}
    width = float(payload["width_ns_m"])
    length = float(payload["length_ew_m"])
    return {
        "status": "STRUCTURALLY_VALID_NON_REGULATORY",
        "public_input_hash": digest(payload),
        "site_geometry": {"polygon_m": [[0.0, 0.0], [width, 0.0],
                                        [width, length], [0.0, length]],
                          "geographic_north": "NOT_ESTABLISHED_BY_SITE_TYPE",
                          "street_edge": "NOT_ESTABLISHED_WITHOUT_ACCESS_DEFINITION"},
        "site_type": payload["site_type"],
        "unit_count": payload["unit_count"],
        "bedroom_count": None,
        "bedroom_derivation_status": "NOT_YET_DERIVED",
        "parcel_buildable_envelope": None,
        "legal_compliance": False,
    }


def synthetic_profile(profile_id, scope, city_id, rule_map, *, start="2026-01-01", end=None,
                      revision=1, qualified=False):
    """A sealed synthetic record. Not evidence of a real rule or source."""
    body = {
        "profile_id": profile_id, "scope": scope, "city_id": city_id,
        "effective_from": start, "effective_until": end,
        "revision": revision, "qualified": qualified,
        "source_marker": FIXTURE_MARKER,
        "rules": deepcopy(rule_map),
    }
    body["fingerprint"] = digest(body)
    return body


def _validate_profile(profile, when, expected_scope, expected_city):
    if not isinstance(profile, dict):
        return "PROFILE_MISSING"
    if profile.get("source_marker") != FIXTURE_MARKER:
        return "NON_REGULATORY_MARKER_REQUIRED"
    if profile.get("qualified") is not False:
        return "UNTRUSTED_AUTHORITY_FORBIDDEN"
    if profile.get("scope") != expected_scope or profile.get("city_id") != expected_city:
        return "PROFILE_SCOPE_MISMATCH"
    copy = {k: v for k, v in profile.items() if k != "fingerprint"}
    if profile.get("fingerprint") != digest(copy):
        return "PROFILE_FINGERPRINT_STALE"
    try:
        first = date.fromisoformat(profile["effective_from"])
        last = date.fromisoformat(profile["effective_until"]) if profile["effective_until"] else None
    except (KeyError, TypeError, ValueError):
        return "INVALID_EFFECTIVE_DATE"
    if first > when or (last is not None and when > last):
        return "PROFILE_OUTSIDE_EFFECTIVE_DATE"
    if not isinstance(profile.get("rules"), dict):
        return "RULE_MAP_INVALID"
    if any(not isinstance(key, str) or not key.startswith("TEST:") for key in profile["rules"]):
        return "ONLY_SYNTHETIC_RULE_IDS_ALLOWED"
    return None


def resolve_synthetic_multicity(brief, *, national, city_profiles, design_date):
    """Fail-closed multi-city isolation. No statutory qualification is possible."""
    original_brief = deepcopy(brief)
    checked = validate_brief(brief)
    if checked["status"] == "INPUT_REQUIRED":
        return checked
    try:
        day = date.fromisoformat(design_date)
    except (TypeError, ValueError):
        return {"status": "INPUT_REQUIRED", "findings": ["INVALID_PROJECT_DATE"]}
    city = brief["city_id"]
    if not isinstance(city_profiles, dict) or city not in city_profiles:
        return {"status": "RULE_COVERAGE_REQUIRED", "findings": ["CITY_PROFILE_MISSING"],
                "legal_compliance": False}
    nerr = _validate_profile(national, day, "country", "IR")
    if nerr:
        return {"status": "INPUT_REQUIRED", "findings": ["NATIONAL:" + nerr],
                "legal_compliance": False}
    local = city_profiles[city]
    cerr = _validate_profile(local, day, "city", city)
    if cerr:
        return {"status": "RULE_COVERAGE_REQUIRED", "findings": ["CITY:" + cerr],
                "legal_compliance": False}
    for rule_id in national["rules"]:
        if rule_id in local["rules"] and national["rules"][rule_id] != local["rules"][rule_id]:
            return {"status": "CONFLICT_REVIEW_REQUIRED",
                    "findings": ["NATIONAL_LOCAL_RULE_CONFLICT:" + rule_id],
                    "legal_compliance": False}
    rules = {**national["rules"], **local["rules"]}
    result = {
        "status": "SYNTHETIC_CONTRACT_ONLY",
        "city_id": city,
        "rule_ids": sorted(rules),
        "national_profile_id": national["profile_id"],
        "city_profile_id": local["profile_id"],
        "rulebook_snapshot_hash": digest({"city": city, "date": design_date,
                                         "brief": checked["public_input_hash"],
                                         "national": national["fingerprint"],
                                         "local": local["fingerprint"]}),
        "legal_compliance": False,
        "buildable_envelope": None,
        "bedroom_count": None,
        "source_status": FIXTURE_MARKER,
    }
    assert original_brief == brief
    return result


def classify_two_tier_policy(brief, requested_tier, *, geometry_gate,
                             rule_resolution=None, parcel_evidence=None):
    """Exercise UI policy only. This test helper NEVER grants compliance.

    In particular no self-attested source/validator status can qualify a real
    Rulebook or turn synthetic TEST: rules into construction permission.
    """
    validated = validate_brief(brief)
    if validated["status"] == "INPUT_REQUIRED":
        return {"status": "INPUT_REQUIRED", "compliance_status": "NOT_REQUESTED",
                "legally_approved": False}
    if requested_tier not in {"CONCEPTUAL", "CONTROLLED"}:
        return {"status": "INVALID_TIER", "compliance_status": "NOT_REQUESTED",
                "legally_approved": False}
    if not isinstance(geometry_gate, dict) or geometry_gate.get("status") != "PASS":
        return {"status": "GEOMETRY_NOT_VALIDATED",
                "compliance_status": "NOT_REQUESTED", "legally_approved": False}
    if requested_tier == "CONCEPTUAL":
        return {"status": "CONCEPTUAL_POLICY_ELIGIBLE_TEST_ONLY",
                "compliance_status": "NOT_REQUESTED", "label_fa": "پلان مفهومی",
                "limitations": ["PARCEL_AND_PERMIT_REQUIREMENTS_NOT_VERIFIED"],
                "legally_approved": False}
    if not isinstance(parcel_evidence, dict) or not parcel_evidence:
        return {"status": "INPUT_REQUIRED", "compliance_status": "INPUT_REQUIRED",
                "missing": ["PARCEL_AUTHORITY_EVIDENCE"],
                "legally_approved": False}
    if not isinstance(rule_resolution, dict) or rule_resolution.get("status") in {
            "RULE_COVERAGE_REQUIRED", "SOURCE_COVERAGE_REQUIRED"}:
        return {"status": "RULE_COVERAGE_REQUIRED",
                "compliance_status": "SOURCE_COVERAGE_REQUIRED",
                "legally_approved": False}
    if rule_resolution.get("status") == "CONFLICT_REVIEW_REQUIRED":
        return {"status": "CONFLICT_REVIEW_REQUIRED",
                "compliance_status": "CONFLICT", "legally_approved": False}
    return {"status": "AUTHORITY_REVIEW_REQUIRED",
            "compliance_status": "SOURCE_COVERAGE_REQUIRED",
            "legally_approved": False}


class MultiCityContractPoCTests(unittest.TestCase):
    def setUp(self):
        self.brief = {"project_id": "P-1", "city_id": "IR-X1",
                      "width_ns_m": 10, "length_ew_m": 20,
                      "site_type": "NORTHERN", "unit_count": 1, "revision": 1}
        self.national = synthetic_profile("NATION", "country", "IR", {"TEST:SHARED": "same"})
        self.local1 = synthetic_profile("CITY-1", "city", "IR-X1", {"TEST:A": "a"})
        self.local2 = synthetic_profile("CITY-2", "city", "IR-X2", {"TEST:B": "b"})

    def resolve(self, **kw):
        return resolve_synthetic_multicity(
            kw.get("brief", self.brief), national=kw.get("national", self.national),
            city_profiles=kw.get("profiles", {"IR-X1": self.local1, "IR-X2": self.local2}),
            design_date=kw.get("when", "2026-06-01"))

    def test_structural_brief_and_no_spurious_legal_envelope(self):
        result = validate_brief(self.brief)
        self.assertEqual(result["status"], "STRUCTURALLY_VALID_NON_REGULATORY")
        self.assertIsNone(result["parcel_buildable_envelope"])
        self.assertIsNone(result["bedroom_count"])
        self.assertFalse(result["legal_compliance"])

    def test_no_implicit_geographic_north_or_access_edge(self):
        n = validate_brief(self.brief)
        south = {**self.brief, "site_type": "SOUTHERN"}
        s = validate_brief(south)
        self.assertEqual(n["site_geometry"], s["site_geometry"])
        self.assertEqual(n["site_geometry"]["street_edge"],
                         "NOT_ESTABLISHED_WITHOUT_ACCESS_DEFINITION")

    def test_user_cannot_enter_bedrooms_or_floor_count(self):
        for key in ("bedrooms", "floor_count", "parcel_id", "setback_m"):
            with self.subTest(key=key):
                result = validate_brief({**self.brief, key: 2})
                self.assertEqual(result["status"], "INPUT_REQUIRED")

    def test_invalid_dimensions_and_unit_count_fail_closed(self):
        for key, val in (("width_ns_m", 0), ("length_ew_m", float("inf")),
                         ("width_ns_m", True), ("unit_count", 0),
                         ("unit_count", 5), ("unit_count", True)):
            with self.subTest(key=key, value=val):
                self.assertEqual(validate_brief({**self.brief, key: val})["status"],
                                 "INPUT_REQUIRED")

    def test_each_unit_count_in_input_contract(self):
        for count in (1, 2, 3, 4):
            self.assertEqual(validate_brief({**self.brief, "unit_count": count})["unit_count"], count)

    def test_city_isolation(self):
        a = self.resolve()
        b = self.resolve(brief={**self.brief, "city_id": "IR-X2"})
        self.assertIn("TEST:A", a["rule_ids"])
        self.assertNotIn("TEST:B", a["rule_ids"])
        self.assertIn("TEST:B", b["rule_ids"])
        self.assertNotIn("TEST:A", b["rule_ids"])
        self.assertIn("TEST:SHARED", a["rule_ids"])
        self.assertIn("TEST:SHARED", b["rule_ids"])
        self.assertNotEqual(a["rulebook_snapshot_hash"], b["rulebook_snapshot_hash"])

    def test_missing_city_no_tehran_or_other_fallback(self):
        missing = self.resolve(brief={**self.brief, "city_id": "IR-NOT-COVERED"})
        self.assertEqual(missing["status"], "RULE_COVERAGE_REQUIRED")
        self.assertEqual(missing["findings"], ["CITY_PROFILE_MISSING"])

    def test_city_profile_scope_cannot_cross_to_another_city(self):
        r = self.resolve(profiles={"IR-X1": self.local2})
        self.assertIn("CITY:PROFILE_SCOPE_MISMATCH", r["findings"])

    def test_stale_profile_fingerprint_fails_closed(self):
        local = deepcopy(self.local1)
        local["revision"] = 2
        r = self.resolve(profiles={"IR-X1": local})
        self.assertIn("CITY:PROFILE_FINGERPRINT_STALE", r["findings"])

    def test_date_limits_are_enforced(self):
        self.assertIn("OUTSIDE_EFFECTIVE_DATE",
                      self.resolve(when="2025-06-01")["findings"][0])
        later = synthetic_profile("CITY-1", "city", "IR-X1", {"TEST:A": "a"},
                                  start="2026-07-01")
        self.assertIn("OUTSIDE_EFFECTIVE_DATE",
                      self.resolve(profiles={"IR-X1": later})["findings"][0])

    def test_change_date_or_version_changes_snapshot(self):
        first = self.resolve()
        changed_date = self.resolve(when="2026-06-02")
        v2 = synthetic_profile("CITY-1", "city", "IR-X1", {"TEST:A": "a"}, revision=2)
        changed_version = self.resolve(profiles={"IR-X1": v2})
        self.assertNotEqual(first["rulebook_snapshot_hash"], changed_date["rulebook_snapshot_hash"])
        self.assertNotEqual(first["rulebook_snapshot_hash"], changed_version["rulebook_snapshot_hash"])

    def test_national_city_conflict_requires_review(self):
        bad = synthetic_profile("CITY-1", "city", "IR-X1", {"TEST:SHARED": "different"})
        result = self.resolve(profiles={"IR-X1": bad})
        self.assertEqual(result["status"], "CONFLICT_REVIEW_REQUIRED")
        self.assertFalse(result["legal_compliance"])

    def test_claimed_authority_cannot_be_self_attested(self):
        deceptive = synthetic_profile("CITY-1", "city", "IR-X1", {"TEST:A": "a"}, qualified=True)
        result = self.resolve(profiles={"IR-X1": deceptive})
        self.assertIn("UNTRUSTED_AUTHORITY_FORBIDDEN", result["findings"][0])

    def test_missing_synthetic_marker_fails(self):
        fake = deepcopy(self.local1)
        fake["source_marker"] = "OFFICIAL"
        fake["fingerprint"] = digest({k: v for k, v in fake.items() if k != "fingerprint"})
        result = self.resolve(profiles={"IR-X1": fake})
        self.assertIn("NON_REGULATORY_MARKER_REQUIRED", result["findings"][0])

    def test_determinism_and_no_input_mutation(self):
        original = deepcopy(self.brief)
        r1, r2 = self.resolve(), self.resolve()
        self.assertEqual(r1, r2)
        self.assertEqual(self.brief, original)
        self.assertEqual(r1["status"], "SYNTHETIC_CONTRACT_ONLY")
        self.assertFalse(r1["legal_compliance"])


    def test_conceptual_policy_has_permanent_nonlegal_label(self):
        status = classify_two_tier_policy(
            self.brief, "CONCEPTUAL", geometry_gate={"status": "PASS"})
        self.assertEqual(status["status"], "CONCEPTUAL_POLICY_ELIGIBLE_TEST_ONLY")
        self.assertEqual(status["label_fa"], "پلان مفهومی")
        self.assertEqual(status["compliance_status"], "NOT_REQUESTED")
        self.assertFalse(status["legally_approved"])

    def test_conceptual_not_blocked_by_missing_parcel_authority(self):
        status = classify_two_tier_policy(
            self.brief, "CONCEPTUAL", geometry_gate={"status": "PASS"},
            parcel_evidence=None, rule_resolution=None)
        self.assertEqual(status["status"], "CONCEPTUAL_POLICY_ELIGIBLE_TEST_ONLY")
        self.assertIn("PARCEL_AND_PERMIT_REQUIREMENTS_NOT_VERIFIED",
                      status["limitations"])

    def test_controlled_requires_specific_parcel_evidence(self):
        status = classify_two_tier_policy(
            self.brief, "CONTROLLED", geometry_gate={"status": "PASS"},
            rule_resolution=self.resolve())
        self.assertEqual(status["status"], "INPUT_REQUIRED")
        self.assertIn("PARCEL_AUTHORITY_EVIDENCE", status["missing"])
        self.assertFalse(status["legally_approved"])

    def test_controlled_rejects_synthetic_profile_even_with_parcel(self):
        status = classify_two_tier_policy(
            self.brief, "CONTROLLED", geometry_gate={"status": "PASS"},
            parcel_evidence={"sample": "synthetic"},
            rule_resolution=self.resolve())
        self.assertEqual(status["status"], "AUTHORITY_REVIEW_REQUIRED")
        self.assertFalse(status["legally_approved"])

    def test_self_attested_qualified_rule_cannot_issue_compliance(self):
        status = classify_two_tier_policy(
            self.brief, "CONTROLLED", geometry_gate={"status": "PASS"},
            parcel_evidence={"sample": "synthetic"},
            rule_resolution={"status": "QUALIFIED_IN_SCOPE"})
        self.assertNotEqual(status["compliance_status"], "CHECKED_IN_SCOPE")
        self.assertFalse(status["legally_approved"])

    def test_invalid_geometry_blocks_both_tiers(self):
        for tier in ("CONCEPTUAL", "CONTROLLED"):
            with self.subTest(tier=tier):
                status = classify_two_tier_policy(
                    self.brief, tier, geometry_gate={"status": "FAIL"},
                    parcel_evidence={"sample": "synthetic"}, rule_resolution=self.resolve())
                self.assertEqual(status["status"], "GEOMETRY_NOT_VALIDATED")
                self.assertFalse(status["legally_approved"])

    def test_controlled_reports_coverage_and_conflict_without_pass(self):
        for resolution, expected in (
            ({"status": "RULE_COVERAGE_REQUIRED"}, "SOURCE_COVERAGE_REQUIRED"),
            ({"status": "CONFLICT_REVIEW_REQUIRED"}, "CONFLICT"),
        ):
            with self.subTest(expected=expected):
                status = classify_two_tier_policy(
                    self.brief, "CONTROLLED", geometry_gate={"status": "PASS"},
                    parcel_evidence={"sample": "synthetic"}, rule_resolution=resolution)
                self.assertEqual(status["compliance_status"], expected)
                self.assertFalse(status["legally_approved"])

    def test_invalid_tier_or_public_brief_fails_closed(self):
        unknown = classify_two_tier_policy(
            self.brief, "AUTO_COMPLIANT", geometry_gate={"status": "PASS"})
        self.assertEqual(unknown["status"], "INVALID_TIER")
        extra = classify_two_tier_policy(
            {**self.brief, "bedrooms": 3}, "CONCEPTUAL",
            geometry_gate={"status": "PASS"})
        self.assertEqual(extra["status"], "INPUT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
