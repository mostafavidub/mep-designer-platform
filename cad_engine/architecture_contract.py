"""Experimental input-independent Planha Canonical Architecture v2 contract.

This module is an adapter boundary, not a production migration.  It maps the
current deterministic RAW DXF result without changing its meaning or authority.
Future adapters must implement the same result envelope and still pass the
independent validator.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from hashlib import sha256
import json
import math
import unicodedata


SCHEMA = "planha-canonical-architecture/3.2"
ADAPTER_ID = "planha.raw-dxf-current-model-adapter"
ADAPTER_VERSION = "1.0.0"
IDENTITY_VERSION = "planha-canonical-identity/2.1"
INPUT_KINDS = {"RAW_DXF", "CERTIFIED_DXF", "PLANHA_PACKAGE", "IFC"}
STATUSES = {"VERIFIED", "SUPPORTED", "AMBIGUOUS", "INPUT_REQUIRED", "CONFLICT", "REJECTED"}
ORIGINS = {"SOURCE_EXPLICIT", "SOURCE_GEOMETRIC", "SOURCE_SEMANTIC", "STRUCTURED_INPUT",
           "DERIVED_DETERMINISTIC", "HUMAN_CONFIRMED", "VISION_SUPPORT_ONLY"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


_ENTITY_COLLECTION_IDS = {
    "levels": "level_id", "frames": "frame_id", "walls": "wall_id",
    "physical_spaces": "physical_space_id", "functional_zones": "zone_id",
    "apertures": "aperture_id", "portals": "opening_id", "voids": "void_id",
    "dimensions": "dimension_id", "unresolved_items": "unresolved_item_id",
    "evidence_registry": "evidence_id",
    "title_block_fields": "title_block_field_id",
}
_SET_LIKE_LISTS = {"source_handles", "source_frame_ids", "represented_level_ids",
                   "evidence_ids", "host_wall_ids", "review_decision_ids", "origins",
                   "validator_issue_ids_covered", "allowed_origins", "vision_independent_grants"}
_SEMANTIC_TOP_LEVEL = ("schema", "contract_status", "source", "levels", "frames", "walls",
                       "physical_spaces", "functional_zones", "apertures", "portals", "voids",
                       "dimensions", "graphs", "unresolved_items", "evidence_registry",
                       "text_evidence", "title_block_fields", "authority_model",
                       "review_registry", "spatial_authority", "engineering_authority_matrix",
                       "traceability", "release")


def _normalized_scalar(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NON_FINITE_SEMANTIC_NUMBER")
        if value == 0:
            return 0
        if value.is_integer():
            return int(value)
    return value


def _semantic_normalize(value, key=None):
    if isinstance(value, dict):
        return {str(k): _semantic_normalize(v, str(k)) for k, v in sorted(value.items())}
    if isinstance(value, list):
        rows = [_semantic_normalize(v) for v in value]
        if key in _SET_LIKE_LISTS:
            unique = {canonical_json(v): v for v in rows}
            return [unique[token] for token in sorted(unique)]
        if key in _ENTITY_COLLECTION_IDS:
            identity = _ENTITY_COLLECTION_IDS[key]
            return sorted(rows, key=lambda row: (str(row.get(identity) if isinstance(row, dict) else ""),
                                                  canonical_json(row)))
        if key in {"adjacency", "enclosure", "access", "accepted_decisions", "stale_review_decisions",
                   "rejected_review_decisions", "decision_history"}:
            return sorted(rows, key=canonical_json)
        return rows
    return _normalized_scalar(value)


def _semantic_engine_identity(identity):
    identity = identity or {}
    return {key: deepcopy(identity.get(key)) for key in
            ("git_commit", "commit_sha", "sha", "build_identity_hash") if identity.get(key) is not None}


def legacy_semantic_projection(model):
    """Explicit v1 engineering projection; runtime diagnostics never define architecture identity."""
    fields = ("schema", "source", "frames", "canonical_walls", "wall_junctions",
              "continuity_closures", "endpoint_closures", "internal_wall_gaps",
              "building_envelopes", "architectural_voids", "physical_spaces", "functional_zones",
              "openings", "enclosure_graph", "access_graph", "dimensions", "completeness",
              "gap_human_review")
    return _semantic_normalize({key: deepcopy(model.get(key)) for key in fields if key in model})


def canonical_semantic_projection(model):
    """Schema-aware model identity, distinct from exact representation/integrity hashing."""
    projected = {key: deepcopy(model.get(key)) for key in _SEMANTIC_TOP_LEVEL if key in model}
    trace = projected.get("traceability") or {}
    trace["engine_identity"] = _semantic_engine_identity(trace.get("engine_identity"))
    trace.pop("legacy_content_hash", None)
    projected["traceability"] = trace
    return _semantic_normalize(projected)


def canonical_model_hash(model):
    return content_hash(canonical_semantic_projection(model))


def assign_canonical_model_hash(model):
    model.pop("canonical_model_hash", None)
    model["canonical_model_hash"] = canonical_model_hash(model)
    return model


def _status(value, default="INPUT_REQUIRED"):
    value = str(value or default).upper()
    if value in {"HIGH_CONFIDENCE", "SUPPORTED_PARTITION", "SUPPORTED_CLOSURE", "HUMAN_CONFIRMED"}:
        return "SUPPORTED"
    if value == "PASS":
        return "VERIFIED"
    return value if value in STATUSES else default


def _authority(status, origins, **grants):
    normalized = _status(status)
    effective = normalized in {"SUPPORTED", "VERIFIED"}
    return {"status": normalized, "origins": sorted(set(origins)),
            "material_geometry": effective and bool(grants.get("material_geometry", False)),
            "wall": effective and bool(grants.get("wall", False)),
            "portal": effective and bool(grants.get("portal", False)),
            "access": effective and bool(grants.get("access", False)),
            "routing": effective and bool(grants.get("routing", False)),
            "release": normalized == "VERIFIED" and bool(grants.get("release", False))}


def _evidence_ids(items, prefix, owner_id):
    rows = []
    for item in sorted((deepcopy(item) for item in items or []), key=canonical_json):
        rows.append({"evidence_id": "%s-%s" % (prefix, content_hash([owner_id, item])[:16].upper()),
                     "owner_id": owner_id,
                     "origin": "VISION_SUPPORT_ONLY" if "VISION" in str(item).upper() else "DERIVED_DETERMINISTIC",
                     "payload": deepcopy(item)})
    return rows


class ArchitectureInputAdapter(ABC):
    """Future adapter interface. No adapter bypasses independent validation."""

    input_kind = None
    implementation_status = "UNIMPLEMENTED"

    @abstractmethod
    def adapt(self, payload):
        """Return canonical_candidate, diagnostics, source_identity and provenance."""
        raise NotImplementedError


class RawDxfCurrentModelAdapter(ArchitectureInputAdapter):
    input_kind = "RAW_DXF"
    implementation_status = "EXPERIMENTAL_INTERNAL"

    def adapt(self, payload):
        candidate = adapt_current_architecture(payload)
        return {"canonical_candidate": candidate,
                "adapter_diagnostics": {"status": "PASS", "authority_promotions": 0,
                                         "production_consumer_enabled": False},
                "source_identity": deepcopy(candidate["source"]),
                "authority_provenance": deepcopy(candidate["authority_model"])}


class UnimplementedArchitectureAdapter(ArchitectureInputAdapter):
    def __init__(self, input_kind):
        if input_kind not in INPUT_KINDS - {"RAW_DXF"}:
            raise ValueError("INPUT_KIND_UNSUPPORTED")
        self.input_kind = input_kind

    def adapt(self, payload):
        raise NotImplementedError("%s_ADAPTER_NOT_IMPLEMENTED" % self.input_kind)


def adapt_current_architecture(current_model, engine_identity=None):
    """Map canonical-architectural-model/1.0 to v2 without authority promotion."""
    model = deepcopy(current_model)
    source = model.get("source") or {}
    source_sha = source.get("source_sha256")
    source_record = {"source_type": "RAW_DXF", "source_sha256": source_sha,
                     "source_revision_identity": source_sha,
                     "units": source.get("insunits"),
                     "effective_scale": source.get("metres_per_unit"),
                     "coordinate_system": {"status": "INPUT_REQUIRED", "origin": None},
                     "adapter": {"adapter_id": ADAPTER_ID, "adapter_version": ADAPTER_VERSION,
                                 "implementation_status": "EXPERIMENTAL_INTERNAL"}}
    frames = []
    levels = []
    level_rows = {}
    for row in model.get("frames") or []:
        represented = sorted(set(row.get("represented_levels") or
                                 ([row.get("level_candidate")] if row.get("level_candidate") else [])))
        level_id = row.get("level_candidate") or (represented[0] if len(represented) == 1 else None)
        relationship = ("ROOF_HEADROOM" if "ROOF_HEADROOM" in represented else
                        "ROOF" if represented == ["ROOF"] else
                        "TYPICAL" if len(represented) > 1 else
                        "SINGLE" if len(represented) == 1 else "UNRESOLVED")
        compatibility_level_id = level_id or "LEVEL-UNRESOLVED-%s" % row.get("frame_id")
        title_text = deepcopy(row.get("title_text") or (row.get("title_evidence") or {}).get("raw_text") or [])
        frames.append({"frame_id": row.get("frame_id"), "level_id": compatibility_level_id,
                       "primary_level_id": level_id, "represented_level_ids": represented,
                       "level_relationship": relationship,
                       "frame_type": row.get("frame_type"), "bounds": deepcopy(row.get("bounds")),
                       "scope_relevance": row.get("scope_relevance"),
                       "source_identity": source_sha, "status": _status(row.get("status"), "SUPPORTED"),
                       "title_evidence": {"raw_text": title_text,
                                          "normalized_interpretation": relationship,
                                          "represented_level_ids": represented,
                                          "source_handles": sorted(set(row.get("title_source_handles") or [])),
                                          "provenance": "DXF_TEXT_WITHIN_FRAME" if title_text else "NONE"}})
        emitted = represented or [compatibility_level_id]
        for represented_id in emitted:
            target = level_rows.setdefault(represented_id, {"level_id": represented_id,
                "name": represented_id if represented else None,
                "level_kind": "ROOF_HEADROOM" if represented_id == "ROOF_HEADROOM" else
                              "ROOF" if represented_id == "ROOF" else
                              "BUILDING_LEVEL" if represented else "UNRESOLVED",
                "status": "SUPPORTED" if represented else "INPUT_REQUIRED", "source_frame_ids": []})
            target["source_frame_ids"].append(row.get("frame_id"))
    for row in level_rows.values():
        row["source_frame_ids"] = sorted(set(row["source_frame_ids"]))
        levels.append(row)

    evidence_registry = []
    walls = []
    for row in model.get("canonical_walls") or []:
        ev = _evidence_ids(row.get("evidence") or [], "WALL-EV", row.get("wall_id"))
        evidence_registry.extend(ev)
        wall_status = _status(row.get("status"), "SUPPORTED")
        walls.append({"wall_id": row.get("wall_id"), "frame_id": row.get("frame_id"),
                      "centerline": deepcopy(row.get("centerline")), "face_a": deepcopy(row.get("face_a")),
                      "face_b": deepcopy(row.get("face_b")), "thickness": row.get("thickness"),
                      "representation": row.get("representation"),
                      "occupied_intervals": deepcopy((row.get("wall_solid") or {}).get("occupied_intervals") or []),
                      "interruptions": deepcopy(row.get("interruptions") or []),
                      "source_handles": deepcopy(row.get("source_handles") or []),
                      "source_roles": deepcopy(row.get("source_roles") or []),
                      "source_classifications": deepcopy(row.get("source_classifications") or []),
                      "negative_evidence": deepcopy(row.get("negative_evidence") or []),
                      "evidence_ids": [x["evidence_id"] for x in ev], "status": wall_status,
                      "authority": _authority(wall_status, ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                                              material_geometry=True, wall=True)})

    from .architecture_separator_evidence import bind_boundary, refresh_separator_authority
    spaces = []
    for row in model.get("physical_spaces") or []:
        ev = _evidence_ids(row.get("evidence") or [], "SPACE-EV", row.get("physical_space_id"))
        evidence_registry.extend(ev)
        geometry_status = _status(row.get("geometry_status") or row.get("status"))
        if not (row.get("geometry_evidence") or {}).get("status"):
            geometry_status = "INPUT_REQUIRED"
        # Legacy semantic-only records cannot acquire material authority merely
        # because this adapter supplies a SOURCE_GEOMETRIC origin flag.
        legacy_evidence=row.get("evidence") or []
        if "geometry_status" not in row and legacy_evidence and all(
                e.get("class") in {"TEXT","OBJECT_SIGNATURE","SEMANTIC_LABEL","VISION_SUPPORT_ONLY"}
                for e in legacy_evidence):
            geometry_status="INPUT_REQUIRED"
        spaces.append({"physical_space_id": row.get("physical_space_id"), "level_id": row.get("level_id"),
                       "represented_level_ids": sorted(set(row.get("represented_level_ids") or [])),
                       "frame_id": row.get("frame_id"), "polygon": deepcopy(row.get("polygon")),
                       "interior_rings": deepcopy(row.get("interior_rings") or []), "area_m2": row.get("area_m2"),
                       "perimeter_m": row.get("perimeter_m"), "category": row.get("category"), "use": row.get("use"),
                       "topology_status": geometry_status, "geometry_status": geometry_status,
                       "semantic_status": _status(row.get("semantic_status") or row.get("status")),
                       **({"geometry_evidence": deepcopy(row["geometry_evidence"])} if "geometry_evidence" in row else {}),
                       "source_handles": deepcopy(row.get("source_handles") or []),
                       "evidence_ids": [x["evidence_id"] for x in ev],
                       "geometry_fingerprint": (row.get("traceability") or {}).get("geometry_fingerprint"),
                       "space_geometry_type": row.get("space_geometry_type") or "OTHER",
                       "boundary_segments": deepcopy(row.get("boundary_segments") or []),
                       "authority_level": row.get("authority_level") or "GEOMETRY_CANDIDATE",
                       "area_authority": row.get("area_authority") or "NONE",
                       "centroid": deepcopy(row.get("centroid")),
                       "bounding_box": deepcopy(row.get("bounding_box")),
                       "stair_assembly_ids": deepcopy(row.get("stair_assembly_ids") or []),
                       "provenance_fingerprint": row.get("provenance_fingerprint"),
                       **({"candidate_id": row["candidate_id"], "candidate_role": row.get("candidate_role")} if "candidate_id" in row else {}),
                       "authority": _authority(geometry_status, ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                                               material_geometry=False)})
        evidence_registry.extend(bind_boundary(spaces[-1], source_sha))

    zones = []
    for row in model.get("functional_zones") or []:
        ev = _evidence_ids(row.get("evidence") or [], "ZONE-EV", row.get("zone_id"))
        evidence_registry.extend(ev)
        explicit = row.get("boundary_status") == "explicit" and bool(row.get("polygon"))
        zones.append({"zone_id": row.get("zone_id"), "physical_space_id": row.get("physical_space_id"),
                      "category": row.get("category"), "boundary_status": row.get("boundary_status"),
                      "polygon": deepcopy(row.get("polygon")) if explicit else None,
                      "semantic_status": _status(row.get("status")), "evidence_ids": [x["evidence_id"] for x in ev],
                      "authority": _authority(row.get("status"), ["SOURCE_SEMANTIC", "DERIVED_DETERMINISTIC"],
                                              material_geometry=False)})

    apertures = []
    for row in (model.get("internal_wall_gaps") or {}).get("items") or []:
        legacy_review_trace = []
        if row.get("status") == "HUMAN_CONFIRMED":
            legacy_identity = [source_sha, row.get("frame_id"), row.get("gap_id"), row.get("geometry"),
                               row.get("source_handles"), row.get("review_question_id")]
            legacy_review_trace = [{"review_item_id": row.get("review_question_id") or
                                                      "LEGACY-REVIEW-" + content_hash(legacy_identity)[:16].upper(),
                                    "decision": row.get("classification"), "source_sha256": source_sha,
                                    "geometry_fingerprint": content_hash(row.get("geometry")),
                                    "evidence_fingerprint": content_hash(row.get("source_handles") or []),
                                    "review_fingerprint": content_hash(legacy_identity)}]
        apertures.append({"aperture_id": row.get("gap_id"), "frame_id": row.get("frame_id"),
                          "classification": row.get("classification"), "status": _status(row.get("status")),
                          "review_status": "CONFIRMED" if row.get("status") == "HUMAN_CONFIRMED" else "NOT_REVIEWED",
                          "review_authority": "HUMAN_SOURCE_INTERPRETATION" if row.get("status") == "HUMAN_CONFIRMED" else "NONE",
                          "review_trace": legacy_review_trace,
                          "geometry": deepcopy(row.get("geometry")),
                          "host_wall_ids": deepcopy(row.get("host_wall_ids") or []),
                          "source_handles": deepcopy(row.get("source_handles") or []),
                          "review_question_id": row.get("review_question_id"),
                          "authority": _authority(row.get("status"),
                                                  ["HUMAN_CONFIRMED"] if row.get("status") == "HUMAN_CONFIRMED" else
                                                  ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                                                  material_geometry=False)})

    portals = []
    for row in model.get("openings") or []:
        ev = _evidence_ids(row.get("evidence") or [], "PORTAL-EV", row.get("opening_id"))
        evidence_registry.extend(ev)
        verified = _status(row.get("status")) == "VERIFIED"
        portals.append({"opening_id": row.get("opening_id"), "portal_id": row.get("portal_id"),
                        "type": str(row.get("kind") or "UNKNOWN").upper(), "frame_id": row.get("frame_id"),
                        "host_wall_id": row.get("host_wall_id"), "host_aperture_id": row.get("host_gap_id"),
                        "material_aperture_status": "VERIFIED" if verified and row.get("host_gap_id") else "INPUT_REQUIRED",
                        "space_a": row.get("space_a"), "space_b": row.get("space_b"),
                        "geometry": deepcopy(row.get("portal_geometry") or row.get("opening_geometry") or row.get("geometry")),
                        "source_handles": deepcopy(row.get("source_handles") or ([row.get("source_handle")] if row.get("source_handle") else [])),
                        "evidence_ids": [x["evidence_id"] for x in ev], "status": _status(row.get("status")),
                        "authority": _authority(row.get("status"), ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                                                portal=verified, access=verified and row.get("kind") in {"door", "open_passage"})})

    voids = []
    for row in (model.get("architectural_voids") or {}).get("items") or []:
        voids.append({"void_id": row.get("void_id"), "frame_id": row.get("frame_id"), "type": row.get("void_type"),
                      "boundary": deepcopy(row.get("boundary")),
                      "area_m2": row.get("area") * float(source.get("metres_per_unit") or 1.0) ** 2 if row.get("area") is not None else None,
                      "source_roles": deepcopy(row.get("source_roles") or []),
                      "negative_evidence": deepcopy(row.get("negative_evidence") or []),
                      "source_handles": deepcopy(row.get("source_handles") or []),
                      "geometry_status": _status(row.get("status")), "topology_role": "VOID",
                      "routing_authority": row.get("routing_authority") or "NONE",
                      "label_evidence": deepcopy(row.get("label_evidence")),
                      "authority": _authority(row.get("status"), ["SOURCE_GEOMETRIC", "SOURCE_SEMANTIC", "DERIVED_DETERMINISTIC"],
                                              material_geometry=False, routing=False)})

    dimensions = []
    for row in model.get("dimensions") or []:
        association = row.get("association_status") or row.get("status") or "INPUT_REQUIRED"
        dimension_id = row.get("dimension_id") or row.get("handle")
        if not dimension_id:
            identity = {"source_sha256": source_sha, "entity_type": row.get("entity_type") or "DIMENSION",
                        "source_insert_handle": row.get("source_insert_handle"),
                        "source_block_path": deepcopy(row.get("source_block_path") or []),
                        "definition_points": deepcopy(row.get("definition_points") or []),
                        "witness_points": deepcopy(row.get("witness_points") or []),
                        "dimension_type": row.get("dimension_type"), "layer": row.get("layer")}
            dimension_id = "DIMENSION-" + content_hash(_semantic_normalize(identity))[:20].upper()
        dimensions.append({"dimension_id": dimension_id,
                           "source_id": row.get("handle"), "annotated_value": row.get("measurement"),
                           "units": source.get("insunits"), "witness_points": deepcopy(row.get("witness_points") or []),
                           "definition_points": deepcopy(row.get("definition_points") or []),
                           "semantic_association": deepcopy(row.get("association_basis")),
                           "association_status": _status(association),
                           "authority": _authority(association, ["SOURCE_EXPLICIT"], material_geometry=False)})

    access = deepcopy((model.get("access_graph") or {}).get("edges") or [])
    adjacency = [{"space_a": min(left, right), "space_b": max(left, right),
                  "provenance": ["DERIVED_DETERMINISTIC"]}
                 for left, right in sorted({(space["physical_space_id"], other)
                                            for space in model.get("physical_spaces") or []
                                            for other in space.get("adjacent_space_ids") or []})
                 if left != right]
    unresolved = []
    for issue in (model.get("completeness") or {}).get("issues") or []:
        if issue.get("code") == "SEPARATOR_ROLE_REQUIRED":
            continue  # Rebuilt from source interval evidence below, never suppressed.
        unresolved.append({"unresolved_item_id": "UNRESOLVED-%s" % content_hash(issue)[:16].upper(),
                           "object_or_region_id": issue.get("space_id") or issue.get("frame_id"),
                           "issue_type": issue.get("code") or "UNKNOWN", "evidence": deepcopy(issue),
                           "downstream_impact": "BLOCKS_RELEASE", "review_requirement": "BOUNDED_OR_INPUT_REQUIRED"})
    for row in portals:
        if row["status"] != "VERIFIED":
            unresolved.append({"unresolved_item_id": "UNRESOLVED-%s" % content_hash(row["opening_id"])[:16].upper(),
                               "object_or_region_id": row["opening_id"], "issue_type": "PORTAL_UNRESOLVED",
                               "evidence": {"status": row["status"]}, "downstream_impact": "NO_ACCESS_AUTHORITY",
                               "review_requirement": "SOURCE_DEPENDENT"})

    spatial_authority = deepcopy(model.get("spatial_authority") or {})
    current_release = bool((model.get("completeness") or {}).get("release_allowed")) and spatial_authority.get("status") == "VERIFIED"
    contract = {"schema": SCHEMA, "contract_status": "EXPERIMENTAL_INTERNAL",
                "source": source_record, "levels": levels, "frames": frames, "walls": walls,
                "physical_spaces": spaces, "functional_zones": zones, "apertures": apertures, "portals": portals,
                "voids": voids, "dimensions": dimensions,
                "text_evidence": deepcopy(model.get("text_evidence") or {
                    "schema": "planha-architectural-text-evidence/1.0",
                    "contract_version": SCHEMA, "items": [],
                    "metrics": {"exact_occurrence_count": 0, "template_definition_count": 0,
                                "attribute_instance_count": 0, "geometry_authority_count": 0},
                }),
                "title_block_fields": deepcopy(model.get("title_block_fields") or []),
                "graphs": {"adjacency": adjacency,
                           "enclosure": deepcopy((model.get("enclosure_graph") or {}).get("edges") or []),
                           "access": access},
                "unresolved_items": unresolved, "evidence_registry": evidence_registry,
                "authority_model": {"dimensions": ["geometry_status", "semantic_status", "topology_status",
                                                            "separator_status", "review_status", "release_status"],
                                    "allowed_origins": sorted(ORIGINS),
                                    "vision_independent_grants": []},
                "review_registry": deepcopy(model.get("gap_human_review") or {}),
                "spatial_authority": deepcopy(spatial_authority or {
                    "schema": "planha-architecture-spatial-authority/1.0",
                    "status": "INPUT_REQUIRED", "text_creates_geometry": False,
                    "vision_geometry_authority": False,
                    "site_boundaries": [], "site_spaces": [],
                    "vertical_circulation": {"stair_assemblies": [], "elevators": [], "shafts": []},
                    "graph_qualification": {"enclosure_graph": {"status": "INPUT_REQUIRED"},
                                            "access_graph": {"status": "INPUT_REQUIRED"}},
                    "engineering_authority_matrix": {"facts": {}, "consumers": {}},
                    "counters": {"unsupported_verified_geometry": 0,
                                 "text_created_verified_geometry": 0,
                                 "unsupported_verified_stairs": 0},
                }),
                "engineering_authority_matrix": deepcopy(
                    ((model.get("spatial_authority") or {}).get("engineering_authority_matrix") or
                     {"facts": {}, "consumers": {}})),
                "traceability": {"source_sha256": source_sha, "adapter_id": ADAPTER_ID,
                                 "adapter_version": ADAPTER_VERSION,
                                 "engine_identity": _semantic_engine_identity(engine_identity),
                                 "legacy_schema": model.get("schema"),
                                 "legacy_model_hash": content_hash(legacy_semantic_projection(model)),
                                 "legacy_content_hash": content_hash(model),
                                 "canonical_identity_version": IDENTITY_VERSION},
                "execution_diagnostics": {"engine_identity": deepcopy(engine_identity or {}),
                                          "enclosure_candidates": deepcopy(model.get("enclosure_candidates") or [])},
                "release": {"status": "VERIFIED" if current_release else "INPUT_REQUIRED",
                            "downstream_engineering_allowed": current_release and bool((model.get("completeness") or {}).get("downstream_engineering_allowed")),
                            "release_allowed": current_release}}
    contract["evidence_registry"] = list({r["evidence_id"]: r for r in evidence_registry}.values())
    refresh_separator_authority(contract)
    return assign_canonical_model_hash(contract)
