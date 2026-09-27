# ADR: Canonical Architectural Space Understanding Engine

## Status

Proposed — implementation and evidence tracked by SWCIS-2026-0284.

## Decision

Planha will use one canonical, deterministic-first architectural model. A
`PhysicalSpace` represents connected geometry; zero or more `FunctionalZone`
records describe uses inside it. Downstream disciplines consume this model and
must not independently re-detect rooms.

The pipeline order is source validation, frame classification, calibration,
primitive extraction, canonical wall reconstruction, wall-interruption analysis,
enclosure continuity, envelope inference, physical-space subdivision, portal
classification, access-graph generation, semantic zoning, dimension association,
optional vision reconciliation, evidence fusion, completeness evaluation and
targeted human review.

Wall Material, Enclosure Barrier and Access Edge are separate authorities. A
non-material topological closure may bridge a source-supported interruption for
envelope/subdivision purposes, but it is never a routing obstacle and never
creates pedestrian access. Portal type is classified only after physical spaces
exist. A supported but uncorroborated single-line break remains diagnostic and
cannot be promoted merely because it would complete a desired room.

Native CAD Opening Evidence is also a separate, pre-envelope supporting record.
Existing block/layer and combined swing-arc/leaf/wall detectors may report an
opening hypothesis and candidate Wall Objects before Physical Spaces exist, but
that record is not a Portal, does not fabricate a material gap, cannot create an
Access Edge and cannot authorize continuity without independent wall evidence.

Wall authority is a first-class canonical object rather than a source LINE. The
model distinguishes wall-axis continuity from occupied wall solid, records
interruptions as candidate openings, constructs enclosure-only virtual closures,
and keeps the Enclosure Graph separate from the portal-driven Access Graph.

Wall admission is a bounded evidence funnel rather than an early binary layer
filter. Raw geometry retains extraction rejection reasons; confirmed walls seed
the graph; local/partial parallel-face families, scale-aware junctions,
collinear continuity and non-pathological enclosure gain may promote supported
partition candidates in bounded passes. Labels and fixtures are supporting
anchors only and never generate geometry. Every promotion records its prior
state, evidence, topology before/after and source handles.
Building Envelope and EXTERIOR are explicit topology records. Portal fusion may
bind only to a compatible Wall Object gap and cannot override a continuous wall.

Building Envelope selection is evidence-based. The engine first enumerates all
closed canonical cycles and records their labels, topology, boundary-wall
quality, fixtures and provenance. It then constructs a Plan Region Graph with
explicit `BUILDING_INTERIOR`, `SEMI_EXTERIOR`, `SITE_EXTERIOR`, courtyard,
lightwell, void and unknown roles. The envelope is derived only from defensible
interior regions; a drawing frame, site enclosure, or largest closed cycle has
no envelope authority. Mixed interior/site evidence and competing components
fail closed instead of being resolved by a hidden weighted score.

Physical-space cells are produced from an explicitly noded Enclosure Barrier
Graph containing the selected Building Envelope, occupied Wall Object intervals,
supported void boundaries and non-material Virtual Closures. Legacy stitched-axis
polygonization is retained only as an internal comparison/fail-closed fallback;
it is not allowed to silently replace a valid canonical subdivision. Where both
wall faces are unavailable, the physical boundary is explicitly recorded as a
centerline approximation rather than face-resolved geometry.

Vision is accessed through an adapter and is invoked only for unresolved regions.
Its evidence is advisory until reconciled with CAD. Critical ambiguity fails
closed. Stable identities are content-derived from source, frame, level and
normalized geometry.

## Consequences

- Open plans are no longer represented by invented walls.
- Missing labels do not imply missing geometry.
- Unknown areas cannot silently disappear.
- Existing PMM consumers receive a compatibility projection during migration.
- More drawings will truthfully stop at `INPUT_REQUIRED` until evidence or a
  focused human decision resolves the ambiguity.
