# Task 01 — Architecture / Levels / Roof / Shafts

## Status

PARTIAL (cohort) / PASS (benchmark project 4) — evidence-backed linework
polygonization and adaptive clear-space segmentation are implemented.  The
engine now reconstructs every room and shaft in project 4 without fabricating
an enclosing box.  Projects whose source does not contain a resolvable plan
frame or whose open spaces have no architectural separator remain explicitly
`INPUT_REQUIRED`.

## Baseline staging build before this change

- Web commit: `937277272e78eafe7ff604e10c86150578c46a13`
- Worker commit: `937277272e78eafe7ff604e10c86150578c46a13`
- Production changed: no

## Real-project evidence

Benchmark project 38 (`Task 1 Architecture API Benchmark 04 - f60310f`) was re-analysed from the architecture DXF only.

- Unit inference: PASS, `effective_scale_to_m=1.0`
- Unit provenance: `dimension-measurement-override-mm-header-to-m`, high confidence
- Authoritative levels: one ground floor
- Pseudo roof: rejected and retained only as non-active candidate evidence
- Canonical frame: detected, `4388.419454,-5951.757377,4409.419454,-5922.057377`
- Model status before: `INPUT_REQUIRED`
- Model status after: `PASS`
- Missing evidence after: none
- Fabricated geometry count: `0`
- Rooms before/after: 4 label-backed; valid polygons: `0 -> 4`
- Shafts before/after: 1 label-backed; valid polygons: `0 -> 1`
- Boundary method: noded source-line polygonization followed by the smallest
  label-exclusive clear-space offset where an evidenced door gap prevents a
  direct closed cell
- Audit evidence retained per polygon: source DXF handles, source layers,
  source entity count, clearance offset, method, confidence and deterministic
  geometry fingerprint
- Fragmented entities previously reported as doors: 180 before, 1 composite symbol after canonical scoping/component grouping

## Exact artifact reopen

Revision 3 was generated before the stricter geometry disclosure gate and independently reopened from the downloaded artifact.

- Path: `/tmp/planha-project-38-final-unit-valid.dxf`
- Bytes: `19529020`
- SHA-256: `9bf095195d06cf5e231bac8a40bdf87faeacebda3b4e405c5ddb6fef3132b3cd`
- DXF version: `AC1027`
- Modelspace entities: `2834`
- Layers: `296`
- Dimensions: `24`
- Layouts: `Layout2`, `Model`

Roof text in the output is limited to vent termination/details/notes; no roof plan was activated.

## Regression cohort

Architecture files for projects 1, 2, 3, 4 and 7 were evaluated with the same
code. Unit inference passed on all five. Results at the authoritative-level
model are:

- Project 1: `5/19` room polygons, `1/1` shaft polygons — `INPUT_REQUIRED`
- Project 2: `0/22` room polygons; no canonical frame — `INPUT_REQUIRED`
- Project 3: `6/13` room polygons, `2/2` shaft polygons — `INPUT_REQUIRED`
- Project 4: `4/4` room polygons, `1/1` shaft polygons — `PASS`
- Project 7: `4/7` room polygons — `INPUT_REQUIRED`

The remaining labels in projects 1, 3 and 7 occupy genuinely shared/open
cells in the submitted linework.  Splitting these cells by a guessed rectangle
or Voronoi boundary would fabricate architecture, so the final gate correctly
requests input. Project 2 must first obtain a confirmed canonical plan frame.

## Tests

- 38 focused architecture/level/fixture integration tests pass.
- New cases cover open LINE entity polygonization, door-gap segmentation,
  shaft enclosure recovery, multi-label outline rejection, dimension-layer
  exclusion, deterministic fingerprints and source-DXF immutability.

## Remaining acceptance gap

Task 01 is PASS for project 4 but cannot be marked PASS for the full benchmark
cohort until project 2 has a confirmed frame and the unresolved shared/open
spaces in projects 1, 3 and 7 receive real architectural separators or an
explicit user-approved space-zone boundary. Per the requested vertical-slice
order, Sanitary + Vent must not be declared started for those projects.
