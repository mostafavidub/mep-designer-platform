"""Focused synthetic tests; no value in this file is regulatory or Golden truth."""
from __future__ import annotations

import copy
import math
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from shapely.geometry import Polygon

from cad_engine.residential_foundation import load_catalog
from cad_engine.residential_symbols import create_symbol
from cad_engine.residential_placement_qa import (
    MARKERS, create_placement_instance, placement_content, profile_content,
    stable_hash, validate_clearance_profile, validate_placement_scene,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
ROOT = Path(__file__).resolve().parents[1]


def symbol(symbol_id="AR-SOFA", *, width=.8, depth=.6):
    return create_symbol(symbol_id, width_m=width, depth_m=depth, origin_m=[0, 0],
                         rotation_deg=0, dimension_basis="VISUALIZATION_ONLY",
                         steps=10 if symbol_id == "AR-STAIR" else None)


def profile(clearance_id="usage", symbol_id="AR-SOFA", clearance_type="USAGE_CLEARANCE",
            polygon=None, mandatory=False, policy="PROHIBITED", qualified=False, synthetic=True):
    value = {
        "schema_version": "architecture-clearance-profile/1.0", "clearance_id": clearance_id,
        "symbol_id": symbol_id, "symbol_category": symbol(symbol_id)["category"], "clearance_type": clearance_type,
        "local_geometry": {"polygons": [polygon or [[0, 0], [0.8, 0], [0.8, 1], [0, 1], [0, 0]]]},
        "coordinate_system": "SYMBOL_LOCAL_2D", "units": "m", "applicable_configuration": "ANY",
        "operating_mode": "SYNTHETIC_TEST",
        "applicability_conditions": {"evaluation_status": "APPLICABLE"} if mandatory else {},
        "mandatory_or_heuristic": "MANDATORY" if mandatory else "HEURISTIC",
        "coexistence_policy": policy,
        "source_type": "NATIONAL_CODE" if mandatory else "ERGONOMIC_REFERENCE",
        "source_id": "SYNTHETIC-SOURCE", "source_revision": "test-1",
        "source_hash": HASH_A if qualified else None,
        "rule_or_clause_reference": "SYNTHETIC-CLAUSE" if mandatory else None,
        "verification_status": "AUTHORITY_QUALIFIED" if qualified else "SYNTHETIC",
    }
    if synthetic:
        value["markers"] = sorted(MARKERS)
    value["dependency_fingerprint"] = stable_hash(profile_content(value))
    return value


class FakeAuthorityResolver:
    def __init__(self, revision="test-1"):
        self.revision = revision

    def resolve_source(self, source_id):
        return {"source_id": source_id, "source_revision": self.revision, "source_hash": HASH_A}

    def resolve_rule(self, rule_reference):
        return {"rule_reference": rule_reference, "source_id": "SYNTHETIC-SOURCE",
                "verification_status": "AUTHORITY_QUALIFIED"}


def space_polygon():
    return [[0, 0], [6, 0], [6, 5], [0, 5], [0, 0]]


def scene(*, placements=None, profiles=None, access=None, obstacles=None):
    polygon = space_polygon()
    fingerprint = stable_hash({"polygon": polygon, "coordinate_frame": "FRAME-1"})
    return {
        "schema_version": "architecture-placement-scene/1.0", "project_id": "PROJECT-1",
        "physical_space": {"physical_space_id": "SPACE-1", "project_id": "PROJECT-1",
                           "coordinate_frame": "FRAME-1", "polygon": polygon,
                           "geometry_fingerprint": fingerprint, "authority_status": "VERIFIED",
                           "material_geometry": True},
        "hosts": [{"host_id": "HOST-1", "project_id": "PROJECT-1", "coordinate_frame": "FRAME-1",
                   "geometry": [[1, 0], [1, 5]],
                   "geometry_fingerprint": stable_hash({"coordinate_frame": "FRAME-1", "geometry": [[1, 0], [1, 5]]})}],
        "clearance_profiles": profiles or [], "placements": placements or [],
        "obstacles": obstacles or [], "access_path_checks": access or [], "runtime_enabled": False,
        "markers": sorted(MARKERS),
    }


def placement(sym, placement_id, position, scene_value, refs=None, host=False, program_hash=HASH_A,
              rotation=0):
    room = scene_value["physical_space"]
    return create_placement_instance(
        sym, placement_id=placement_id, project_id=scene_value["project_id"],
        physical_space_id=room["physical_space_id"], physical_space_fingerprint=room["geometry_fingerprint"],
        coordinate_frame=room["coordinate_frame"], position=position, rotation_deg=rotation,
        clearance_profile_references=refs or [], host_id="HOST-1" if host else None,
        host_fingerprint=scene_value["hosts"][0]["geometry_fingerprint"] if host else None, code_basis_hash=HASH_B,
        relevant_program_hash=program_hash,
    )


def validate(value, *, resolver=None, dependencies=None, symbols=None):
    if symbols is None:
        symbols = {item["symbol_id"]: {"parameter_hash": item["parameter_hash"],
                                        "geometry_fingerprint": item["symbol_geometry_fingerprint"],
                                        "footprint": item["local_footprint"]} for item in value["placements"]}
    if dependencies is None:
        dependencies = {"code_basis_hash": HASH_B, "relevant_program_hash": HASH_A}
    return validate_placement_scene(value, authority_resolver=resolver,
                                    current_dependencies=dependencies, current_symbols=symbols)


class SymbolCompatibilityTests(unittest.TestCase):
    def test_all_41_ids_and_legacy_geometry_remain_compatible(self):
        rows = load_catalog("symbols")["symbols"]
        self.assertEqual(len(rows), 41)
        self.assertEqual(len({row["symbol_id"] for row in rows}), 41)
        for row in rows:
            with self.subTest(symbol=row["symbol_id"]):
                result = symbol(row["symbol_id"])
                self.assertEqual(result["symbol_id"], row["symbol_id"])
                self.assertEqual(result["units"], "m")
                self.assertTrue(Polygon(result["footprint"]).is_valid)
                self.assertEqual(result["clearance_regions"], [])
                self.assertEqual(len(result["geometry_fingerprint"]), 64)

    def test_legacy_usage_is_heuristic_and_never_code_authority(self):
        result = create_symbol("AR-SOFA", width_m=.8, depth_m=.6, origin_m=[0, 0], rotation_deg=0,
                               dimension_basis="OWNER_MEASURED", usage_clearance_m=.5,
                               clearance_source="owner-measurement")
        region = result["clearance_regions"][0]
        self.assertEqual(region["clearance_type"], "USAGE_CLEARANCE")
        self.assertEqual(region["mandatory_or_heuristic"], "HEURISTIC")
        self.assertEqual(region["verification_status"], "UNVERIFIED")

    def test_determinism_rotation_translation_and_height_validation(self):
        base = symbol()
        same = symbol()
        rotated = create_symbol("AR-SOFA", width_m=.8, depth_m=.6, origin_m=[2, 3], rotation_deg=90,
                                dimension_basis="VISUALIZATION_ONLY")
        self.assertEqual(base["parameter_hash"], same["parameter_hash"])
        self.assertAlmostEqual(Polygon(base["footprint"]).area, Polygon(rotated["footprint"]).area)
        self.assertEqual(base["geometry_fingerprint"], rotated["geometry_fingerprint"])
        placed = create_placement_instance(rotated, placement_id="T", project_id="P", physical_space_id="S",
                                           physical_space_fingerprint=HASH_A, coordinate_frame="F",
                                           position=[4, 5], rotation_deg=90, clearance_profile_references=[])
        self.assertEqual(placed["local_footprint"], base["local_footprint"])
        for bad in [0, -1, float("nan"), float("inf"), True]:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                create_symbol("AR-SOFA", width_m=.8, depth_m=.6, height_m=bad, origin_m=[0, 0],
                              rotation_deg=0, dimension_basis="VISUALIZATION_ONLY")


class ClearanceContractTests(unittest.TestCase):
    def test_five_typed_clearance_classes_validate_structurally(self):
        for value in ["OBJECT_FOOTPRINT", "USAGE_CLEARANCE", "ACCESS_CLEARANCE",
                      "MAINTENANCE_CLEARANCE", "CODE_REQUIRED_CLEARANCE"]:
            mandatory = value in {"ACCESS_CLEARANCE", "CODE_REQUIRED_CLEARANCE"}
            row = profile(clearance_id=value, clearance_type=value, mandatory=mandatory,
                          qualified=mandatory, synthetic=not mandatory)
            current = {"SYNTHETIC-SOURCE": {"source_id": "SYNTHETIC-SOURCE", "source_revision": "test-1",
                                             "source_hash": HASH_A}}
            result = validate_clearance_profile(row, authority_resolver=FakeAuthorityResolver())
            self.assertNotIn(result["status"], {"INPUT_REQUIRED", "STALE_BINDING"})

    def test_mandatory_clearance_requires_independent_authority(self):
        row = profile(clearance_type="CODE_REQUIRED_CLEARANCE", mandatory=True, qualified=False)
        result = validate_clearance_profile(row)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("MANDATORY_AUTHORITY_REQUIRED", {f["code"] for f in result["findings"]})

    def test_synthetic_data_cannot_assert_regulatory_authority(self):
        row = profile(clearance_type="CODE_REQUIRED_CLEARANCE", mandatory=True, qualified=True, synthetic=True)
        result = validate_clearance_profile(row, authority_resolver=FakeAuthorityResolver())
        self.assertIn("SYNTHETIC_AUTHORITY_FORBIDDEN", {f["code"] for f in result["findings"]})
        self.assertFalse(result["regulatory_authority"])

    def test_missing_and_stale_sources_fail_closed(self):
        row = profile(clearance_type="ACCESS_CLEARANCE", mandatory=True, qualified=True, synthetic=False)
        self.assertEqual(validate_clearance_profile(row)["status"], "INPUT_REQUIRED")
        result = validate_clearance_profile(row, authority_resolver=FakeAuthorityResolver(revision="changed"))
        self.assertEqual(result["status"], "STALE_BINDING")


class PlacementValidationTests(unittest.TestCase):
    def test_real_canonical_symbol_uses_local_geometry_for_stale_binding(self):
        value = scene()
        current = create_symbol("AR-SOFA", width_m=.8, depth_m=.6, origin_m=[2, 3],
                                rotation_deg=37, dimension_basis="VISUALIZATION_ONLY")
        value["placements"] = [placement(current, "P1", [1, 1], value, rotation=19)]
        result = validate(value, symbols={current["symbol_id"]: current})
        self.assertNotIn("STALE_SYMBOL_BINDING", {f["code"] for f in result["findings"]})

        changed = copy.deepcopy(current)
        changed["local_footprint"][1][0] += .1
        result = validate(value, symbols={current["symbol_id"]: changed})
        self.assertIn("STALE_SYMBOL_BINDING", {f["code"] for f in result["findings"]})

    def test_invalid_nested_profiles_fail_closed_without_geometry_traversal(self):
        nonfinite = profile("nonfinite")
        nonfinite["local_geometry"]["polygons"][0][1][0] = float("nan")
        malformed = [
            {"clearance_id": "missing"},
            {**profile("null"), "local_geometry": None},
            {**profile("collection"), "local_geometry": {"polygons": ["not-a-polygon"]}},
            profile("self-intersecting", polygon=[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]),
            nonfinite,
        ]
        for item in malformed:
            with self.subTest(clearance=item.get("clearance_id")):
                value = scene(profiles=[item])
                result = validate(value)
                self.assertEqual(result["status"], "INPUT_REQUIRED")
                self.assertTrue(result["findings"])

    def test_regulatory_dimension_never_passes_without_evaluated_authority(self):
        for profiles, resolver in [
            ([], None),
            ([profile("synthetic")], None),
            ([profile("code", clearance_type="CODE_REQUIRED_CLEARANCE", mandatory=True,
                      qualified=True, synthetic=True)], FakeAuthorityResolver()),
            ([profile("code", clearance_type="CODE_REQUIRED_CLEARANCE", mandatory=True,
                      qualified=True, synthetic=False)], None),
        ]:
            with self.subTest(profiles=len(profiles), resolver=resolver is not None):
                value = scene(profiles=profiles)
                if profiles:
                    value["placements"] = [placement(symbol(), "P1", [1, 1], value,
                                                       [profiles[0]["clearance_id"]])]
                result = validate(value, resolver=resolver)
                self.assertNotEqual(result["dimensions"]["REGULATORY_COMPLIANCE"], "PASS")

        missing_applicability = profile("code", clearance_type="CODE_REQUIRED_CLEARANCE",
                                        mandatory=True, qualified=True, synthetic=False)
        missing_applicability["applicability_conditions"] = {}
        missing_applicability["dependency_fingerprint"] = stable_hash(profile_content(missing_applicability))
        value = scene(profiles=[missing_applicability])
        value["placements"] = [placement(symbol(), "P1", [1, 1], value, ["code"])]
        result = validate(value, resolver=FakeAuthorityResolver())
        self.assertIn("MANDATORY_APPLICABILITY_REQUIRED", {f["code"] for f in result["findings"]})
        self.assertNotEqual(result["dimensions"]["REGULATORY_COMPLIANCE"], "PASS")

    def test_independently_qualified_applicable_clearance_can_pass_regulatory_dimension(self):
        qualified = profile("code", clearance_type="CODE_REQUIRED_CLEARANCE", mandatory=True,
                            qualified=True, synthetic=False)
        value = scene(profiles=[qualified])
        value["placements"] = [placement(symbol(), "P1", [1, 1], value, ["code"])]
        result = validate(value, resolver=FakeAuthorityResolver())
        self.assertEqual(result["dimensions"]["REGULATORY_COMPLIANCE"], "PASS")
        self.assertEqual(result["dimensions"]["PROFESSIONAL_REVIEW"], "NOT_REVIEWED")

    def test_explicit_obstacles_block_objects_and_door_operation_not_boundary_touch(self):
        value = scene(obstacles=[[[1.2, 1.1], [1.6, 1.1], [1.6, 1.5], [1.2, 1.5], [1.2, 1.1]]])
        value["placements"] = [placement(symbol(), "P1", [1, 1], value)]
        self.assertIn("OBJECT_OBSTACLE_COLLISION", {f["code"] for f in validate(value)["findings"]})

        value = scene(obstacles=[[[1.8, 1], [2.2, 1], [2.2, 1.4], [1.8, 1.4], [1.8, 1]]])
        value["placements"] = [placement(symbol(), "P1", [1, 1], value)]
        self.assertNotIn("OBJECT_OBSTACLE_COLLISION", {f["code"] for f in validate(value)["findings"]})

        value = scene(obstacles=[[[1.3, 1.3], [1.5, 1.3], [1.5, 1.5], [1.3, 1.5], [1.3, 1.3]]])
        value["placements"] = [placement(symbol("AR-DOOR", width=.9, depth=.04), "D1", [1, 1], value,
                                           host=True)]
        codes = {f["code"] for f in validate(value)["findings"]}
        self.assertIn("DOOR_SWING_OBSTACLE_COLLISION", codes)

    def test_valid_non_authoritative_placement_remains_review_required(self):
        value = scene()
        value["placements"] = [placement(symbol(), "P1", [1, 1], value)]
        before = copy.deepcopy(value)
        result = validate(value)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertTrue(result["input_unchanged"])
        self.assertEqual(value, before)
        self.assertFalse(result["professional_approval"])

    def test_footprint_containment_and_object_collision(self):
        value = scene()
        value["placements"] = [placement(symbol(), "P1", [5.5, 1], value)]
        self.assertIn("FOOTPRINT_OUTSIDE_SPACE", {f["code"] for f in validate(value)["findings"]})
        value = scene()
        value["placements"] = [placement(symbol(), "P1", [1, 1], value), placement(symbol(), "P2", [1.2, 1.1], value)]
        self.assertIn("OBJECT_COLLISION", {f["code"] for f in validate(value)["findings"]})

    def test_clearance_containment_and_overlap_semantics(self):
        for policy, expected in [("PROHIBITED", "CLEARANCE_OBSTRUCTED"),
                                 ("CONDITIONAL_REVIEW", "CLEARANCE_OVERLAP_REVIEW"),
                                 ("PERMITTED", None)]:
            p = profile(policy=policy)
            value = scene(profiles=[p])
            value["placements"] = [placement(symbol(), "P1", [1, 1], value, [p["clearance_id"]]),
                                    placement(symbol("AR-ARMCHAIR"), "P2", [1, 1.7], value)]
            codes = {f["code"] for f in validate(value)["findings"]}
            if expected:
                self.assertIn(expected, codes)
            else:
                self.assertNotIn("CLEARANCE_OBSTRUCTED", codes)
                self.assertNotIn("CLEARANCE_OVERLAP_REVIEW", codes)
        p = profile(polygon=[[0, 0], [8, 0], [8, 1], [0, 1], [0, 0]])
        value = scene(profiles=[p]); value["placements"] = [placement(symbol(), "P1", [0, 0], value, [p["clearance_id"]])]
        self.assertIn("CLEARANCE_OUTSIDE_SPACE", {f["code"] for f in validate(value)["findings"]})

    def test_door_swing_and_host_evidence(self):
        value = scene()
        door = placement(symbol("AR-DOOR", width=.9, depth=.04), "D1", [1, 1], value)
        chair = placement(symbol("AR-ARMCHAIR"), "P1", [1.2, 1.2], value)
        value["placements"] = [door, chair]
        codes = {f["code"] for f in validate(value)["findings"]}
        self.assertIn("MISSING_DOOR_HOST", codes); self.assertIn("DOOR_SWING_COLLISION", codes)
        value = scene(); door = placement(symbol("AR-DOOR", width=.9, depth=.04), "D1", [1, 1], value, host=True)
        value["hosts"][0]["geometry_fingerprint"] = HASH_A
        value["placements"] = [door]
        self.assertIn("STALE_HOST_BINDING", {f["code"] for f in validate(value)["findings"]})
        value = scene(); door = placement(symbol("AR-DOOR", width=.9, depth=.04), "D1", [2, 1], value, host=True)
        value["placements"] = [door]
        self.assertIn("DOOR_HOST_GEOMETRY_MISMATCH", {f["code"] for f in validate(value)["findings"]})

    def test_access_path_open_blocked_and_unknown_authority(self):
        p = profile("access", clearance_type="ACCESS_CLEARANCE", mandatory=False)
        check = {"check_id": "A1", "start": [0.8, 2.5], "goal": [5.2, 2.5],
                 "required_width_m": .5, "clearance_profile_id": "access"}
        value = scene(profiles=[p], access=[check])
        self.assertNotIn("ACCESS_PATH_BLOCKED", {f["code"] for f in validate(value)["findings"]})
        wall = [[2.8, 0], [3.2, 0], [3.2, 5], [2.8, 5], [2.8, 0]]
        value = scene(profiles=[p], access=[check], obstacles=[wall])
        self.assertIn("ACCESS_PATH_BLOCKED", {f["code"] for f in validate(value)["findings"]})
        mandatory = profile("access", clearance_type="ACCESS_CLEARANCE", mandatory=True, qualified=False)
        value = scene(profiles=[mandatory], access=[check])
        codes = {f["code"] for f in validate(value)["findings"]}
        self.assertTrue({"MANDATORY_AUTHORITY_REQUIRED", "ACCESS_AUTHORITY_REQUIRED"} & codes)

    def test_stale_space_symbol_program_and_cross_project_bindings(self):
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); value["placements"] = [item]
        item["physical_space_fingerprint"] = HASH_A
        self.assertIn("STALE_SPACE_BINDING", {f["code"] for f in validate(value)["findings"]})
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); value["placements"] = [item]
        item["parameter_hash"] = HASH_B
        self.assertIn("STALE_PLACEMENT", {f["code"] for f in validate(value)["findings"]})
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); value["placements"] = [item]
        result = validate(value, dependencies={"code_basis_hash": HASH_B, "relevant_program_hash": HASH_B})
        self.assertIn("STALE_DEPENDENCY", {f["code"] for f in result["findings"]})
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); item["project_id"] = "OTHER"; value["placements"] = [item]
        self.assertIn("CROSS_PROJECT_OR_SPACE_BINDING", {f["code"] for f in validate(value)["findings"]})

    def test_irrelevant_owner_preference_is_not_a_material_dependency(self):
        value = scene(); value["placements"] = [placement(symbol(), "P1", [1, 1], value, program_hash=HASH_A)]
        first = validate(value)
        unrelated_owner_color = "blue"
        unrelated_owner_color = "green"
        second = validate(value)
        self.assertEqual(first, second); self.assertEqual(unrelated_owner_color, "green")

    def test_schema_rejects_nonfinite_transform_and_geometry(self):
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); item["position"][0] = float("nan"); value["placements"] = [item]
        self.assertEqual(validate(value)["status"], "INPUT_REQUIRED")
        with self.assertRaises(ValueError):
            placement(symbol(), "P1", [float("inf"), 0], scene())

    def test_transformation_identity_is_deterministic(self):
        value = scene(); a = placement(symbol(), "P1", [2, 3], value); b = placement(symbol(), "P1", [2, 3], value)
        self.assertEqual(a, b)
        moved = copy.deepcopy(a); moved["position"] = [3, 3]
        moved["dependency_fingerprint"] = stable_hash(placement_content(moved))
        self.assertNotEqual(a["dependency_fingerprint"], moved["dependency_fingerprint"])

    def test_invalid_transform_missing_current_bindings_and_malformed_profile_fail_closed(self):
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); value["placements"] = [item]
        item["transformation"][4] = 9
        item["dependency_fingerprint"] = stable_hash(placement_content(item))
        self.assertIn("INVALID_TRANSFORMATION", {f["code"] for f in validate(value)["findings"]})
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); value["placements"] = [item]
        direct = validate_placement_scene(value, current_symbols=None, current_dependencies=None)
        self.assertTrue({"CURRENT_SYMBOL_REQUIRED", "CURRENT_DEPENDENCIES_REQUIRED"} <= {f["code"] for f in direct["findings"]})
        value = scene(profiles=[{}])
        self.assertEqual(validate(value)["status"], "INPUT_REQUIRED")

    def test_qualified_mandatory_clearance_geometry_can_be_checked_without_granting_approval(self):
        p = profile("code", clearance_type="CODE_REQUIRED_CLEARANCE", mandatory=True,
                    qualified=True, synthetic=False,
                    polygon=[[0, 0], [7, 0], [7, 1], [0, 1], [0, 0]])
        value = scene(profiles=[p]); value["placements"] = [placement(symbol(), "P1", [0, 0], value, ["code"])]
        result = validate(value, resolver=FakeAuthorityResolver())
        self.assertIn("CLEARANCE_OUTSIDE_SPACE", {f["code"] for f in result["findings"]})
        self.assertFalse(result["professional_approval"])

    def test_stale_physical_space_geometry_and_units_fail_closed(self):
        value = scene(); value["physical_space"]["polygon"][1][0] = 7
        self.assertIn("STALE_SPACE_GEOMETRY", {f["code"] for f in validate(value)["findings"]})
        value = scene(); item = placement(symbol(), "P1", [1, 1], value); item["coordinate_frame"] = "OTHER"; value["placements"] = [item]
        self.assertIn("COORDINATE_FRAME_MISMATCH", {f["code"] for f in validate(value)["findings"]})


class GovernanceGuardTests(unittest.TestCase):
    def test_schemas_are_valid_and_runtime_is_not_imported(self):
        for name in ["clearance-profile.schema.json", "placement-scene.schema.json"]:
            schema = __import__("json").loads((ROOT / "standards/test-suites/residential" / name).read_text())
            Draft202012Validator.check_schema(schema)
        main = (ROOT / "cad_engine/main.py").read_text()
        self.assertNotIn("residential_placement_qa", main)
        self.assertFalse((ROOT / "cad_engine/residential_placement_qa_v1.py").exists())


if __name__ == "__main__":
    unittest.main()
