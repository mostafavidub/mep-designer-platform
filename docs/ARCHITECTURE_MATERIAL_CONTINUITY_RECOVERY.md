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

The old endpoint rule also treated aligned proximity as sufficient continuity.
The corrected rule requires exact shared source lineage for governed drafting
fragmentation, proven double-face material on both orthogonal sides for corner
continuity, or independently localized opening evidence for an aperture. A
nearby endpoint by itself remains unresolved.

Wall-interruption closures now require material on both sides of the
interruption. They retain their MATINT bindings and explicitly carry
`material = false`, `material_geometry = NONE`, and Wall, Portal, Routing and
Access authority `NONE`.

## Deterministic material graph

The architecture output now contains a diagnostic
`material-continuity-graph/1.0` for every relevant frame. Source material and
governed non-material continuity remain distinct edge types. Components expose
MATINT count, Wall/source identity, length, bounds, node/open-endpoint count,
closure count, cycle rank, and closed-cycle status. Open endpoints preserve
MATINT/Wall/handle/lineage/orientation identity and list nearest endpoints only
as diagnostics. Nearest endpoints never create graph edges.

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
for the critical Roof or Typical discontinuities. The larger material graph is
distributed across many components; the closed components are local/detail
cycles rather than a defensible building shell. Several short relations join a
high-confidence double-face Wall to recovered single-line geometry and are
bounded source-role questions. Other aligned gaps lack shared lineage or
opening proof and remain unresolved. No transform or nested-lineage loss was
found in the critical witnesses.

The engine therefore remains fail-closed. Human review may classify an existing
stable source segment as separator/non-separator/unknown, but may not draw a
Wall or create an aperture. Mechanical release remains blocked until a complete
source-supported shell is independently qualified.

## Final frozen-source replay

The final implementation was replayed once after targeted tests passed. Roof
contains 105 MATINT edges across 69 components after 31 governed closures, with
124 open endpoints, seven closed local components, and aggregate cycle rank
eight. Its largest connected component contains six MATINTs, 41.547 m of source
material, five closures, two open endpoints, and no cycle. Typical contains 169
MATINT edges across 101 components after 49 governed closures, with 178 open
endpoints, eleven closed local components, and aggregate cycle rank thirteen.
Its largest component contains seven MATINTs, 14.496 m of material, five
closures, two open endpoints, and no cycle. Neither frame has a defensible
canonical envelope or canonical cell.

Across both frames there are 79 proven corner relations, 45 bounded
`SOURCE_ROLE_CLASSIFICATION_REQUIRED` relations, and 31 unresolved relations.
There are zero qualified opening-evidence records and therefore zero proven
Door or Window aperture closures. The replay preserved all 257 Wall IDs and all
19 Physical Space IDs in order, four verified spaces, 37 input requirements,
15 review decisions, Dimension reconciliation `PASS` with zero conflicts,
zero Vision calls, and disabled Architecture and Mechanical release.
