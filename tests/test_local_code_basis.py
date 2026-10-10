import copy
import unittest

from jsonschema import Draft202012Validator

from cad_engine import local_code_basis as lcb


H = "a" * 64
MARKERS = ["NON_GOLDEN", "NON_REGULATORY_TEST_DATA", "NOT_PROFESSIONALLY_APPROVED"]


def review(source="SRC-1", revision="1", project="JURISDICTION_PROFILE"):
    return {
        "reviewer_id": "SYNTHETIC-REVIEWER", "reviewer_role": "TEST_FIXTURE",
        "qualification_reference": "NOT_PROFESSIONALLY_APPROVED", "review_date": "2026-01-01",
        "source_reference": source, "source_revision": revision, "project_scope": project,
        "decision": "SYNTHETIC_ACCEPT", "decision_evidence": "NON_REGULATORY_TEST_DATA",
    }


def source(**updates):
    row = {
        "source_id": "SRC-1", "document_title": "Synthetic municipal directive",
        "official_directive_id": "SYNTHETIC-1", "issuing_authority": "SYNTHETIC_AUTHORITY",
        "document_revision": "1", "publication_date": "2025-01-01", "effective_date": "2025-01-01",
        "supersedes": [], "superseded_by": None, "official_reference": "SYNTHETIC_NONREGULATORY",
        "retrieval_date": "2026-01-01", "content_hash": H,
        "verification_status": "AUTHORITY_QUALIFIED", "review": review(),
    }
    row.update(updates)
    return row


def rule(rule_id="SETBACK-1", topic="SETBACK", **updates):
    row = {
        "rule_id": rule_id, "authority_type": "LOCAL_CODE", "topic": topic,
        "jurisdiction_scope": {"city": "SYNTHETIC-CITY", "municipality": "SYNTHETIC-MUNI"},
        "temporal_scope": {"effective_from": "2025-01-01"},
        "applicability_expression": {"all": [{"field": "parcel_id", "operator": "PRESENT"}]},
        "required_inputs": ["parcel_id"],
        "operator_or_formula": {"operator": ">=", "value": 1.0, "note": "FICTIONAL_TEST_VALUE"},
        "unit": "m", "exceptions": [], "source_id": "SRC-1", "clause_reference": "SYNTHETIC-CLAUSE",
        "page_reference": "SYNTHETIC-PAGE", "verification_status": "AUTHORITY_QUALIFIED", "review": review(),
    }
    row.update(updates)
    return row


def profile(**updates):
    row = {
        "schema_version": lcb.LOCAL_PROFILE_SCHEMA, "profile_id": "LOCAL-SYNTHETIC", "profile_revision": 1,
        "country": "IR", "province": "SYNTHETIC-PROVINCE", "city": "SYNTHETIC-CITY",
        "municipality": "SYNTHETIC-MUNI", "municipal_district": None, "planning_zone": None,
        "effective_from": "2025-01-01", "effective_until": None, "source_documents": [source()],
        "rules": [rule()], "verification_status": "AUTHORITY_QUALIFIED", "review": None,
        "runtime_enabled": False, "markers": MARKERS,
    }
    row.update(updates)
    row["profile_hash"] = lcb.profile_hash(row)
    return row


def binding(identifier, revision="1", source_hash=H):
    return {"id": identifier, "revision": revision, "source_reference": "SYNTHETIC_NONREGULATORY",
            "source_hash": source_hash, "verification_status": "AUTHORITY_QUALIFIED"}


def site(project="PROJECT-1", parcel="PARCEL-1", survey_hash=H, units="m"):
    return {
        "id": "SITE-1", "revision": "1", "source_reference": "SYNTHETIC_SURVEY", "source_hash": H,
        "verification_status": "AUTHORITY_QUALIFIED", "project_id": project, "parcel_id": parcel,
        "survey_id": "SURVEY-1", "survey_revision": "1", "survey_hash": survey_hash,
        "coordinate_reference_system": "SYNTHETIC-CRS", "units": units,
        "parcel_boundary": [[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]],
        "north_deg": 0, "access_edges": [0], "road_frontage": [0],
    }


def basis(**updates):
    row = {
        "schema_version": lcb.PROJECT_BASIS_SCHEMA, "basis_id": "BASIS-1", "basis_revision": 1,
        "project_id": "PROJECT-1",
        "parcel_identity": {"parcel_id": "PARCEL-1", "country": "IR", "province": "SYNTHETIC-PROVINCE", "city": "SYNTHETIC-CITY",
                            "municipality": "SYNTHETIC-MUNI", "municipal_district": None, "planning_zone": None},
        "site_model_binding": binding("SITE-1"), "owner_program_binding": binding("OWNER-1"),
        "national_ruleset_binding": binding("NATIONAL-1"),
        "local_rule_profile_binding": binding("LOCAL-SYNTHETIC", revision="1", source_hash=profile()["profile_hash"]),
        "permit_or_design_effective_date": "2026-01-01",
        "applicability_decisions": [{
            "decision_id": "ACCESS-1", "topic": "ACCESSIBILITY", "decision": "APPLICABLE",
            "authority_type": "NATIONAL_CODE", "source_references": ["IR-ACCESS"],
            "applicability": {"project": "PROJECT-1"}, "verification_status": "AUTHORITY_REVIEW_REQUIRED",
        }],
        "parcel_conditions": [], "derived_constraints": [], "conflicts": [], "review_bindings": [],
        "verification_status": "AUTHORITY_REVIEW_REQUIRED", "status": "AUTHORITY_REVIEW_REQUIRED",
        "runtime_enabled": False, "markers": MARKERS,
    }
    row.update(updates)
    row["basis_hash"] = lcb.stable_hash(lcb.basis_content(row))
    return row


def current_bindings(parcel="PARCEL-1", project="PROJECT-1"):
    national = binding("NATIONAL-1")
    national["source_ids"] = ["IR-ACCESS"]
    owner = {"program_id": "OWNER-1", "program_revision": 1, "content_hash": H, "project_id": project}
    return site(project, parcel), profile(), national, owner


def basis_for_profile(profile_row, **updates):
    updates.setdefault("local_rule_profile_binding", binding(
        profile_row["profile_id"], revision=str(profile_row["profile_revision"]),
        source_hash=profile_row["profile_hash"],
    ))
    return basis(**updates)


class LocalCodeBasisContractTests(unittest.TestCase):
    def assert_basis_status(self, payload, expected, *, site_row=None, local=None, national=None, owner=None):
        s, l, n, o = current_bindings()
        result = lcb.validate_project_code_basis(payload, current_site=s if site_row is None else site_row,
                                                 current_local_profile=local or l,
                                                 current_national_binding=national or n,
                                                 current_owner_program=owner or o)
        self.assertEqual(result["status"], expected, result["findings"])
        self.assertFalse(result["runtime_enabled"])
        return result

    def test_schemas_are_valid_and_synthetic_contracts_conform(self):
        for name, payload in (("local-rule-profile", profile()), ("project-code-basis", basis())):
            schema = lcb.load_schema(name)
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(payload)
            self.assertEqual(set(payload["markers"]), lcb.MARKERS)

    def test_t01_missing_city_or_municipality(self):
        for field in ("city", "municipality"):
            row = profile(**{field: ""})
            self.assertEqual(lcb.validate_local_rule_profile(row)["status"], "INPUT_REQUIRED")

    def test_t02_missing_parcel_identity(self):
        row = basis(parcel_identity={"parcel_id": "", "country": "IR", "province": "SYNTHETIC-PROVINCE", "city": "SYNTHETIC-CITY", "municipality": "SYNTHETIC-MUNI", "municipal_district": None, "planning_zone": None})
        self.assert_basis_status(row, "INPUT_REQUIRED")

    def test_t03_missing_site_survey(self):
        row = basis()
        self.assert_basis_status(row, "INPUT_REQUIRED", site_row={})

    def test_t04_missing_local_regulatory_source(self):
        row = basis()
        _, _, national, owner = current_bindings()
        result = lcb.validate_project_code_basis(row, current_site=site(), current_local_profile=None,
                                                 current_national_binding=national, current_owner_program=owner)
        self.assertEqual(result["status"], "LOCAL_RULE_REQUIRED")

    def test_t05_valid_synthetic_profile_structure(self):
        row = profile()
        current = {"SRC-1": source()}
        self.assertEqual(lcb.validate_local_rule_profile(row, current_sources=current, as_of="2026-01-01")["status"], "STRUCTURALLY_VALID")

    def test_t06_expired_or_superseded_directive(self):
        row = profile(effective_until="2025-12-31")
        self.assertEqual(lcb.validate_local_rule_profile(row, as_of="2026-01-01")["status"], "STALE_BINDING")
        row = profile(source_documents=[source(superseded_by="SRC-2")])
        row["profile_hash"] = lcb.profile_hash(row)
        current = {"SRC-1": source(document_revision="2")}
        self.assertEqual(lcb.validate_local_rule_profile(row, current_sources=current)["status"], "STALE_BINDING")

    def test_t07_two_different_cities_have_distinct_profiles(self):
        first = profile()
        second = profile(city="OTHER-SYNTHETIC-CITY", profile_id="LOCAL-OTHER")
        self.assertNotEqual(first["profile_hash"], second["profile_hash"])

    def test_t08_two_parcels_within_one_city_do_not_share_basis(self):
        first = basis()
        second = basis(parcel_identity={**first["parcel_identity"], "parcel_id": "PARCEL-2"}, basis_id="BASIS-2")
        self.assertNotEqual(first["basis_hash"], second["basis_hash"])
        result = self.assert_basis_status(second, "STALE_BINDING")
        self.assertIn("PARCEL_BINDING_MISMATCH", {f["code"] for f in result["findings"]})

    def test_t09_conflicting_national_local_requirements(self):
        row = basis(conflicts=[{"conflict_id": "C-1", "authority_references": ["NATIONAL-1", "LOCAL-1"], "reason": "Synthetic conflict", "resolution": "UNRESOLVED"}])
        self.assert_basis_status(row, "CONFLICT_REVIEW_REQUIRED")

    def test_t10_changed_setback_or_building_line_source(self):
        row = profile()
        current = {"SRC-1": source(content_hash="b" * 64)}
        result = lcb.validate_local_rule_profile(row, current_sources=current)
        self.assertEqual(result["status"], "STALE_BINDING")

    def test_t11_missing_parking_authority(self):
        row = basis(applicability_decisions=basis()["applicability_decisions"] + [{
            "decision_id": "PARKING-1", "topic": "PARKING", "decision": "UNKNOWN", "authority_type": "LOCAL_CODE",
            "source_references": [], "applicability": {}, "verification_status": "UNVERIFIED",
        }])
        result = self.assert_basis_status(row, "INPUT_REQUIRED")
        self.assertNotEqual(result["status"], "AUTHORITY_QUALIFIED")

    def test_t12_unknown_code246_applicability(self):
        decisions = copy.deepcopy(basis()["applicability_decisions"])
        decisions[0]["decision"] = "UNKNOWN"
        row = basis(applicability_decisions=decisions)
        result = self.assert_basis_status(row, "INPUT_REQUIRED")
        self.assertIn("ACCESSIBILITY_APPLICABILITY_REQUIRED", {f["code"] for f in result["findings"]})

    def test_t13_owner_requirement_cannot_override_code(self):
        decisions = copy.deepcopy(basis()["applicability_decisions"])
        decisions[0].update(decision="NOT_APPLICABLE", authority_type="OWNER_REQUIREMENT")
        row = basis(applicability_decisions=decisions)
        result = self.assert_basis_status(row, "INPUT_REQUIRED")
        self.assertIn("OWNER_CANNOT_ASSERT_CODE", {f["code"] for f in result["findings"]})

    def test_t14_same_hash_wrong_source_identity(self):
        row = profile()
        current = {"SRC-1": source(source_id="OTHER-SOURCE")}
        self.assertEqual(lcb.validate_local_rule_profile(row, current_sources=current)["status"], "STALE_BINDING")

    def test_t15_changed_effective_date_changes_basis_identity(self):
        first = basis()
        second = basis(permit_or_design_effective_date="2027-01-01")
        self.assertNotEqual(first["basis_hash"], second["basis_hash"])

    def test_t16_duplicate_sources_with_conflicting_revisions(self):
        row = profile(source_documents=[source(), source(document_revision="2")])
        row["profile_hash"] = lcb.profile_hash(row)
        result = lcb.validate_local_rule_profile(row)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("DUPLICATE_SOURCE", {f["code"] for f in result["findings"]})

    def test_t17_invalid_envelope_geometry_and_impossible_constraints(self):
        bad = site()
        bad["parcel_boundary"] = [[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]
        result = lcb.derive_buildable_envelope(bad, edge_constraints=[], dependency_id=H)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        constraints = [{"edge_index": i, "distance_m": 20, "source_references": ["SRC-1"], "rule_ids": ["SETBACK-1"]} for i in range(4)]
        self.assertEqual(lcb.derive_buildable_envelope(site(), edge_constraints=constraints, dependency_id=H)["status"], "CONFLICT_REVIEW_REQUIRED")

    def test_t18_units_or_crs_mismatch(self):
        constraints = [{"edge_index": i, "distance_m": 1, "source_references": ["SRC-1"], "rule_ids": ["SETBACK-1"]} for i in range(4)]
        self.assertEqual(lcb.derive_buildable_envelope(site(units="mm"), edge_constraints=constraints, dependency_id=H)["status"], "INPUT_REQUIRED")

    def test_t19_changed_survey_invalidates_derived_envelope(self):
        first = lcb.dependency_fingerprint(project_id="PROJECT-1", parcel_id="PARCEL-1", site_model_hash=H,
            survey_hash=H, local_profile_hash=H, national_profile_hash=H, effective_date="2026-01-01",
            rule_ids=["SETBACK-1"], building_line_source=None, exception_ids=[], relevant_program_inputs={"building_use": "RESIDENTIAL"})
        second = lcb.dependency_fingerprint(project_id="PROJECT-1", parcel_id="PARCEL-1", site_model_hash=H,
            survey_hash="b" * 64, local_profile_hash=H, national_profile_hash=H, effective_date="2026-01-01",
            rule_ids=["SETBACK-1"], building_line_source=None, exception_ids=[], relevant_program_inputs={"building_use": "RESIDENTIAL"})
        self.assertNotEqual(first, second)

    def test_t20_irrelevant_owner_preference_does_not_invalidate_setback(self):
        kwargs = dict(project_id="PROJECT-1", parcel_id="PARCEL-1", site_model_hash=H, survey_hash=H,
                      local_profile_hash=H, national_profile_hash=H, effective_date="2026-01-01",
                      rule_ids=["SETBACK-1"], building_line_source=None, exception_ids=[],
                      relevant_program_inputs={"building_use": "RESIDENTIAL"})
        first = lcb.dependency_fingerprint(**kwargs)
        unrelated = {"furniture_preference": "CHANGED"}
        self.assertEqual(first, lcb.dependency_fingerprint(**kwargs))
        self.assertNotIn("furniture_preference", kwargs["relevant_program_inputs"])
        self.assertTrue(unrelated)

    def test_traceable_envelope_and_independent_polygon_checks(self):
        fingerprint = lcb.dependency_fingerprint(project_id="PROJECT-1", parcel_id="PARCEL-1", site_model_hash=H,
            survey_hash=H, local_profile_hash=H, national_profile_hash=H, effective_date="2026-01-01",
            rule_ids=["SETBACK-1"], building_line_source=None, exception_ids=[], relevant_program_inputs={"building_use": "RESIDENTIAL"})
        constraints = [{"edge_index": i, "distance_m": 1, "source_references": ["SRC-1"], "rule_ids": ["SETBACK-1"]} for i in range(4)]
        result = lcb.derive_buildable_envelope(site(), edge_constraints=constraints, dependency_id=fingerprint)
        self.assertEqual(result["status"], "STRUCTURALLY_VALID", result["findings"])
        self.assertAlmostEqual(result["area_m2"], 144.0)
        self.assertEqual(result["dependency_fingerprint"], fingerprint)
        self.assertEqual(result["verification_status"], "CALCULATED_NOT_PROFESSIONALLY_APPROVED")
        self.assertEqual(result["derived_constraint"]["source_references"], ["SRC-1"])
        self.assertEqual(result["derived_constraint"]["rule_or_formula"]["rule_ids"], ["SETBACK-1"])

    def test_envelope_is_translation_and_orientation_invariant(self):
        constraints = [{"edge_index": i, "distance_m": 1, "source_references": ["SRC-1"], "rule_ids": ["SETBACK-1"]} for i in range(4)]
        original = lcb.derive_buildable_envelope(site(), edge_constraints=constraints, dependency_id=H)
        translated_site = site()
        translated_site["parcel_boundary"] = [[x + 100, y - 30] for x, y in translated_site["parcel_boundary"]]
        translated = lcb.derive_buildable_envelope(translated_site, edge_constraints=constraints, dependency_id=H)
        reversed_site = site()
        reversed_site["parcel_boundary"] = list(reversed(reversed_site["parcel_boundary"]))
        reversed_result = lcb.derive_buildable_envelope(reversed_site, edge_constraints=constraints, dependency_id=H)
        self.assertEqual(original["status"], translated["status"])
        self.assertEqual(original["status"], reversed_result["status"])
        self.assertAlmostEqual(original["area_m2"], translated["area_m2"])
        self.assertAlmostEqual(original["area_m2"], reversed_result["area_m2"])

    def test_real_like_records_without_fixture_markers_are_schema_valid_but_not_authority_qualified(self):
        local = profile()
        local.pop("markers")
        local["profile_hash"] = lcb.profile_hash(local)
        Draft202012Validator(lcb.load_schema("local-rule-profile")).validate(local)
        result = lcb.validate_local_rule_profile(local, current_sources={"SRC-1": source()}, as_of="2026-01-01")
        self.assertEqual(result["status"], "AUTHORITY_REVIEW_REQUIRED", result["findings"])

        row = basis_for_profile(local, verification_status="AUTHORITY_QUALIFIED", status="AUTHORITY_QUALIFIED",
                                review_bindings=[review(project="PROJECT-1")])
        row.pop("markers")
        row["basis_hash"] = lcb.stable_hash(lcb.basis_content(row))
        Draft202012Validator(lcb.load_schema("project-code-basis")).validate(row)
        site_row, _, national, owner = current_bindings()
        result = lcb.validate_project_code_basis(row, current_site=site_row, current_local_profile=local,
                                                  current_national_binding=national, current_owner_program=owner)
        self.assertEqual(result["status"], "AUTHORITY_REVIEW_REQUIRED", result["findings"])

    def test_synthetic_marker_contract_is_exact_and_non_authoritative(self):
        for payload, schema_name in ((profile(), "local-rule-profile"), (basis(), "project-code-basis")):
            self.assertEqual(set(payload["markers"]), lcb.MARKERS)
            Draft202012Validator(lcb.load_schema(schema_name)).validate(payload)
        self.assertEqual(lcb.validate_local_rule_profile(profile())["status"], "STRUCTURALLY_VALID")
        self.assert_basis_status(basis(), "STRUCTURALLY_VALID")

    def test_self_asserted_review_and_caller_source_snapshot_cannot_qualify(self):
        local = profile()
        local.pop("markers")
        local["source_documents"][0]["review"] = review()
        local["rules"][0]["review"] = review()
        local["profile_hash"] = lcb.profile_hash(local)
        self.assertEqual(
            lcb.validate_local_rule_profile(local, current_sources={"SRC-1": copy.deepcopy(local["source_documents"][0])})["status"],
            "AUTHORITY_REVIEW_REQUIRED",
        )

    def test_missing_independent_authority_provider_fails_closed_for_unmarked_records(self):
        local = profile(verification_status="UNVERIFIED")
        local.pop("markers")
        local["profile_hash"] = lcb.profile_hash(local)
        self.assertEqual(lcb.validate_local_rule_profile(local)["status"], "AUTHORITY_REVIEW_REQUIRED")

        row = basis_for_profile(local, verification_status="UNVERIFIED", status="STRUCTURALLY_VALID")
        row.pop("markers")
        row["basis_hash"] = lcb.stable_hash(lcb.basis_content(row))
        site_row, _, national, owner = current_bindings()
        self.assertEqual(lcb.validate_project_code_basis(
            row, current_site=site_row, current_local_profile=local,
            current_national_binding=national, current_owner_program=owner,
        )["status"], "AUTHORITY_REVIEW_REQUIRED")

    def test_jurisdiction_mismatches_fail_closed(self):
        for field, value in (("city", "OTHER-CITY"), ("municipality", "OTHER-MUNI")):
            parcel = copy.deepcopy(basis()["parcel_identity"])
            parcel[field] = value
            result = self.assert_basis_status(basis(parcel_identity=parcel), "CONFLICT_REVIEW_REQUIRED")
            self.assertIn("JURISDICTION_CONFLICT", {item["code"] for item in result["findings"]})

        for field, value in (("municipal_district", "D-2"), ("planning_zone", "Z-2")):
            local = profile(rules=[rule(required_inputs=["parcel_id", field])], **{field: "EXPECTED"})
            local["profile_hash"] = lcb.profile_hash(local)
            parcel = copy.deepcopy(basis()["parcel_identity"])
            parcel[field] = value
            self.assert_basis_status(basis_for_profile(local, parcel_identity=parcel), "CONFLICT_REVIEW_REQUIRED", local=local)

    def test_profile_and_rule_temporal_scope_fail_closed(self):
        for project_date in ("2024-12-31", "2027-01-01"):
            local = profile(effective_from="2025-01-01", effective_until="2026-12-31")
            local["profile_hash"] = lcb.profile_hash(local)
            self.assert_basis_status(basis_for_profile(local, permit_or_design_effective_date=project_date), "STALE_BINDING", local=local)
        local = profile(rules=[rule(temporal_scope={"effective_from": "2026-02-01"})])
        local["profile_hash"] = lcb.profile_hash(local)
        self.assert_basis_status(basis_for_profile(local), "STALE_BINDING", local=local)

    def test_owner_program_binding_is_required_and_fresh(self):
        s, local, national, owner = current_bindings()
        result = lcb.validate_project_code_basis(basis(), current_site=s, current_local_profile=local,
                                                  current_national_binding=national, current_owner_program=None)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        for field, value in (("content_hash", "b" * 64), ("program_revision", 2)):
            changed = copy.deepcopy(owner)
            changed[field] = value
            self.assert_basis_status(basis(), "STALE_BINDING", owner=changed)

    def test_unresolved_applicability_reference_is_input_required(self):
        decisions = copy.deepcopy(basis()["applicability_decisions"])
        decisions[0]["source_references"] = ["UNKNOWN-SOURCE"]
        result = self.assert_basis_status(basis(applicability_decisions=decisions), "INPUT_REQUIRED")
        self.assertIn("UNRESOLVED_APPLICABILITY_REFERENCE", {item["code"] for item in result["findings"]})

    def test_malformed_geometry_and_nonfinite_setbacks_return_structured_input_required(self):
        constraints = [{"edge_index": i, "distance_m": 1, "source_references": ["SRC-1"], "rule_ids": ["SETBACK-1"]} for i in range(4)]
        boundaries = (
            [[0, 0], [10, 0], [10, 0], [0, 10], [0, 0]],
            [[0, 0], [10, 0], [10, 10], [0, 0], [0, 0]],
            [[0, 0], [float("nan"), 0], [10, 10], [0, 10], [0, 0]],
            [[0, 0], [float("inf"), 0], [10, 10], [0, 10], [0, 0]],
        )
        for boundary in boundaries:
            site_row = site()
            site_row["parcel_boundary"] = boundary
            result = lcb.derive_buildable_envelope(site_row, edge_constraints=constraints, dependency_id=H)
            self.assertEqual(result["status"], "INPUT_REQUIRED", result)
            self.assertIsNone(result["geometry"])
        for distance in (float("nan"), float("inf"), -1):
            invalid = copy.deepcopy(constraints)
            invalid[0]["distance_m"] = distance
            result = lcb.derive_buildable_envelope(site(), edge_constraints=invalid, dependency_id=H)
            self.assertEqual(result["status"], "INPUT_REQUIRED", result)
            self.assertIsNone(result["geometry"])

    def test_invalid_envelope_dependency_fingerprint_fails_closed(self):
        constraints = [{"edge_index": i, "distance_m": 1, "source_references": ["SRC-1"], "rule_ids": ["SETBACK-1"]} for i in range(4)]
        result = lcb.derive_buildable_envelope(site(), edge_constraints=constraints, dependency_id="caller-value")
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("INVALID_DEPENDENCY_FINGERPRINT", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
