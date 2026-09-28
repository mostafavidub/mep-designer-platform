# ADR: Canonical Architectural Space Understanding Engine

## Status

Proposed — implementation and evidence tracked by SWCIS-2026-0284.

The external Vision integration is gated task-by-task. `SHELL_AND_BOUNDARIES_V1`
uses the full authoritative render with a bounded provider-neutral schema and an
independent cache identity. Region and opening contracts must not be enabled
until the V1 provider proof returns a schema-valid, architecturally useful result.
Invalid V1 provider JSON is quarantined outside the successful cache with an
exact validation path and key/type diff; it cannot reach the Evidence Graph.
Provider-specific normalization may be added only after an observed raw mismatch
proves a finite, semantics-preserving mapping.

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

Vision task, provider transport and canonical evidence contract are separate
authorities. A provider-facing strict-tool schema may project the canonical
contract onto the provider's documented structural keyword subset, but every
result must still pass the unchanged local canonical validator. Provider,
model, task, transport, prompt/schema versions and source/render hashes form
the cache identity. Transport failures and invalid arguments are quarantined
outside the successful cache. A fallback transport is permitted only by the
explicit capability policy and never changes architectural meaning.

The DeepSeek `deepseek-flash` strict-tool transport is structurally qualified
for `SHELL_BOUNDARIES_V1`: a forced non-thinking tool call returned exact,
canonical-valid arguments without normalization. It is not qualified as an
architecturally reliable production provider for this task: the Fasihi Ground
overlay omitted a major portion of the apparent building and classified
apparent interior/stair areas as exterior. JSON-object fallback was correctly
not invoked because the strict transport itself did not time out or fail.

### Vision geometry generation versus candidate classification

Engineering-critical topology uses candidate classification, not unconstrained
Vision geometry generation. CAD and deterministic geometry code own candidate
region polygons, boundary segments and the small finite set of possible
topological bridges. The provider may reference and classify only supplied
stable IDs. It cannot return coordinates, invent IDs, move boundaries, create
wall material, or draw a building shell. The Building Shell is a deterministic
result of the classified region-adjacency graph and the existing multi-evidence
promotion rules.

`SHELL_BOUNDARIES_V1` free-form geometry remains diagnostic-only and is
`UNQUALIFIED_FOR_ENGINEERING_AUTHORITY`. The preferred task is
`SHELL_BOUNDARY_CLASSIFICATION_V1`. It is eligible for a provider call only
after a measurable candidate-graph gate proves bounded candidate counts,
material region coverage, at least one major plan region and independently
hosted CAD text/object evidence. An insufficient graph stops before network use,
leaves Mechanical blocked and reports `FASIHI_CANDIDATE_GRAPH_INSUFFICIENT`.

Candidate Graph v2 is constructed before canonical wall and envelope authority.
It separates source geometry into hard architectural evidence, soft candidate
evidence and hard exclusions; nodes eligible source segments directly, records
polygonization cuts/dangles, exposes atomic faces and traceable weak-boundary
face groups, and diagnoses every hosted or unhosted source label. This breaks
the former circular dependency in which candidate regions could only be drawn
from already accepted canonical `plan_regions`. Candidate faces and non-material
virtual closures remain `CANDIDATE_ONLY` and cannot become wall material merely
because they improve closure or are later selected by Vision.

When a governed frame fails specifically because source architectural geometry
is insufficient, the engine enters `HYBRID_ARCHITECTURAL_RECOVERY`. This path is
boundary-first: raw CAD facts and mapped Vision hypotheses enter a first-class
Evidence Graph before envelope or spaces are constructed. Legacy candidate
spaces are diagnostic-only and cannot veto a new supported enclosure merely
because no legacy polygon overlaps it.

Every final topological boundary has one authority:
`CAD_CONFIRMED`, `MULTI_EVIDENCE_INFERRED_TOPOLOGY`,
`HUMAN_CONFIRMED_TOPOLOGY`, or `UNRESOLVED`. Promotion is rule-based and requires
no hard CAD conflict plus Vision and an independent evidence family; a weighted
score is diagnostic only. Absence of a CAD line is not a CAD contradiction.

An inferred or human-confirmed topological boundary always has
`material_geometry = NONE` and `PHYSICAL_BARRIER_UNKNOWN`. It can close an
enclosure but cannot acquire wall thickness, structural authority, or routing
obstacle authority. Human questions are localized YES/NO/UNKNOWN decisions and
are replayable only while source SHA, frame, hypothesis geometry and question
version remain unchanged.

## Consequences

- Open plans are no longer represented by invented walls.
- Missing labels do not imply missing geometry.
- Unknown areas cannot silently disappear.
- Existing PMM consumers receive a compatibility projection during migration.
- More drawings will truthfully stop at `INPUT_REQUIRED` until evidence or a
  focused human decision resolves the ambiguity.
