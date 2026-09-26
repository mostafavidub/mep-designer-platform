# Architectural Space Engine — Current State and Root Cause

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
