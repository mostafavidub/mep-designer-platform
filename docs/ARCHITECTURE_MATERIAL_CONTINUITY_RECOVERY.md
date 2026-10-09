# Architecture material-continuity recovery

## Scope and private-source governance

- dependency: PR #328 at `8ffac717e5cf61651b8973f0fbc59b931d97768c`
- frozen private source identity: SHA-256 `43c696a6e2703ce746d22b169b90108f0a6a44d3873e56e32f80124793fe1d70`
- no private source bytes, filenames, screenshots, crops, or customer identity are committed

This change diagnoses continuity from identified source-material intervals. It
does not relax Architecture release, create a Wall, infer a Portal, or select a
building shell by size.

## Root causes

`source_supported_endpoint_closures` previously compared canonical Wall-axis
endpoints. A canonical axis is topology identity, not proof that source wall
material reaches its endpoint. This could create non-material continuity far
from the nearest occupied `MATINT-*` interval. The corrected detector compares
only occupied material-interval endpoints and binds every closure to its host
Wall IDs, MATINT IDs, source handles, and source lineage.

The old endpoint rule also treated aligned proximity as sufficient continuity,
and treated orthogonality plus double-face confidence as sufficient corner
authority. The corrected rule requires exact shared source lineage or an
actual localized source-face intersection for corner continuity, exact shared
lineage for drafting fragmentation, or independently localized opening
evidence for an aperture. A nearby endpoint by itself remains unresolved.

Wall-interruption closures now require material on both sides of the
interruption. They retain their MATINT bindings and explicitly carry
`material = false`, `material_geometry = NONE`, and Wall, Portal, Routing and
Access authority `NONE`.

## Deterministic material graph

The architecture output now contains a diagnostic
`material-continuity-graph/1.0` for every relevant frame. Source material is
noded at actual intersections and endpoint-on-material events within the
existing geometry tolerance. Every diagnostic `MATSEG-*` retains its original
MATINT, Wall, handle, lineage and geometry identity. A near miss is not snapped.
Source material and governed non-material continuity remain distinct edge types. Components expose
MATINT count, Wall/source identity, length, bounds, node/open-endpoint count,
closure count, cycle rank, and closed-cycle status. Open endpoints preserve
MATINT/Wall/handle/lineage/orientation identity and list nearest endpoints only
as diagnostics. Nearest endpoints never create graph edges.

Candidate endpoint relations and selected governed closures are separate
layers. All deterministic candidates remain visible even when they share an
endpoint. Endpoint exclusivity applies only to selected proof-bearing closures;
an `INPUT_REQUIRED` alternative is never consumed or hidden by another
candidate.

## Gap taxonomy and authority

The bounded classification vocabulary is:

- `PROVEN_DOOR_APERTURE`
- `PROVEN_WINDOW_APERTURE`
- `GOVERNED_DRAFTING_FRAGMENTATION`
- `PROVEN_CORNER_CONTINUITY`
- `SOURCE_ROLE_CLASSIFICATION_REQUIRED`
- `ENGINE_SOURCE_ROLE_DEFECT`
- `TRANSFORM_OR_LINEAGE_DEFECT`
- `TRUE_SOURCE_GEOMETRY_GAP`
- `UNRESOLVED`

Only the first four can support governed non-material enclosure continuity,
and only after their stated evidence contract is met. Opening evidence grants
no Portal or Access authority. A recovered single source line meeting a proven
material endpoint is classified `SOURCE_ROLE_CLASSIFICATION_REQUIRED`; it is a
bounded source-role question and receives no continuity role. Reference arcs,
legends, north arrows, and unclassified curves never prove an aperture.

## Private-source conclusion

The frozen source contains no independently qualified opening-evidence record
for the currently identified Roof or Typical discontinuities. Several short
relations join high-confidence double-face Walls to recovered single-line
geometry and are bounded source-role candidates. Other relations require
opening evidence or a detector extension. Absence of currently qualified
evidence is not classified as proof that source geometry is absent.

The engine therefore remains fail-closed. Human review may classify an existing
stable source segment as separator/non-separator/unknown, but may not draw a
Wall or create an aperture. Mechanical release remains blocked until a complete
source-supported shell is independently qualified.

## Final frozen-source replay

The final noded replay ran once after all focused graph, false-corner,
candidate-preservation, architecture and governance regressions passed.

Roof retains 105 MATINTs represented by 153 noded graph segments and 31 source
material junctions. After 23 qualified closures it has 53 components, 125 open
endpoints, aggregate cycle rank 17, and four closed local components. The
largest component has seven MATINTs, twelve graph segments, three junctions,
51.507 m of source material, seven open endpoints, three closures, and no
cycle.

Typical retains 169 MATINTs represented by 270 graph segments and 69 source
material junctions. After 43 qualified closures it has 62 components, 151 open
endpoints, aggregate cycle rank 47, and nine closed local components. The
largest component has sixteen MATINTs, 42 graph segments, fourteen junctions,
18.817 m of source material, seventeen open endpoints, three closures, and
cycle rank seven; it is not a closed component.

All 326 deterministic endpoint candidates are retained: 65 selected proven
closures and 261 diagnostic alternatives. The selected proof classes are 64
exact localized source-face intersections and one shared-source-lineage proof.
Of the 79 corners previously called proven, 62 remain selected/proven, one has
source proof but loses selection to an endpoint conflict, and sixteen are
demoted to unresolved. Orthogonality plus proximity proves none.

The previous 31 unresolved relations remain unresolved: six require opening
evidence, 24 expose a remaining deterministic detector limitation, and one is
genuinely ambiguous. Across the complete preserved candidate set, 113 raw
source-role relations reduce deterministically to 41 bounded source-object
groups; those questions are not exposed yet. Qualified opening evidence remains
zero, and no absence is classified `TRUE_SOURCE_GEOMETRY_GAP` merely because a
detector found no evidence.

The replay preserves all 257 Wall IDs and 19 Physical Space IDs in order, four
verified spaces, 37 input requirements, 15 review decisions, Dimension
reconciliation `PASS` with zero conflicts, and zero Vision calls. Both frames
retain zero canonical cells and `INPUT_REQUIRED` envelopes. Architecture and
Mechanical release remain disabled. Because 24 known detector limitations
remain, the correct current status is `BLOCKED_BY_ENGINE_DEFECT`.
