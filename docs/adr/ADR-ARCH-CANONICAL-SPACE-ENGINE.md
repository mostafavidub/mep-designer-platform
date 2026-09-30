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

### Whole-floor Semantic Scout is not Geometry Authority

DeepSeek may inspect a clean whole-floor render and return approximate normalized
centers and bounding boxes for functional observations. Such observations use
`VISION_SEMANTIC_HINT`, with `material_geometry = NONE`,
`routing_authority = NONE`, and `engineering_geometry = false`. A semantic box
is neither a wall nor a room polygon, does not become a routing obstacle, and
cannot authorize equipment placement, room loads, final routing, or release.

Physical Space and Functional Zone remain distinct. Kitchen, dining, and living
hints may overlap inside one open physical space without creating partitions.
Semantic and geometry status are tracked independently: a bathroom can be
strongly supported while its boundary remains `INPUT_REQUIRED`.

Evidence precedence is exact DXF label, deterministic CAD object, agreement
between global and local Vision, local Vision, then global Vision. Contradictions
are retained. Approximate hints map many-to-many onto CAD candidates for evidence
reporting only. The sole downstream mode is `MEP_PREANALYSIS`; final routing,
sizing, loads, placement and engineer-ready output remain blocked until
authoritative geometry exists.

#### Compact multi-pass transport

The monolithic whole-floor response is deprecated after two real Fasihi Ground
calls returned malformed JSON near 4 KB. This is response-budget evidence, not
a claimed provider limit. Semantic Scout v2 keeps the complete render and exact
DXF evidence in the request while minimizing response output: first a compact
whole-floor inventory (`t`, `n`, `c`), then bounded localization calls by
coherent semantic group (`t`, `b`, `c`).

Each call is independently strict, budgeted below 1800 estimated bytes and
observable on success and failure. A technically unusable first response may be
retried exactly once with the same governed request; this applies only to
provider failure, missing/invalid tool call, malformed JSON, or invalid compact
schema. Valid but semantically weak answers are not retried, and no fallback
transport is introduced. Missing a required group prevents a final semantic map.
Provider records are expanded locally with labels, objects, stable IDs, MEP
groups and conflicts while retaining every non-authoritative safety field.

Exact DXF functional text is also materialized as an
`EXACT_DXF_SEMANTIC_ANCHOR` point evidence record. Semantic Anchor Fusion gives
such anchors precedence over Vision while allowing compatible colocated
functions such as Stair+Duct or open-plan Kitchen+Living to coexist without
inventing partitions. Incompatible exact labels remain conflicts. Both anchors
and non-conflicting Vision hints may qualify bounded `MEP_PREANALYSIS` search
and verification priorities, but they retain `material_geometry = NONE`,
`routing_authority = NONE`, and no final engineering authority.

The first controlled Candidate Graph v2 classification used one Fasihi Ground
request, an immutable hash manifest, a source-derived overlay, forced strict-tool
transport and an ID-only schema. DeepSeek returned one tool call but truncated
its argument JSON inside a string at approximately 24 KB. The complete response
was rejected before fusion. No partial salvage, geometry authority, retry,
fallback or second-project call was allowed. V2 input/transport compatibility is
qualified; provider output reliability for the full bounded set is not.

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

### Envelope and portal completion decision (SWCIS 4.57.0)

Canonical wall axes may be topologically joined across a bounded drafting gap
only when both hosts are independently reconstructed high-confidence,
double-face walls.  The permitted distance is derived from the frame-local wall
thickness distribution.  Collinear opening spans and orthogonal corner joins
are recorded as source-supported closure objects with stable provenance.

Such a join is enclosure evidence only.  It has `material = false` and
`wall_authority`, `routing_authority`, `portal_authority`, and
`access_authority` all equal to `NONE`.  It cannot manufacture a wall, door,
window, opening, route obstacle, or access edge.  Oversized gaps, single-line
fragments, and low-confidence walls remain open and fail closed.

`LEGACY_FALLBACK` remains diagnostic and is never release authority for a
Mechanical-authority frame.  Exact labels for compatible living, reception,
dining, kitchen, entrance, and lobby functions may coexist in an open physical
space.  An exact enclosed-service, sleeping, shaft, duct, or utility label in
that same unresolved cell is evidence of a missing partition; semantic labels
cannot promote that geometry to `VERIFIED`.

Fasihi Ground proves a high-confidence outer envelope after this change, but
does not yet prove its internal partitions or any physical portals.  Therefore
the implementation remains fail-closed and is not staging-qualified.

### Internal wall and portal qualification (SWCIS 4.58.0)

Internal wall reconstruction now retains source-admission evidence and marks a
single-line partition recovered by repeated local enclosure support as
`SUPPORTED_PARTITION`; this is evidence, not material promotion.  Endpoint
joins are selected greedily so one physical endpoint cannot participate in
multiple synthetic closures.  Every proposed join receives a stable gap record
before it may enter subdivision, classified as door, window, open passage,
missing wall geometry, drafting break, or unresolved ambiguity.

Nested block geometry retains its top-level insert handle and block path so an
exploded leaf-and-swing assembly is auditable after transformation.  A symbol
near a wall is still insufficient: final Door, Window, Open Passage and access
authority require a compatible, supported interruption on the selected host
wall.  A symbol over continuous wall material is rejected.  Windows never
create access, ambiguous gaps create neither closure nor portal, and all
derived closure geometry remains non-material with no routing authority.

Fasihi Ground still has unresolved internal-wall topology and no qualified
physical portals after this bounded change.  Its completeness therefore stays
`CONFLICT`; deployment and Mechanical authority remain prohibited.

### Replayable gap interpretation gate (SWCIS 4.59.0)

Opening evidence is compatible with a wall interruption only when it shares a
canonical host and is local to that exact gap under a tolerance derived from
source precision, local wall thickness, opening width, and gap width.  Sharing
a wall ID alone is insufficient and cannot classify a distant gap.

After deterministic evidence is exhausted, a human may classify an existing
source-derived gap as Door, Window, Open Passage, Continuous Wall, or Unknown.
The decision is topology interpretation only: it cannot cut a new wall,
manufacture material, or directly grant Portal, routing, or access authority.
Questions and decisions are identified by source SHA, frame, dependency build,
gap geometry, host walls, evidence snapshot, and question version.  Any material
identity change makes only the affected decision stale; stale, malformed, or
conflicting decisions fail closed.  A first run with material unresolved gaps
stops before Dimension Association and downstream Mechanical processing.

After valid review replay stabilizes topology, a dimension may participate in
geometry reconciliation only when both non-default witness points bind to the
current space boundary and their span crosses the space interior.  The checked
geometric value is the distance between those bound references, never the
nearest width or height of the whole space bounding box.  Chain, thickness,
set-out, overall, single-reference, and otherwise unbound dimensions remain
explicitly not evaluated; they are not silently promoted to conflicts.

### Gap-first Portal and Void authority (SWCIS 4.60.0)

A Portal may bind only to an existing local canonical gap with compatible
semantics. A current, fingerprint-valid `HUMAN_CONFIRMED` decision is accepted
by the binding contract, but remains semantic authority only: Portal geometry
is copied from the source-derived gap, never from a swing-arc bounding box.
Every verified Door or Open Passage exposes a stable Portal identifier and a
provenance-rich Access edge retaining the gap, host wall, source handles and
evidence identifiers. Windows, continuous walls and unknown interpretations
create no Access edge.

Swing arcs and leaves are supporting assembly evidence. Neither can cut a wall
or create an aperture. Likewise, a Duct/Shaft label may select or classify
independently closed source geometry but may not create, close, resize or move
a boundary. Where an independent boundary is not proven, the Void remains
input-required and Mechanical routing stays fail-closed. Compatible Reception,
Living and Kitchen semantics may coexist as approximate Functional Zones in one
Open Plan Physical Space; they gain no wall authority.
