# ADR — Structural columns and future exterior-boundary witnesses

Status: Phase 1 accepted; Phase 2 contract design accepted; Phase 2 runtime
authority explicitly deferred.

## Decision

Planha distinguishes five independent facts:

1. `STRUCTURAL_COLUMN_GEOMETRY`: a qualified, source-backed closed footprint.
2. `COLUMN_WALL_INTERFACE`: exact source-supported contact between a column
   face and a Wall's occupied material interval.
3. `COLUMN_FACE_BOUNDARY_WITNESS`: a particular column perimeter interval that
   may support an exterior candidate path.
4. `WALL_MATERIAL_CONTINUITY`: independently proven occupied Wall material.
5. `EXTERIOR_ENVELOPE_AUTHORITY`: a complete validator-qualified boundary.

Phase 1 persists only the first fact. It grants no authority from the remaining
four. Point contact, proximity and owner interpretation cannot create an edge.

## Proposed Phase 2 relation

A future relation record must bind `column_id`, the exact source column face,
`wall_id`, supporting `MATINT` identity, contact point/interval, occurrence
lineage, qualification evidence, competing interpretations, exterior-role
evidence and an explicit authority decision with explanation.

A boundary witness may be considered only when all of the following exist:

- valid source-backed column footprint;
- source-backed occupied Wall material;
- exact Wall/column contact;
- unique applicable column face;
- uniquely supported exterior-facing path;
- no incompatible interpretation;
- no fabricated connector or tolerance-expanded closure;
- complete lineage to original DXF occurrences.

Ambiguous face/path selection remains `INPUT_REQUIRED`. Free-standing interior
columns are ineligible. Point contact alone is insufficient.

## Required future impact review

Phase 2 requires coordinated changes to the canonical schema, geometric relation
graph, exterior-envelope candidate engine, independent validator, serialization,
diagnostic visualization, dimension references and Mechanical obstacle/routing
consumers. It also requires a migration contract and rollback to the prior Git
identity.

Positive fixtures must cover an exterior corner column with two independently
supported contacting Walls. Destructive fixtures must cover interior columns,
near-but-noncontacting columns, decorative squares, repeated handles in distinct
transforms, incomplete footprints, ambiguous faces, point-only contact and real
missing source evidence. None may create a Room or release Mechanical.

## Consequence

Persistent object identity is now available for future evaluation, but no new
Column-to-Envelope authority is active. A separate owner-approved implementation
and independent qualification are required.
