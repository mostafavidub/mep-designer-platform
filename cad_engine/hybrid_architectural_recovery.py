"""Boundary-first CAD/Vision fusion for source-insufficient architecture.

The module deliberately separates topology from material geometry.  A Vision or
human-confirmed edge can close an enclosure, but can never become a physical
wall, structural object, or routing obstacle without native CAD evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any
import json
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union


AUTHORITY_CAD = "CAD_CONFIRMED"
AUTHORITY_INFERRED = "MULTI_EVIDENCE_INFERRED_TOPOLOGY"
AUTHORITY_HUMAN = "HUMAN_CONFIRMED_TOPOLOGY"
AUTHORITY_UNRESOLVED = "UNRESOLVED"

HARD_CONFLICTS = {"STRONG_CAD_WALL_CONFLICT", "DIMENSION_CONFLICT",
                  "GEOMETRIC_OVERLAP_CONFLICT", "FRAME_CONTAMINATION"}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}-{sha256(raw.encode()).hexdigest()[:18].upper()}"


def _line(points: list) -> LineString | None:
    try:
        geometry = LineString(points)
    except (TypeError, ValueError):
        return None
    return geometry if not geometry.is_empty and geometry.length > 0 else None


def _polygon(points: list, holes: list | None = None) -> Polygon | None:
    try:
        geometry = Polygon(points, holes or [])
    except (TypeError, ValueError):
        return None
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry if geometry.geom_type == "Polygon" and geometry.area > 0 else None


@dataclass
class EvidenceGraph:
    """Auditable graph; scoring is diagnostic, promotion uses explicit rules."""

    frame_id: str
    source_sha256: str
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)

    def add_node(self, node_id: str, node_type: str, **payload: Any) -> str:
        self.nodes[node_id] = {"node_id": node_id, "node_type": node_type, **payload}
        return node_id

    def link(self, source: str, relation: str, target: str, **payload: Any) -> None:
        self.edges.append({"source": source, "relation": relation, "target": target, **payload})

    def as_dict(self) -> dict:
        return {"schema": "architectural-evidence-graph/1.0", "frame_id": self.frame_id,
                "source_sha256": self.source_sha256,
                "nodes": [self.nodes[key] for key in sorted(self.nodes)],
                "edges": sorted(self.edges, key=lambda row: (row["source"], row["relation"], row["target"]))}


def map_hypotheses_to_cad(analysis: dict, transform, *, source_sha256: str,
                          render_hash: str, provider: str | None, model: str | None,
                          prompt_version: str, schema_version: str) -> dict:
    """Map every hypothesis while retaining exact pixel and transform provenance."""
    provenance = {"source_sha256": source_sha256, "render_hash": render_hash,
                  "transform_version": "cad-pixel-transform/1", "transform": transform.as_dict(),
                  "provider": provider, "model": model, "prompt_version": prompt_version,
                  "schema_version": schema_version, "status": "VISION_HYPOTHESIS"}

    def points(rows):
        return [[float(v) for v in transform.pixel_to_cad(point)] for point in rows]

    mapped = {"frame_id": analysis["frame_id"], "provenance": provenance,
              "building_shells": [], "boundary_hypotheses": [], "region_roles": [],
              "physical_spaces": [], "functional_zones": [], "doors": [], "windows": [],
              "open_passages": [], "stairs": [], "shafts": [], "unresolved_regions": []}
    for row in analysis.get("building_shells") or []:
        mapped["building_shells"].append({**row, "outer_ring_cad": points(row["outer_ring_px"]),
            "inner_rings_cad": [points(ring) for ring in row["inner_rings_px"]], "provenance": provenance})
    for row in analysis.get("boundary_hypotheses") or []:
        mapped["boundary_hypotheses"].append({**row, "geometry_cad": points(row["geometry_px"]),
                                                "provenance": provenance})
    for row in analysis.get("region_roles") or []:
        mapped["region_roles"].append({**row, "polygon_cad": points(row["polygon_px"]),
                                        "provenance": provenance})
    for row in analysis.get("physical_spaces") or []:
        mapped["physical_spaces"].append({**row, "polygon_cad": points(row["polygon_px"]),
                                           "provenance": provenance})
    for row in analysis.get("functional_zones") or []:
        mapped["functional_zones"].append({**row, "geometry_cad": points(row["geometry_px"]),
                                            "provenance": provenance})
    for kind in ("doors", "windows", "open_passages", "stairs", "shafts", "unresolved_regions"):
        for row in analysis.get(kind) or []:
            key = "geometry_px"
            mapped[kind].append({**row, "geometry_cad": points(row.get(key) or []), "provenance": provenance})
    return mapped


def _cad_lines(segments: list[dict], frame_id: str) -> list[tuple[dict, LineString]]:
    result = []
    for row in segments:
        if row.get("frame_id") not in {None, frame_id} or row.get("status") != "ACCEPTED":
            continue
        geometry = _line(row.get("geometry") or [])
        if geometry is not None:
            result.append((row, geometry))
    return result


def _boundary_evidence(line: LineString, *, role: str, adjacent_regions: list[str],
                       cad_lines: list[tuple[dict, LineString]], labels: list[dict],
                       dimensions: list[dict], region_roles: dict[str, str], tolerance: float) -> dict:
    support = ["VISION_GLOBAL_SUPPORT"]
    conflicts = []
    source_handles = []
    exact_length = 0.0
    near_length = 0.0
    search = max(tolerance * 8, line.length * .015)
    for row, cad in cad_lines:
        overlap = cad.intersection(line.buffer(max(tolerance * 2, line.length * .002))).length
        if overlap > 0:
            near_length += overlap
            source_handles.append(row.get("source_handle"))
        if cad.distance(line) <= max(tolerance * 2, line.length * .002):
            exact_length += overlap
        crossing = cad.crosses(line) and cad.intersection(line).geom_type == "Point"
        if crossing and min(cad.length, line.length) > tolerance * 10:
            conflicts.append("STRONG_CAD_WALL_CONFLICT")
    if exact_length / max(line.length, 1e-12) >= .75:
        support.append("CAD_WALL_EXACT")
    elif near_length / max(line.length, 1e-12) >= .35:
        support.append("CAD_WALL_NEAR")

    # Labels are independent of Vision.  Labels on both sides of a separator
    # support room separation; a label inside a proposed enclosure supports its region.
    side = max(search * 2, line.length * .04)
    left = right = 0
    a, b = list(line.coords)[0], list(line.coords)[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    for label in labels:
        point = label.get("point")
        if not point or Point(point).distance(line) > max(line.length, side * 8):
            continue
        cross = dx * (float(point[1]) - a[1]) - dy * (float(point[0]) - a[0])
        if cross > 0: left += 1
        elif cross < 0: right += 1
    if left and right:
        support.append("LABEL_SEPARATION")

    roles = {region_roles.get(identity) for identity in adjacent_regions} - {None, "UNKNOWN"}
    if role in {"EXTERIOR_SHELL", "COURTYARD_EDGE"} and roles:
        support.append("SITE_INTERIOR_ROLE_SUPPORT")
    if dimensions and any(any(Point(p).distance(line) <= search * 3 for p in row.get("definition_points") or [])
                          for row in dimensions):
        support.append("DIMENSION_SUPPORT")

    hard = sorted(set(conflicts) & HARD_CONFLICTS)
    independent = sorted(set(support) - {"VISION_GLOBAL_SUPPORT", "VISION_LOCAL_SUPPORT",
                                         "CAD_WALL_EXACT", "CAD_WALL_NEAR"})
    if "CAD_WALL_EXACT" in support and not hard:
        authority, material = AUTHORITY_CAD, "PHYSICAL_WALL"
    elif not hard and (independent or "CAD_WALL_NEAR" in support):
        authority, material = AUTHORITY_INFERRED, "NONE"
    else:
        authority, material = AUTHORITY_UNRESOLVED, "UNKNOWN"
    return {"support_classes": sorted(set(support)), "conflict_classes": hard,
            "source_handles": sorted({value for value in source_handles if value}),
            "authority": authority, "material_geometry": material,
            "physical_barrier": "PROVEN" if material == "PHYSICAL_WALL" else "PHYSICAL_BARRIER_UNKNOWN",
            "diagnostic_score": round(min(1.0, .3 + .35 * bool(independent) + .5 * ("CAD_WALL_EXACT" in support)
                                               + .2 * ("CAD_WALL_NEAR" in support)), 3)}


def _segments_from_ring(points: list) -> list[list[list[float]]]:
    return [[points[index], points[(index + 1) % len(points)]] for index in range(len(points))]


def build_boundary_evidence_graph(*, mapped: dict, segments: list[dict], texts: list[dict],
                                  dimensions: list[dict], source_sha256: str,
                                  tolerance: float) -> dict:
    frame_id = mapped["frame_id"]
    graph = EvidenceGraph(frame_id=frame_id, source_sha256=source_sha256)
    cad_lines = _cad_lines(segments, frame_id)
    for row, _ in cad_lines:
        graph.add_node(row["segment_id"], "CAD_SEGMENT", authority=AUTHORITY_CAD,
                       source_handle=row.get("source_handle"), geometry=row.get("geometry"))
    for index, row in enumerate(texts):
        if row.get("point"):
            graph.add_node(_stable_id("LABEL", frame_id, index, row.get("text"), row["point"]),
                           "TEXT_LABEL", text=row.get("text"), point=row["point"])

    region_roles = {row["region_id"]: row["role"] for row in mapped["region_roles"]}
    shell_adjacent=[identity for identity,role in region_roles.items()
                    if role in {"BUILDING_INTERIOR","SITE_EXTERIOR","SEMI_EXTERIOR","COURTYARD","LIGHTWELL"}]
    boundary_rows = list(mapped["boundary_hypotheses"])
    known = {row["boundary_id"] for row in boundary_rows}
    for shell in mapped["building_shells"]:
        for index, geometry in enumerate(_segments_from_ring(shell["outer_ring_cad"])):
            identity = f"{shell['shell_id']}:EDGE:{index}"
            if identity not in known:
                boundary_rows.append({"boundary_id": identity, "geometry_cad": geometry,
                    "geometry_px": [], "role": "EXTERIOR_SHELL", "adjacent_regions": shell_adjacent,
                    "evidence": shell["evidence"], "confidence": shell["confidence"],
                    "uncertainties": shell["uncertainties"], "provenance": shell["provenance"]})
    boundaries = []
    for row in boundary_rows:
        line = _line(row.get("geometry_cad") or [])
        if line is None:
            continue
        evidence = _boundary_evidence(line, role=row["role"], adjacent_regions=row["adjacent_regions"],
            cad_lines=cad_lines, labels=texts, dimensions=dimensions, region_roles=region_roles,
            tolerance=tolerance)
        identity = row["boundary_id"] or _stable_id("BOUNDARY", frame_id, list(line.coords))
        record = {**row, **evidence, "boundary_id": identity,
                  "geometry_cad": [[float(x), float(y)] for x, y in line.coords],
                  "status": "SUPPORTED" if evidence["authority"] != AUTHORITY_UNRESOLVED else "HUMAN_REQUIRED"}
        boundaries.append(record)
        graph.add_node(identity, "VISION_BOUNDARY", role=row["role"], geometry=record["geometry_cad"],
                       authority=evidence["authority"], material_geometry=evidence["material_geometry"])
        for support in evidence["support_classes"]:
            support_id = _stable_id("EVIDENCE", identity, support)
            graph.add_node(support_id, "EVIDENCE_CLASS", evidence_class=support)
            graph.link(support_id, "SUPPORTS", identity)
        for conflict in evidence["conflict_classes"]:
            conflict_id = _stable_id("CONFLICT", identity, conflict)
            graph.add_node(conflict_id, "CONFLICT", conflict_class=conflict)
            graph.link(conflict_id, "CONTRADICTS", identity)
        for segment_id in [row["segment_id"] for row, cad in cad_lines if cad.distance(line) <= max(tolerance * 8, line.length * .015)]:
            graph.link(segment_id, "ALIGNS_WITH", identity)
    return {"evidence_graph": graph.as_dict(), "boundaries": boundaries}


def _boundary_authority_for_edge(edge: LineString, boundaries: list[dict], tolerance: float) -> str:
    covered = {AUTHORITY_CAD: 0.0, AUTHORITY_INFERRED: 0.0, AUTHORITY_HUMAN: 0.0}
    for row in boundaries:
        line = _line(row["geometry_cad"])
        if line is None:
            continue
        amount = edge.intersection(line.buffer(max(tolerance * 4, edge.length * .01))).length
        if row["authority"] in covered:
            covered[row["authority"]] += amount
    authority, length = max(covered.items(), key=lambda item: item[1])
    return authority if length / max(edge.length, 1e-12) >= .55 else AUTHORITY_UNRESOLVED


def construct_hybrid_topology(*, mapped: dict, boundary_analysis: dict,
                              source_sha256: str, tolerance: float,
                              human_decisions: list[dict] | None = None) -> dict:
    boundaries = [dict(row) for row in boundary_analysis["boundaries"]]
    decisions = human_decisions or []
    for decision in decisions:
        if decision.get("answer") not in {"YES", "A", "B"}:
            continue
        for hypothesis_id in decision.get("affected_hypothesis_ids") or []:
            for row in boundaries:
                if row["boundary_id"] == hypothesis_id:
                    row.update(authority=AUTHORITY_HUMAN, material_geometry="NONE",
                               physical_barrier="PHYSICAL_BARRIER_UNKNOWN", status="SUPPORTED")

    shell_records = []
    for shell in mapped["building_shells"]:
        polygon = _polygon(shell["outer_ring_cad"], shell["inner_rings_cad"])
        if polygon is None:
            continue
        edge_authorities = [_boundary_authority_for_edge(_line(edge), boundaries, tolerance)
                            for edge in _segments_from_ring(shell["outer_ring_cad"])]
        perimeter = max(polygon.length, 1e-12)
        lengths = {key: 0.0 for key in (AUTHORITY_CAD, AUTHORITY_INFERRED, AUTHORITY_HUMAN, AUTHORITY_UNRESOLVED)}
        for edge, authority in zip(_segments_from_ring(shell["outer_ring_cad"]), edge_authorities):
            lengths[authority] += _line(edge).length
        shell_records.append({"envelope_id": _stable_id("HYBRID-ENVELOPE", source_sha256, mapped["frame_id"],
                                                          shell["outer_ring_cad"]),
            "frame_id": mapped["frame_id"], "outer_ring": shell["outer_ring_cad"],
            "interior_voids": shell["inner_rings_cad"], "area": polygon.area, "perimeter": polygon.length,
            "authority_composition": {key: round(value / perimeter, 6) for key, value in lengths.items()},
            "status": "INPUT_REQUIRED" if lengths[AUTHORITY_UNRESOLVED] / perimeter > .02 else "HIGH_CONFIDENCE",
            "geometry_authority": "MIXED", "vision_hypothesis_ids": [shell["shell_id"]],
            "material_geometry": "MIXED_OR_UNKNOWN"})

    spaces = []
    for hypothesis in mapped["physical_spaces"]:
        polygon = _polygon(hypothesis["polygon_cad"])
        if polygon is None:
            continue
        authorities = [_boundary_authority_for_edge(_line(edge), boundaries, tolerance)
                       for edge in _segments_from_ring(hypothesis["polygon_cad"])]
        unresolved = sum(_line(edge).length for edge, authority in zip(
            _segments_from_ring(hypothesis["polygon_cad"]), authorities) if authority == AUTHORITY_UNRESOLVED)
        ratio = unresolved / max(polygon.length, 1e-12)
        supported = ratio <= .02
        candidates = sorted(hypothesis.get("semantic_candidates") or [],
                            key=lambda row: float(row.get("confidence", 0)), reverse=True)
        semantic = candidates[0]["type"] if candidates else "unknown"
        authority_set = set(authorities)
        geometry_authority = (next(iter(authority_set)) if len(authority_set) == 1 else "MIXED")
        space_id = _stable_id("HYBRID-SPACE", source_sha256, mapped["frame_id"], hypothesis["polygon_cad"])
        spaces.append({"physical_space_id": space_id, "space_id": space_id, "frame_id": mapped["frame_id"],
            "polygon": hypothesis["polygon_cad"], "interior_rings": [],
            "centroid": [polygon.centroid.x, polygon.centroid.y],
            "geometric_area_drawing_units": polygon.area, "area_m2": None,
            "category": semantic, "use": semantic,
            "status": "HIGH_CONFIDENCE" if supported and semantic != "unknown" else "INPUT_REQUIRED",
            "confidence": float(candidates[0].get("confidence", 0)) if candidates else 0.0,
            "geometry_authority": geometry_authority,
            "boundary_authorities": authorities, "source_handles": [],
            "vision_hypothesis_ids": [hypothesis["vision_space_id"]], "human_decision_ids": [],
            "evidence": [{"class": "HYBRID_BOUNDARY_FIRST_RECONSTRUCTION",
                          "authority": geometry_authority, "unresolved_perimeter_ratio": ratio}],
            "functional_zones": [], "adjacent_space_ids": [],
            "material_barrier_policy": "PHYSICAL_BARRIER_UNKNOWN_UNLESS_CAD_CONFIRMED"})

    # Vision zones never generate enclosure edges.
    zones = []
    for zone in mapped["functional_zones"]:
        geometry = _polygon(zone["geometry_cad"])
        host = None
        if geometry is not None:
            host = next((space for space in spaces if _polygon(space["polygon"]).covers(geometry.representative_point())), None)
        record = {"functional_zone_id": _stable_id("ZONE", source_sha256, mapped["frame_id"], zone["zone_id"]),
                  "frame_id": mapped["frame_id"], "polygon": zone["geometry_cad"],
                  "semantic_type": zone["semantic_type"], "host_space_id": host and host["physical_space_id"],
                  "authority": "VISION_SEMANTIC_HYPOTHESIS", "creates_boundary": False}
        zones.append(record)
        if host:
            host["functional_zones"].append(record)

    overlaps = sum(_polygon(spaces[i]["polygon"]).intersection(_polygon(spaces[j]["polygon"])).area
                   for i in range(len(spaces)) for j in range(i + 1, len(spaces)))
    portals=[]; access_edges=[]
    for collection,kind in (("doors","DOOR"),("windows","WINDOW"),("open_passages","OPEN_PASSAGE")):
        for index,hypothesis in enumerate(mapped[collection]):
            geometry=_line(hypothesis.get("geometry_cad") or [])
            host=None
            if geometry is not None:
                candidates=[row for row in boundaries if _line(row["geometry_cad"]) is not None]
                authority_rank={AUTHORITY_CAD:0,AUTHORITY_HUMAN:1,AUTHORITY_INFERRED:2,AUTHORITY_UNRESOLVED:3}
                host=min(candidates,key=lambda row:(_line(row["geometry_cad"]).distance(geometry),
                                                    authority_rank.get(row["authority"],4)),default=None)
                if host is not None and _line(host["geometry_cad"]).distance(geometry)>max(tolerance*8,geometry.length*.25):
                    host=None
            if host and host["authority"]==AUTHORITY_CAD:
                authority="CAD_SUPPORTED_PORTAL"
            elif host and host["authority"] in {AUTHORITY_INFERRED,AUTHORITY_HUMAN} and float(hypothesis.get("confidence",0))>=.9:
                authority="MULTI_EVIDENCE_INFERRED_PORTAL" if host["authority"]==AUTHORITY_INFERRED else "HUMAN_CONFIRMED_PORTAL"
            else:
                authority="UNRESOLVED"
            portal_id=_stable_id("HYBRID-PORTAL",source_sha256,mapped["frame_id"],kind,index,
                                 hypothesis.get("geometry_cad"))
            record={"portal_id":portal_id,"kind":kind,"geometry":hypothesis.get("geometry_cad") or [],
                    "host_boundary_id":host and host["boundary_id"],"connects":hypothesis.get("connects") or [],
                    "authority":authority,"status":"HIGH_CONFIDENCE" if authority!="UNRESOLVED" else "INPUT_REQUIRED",
                    "material_geometry":"NONE","vision_hypothesis":hypothesis}
            portals.append(record)
            if kind in {"DOOR","OPEN_PASSAGE"} and authority!="UNRESOLVED" and len(record["connects"])==2:
                access_edges.append({"portal_id":portal_id,"space_a":record["connects"][0],
                                     "space_b":record["connects"][1],"authority":authority})
    unresolved_boundaries = [row for row in boundaries if row["authority"] == AUTHORITY_UNRESOLVED]
    questions = [{"question_id": _stable_id("QUESTION", source_sha256, mapped["frame_id"], row["boundary_id"]),
                  "frame_id": mapped["frame_id"], "question_version": "hybrid-boundary-question/1",
                  "question": "Is there a separating architectural boundary in the highlighted location?",
                  "options": ["YES", "NO", "UNKNOWN"], "geometry": row["geometry_cad"],
                  "affected_hypothesis_ids": [row["boundary_id"]],
                  "reason": "VISION_ONLY_MATERIAL_TOPOLOGY", "source_sha256": source_sha256}
                 for row in unresolved_boundaries[:3]]
    return {"schema": "hybrid-architectural-topology/1.0", "frame_id": mapped["frame_id"],
            "trigger": "SOURCE_ARCHITECTURE_GEOMETRY_INSUFFICIENT", "mode": "HYBRID_ARCHITECTURAL_RECOVERY",
            "authority_lattice": [AUTHORITY_CAD, AUTHORITY_INFERRED, AUTHORITY_HUMAN, AUTHORITY_UNRESOLVED],
            "boundaries": boundaries, "building_envelopes": shell_records, "physical_spaces": spaces,
            "functional_zones": zones, "portals":portals,
            "access_graph":{"nodes":[space["physical_space_id"] for space in spaces],"edges":access_edges},
            "topology_operations":{"supported":["MERGE_WEAK_CELLS","SPLIT_BY_SUPPORTED_BOUNDARY",
                                                   "CREATE_SPACE_FROM_SUPPORTED_ENCLOSURE"],
                                   "applied":[{"operation":"CREATE_SPACE_FROM_SUPPORTED_ENCLOSURE",
                                               "space_id":space["physical_space_id"],"reversible":True}
                                              for space in spaces]},
            "overlap_area": overlaps, "human_questions": questions,
            "remaining_unresolved_boundaries": len(unresolved_boundaries),
            "status": ("CONFLICT" if overlaps > max(tolerance * tolerance, 1e-12) else
                       ("TARGETED_HUMAN_DECISION" if questions else "PASS")),
            "mechanical_safety": {"vision_boundary_is_wall_material": False,
                "human_boundary_is_wall_material": False,
                "unknown_material_boundary_policy": "PHYSICAL_BARRIER_UNKNOWN",
                "downstream_engineering_allowed": not questions and overlaps == 0}}


def validate_human_decision(decision: dict, *, source_sha256: str, frame_id: str,
                            hypothesis_geometry_hash: str, question_version: str) -> dict:
    expected = {"source_sha256": source_sha256, "frame_id": frame_id,
                "hypothesis_geometry_hash": hypothesis_geometry_hash,
                "question_version": question_version}
    invalid = [key for key, value in expected.items() if decision.get("invalidation_inputs", {}).get(key) != value]
    return {"valid": not invalid, "invalidated_by": invalid,
            "authority": AUTHORITY_HUMAN if not invalid else AUTHORITY_UNRESOLVED}
