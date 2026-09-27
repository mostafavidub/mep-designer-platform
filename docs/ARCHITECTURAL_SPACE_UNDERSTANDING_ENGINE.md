# Canonical Architectural Space Understanding Engine

## Contract

`cad_engine.architectural_space_engine` is the single canonical producer of
architectural space knowledge. It returns schema
`canonical-architectural-model/1.0`. Existing `rooms` are a temporary projection;
new consumers use `physical_spaces`, `functional_zones`, `architectural_objects`,
`dimensions`, `frames` and `completeness`.

## Pipeline

1. Hash and validate the source and read declared units.
2. Extract traceable CAD primitives, including nested INSERT evidence and native
   DIMENSION records.
3. Reuse the governed frame detector; unknown/non-floor drawings remain explicit.
4. Derive an adaptive geometry tolerance from project units and line statistics.
5. Infer repeated frame-local wall thicknesses, pair faces and stitch collinear
   fragments into stable canonical Wall Objects.
6. Separate continuous wall-axis topology from occupied wall-solid intervals;
   gaps remain traceable candidate openings and become enclosure-only virtual
   closures.
7. Derive a first-class Building Envelope from canonical wall cycles and retain
   an explicit unbounded EXTERIOR face.
8. Polygonize the canonical enclosure graph, falling back to already-classified
   source boundaries only when the canonical graph cannot prove a closed cycle.
9. Create deterministic physical-space IDs from source, frame and normalized ring.
10. Fuse text, block/layer signature, object and spatial evidence.
11. Represent multiple functions inside one cell as Functional Zones; never create
   fake partition walls.
12. Associate dimensions conservatively with nearby boundaries and preserve source
   handles, measurement, definition points and overrides.
13. Generate separate Enclosure and Access graphs, label-host evidence chains, a
    machine report and SVG QA overlays.
14. Report every unknown frame, unknown space or unit problem as INPUT_REQUIRED.
15. Block Mechanical calculations, topology and routing before they execute when
    completeness is not VERIFIED.

## Identity and evidence

Physical-space IDs are deterministic for the same approved source, frame and
normalized geometry. Geometry fingerprints remain stable across irrelevant layer
renames. Each accepted record carries source SHA, frame ID, CAD handles and its
evidence classes.

## Physical space and functional zone

A physical space is a connected bounded region. A functional zone is a semantic
use within that region. A continuous Living/Dining/Kitchen therefore produces one
physical space and three zones with approximate zone boundaries, not three fake
rooms.

## Vision boundary

The engine exposes a provider-neutral `VisionAdapter` and structured
`VisionCandidate`. The initial provider is deliberately disabled: an unresolved
semantic region remains INPUT_REQUIRED until a governed image renderer, coordinate
mapping and provider are configured and validated. Vision may add evidence but
cannot overwrite contradictory CAD facts.

## Human review

The SVG preview contains only canonical cells with status colors, stable IDs,
type and area. The UI must present unresolved issues only. A user response is an
additional evidence record; it does not mutate or erase original DXF evidence.

## Performance and safety

Source hashing is single-pass, block recursion is bounded to twelve levels, source
size is capped, and frame-local polygonization avoids cross-sheet spaces. Runtime,
entity counts, candidate counts and adaptive tolerance are recorded. ZIP expansion
continues to be owned by the existing hardened upload layer; the canonical engine
receives its validated extracted DXF path.

## Migration

`app.architecture_reconstruction_v1` attaches the canonical model to upload
analysis and projects it into existing topology fields. PMM stores the full model
additively. Old persisted projects remain readable, but only newly analyzed models
that pass canonical completeness can authorize downstream engineering.

## Canonical wall and portal authority

Source LINE entities are provenance, not wall identity. A Wall Object owns its
axis, occupied intervals, inferred interruptions, source fragments, junctions and
confidence. Portal fusion searches for a compatible Wall Object span and a proven
gap; no source line is required at the centre of an opening. A continuous strong
wall still rejects the portal. Vision confidence thresholds and fail-closed
mechanical release are unchanged.

## Current limitations

- A configured Vision provider/render-coordinate adapter is not yet available;
  ambiguous exploded text therefore stays INPUT_REQUIRED.
- Door/window portal hosting is not promoted without a verified Wall Object gap.
- Curved wall pairing, exterior/semi-exterior region classification and full
  face-pair consolidation still require additional benchmark evidence.
- Private benchmark drawings are not committed and are never generation inputs.
