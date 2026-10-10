import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from cad_engine import owner_program as op
from cad_engine import residential_foundation as foundation


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "standards/test-suites/residential/fixtures/owner-program-v2"
SCHEMAS = ROOT / "standards/test-suites/residential"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def binding(source_hash="b" * 64):
    return {
        "id": "SYNTHETIC",
        "version": "1",
        "source_reference": "SYNTHETIC_NONREGULATORY",
        "source_hash": source_hash,
        "verification_status": "VERIFIED",
    }


def authoritative_bindings(site=None, national=None, local=None):
    return {
        "site_binding": copy.deepcopy(site or binding()),
        "national_ruleset_binding": copy.deepcopy(national or binding()),
        "local_profile_binding": copy.deepcopy(local or binding()),
    }


def geometry_fact(evidence_input_id):
    return {
        "field_id": "geometry_feasibility",
        "value": "VERIFIED",
        "unit": None,
        "source_type": "SYNTHETIC_GEOMETRY_VALIDATOR",
        "source_reference": "SYNTHETIC_NON_GOLDEN_GEOMETRY",
        "source_hash": "e" * 64,
        "authority_type": "DERIVED_GEOMETRY",
        "verification_status": "VERIFIED",
        "revision": 1,
        "dependencies": [evidence_input_id],
    }


def geometry_evidence_for(draft, site=None, national=None, local=None):
    site = site or binding()
    national = national or binding()
    local = local or binding()
    evidence_id = op.evidence_input_identity(
        draft, site_binding=site, national_ruleset_binding=national, local_profile_binding=local
    )
    return geometry_fact(evidence_id)


def rehash_resolved(payload):
    basis = {
        key: payload[key]
        for key in (
            "project_id", "program_id", "program_revision", "owner_program_hash",
            "canonical_unit_program_hash", "evidence_input_id", "site_binding", "national_ruleset_binding",
            "local_profile_binding", "derived_project_facts", "geometry_feasibility",
        )
    }
    payload["resolved_id"] = f"resolved-{foundation.stable_hash(basis)[:20]}"
    payload.pop("resolution_hash", None)
    payload["resolution_hash"] = op._json_hash(payload)


def legacy_program():
    return {
        "program_id": "legacy-program",
        "questionnaire_version": "0.5.0",
        "answers_hash": "a" * 64,
        "required_spaces": ["LIVING", "KITCHEN"],
        "optional_spaces": ["BALCONY"],
        "minimum_counts": {"BEDROOM": 2},
        "preferred_counts": {},
        "adjacency_preferences": [{"from": "KITCHEN", "to": "LIVING", "strength": "MANDATORY"}],
        "avoid_adjacency": [{"from": "BEDROOM", "to": "ENTRY", "strength": "PREFERRED"}],
        "privacy_tiers": {"BEDROOM": "PRIVATE"},
        "day_night_zoning": {},
        "guest_family_zoning": {},
        "service_zoning": {},
        "furniture_expectations": [],
        "accessibility_needs": [],
        "priority_weights": {"privacy": 1},
        "confirmed": True,
    }


def legacy_generation_input():
    return {
        "program": {
            "answers_hash": "a" * 64,
            "questionnaire_version": "0.5.0",
            "confirmed": True,
            "units_per_floor": 1,
            "unit_types": [
                {
                    "unit_type_id": "A",
                    "count": 1,
                    "bedrooms": 2,
                    "target_usable_area_min_m2": 70,
                    "target_usable_area_max_m2": 90,
                    "requirement_strength": "MANDATORY",
                }
            ],
        }
    }


class OwnerProgramV2FixtureTests(unittest.TestCase):
    def test_v2_schemas_and_schema_qualified_fixtures(self):
        draft_schema = op.load_schema("owner-program-draft-v2")
        resolved_schema = op.load_schema("resolved-generation-input-v2")
        Draft202012Validator.check_schema(draft_schema)
        Draft202012Validator.check_schema(resolved_schema)
        draft_validator = Draft202012Validator(draft_schema)
        resolved_validator = Draft202012Validator(resolved_schema)
        for filename in json.loads((FIXTURES / "manifest.json").read_text())["fixtures"]:
            row = json.loads((FIXTURES / filename).read_text())
            if filename == "missing_input_program.json":
                self.assertTrue(list(draft_validator.iter_errors(row["draft"])))
            else:
                draft_validator.validate(row["draft"])
            if row["resolution"] and row["resolution"]["expected_status"] in {
                "VALIDATED_INPUT",
                "NEEDS_GEOMETRIC_FEASIBILITY_CHECK",
                "LOCAL_RULE_REQUIRED",
            }:
                spec = row["resolution"]
                resolved = op.resolve_generation_input(
                    row["draft"],
                    site_binding=spec["site_binding"],
                    national_ruleset_binding=spec["national_ruleset_binding"],
                    local_profile_binding=spec["local_profile_binding"],
                    derived_project_facts=spec["derived_project_facts"],
                    geometry_feasibility=spec["geometry_feasibility"],
                    current_bindings=authoritative_bindings(
                        spec["site_binding"], spec["national_ruleset_binding"], spec["local_profile_binding"]
                    ),
                    current_geometry_evidence=(
                        spec["derived_project_facts"][0]
                        if spec["geometry_feasibility"] == "VERIFIED"
                        else None
                    ),
                )["resolved_input"]
                resolved_validator.validate(resolved)

    def test_official_synthetic_fixture_matrix(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        self.assertEqual(
            manifest["markers"],
            ["NON_GOLDEN", "SYNTHETIC_TEST_INPUT", "NOT_PROFESSIONALLY_APPROVED"],
        )
        self.assertEqual(len(manifest["fixtures"]), 6)
        for filename in manifest["fixtures"]:
            with self.subTest(fixture=filename):
                row = json.loads((FIXTURES / filename).read_text())
                self.assertEqual(set(row["markers"]), set(manifest["markers"]))
                draft_result = op.validate_owner_program_draft(row["draft"])
                self.assertEqual(draft_result["status"], row["expected_draft_status"])
                self.assertFalse(draft_result["runtime_enabled"])
                if row["resolution"]:
                    spec = row["resolution"]
                    resolved = op.resolve_generation_input(
                        row["draft"],
                        site_binding=spec["site_binding"],
                        national_ruleset_binding=spec["national_ruleset_binding"],
                        local_profile_binding=spec["local_profile_binding"],
                        derived_project_facts=spec["derived_project_facts"],
                        geometry_feasibility=spec["geometry_feasibility"],
                        current_bindings=authoritative_bindings(
                            spec["site_binding"], spec["national_ruleset_binding"], spec["local_profile_binding"]
                        ),
                        current_geometry_evidence=(
                            spec["derived_project_facts"][0]
                            if spec["geometry_feasibility"] == "VERIFIED"
                            else None
                        ),
                    )
                    self.assertEqual(resolved["validation"]["status"], spec["expected_status"])
                    self.assertFalse(resolved["resolved_input"]["runtime_enabled"])

    def test_deterministic_serialization_and_hashes(self):
        draft = fixture("valid_residential_program")["draft"]
        baseline = op.validate_owner_program_draft(draft)
        for _ in range(7):
            self.assertEqual(op.validate_owner_program_draft(copy.deepcopy(draft)), baseline)


class OwnerProgramV2MigrationTests(unittest.TestCase):
    def test_v1_contract_and_questionnaire_behavior_remain_available(self):
        schema = json.loads((SCHEMAS / "owner-program.schema.json").read_text())
        self.assertEqual(schema["$id"], "architecture-owner-program/1.0")
        self.assertEqual(foundation.questionnaire_state({})["status"], "INPUT_REQUIRED")
        self.assertEqual(foundation.load_catalog("owner-questionnaire")["schema_version"], "architecture-owner-program/1.0")

    def test_v1_migration_preserves_payload_and_reports_missing_unit_program(self):
        legacy = legacy_program()
        migrated = op.migrate_v1_owner_program(legacy, project_id="project")
        self.assertTrue(migrated["lossless_preservation"])
        self.assertEqual(migrated["draft"]["legacy"]["preserved_payload"], legacy)
        self.assertIn("MATERIAL_INPUT_NOT_PRESENT", {x["code"] for x in migrated["migration_findings"]})
        self.assertTrue(all(x["authority_type"] == "UNKNOWN_LEGACY_SOURCE" for x in migrated["draft"]["provenance"]))
        self.assertEqual(migrated["validation"]["status"], "DRAFT_VALID")
        Draft202012Validator(op.load_schema("owner-program-draft-v2")).validate(migrated["draft"])

    def test_generation_input_adapter_supplies_the_one_canonical_unit_program(self):
        migrated = op.migrate_v1_owner_program(
            legacy_program(), project_id="project", legacy_generation_input=legacy_generation_input()
        )
        self.assertEqual(migrated["migration_findings"], [])
        self.assertEqual(
            migrated["draft"]["unit_program"],
            {
                "units_per_floor": legacy_generation_input()["program"]["units_per_floor"],
                "unit_types": legacy_generation_input()["program"]["unit_types"],
            },
        )
        Draft202012Validator(op.load_schema("owner-program-draft-v2")).validate(migrated["draft"])

    def test_migration_is_deterministic_and_does_not_modify_v1(self):
        legacy = legacy_program()
        before = copy.deepcopy(legacy)
        first = op.migrate_v1_owner_program(legacy, project_id="project", legacy_generation_input=legacy_generation_input())
        second = op.migrate_v1_owner_program(legacy, project_id="project", legacy_generation_input=legacy_generation_input())
        self.assertEqual(first, second)
        self.assertEqual(legacy, before)


class OwnerProgramV2ValidationTests(unittest.TestCase):
    def test_incomplete_draft_is_savable_without_site_or_local_profile(self):
        migrated = op.migrate_v1_owner_program(legacy_program(), project_id="project")
        self.assertEqual(migrated["validation"]["status"], "DRAFT_VALID")
        self.assertNotIn("site_binding", migrated["draft"])

    def test_incomplete_draft_cannot_be_promoted_by_verified_flags(self):
        migrated = op.migrate_v1_owner_program(legacy_program(), project_id="project")
        result = op.resolve_generation_input(
            migrated["draft"],
            site_binding=binding(),
            national_ruleset_binding=binding(),
            local_profile_binding=binding(),
            geometry_feasibility="VERIFIED",
            current_bindings=authoritative_bindings(),
        )
        self.assertEqual(migrated["validation"]["status"], "DRAFT_VALID")
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        codes = {item["code"] for item in result["validation"]["findings"]}
        self.assertIn("INCOMPLETE_UNIT_PROGRAM", codes)
        self.assertIn("UNVERIFIED_MATERIAL_PROVENANCE", codes)

    def test_material_provenance_requires_integrity_and_compatible_authority(self):
        draft = fixture("valid_residential_program")["draft"]
        bad = copy.deepcopy(draft)
        bad["provenance"][0]["source_hash"] = "not-a-hash"
        bad["provenance"][0]["revision"] = 0
        bad["provenance"][0]["source_reference"] = ""
        bad["provenance"][0]["authority_type"] = "DERIVED_GEOMETRY"
        validation = op.validate_owner_program_draft(bad)
        self.assertEqual(validation["status"], "INPUT_REQUIRED")
        codes = {item["code"] for item in validation["findings"]}
        self.assertIn("INVALID_PROVENANCE", codes)
        resolved = op.resolve_generation_input(
            bad, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            geometry_feasibility="VERIFIED", current_bindings=authoritative_bindings(),
        )
        self.assertEqual(resolved["validation"]["status"], "INPUT_REQUIRED")
        self.assertIn("INVALID_FIELD_AUTHORITY", {item["code"] for item in resolved["validation"]["findings"]})

    def test_owner_preference_cannot_authorize_code246_not_applicable(self):
        draft = fixture("valid_residential_program")["draft"]
        regulatory = next(
            item for item in draft["provenance"]
            if item["field_id"] == "preferences.accessibility.regulatory_obligation"
        )
        regulatory["authority_type"] = "OWNER_PREFERENCE"
        result = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            current_bindings=authoritative_bindings(),
        )
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        self.assertIn("INVALID_FIELD_AUTHORITY", {item["code"] for item in result["validation"]["findings"]})

    def test_unknown_or_unverified_accessibility_applicability_fails_resolution_only(self):
        draft = fixture("valid_residential_program")["draft"]
        draft["preferences"]["accessibility"]["regulatory_obligation"] = "UNKNOWN"
        regulatory = next(
            item for item in draft["provenance"]
            if item["field_id"] == "preferences.accessibility.regulatory_obligation"
        )
        regulatory["value"] = "UNKNOWN"
        regulatory["verification_status"] = "UNVERIFIED"
        self.assertEqual(op.validate_owner_program_draft(draft)["status"], "DRAFT_VALID")
        result = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            current_bindings=authoritative_bindings(),
        )
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        codes = {item["code"] for item in result["validation"]["findings"]}
        self.assertIn("ACCESSIBILITY_APPLICABILITY_REQUIRED", codes)
        self.assertIn("UNVERIFIED_MATERIAL_PROVENANCE", codes)

    def test_mandatory_accessibility_overrides_conflicting_owner_preference(self):
        draft = fixture("conditional_accessibility")["draft"]
        draft["preferences"]["accessibility"]["owner_preference"] = "PROHIBIT"
        owner = next(
            item for item in draft["provenance"]
            if item["field_id"] == "preferences.accessibility.owner_preference"
        )
        owner["value"] = "PROHIBIT"
        result = op.validate_owner_program_draft(draft)
        self.assertEqual(result["status"], "DEFINITELY_INVALID")
        self.assertIn("ACCESSIBILITY_AUTHORITY_CONFLICT", {item["code"] for item in result["findings"]})

    def test_geometry_evidence_requires_exact_input_dependency_and_independent_record(self):
        draft = fixture("valid_residential_program")["draft"]
        evidence = geometry_evidence_for(draft)
        evidence["dependencies"] = []
        result = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            derived_project_facts=[evidence], geometry_feasibility="VERIFIED",
            current_bindings=authoritative_bindings(), current_geometry_evidence=evidence,
        )
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        self.assertIn("GEOMETRY_PROOF_REQUIRED", {item["code"] for item in result["validation"]["findings"]})

    def test_geometry_evidence_from_another_project_is_rejected(self):
        original = fixture("valid_residential_program")["draft"]
        evidence = geometry_evidence_for(original)
        other = copy.deepcopy(original)
        other["project_id"] = "OTHER-PROJECT"
        result = op.resolve_generation_input(
            other, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            derived_project_facts=[evidence], geometry_feasibility="VERIFIED",
            current_bindings=authoritative_bindings(), current_geometry_evidence=evidence,
        )
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        self.assertIn("GEOMETRY_PROOF_REQUIRED", {item["code"] for item in result["validation"]["findings"]})

    def test_program_or_unit_change_invalidates_previous_geometry_evidence(self):
        draft = fixture("valid_residential_program")["draft"]
        evidence = geometry_evidence_for(draft)
        resolved = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            derived_project_facts=[evidence], geometry_feasibility="VERIFIED",
            current_bindings=authoritative_bindings(), current_geometry_evidence=evidence,
        )["resolved_input"]
        for mutation in ("program", "unit"):
            changed = copy.deepcopy(draft)
            if mutation == "program":
                changed["program_revision"] += 1
            else:
                changed["unit_program"]["unit_types"][0]["bedrooms"] += 1
            result = op.validate_resolved_generation_input(
                resolved, draft=changed, current_bindings=authoritative_bindings(), current_geometry_evidence=evidence
            )
            self.assertEqual(result["status"], "STALE_BINDING")

    def test_authority_snapshot_change_invalidates_previous_geometry_evidence(self):
        draft = fixture("valid_residential_program")["draft"]
        old = (binding("1" * 64), binding("2" * 64), binding("3" * 64))
        evidence = geometry_evidence_for(draft, *old)
        for index, name in enumerate(("site", "national", "local")):
            changed = list(old)
            changed[index] = binding("9" * 64)
            result = op.resolve_generation_input(
                draft, site_binding=changed[0], national_ruleset_binding=changed[1], local_profile_binding=changed[2],
                derived_project_facts=[evidence], geometry_feasibility="VERIFIED",
                current_bindings=authoritative_bindings(*changed), current_geometry_evidence=evidence,
            )
            with self.subTest(binding=name):
                self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
                self.assertIn("GEOMETRY_PROOF_REQUIRED", {item["code"] for item in result["validation"]["findings"]})

    def test_questionnaire_answers_are_bound_to_content_hash(self):
        draft = fixture("valid_residential_program")["draft"]
        draft["questionnaire_answers"] = {}
        result = op.validate_owner_program_draft(draft)
        self.assertIn("STALE_QUESTIONNAIRE_ANSWERS", {item["code"] for item in result["findings"]})

    def test_caller_verified_bindings_are_not_independent_proof(self):
        draft = fixture("valid_residential_program")["draft"]
        evidence_id = op.evidence_input_identity(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding()
        )
        result = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            geometry_feasibility="VERIFIED",
            derived_project_facts=[geometry_fact(evidence_id)],
            current_geometry_evidence=geometry_fact(evidence_id),
        )
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        self.assertIn("CURRENT_BINDINGS_REQUIRED", {item["code"] for item in result["validation"]["findings"]})

    def test_caller_geometry_verified_flag_requires_evidence_record(self):
        draft = fixture("valid_residential_program")["draft"]
        result = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            geometry_feasibility="VERIFIED", current_bindings=authoritative_bindings(),
        )
        self.assertEqual(result["validation"]["status"], "INPUT_REQUIRED")
        self.assertIn("GEOMETRY_PROOF_REQUIRED", {item["code"] for item in result["validation"]["findings"]})

    def test_cross_project_identity_tamper_fails_even_when_rehashed(self):
        draft = fixture("valid_residential_program")["draft"]
        evidence_id = op.evidence_input_identity(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding()
        )
        evidence = geometry_fact(evidence_id)
        resolved = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            geometry_feasibility="VERIFIED", derived_project_facts=[evidence],
            current_bindings=authoritative_bindings(),
            current_geometry_evidence=evidence,
        )["resolved_input"]
        resolved["project_id"] = "OTHER-PROJECT"
        rehash_resolved(resolved)
        result = op.validate_resolved_generation_input(
            resolved, draft=draft, current_bindings=authoritative_bindings(), current_geometry_evidence=evidence
        )
        self.assertEqual(result["status"], "STALE_BINDING")
        self.assertIn("SOURCE_DRAFT_IDENTITY_MISMATCH", {item["code"] for item in result["findings"]})

    def test_resolution_status_tamper_fails_even_when_rehashed(self):
        draft = fixture("valid_residential_program")["draft"]
        resolved = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            current_bindings=authoritative_bindings(),
        )["resolved_input"]
        self.assertEqual(resolved["resolution_status"], "NEEDS_GEOMETRIC_FEASIBILITY_CHECK")
        resolved["resolution_status"] = "VALIDATED_INPUT"
        rehash_resolved(resolved)
        result = op.validate_resolved_generation_input(resolved, draft=draft, current_bindings=authoritative_bindings())
        self.assertEqual(result["status"], "STALE_BINDING")
        self.assertIn("RESOLUTION_STATUS_MISMATCH", {item["code"] for item in result["findings"]})

    def test_public_validator_rejects_snapshot_missing_finalization_fields(self):
        row = fixture("valid_residential_program")
        draft = row["draft"]
        spec = row["resolution"]
        current_bindings = authoritative_bindings(
            spec["site_binding"], spec["national_ruleset_binding"], spec["local_profile_binding"]
        )
        evidence = spec["derived_project_facts"][0]
        resolved = op.resolve_generation_input(
            draft,
            site_binding=spec["site_binding"],
            national_ruleset_binding=spec["national_ruleset_binding"],
            local_profile_binding=spec["local_profile_binding"],
            derived_project_facts=spec["derived_project_facts"],
            geometry_feasibility=spec["geometry_feasibility"],
            current_bindings=current_bindings,
            current_geometry_evidence=evidence,
        )["resolved_input"]
        self.assertEqual(resolved["resolution_status"], "VALIDATED_INPUT")

        resolved.pop("resolution_status")
        resolved.pop("resolution_hash")
        result = op.validate_resolved_generation_input(
            resolved,
            draft=draft,
            current_bindings=current_bindings,
            current_geometry_evidence=evidence,
        )

        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertTrue(
            {"$.resolution_status", "$.resolution_hash"}
            <= {item["path"] for item in result["findings"]}
        )

    def test_malformed_public_inputs_fail_closed_without_crashing(self):
        for payload in (None, [], {"schema_version": op.SCHEMA_VERSION_DRAFT, "preferences": {"accessibility": []}}):
            with self.subTest(payload=payload):
                result = op.validate_owner_program_draft(payload)
                self.assertIn(result["status"], {"INPUT_REQUIRED", "DEFINITELY_INVALID"})
        result = op.validate_resolved_generation_input([], draft={})
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        resolution = op.resolve_generation_input(
            None, site_binding=None, national_ruleset_binding=None, local_profile_binding=None
        )
        self.assertIsNone(resolution["resolved_input"])
        self.assertEqual(resolution["validation"]["status"], "INPUT_REQUIRED")
        malformed = binding()
        malformed["source_reference"] = {"not-json"}
        resolution = op.resolve_generation_input(
            fixture("valid_residential_program")["draft"], site_binding=malformed,
            national_ruleset_binding=binding(), local_profile_binding=binding(),
            current_bindings=authoritative_bindings(malformed, binding(), binding()),
        )
        self.assertEqual(resolution["validation"]["status"], "INPUT_REQUIRED")
        self.assertIsNone(resolution["resolved_input"]["resolution_hash"])

    def test_provenance_is_required_and_must_match_canonical_value(self):
        draft = fixture("valid_residential_program")["draft"]
        missing = copy.deepcopy(draft)
        missing["provenance"].pop()
        self.assertEqual(op.validate_owner_program_draft(missing)["status"], "INPUT_REQUIRED")
        mismatch = copy.deepcopy(draft)
        mismatch["provenance"][0]["value"] = "fabricated"
        findings = op.validate_owner_program_draft(mismatch)["findings"]
        self.assertIn("PROVENANCE_VALUE_MISMATCH", {x["code"] for x in findings})

    def test_conditional_answer_outside_scope_is_invalid(self):
        draft = fixture("valid_residential_program")["draft"]
        draft["questionnaire_answers"] = {
            "purpose": "OWNER_USE",
            "market": "unsupported out-of-scope answer",
        }
        result = op.validate_owner_program_draft(draft)
        self.assertEqual(result["status"], "DEFINITELY_INVALID")
        self.assertIn("CONDITIONAL_ANSWER_OUT_OF_SCOPE", {x["code"] for x in result["findings"]})

    def test_missing_local_profile_fails_closed(self):
        row = fixture("unknown_local_regulations")
        spec = row["resolution"]
        result = op.resolve_generation_input(
            row["draft"],
            site_binding=spec["site_binding"],
            national_ruleset_binding=spec["national_ruleset_binding"],
            local_profile_binding=spec["local_profile_binding"],
            current_bindings=authoritative_bindings(
                spec["site_binding"], spec["national_ruleset_binding"], spec["local_profile_binding"]
            ),
        )
        self.assertEqual(result["validation"]["status"], "LOCAL_RULE_REQUIRED")

    def test_missing_site_or_national_authority_fails_closed(self):
        draft = fixture("valid_residential_program")["draft"]
        missing = {"id": None, "version": None, "source_reference": None, "source_hash": None, "verification_status": "INPUT_REQUIRED"}
        no_site = op.resolve_generation_input(
            draft, site_binding=missing, national_ruleset_binding=binding(), local_profile_binding=binding(),
            current_bindings=authoritative_bindings(missing, binding(), binding()),
        )
        self.assertEqual(no_site["validation"]["status"], "INPUT_REQUIRED")
        no_national = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=missing, local_profile_binding=binding(),
            current_bindings=authoritative_bindings(binding(), missing, binding()),
        )
        self.assertEqual(no_national["validation"]["status"], "INPUT_REQUIRED")

    def test_changed_source_hash_invalidates_resolution(self):
        draft = fixture("valid_residential_program")["draft"]
        resolved = op.resolve_generation_input(
            draft,
            site_binding=binding("1" * 64),
            national_ruleset_binding=binding("2" * 64),
            local_profile_binding=binding("3" * 64),
            current_bindings=authoritative_bindings(binding("1" * 64), binding("2" * 64), binding("3" * 64)),
        )["resolved_input"]
        current = {
            "site_binding": binding("9" * 64),
            "national_ruleset_binding": binding("2" * 64),
            "local_profile_binding": binding("3" * 64),
        }
        result = op.validate_resolved_generation_input(resolved, draft=draft, current_bindings=current)
        self.assertEqual(result["status"], "STALE_BINDING")

    def test_resolved_identity_is_bound_to_authority_snapshot(self):
        draft = fixture("valid_residential_program")["draft"]
        first = op.resolve_generation_input(
            draft, site_binding=binding("1" * 64), national_ruleset_binding=binding("2" * 64), local_profile_binding=binding("3" * 64),
            current_bindings=authoritative_bindings(binding("1" * 64), binding("2" * 64), binding("3" * 64)),
        )["resolved_input"]
        second = op.resolve_generation_input(
            draft, site_binding=binding("9" * 64), national_ruleset_binding=binding("2" * 64), local_profile_binding=binding("3" * 64),
            current_bindings=authoritative_bindings(binding("9" * 64), binding("2" * 64), binding("3" * 64)),
        )["resolved_input"]
        self.assertNotEqual(first["resolved_id"], second["resolved_id"])
        self.assertNotEqual(first["resolution_hash"], second["resolution_hash"])

    def test_resolved_hash_rejects_post_resolution_mutation(self):
        draft = fixture("valid_residential_program")["draft"]
        resolved = op.resolve_generation_input(
            draft, site_binding=binding(), national_ruleset_binding=binding(), local_profile_binding=binding(),
            current_bindings=authoritative_bindings(),
        )["resolved_input"]
        resolved["derived_project_facts"].append({
            "field_id": "fabricated",
            "value": True,
            "unit": None,
            "source_type": "TEST",
            "source_reference": "TEST",
            "source_hash": "f" * 64,
            "authority_type": "SYSTEM_CALCULATION",
            "verification_status": "VERIFIED",
            "revision": 1,
            "dependencies": [],
        })
        result = op.validate_resolved_generation_input(resolved, draft=draft)
        self.assertEqual(result["status"], "STALE_BINDING")
        self.assertLessEqual({"INVALID_RESOLVED_ID", "INVALID_RESOLUTION_HASH"}, {x["code"] for x in result["findings"]})

    def test_structural_resolution_does_not_claim_geometry_feasibility(self):
        draft = fixture("valid_residential_program")["draft"]
        result = op.resolve_generation_input(
            draft,
            site_binding=binding(),
            national_ruleset_binding=binding(),
            local_profile_binding=binding(),
            current_bindings=authoritative_bindings(),
        )
        self.assertEqual(result["validation"]["status"], "NEEDS_GEOMETRIC_FEASIBILITY_CHECK")
        self.assertFalse(result["validation"]["geometry_feasibility_proven"])

    def test_no_hidden_defaults_or_runtime_activation(self):
        draft = fixture("valid_residential_program")["draft"]
        self.assertFalse(draft["runtime_enabled"])
        self.assertNotIn("default_priority_weights", draft)
        self.assertNotIn("local_regulations", draft)
        self.assertNotIn("generator_enabled", draft)


if __name__ == "__main__":
    unittest.main()
