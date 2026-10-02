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


SCHEMA = "planha-canonical-architecture/2.0"
ADAPTER_ID = "planha.raw-dxf-current-model-adapter"
ADAPTER_VERSION = "1.0.0"
INPUT_KINDS = {"RAW_DXF", "CERTIFIED_DXF", "PLANHA_PACKAGE", "IFC"}
STATUSES = {"VERIFIED", "SUPPORTED", "AMBIGUOUS", "INPUT_REQUIRED", "CONFLICT", "REJECTED"}
ORIGINS = {"SOURCE_EXPLICIT", "SOURCE_GEOMETRIC", "SOURCE_SEMANTIC", "STRUCTURED_INPUT",
           "DERIVED_DETERMINISTIC", "HUMAN_CONFIRMED", "VISION_SUPPORT_ONLY"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _status(value, default="INPUT_REQUIRED"):
    value = str(value or default).upper()
    if value == "HIGH_CONFIDENCE":
        return "SUPPORTED"
    if value == "PASS":
        return "VERIFIED"
    return value if value in STATUSES else default


def _authority(status, origins, **grants):
    return {"status": _status(status), "origins": sorted(set(origins)),
            "material_geometry": bool(grants.get("material_geometry", False)),
            "wall": bool(grants.get("wall", False)),
            "portal": bool(grants.get("portal", False)),
            "access": bool(grants.get("access", False)),
            "routing": bool(grants.get("routing", False)),
            "release": bool(grants.get("release", False))}


def _evidence_ids(items, prefix):
    rows = []
    for index, item in enumerate(items or []):
        rows.append({"evidence_id": "%s-%s" % (prefix, content_hash([index, item])[:16].upper()),
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
    seen_levels = set()
    for row in model.get("frames") or []:
        level_id = row.get("level_candidate") or "LEVEL-UNRESOLVED-%s" % row.get("frame_id")
        frames.append({"frame_id": row.get("frame_id"), "level_id": level_id,
                       "frame_type": row.get("frame_type"), "bounds": deepcopy(row.get("bounds")),
                       "scope_relevance": row.get("scope_relevance"),
                       "source_identity": source_sha, "status": _status(row.get("status"), "SUPPORTED")})
        if level_id not in seen_levels:
            levels.append({"level_id": level_id, "name": row.get("level_candidate"),
                           "status": "SUPPORTED" if row.get("level_candidate") else "INPUT_REQUIRED",
                           "source_frame_ids": [row.get("frame_id")]})
            seen_levels.add(level_id)

    evidence_registry = []
    walls = []
    for row in model.get("canonical_walls") or []:
        ev = _evidence_ids(row.get("evidence") or [], "WALL-EV")
        evidence_registry.extend(ev)
        walls.append({"wall_id": row.get("wall_id"), "frame_id": row.get("frame_id"),
                      "centerline": deepcopy(row.get("centerline")), "face_a": deepcopy(row.get("face_a")),
                      "face_b": deepcopy(row.get("face_b")), "thickness": row.get("thickness"),
                      "representation": row.get("representation"),
                      "occupied_intervals": deepcopy((row.get("wall_solid") or {}).get("occupied_intervals") or []),
                      "interruptions": deepcopy(row.get("interruptions") or []),
                      "source_handles": deepcopy(row.get("source_handles") or []),
                      "evidence_ids": [x["evidence_id"] for x in ev], "status": _status(row.get("status"), "SUPPORTED"),
                      "authority": _authority(row.get("status"), ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                                              material_geometry=True, wall=True)})

    spaces = []
    for row in model.get("physical_spaces") or []:
        ev = _evidence_ids(row.get("evidence") or [], "SPACE-EV")
        evidence_registry.extend(ev)
        spaces.append({"physical_space_id": row.get("physical_space_id"), "level_id": row.get("level_id"),
                       "frame_id": row.get("frame_id"), "polygon": deepcopy(row.get("polygon")),
                       "interior_rings": deepcopy(row.get("interior_rings") or []), "area_m2": row.get("area_m2"),
                       "perimeter_m": row.get("perimeter_m"), "category": row.get("category"), "use": row.get("use"),
                       "topology_status": _status(row.get("status")), "source_handles": deepcopy(row.get("source_handles") or []),
                       "evidence_ids": [x["evidence_id"] for x in ev],
                       "geometry_fingerprint": (row.get("traceability") or {}).get("geometry_fingerprint"),
                       "authority": _authority(row.get("status"), ["SOURCE_GEOMETRIC", "DERIVED_DETERMINISTIC"],
                                               material_geometry=True)})

    zones = []
    for row in model.get("functional_zones") or []:
        ev = _evidence_ids(row.get("evidence") or [], "ZONE-EV")
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
        apertures.append({"aperture_id": row.get("gap_id"), "frame_id": row.get("frame_id"),
                          "classification": row.get("classification"), "status": _status(row.get("status")),
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
        ev = _evidence_ids(row.get("evidence") or [], "PORTAL-EV")
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
                      "boundary": deepcopy(row.get("boundary")), "area_m2": row.get("area"),
                      "source_handles": deepcopy(row.get("source_handles") or []),
                      "geometry_status": _status(row.get("status")), "topology_role": "VOID",
                      "routing_authority": row.get("routing_authority") or "NONE",
                      "label_evidence": deepcopy(row.get("label_evidence")),
                      "authority": _authority(row.get("status"), ["SOURCE_GEOMETRIC", "SOURCE_SEMANTIC", "DERIVED_DETERMINISTIC"],
                                              material_geometry=False, routing=False)})

    dimensions = []
    for row in model.get("dimensions") or []:
        association = row.get("association_status") or row.get("status") or "INPUT_REQUIRED"
        dimensions.append({"dimension_id": row.get("dimension_id") or row.get("handle"),
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

    current_release = bool((model.get("completeness") or {}).get("release_allowed"))
    contract = {"schema": SCHEMA, "contract_status": "EXPERIMENTAL_INTERNAL",
                "source": source_record, "levels": levels, "frames": frames, "walls": walls,
                "physical_spaces": spaces, "functional_zones": zones, "apertures": apertures, "portals": portals,
                "voids": voids, "dimensions": dimensions,
                "graphs": {"adjacency": adjacency,
                           "enclosure": deepcopy((model.get("enclosure_graph") or {}).get("edges") or []),
                           "access": access},
                "unresolved_items": unresolved, "evidence_registry": evidence_registry,
                "authority_model": {"dimensions": ["geometry_status", "semantic_status", "topology_status",
                                                            "review_status", "release_status"],
                                    "allowed_origins": sorted(ORIGINS),
                                    "vision_independent_grants": []},
                "review_registry": deepcopy(model.get("gap_human_review") or {}),
                "traceability": {"source_sha256": source_sha, "adapter_id": ADAPTER_ID,
                                 "adapter_version": ADAPTER_VERSION,
                                 "engine_identity": deepcopy(engine_identity or {}),
                                 "legacy_schema": model.get("schema"),
                                 "legacy_model_hash": content_hash(model)},
                "release": {"status": "VERIFIED" if current_release else "INPUT_REQUIRED",
                            "downstream_engineering_allowed": bool((model.get("completeness") or {}).get("downstream_engineering_allowed")),
                            "release_allowed": current_release}}
    contract["canonical_model_hash"] = content_hash(contract)
    return contract
