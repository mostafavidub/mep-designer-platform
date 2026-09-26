# Architectural Space Engine — Current State and Root Cause

## Blind real-project validation — 2026-09-26

The private Fasihi architectural DXF was processed blind. Reference Mechanical
drawings were not opened or used during generation.

| Check | Expected from independent drawing evidence | Detected | Status |
|---|---:|---:|---|
| Authoritative frames | Roof, Level 01, Ground | 3 | PASS |
| Reference-only views | sections/elevations/furniture excluded | excluded | PASS |
| Unit calibration | metres despite an incorrect mm header | metres + declared conflict | PASS |
| Overlapping space area | 0 | 0 after interior-ring preservation | PASS |
| Label-evidenced uses | yard, toilet, terrace, bathroom, duct, bedroom, living, closet, reception, kitchen | extracted; mostly not bound to valid cells | PARTIAL |
| Physical spaces | all real rooms, no drafting cells | 157 candidates, 153 unresolved | FAIL |
| Door/window topology | every accepted opening hosted and linked | no reliable source openings accepted | FAIL |
| Geometric accounted coverage | all authoritative usable area, without overlap | 56.88% | FAIL |
| Vision runtime | localized ambiguity adapter | interface complete; provider absent | CONFIG_REQUIRED |
| Mechanical release | blocked while critical architecture is unresolved | blocked | PASS |

### New root causes and fixes

Exploded SHX/graphic geometry and nested block graphics were entering the wall
graph. Polygon interior rings were also lost during canonical materialization,
recreating overlap after correct polygonization. The implementation now admits
nested/curved boundaries conservatively, rejects high-density glyph layers by
their drawing signature, preserves interior rings in identity and QA, models
accepted openings with host-wall/space topology, reports geometric coverage and
dimension reconciliation, and exposes only unresolved regions for review.

The branch is **not ready for Staging**. The remaining unresolved cells require
a general portal/wall-semantic reconstruction slice. No Fasihi coordinate, name
or dimension has been encoded.

### Multi-project blind regression

| Project | Authority frames | Candidates | Verified | Unknown | Accounted coverage | Overlap | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| P1 | 4 | 444 | 12 | 432 | 47.18% | 0 | CONFLICT |
| P3 | 4 | 268 | 6 | 261 | 9.06% | 0 | CONFLICT |
| P7 | 4 | 399 | 6 | 393 | 48.85% | 0 | CONFLICT |
| Fasihi | 3 | 157 | 4 | 153 | 56.88% | 0 | CONFLICT |

This table is intentionally a release blocker, not a claim of completion. It
shows that overlap preservation is fixed across the corpus while semantic wall
and portal reconstruction remains the dominant unsolved capability.

## General wall reconstruction iteration — 2026-09-26

Boundary-to-source diagnostics were run before changing production inference.
They show that the dominant false-cell source is anonymous top-level geometry,
not short lines: UNKNOWN_GEOMETRY accounts for 98.04% of unresolved Fasihi
cells, 99.07% in P1, 37.79% in P3 and 100% in P7. P3 additionally has 62.21%
of unresolved cells dominated by wall-face geometry. Layer `0` is the largest
unknown contributor in Fasihi, P1 and P7. The unknown segments include both
LINE and LWPOLYLINE entities with long tails up to roughly 30--43 drawing
units, so a generic length cutoff would delete legitimate architecture while
retaining many drafting objects.

The current branch now classifies segments before polygonization, infers
recurring parallel wall-face offsets through a spatial index, keeps unknown
geometry out of the wall graph, selectively admits only label-supported
partitions connected to the accepted wall network, and rejects wall-solid
strip cells using thicknesses inferred from the drawing. Every admission and
rejection is traceable. Anonymous door candidates require combined swing-arc,
leaf and host-wall proximity evidence; an arc alone is rejected.

| Project | Before candidates | After candidates | After verified | After unknown | Coverage | Overlap | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 444 | 132 | 9 | 123 | 97.96% | 0 | 16.79 s |
| P3 | 268 | 160 | 4 | 156 | 11.00% | 0 | 11.00 s |
| P7 | 399 | 146 | 3 | 143 | 59.22% | 0 | 10.30 s |
| Fasihi | 157 | 33 | 4 | 29 | 71.52% | 0 | 23.30 s |

These numbers demonstrate general reduction of false topology without restoring
overlap, but they are not exit evidence. The four real drawings still have zero
verified geometry-derived doors and windows, many unknown regions, and no
independent Golden polygons/portals from which precision, recall or IoU can be
computed. Completeness therefore remains `CONFLICT` and Mechanical remains
fail-closed. Open passage reconstruction, window reconstruction, envelope-first
classification, weak-edge merging and Golden scoring are still release blockers.

### Topology-closure baseline and independent Golden gate

The topology-closure phase deliberately made no further runtime reconstruction
change before creating measurable QA infrastructure. The selected independent
review floors are Fasihi Ground, Fasihi Level 01, P1 Ground and P3 Ground. A
source-only annotation package renders raw DXF primitives for those frame bounds
without importing the reconstruction engine, and creates an initially PENDING
Golden document. The scorer refuses to calculate metrics until an independent
reviewer marks the annotation APPROVED and includes reviewed space polygons.
Golden data lives under test-suite governance and has no runtime import path.

Per-frame diagnostics explain distinct failure modes. P1 has high area coverage
but remains over-segmented/semantically unresolved: its authoritative floors
contain 40--47 remaining cells while only 7--14 architectural labels are hosted.
P3 is a separate envelope failure: every authoritative frame has less than 40%
accounted coverage, and its Ground frame retains 50 cells with only 3 hosted
labels. P7 Ground/Mezzanine primarily combine over-segmentation and semantic
binding failure; its roof frames have envelope failure. Fasihi's two primary
floors are geometrically closer, but semantic binding and real portal detection
remain incomplete. These classifications are diagnostic evidence, not new
project-specific production rules.

Baseline Golden precision/recall/IoU is currently `INCOMPLETE_GOLDEN`, not zero:
the four source-only packages still require independent polygon/portal review.
Runtime envelope, merge and portal changes remain prohibited until this review
establishes the measurable baseline required by the closure specification.

## Runtime authority

The deployed canonical application enters through `cad_engine.main:app`; the web
application installs `app.architecture_reconstruction_v1`, while the Mechanical
CAD pipeline declares `cad_engine.engineering_pipeline_v13` as its reconstruction
authority. File names that contain historical revisions are compatibility debt,
not proof that a capability is complete.

## Current-state classification

| Area | Status | Evidence |
|---|---|---|
| DXF ingestion | PARTIAL | DXF reading and bounded underlay inventory exist; ZIP safety, source cache and complete primitive provenance are not one canonical stage. |
| Frame/level isolation | IMPLEMENTED BUT UNVERIFIED | Plan segmentation and level detectors exist, but unknown frames can still reach independent consumers and no single completeness report owns every frame. |
| Room reconstruction | PARTIAL | Active reconstruction starts with recognized TEXT/MTEXT and optionally attaches the smallest enclosing closed polyline. |
| LINE/ARC wall topology | OPEN | LINE entities are inventoried but not polygonized into all physical-space cells. ARC/SPLINE wall faces are not canonical topology inputs. |
| Semantic classification | PARTIAL | Small duplicated alias maps classify labelled rooms; evidence fusion and canonical ontology are absent. |
| Physical space vs functional zone | OPEN | The current record conflates geometry and room use. |
| Dimensions | PARTIAL | A separate semantic dimension engine exists, but architectural space reconstruction does not associate DIMENSION provenance with each space. |
| Completeness gate | PARTIAL | An 18-control QA gate exists, but it validates supplied records; the producer cannot prove all frame area is accounted for. |
| Visual/human checkpoint | PARTIAL | Architecture review UI exists, but its overlay is built from incomplete geometry and can ask the user to repair what the engine never reconstructed. |
| PMM integration | PARTIAL | PMM stores aggregated `space-group` counts derived from labels, not canonical polygons/zones/openings. |

## Symptom → evidence → root cause → impact

**Symptom:** the review preview omits large portions of a plan, open/unlabelled
spaces disappear, and the user is asked to confirm incomplete polygons.

**Evidence:** `cad_engine.engineering_pipeline_v13.reconstruct_architecture`
creates `rooms` by iterating recognized text and selecting an enclosing closed
polyline. Separate alias dictionaries exist in multiple application and CAD
modules. Individual wall faces, openings, dimensions and unexplained frame area
do not drive room creation.

**Root cause:** there is no canonical, geometry-first architectural model. The
system has parallel feature detectors, not a staged reconstruction engine whose
output is measured for completeness.

**Impact:** downstream Mechanical logic can receive aggregated room counts while
actual regions are missing or mis-hosted. A green feature test therefore cannot
prove that the uploaded architecture is complete.

## Target architecture

One canonical pipeline owns source identity, frames, units, primitives, topology,
physical spaces, functional zones, openings, objects, dimensions, evidence,
ambiguity and completeness. Exact CAD facts are processed first. Vision is an
optional adapter for unresolved semantics only and cannot overwrite contradictory
CAD evidence. Every unresolved critical region becomes `INPUT_REQUIRED`; affected
downstream engineering is blocked.
