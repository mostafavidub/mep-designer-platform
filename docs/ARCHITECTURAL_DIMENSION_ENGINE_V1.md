# Planha Architectural Dimension Engine v1

**Status:** implementation contract  
**Rules:** `ARCH-DIM-001` + existing `MEP-DIM-001` compatibility  
**Governance:** `SWCIS-2026-0282`

## 1. Authority

Architectural dimensioning is a downstream consumer of approved semantic
architectural geometry. It is not routing, sizing, structural design or code
interpretation authority.

The canonical pipeline is:

Semantic Architectural Geometry
→ Drawing Profile
→ Stable Construction References
→ Dimension Requirements
→ Determinacy Graph
→ Consecutive Chains
→ Intentional Checks
→ Dimension Zones/Tiers
→ CAD Materialization
→ Exact-file QA
→ Visual QA.

A positive DXF DIMENSION count is never acceptance evidence.

## 2. Protected baseline

The implementation builds on the merged MEP-DIM-001 source registry and exact
file contract. Mechanical generation continues through the existing
`build_and_materialize_plan_dimensions()` facade. Architectural generation is
additive through `cad_engine.dimensioning` and the architectural compatibility
adapter in `semantic_dimension_engine.py`.

Source measured values, displayed overrides, unit evidence, source DIMTYPE and
preservation status remain independent evidence.

## 3. Reference Model v2

Every generated engineering dimension binds to semantic element/subfeature
references. Supported subfeatures include finish/core/outer/inner faces,
centerlines, grids, column centres, opening jambs/centres, shaft faces, stair
and landing edges and property edges.

Wall face basis is fail-closed. A wall without explicit/proven finish, core or
centreline basis creates a Human Checkpoint; the engine does not silently treat
it as a finish face.

Openings require a proven host for autonomous position dimensioning.

## 4. Profiles

Independent requirement policies exist for:

- ARCHITECTURAL_FLOOR_PLAN
- SITE_PLAN
- PARKING_PLAN
- ROOF_PLAN
- OPENING_LINTEL_PLAN
- FURNITURE_PLAN

Movable furniture is not a construction dimension target.

## 5. Local frames and zones

Each semantic zone receives one or more local coordinate frames. Rotated wings
and multi-axis geometry are isolated into compatible reference graphs before
chain construction. Chain distances are measured in the selected local frame,
not as arbitrary world-coordinate Euclidean midpoint distances.

Ambiguous frames require human review.

## 6. Chains and determinacy

Professional dimension networks are consecutive chains, not all-pairs
distances. Chains:

- sort compatible parallel references in local coordinates;
- suppress zero/near-zero segments;
- keep reference classes consistent;
- may add one intentional CHECK overall;
- carry chain and check-group identity.

Every construction-critical reference must be reachable from a stable datum
through non-CHECK engineering dimensions. CHECK dimensions are excluded from
independent-definition analysis.

Over-dimension QA distinguishes engineering purpose. A geometric setback and a
governed code-clearance dimension may share references without becoming a false
over-constraint.

## 7. Specialist engines

Dedicated generators exist for openings, stairs, shafts/lightwells,
site/setback and parking geometry.

Geometric set-out is never treated as a regulatory requirement. A
CODE_CLEARANCE dimension requires explicit rule identity and authoritative
minimum evidence. Benchmark drawings never provide regulatory minima.

Site setback uses shortest segment-to-segment geometric witnesses rather than
midpoint distance.

## 8. Placement

Engineering intent is immutable before placement. Placement assigns external
and local zones and tiers. The existing proven CAD placement/materialization
facade remains the renderer compatibility layer while the v2 network owns
engineering semantics.

Obstacle coverage includes text, blocks, arcs/circles, hatches, dimensions,
leaders and solid/wipeout-like annotation obstacles when supplied.

Extension-line readability is a separate QA control from text collision.

## 9. Exact-file identity

Planha DXF XData retains intent ID, purpose, semantic reference A/B, unit
evidence, rule ID, engineering values and v2 graph identity:

- chain_id
- check_group_id
- zone_id
- coordinate_frame_id
- tier

Exact-file reopen must prove this identity remains unchanged.

## 10. Architectural Dimension QA

The fail-closed contract contains 30 controls covering units, semantic
references, profile, overall/grid/set-out/partition/opening/stair/shaft/site
requirements, code traceability, checks, closure, under/over-dimensioning,
duplicates, source evidence, zero generated dimensions, placement, extension
lines, tiers, local frames, exact reopen, DXF identity, source isolation and
visual QA.

A FINAL release cannot pass without exact-file and visual evidence.

## 11. Human Checkpoints

Stop autonomous issue when any of these is unresolved:

- wall face basis;
- semantic geometry confidence;
- source conflict;
- zone segmentation;
- code authority;
- opening host;
- local coordinate frame;
- irregular geometry determinacy;
- visually ambiguous output.

Human review is preferred to fabricated certainty.

## 12. Validation

Required validation layers are:

1. unit/contract tests;
2. project-independent synthetic golden cases;
3. destructive fail-closed cases;
4. exact-file save/reopen tests;
5. Mechanical regression;
6. reference benchmark comparison;
7. blind unseen-plan validation;
8. visual QA;
9. SWCIS validation and affected CI.

The private six-project reference corpus remains comparison-only and no
project-specific numeric value may become a hidden product default.

## 13. Release

Default path: branch → static review → targeted tests → affected CI → PR →
protected merge.

Staging and Production are separately owner-approved operations. This
implementation does not authorize either deployment.
