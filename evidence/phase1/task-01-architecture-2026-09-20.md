# Task 01 — Architecture / Levels / Roof / Shafts

## Status

PARTIAL — implemented and verified fail-closed behavior; final room/shaft boundary reconstruction is still input-required on the real benchmark cohort.

## Active staging build

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
- Model status: `INPUT_REQUIRED`
- Missing evidence: `ROOM_BOUNDARY_GEOMETRY`, `SHAFT_BOUNDARY_GEOMETRY`
- Fabricated geometry count: `0`
- Rooms: 4 label-backed; valid polygons: 0
- Shafts: 1 label-backed; valid polygons: 0
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

Architecture files for projects 1, 2, 3, 4 and 7 were evaluated with the same code. Unit inference passed on all five. Canonical print frames were found for all tested levels except project 2. Most room boundaries in these consultant DXFs are not explicit closed room polygons, so the engine now records label-only evidence and does not manufacture room boxes.

## Tests

- 42 focused unit/integration tests passed after canonical-frame scoping, composite symbol grouping, shaft-label evidence and fail-closed geometry changes.
- 8 focused tests and Python compilation passed after user-facing gap disclosure changes.

## Remaining acceptance gap

Task 01 cannot be marked PASS under the phase definition until room and shaft boundaries are reconstructed and verified on real files, or a corrected/structured architectural input supplies those boundaries. Per the requested vertical-slice order, Sanitary + Vent must not be declared started or complete before this gap is closed.
