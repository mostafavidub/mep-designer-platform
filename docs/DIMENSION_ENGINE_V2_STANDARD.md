# Planha Dimension Engine v2 Standard

**Status:** SHADOW-FIRST IMPLEMENTATION CONTRACT  
**Rule:** `MEP-DIM-001`  
**SWCIS:** 4.40.0

## 1. Engineering objective

Dimension Engine v2 is a construction-documentation subsystem, not a CAD decoration layer.

Its acceptance question is:

> If CAD coordinates disappeared and the installer had only the printed drawing, dimensions and symbols, could every P0/P1 construction-critical object be located from stable datums without guessing?

The target network is:

**Minimum Determining SETOUT Graph + Intentional CHECK Dimensions**

Dimension count is never a quality metric.

## 2. Protected v1 baseline

V2 may not regress the locked v1 contract from SWCIS-2026-0280:
source preservation, measured/display separation, override conflict handling, unit sanity, source DIMTYPE/orientation evidence, local axes, Mechanical set-out, exact duplicate control, governed clearances, XData identity, exact-file reopen, final-network reconciliation and the prohibition on count-only acceptance.

The machine baseline is `standards/golden/dimension-engine-v1.baseline.json`.

## 3. Target pipeline

`Semantic Building Model -> Building Reference Model v2 -> Drawing Profile -> Requirement Engine -> Determinacy Solver -> Source Reconciliation -> Redundancy/Check Optimizer -> Placement Solver -> Renderer -> Exact-file QA -> Construction Determinacy Gate`

Dimensioning remains downstream from routing, sizing, equipment selection and architectural geometry authority.

## 4. Canonical ontology

Every Planha-owned engineering dimension has:

- Purpose
- Role: `SETOUT` or `CHECK`
- stable Reference A
- stable Reference B
- native measurement
- canonical metre value when a defensible unit basis exists
- drawing profile
- priority class P0-P3
- rule identity for governed code dimensions
- source lineage/evidence

Supported purposes include PROPERTY, SETBACK, BUILDING_OVERALL, GRID, STRUCTURAL_SETOUT, WALL_SETOUT, ROOM_CLEAR, STAIR, SHAFT, OPENING_SIZE, OPENING_POSITION, EQUIPMENT_SIZE, EQUIPMENT_POSITION, PENETRATION, SLEEVE, RISER, CODE_CLEARANCE, CONSTRUCTION_CLEARANCE and CHECK.

## 5. Building Reference Model v2

Stable semantic subfeatures include:

- GRID_AXIS / GRID_INTERSECTION
- STRUCTURAL_CENTERLINE / STRUCTURAL_FACE
- WALL_CORE_FACE
- WALL_INNER_FINISH_FACE
- WALL_OUTER_FINISH_FACE
- BUILDING_ENVELOPE_FACE
- PROPERTY_BOUNDARY
- SHAFT_FACE
- STAIR_CORE_FACE
- OPENING_JAMB / OPENING_CENTERLINE
- EQUIPMENT_CENTER / EQUIPMENT_FACE
- PIPE_RISER_CENTER
- PENETRATION_CENTER

References carry stable identity, source, confidence, evidence, level/plan identity, datum class and local-axis context.

Anonymous coordinates may be retained as raw evidence, but must not replace an available semantic reference in a production engineering dimension.

## 6. Human checkpoint: wall reference basis

Planha must not guess whether an architectural wall dimension refers to finish face, wall core, structural face or centerline.

If the basis is not explicit, wall-face references are withheld and `WALL_REFERENCE_BASIS_REQUIRED` is emitted.

This checkpoint is scoped. Mechanical drawings may continue using independent GRID, ENVELOPE, STRUCTURE, SHAFT or STAIR datums when they do not depend on ambiguous wall faces.

## 7. Semantic envelope authority

A raw drawing bounding box is not building-envelope authority.

V2 accepts:

1. explicit semantic building-envelope polygons; or
2. proven closed loops of explicitly exterior wall segments.

It models primary/secondary envelope and courtyard boundaries. If neither is provable, it emits `BUILDING_ENVELOPE_NOT_PROVEN`.

Bounding-box values may only be used after semantic equivalence is established.

## 8. Determinacy graph

Construction-critical elements are graph nodes. Stable datums are graph anchors. SETOUT dimensions are constraints.

For free point targets, two independent locating constraints are required unless an explicit host resolves a degree of freedom. For line-like elements, the profile defines the minimum locating constraint count.

The solver selects the smallest explainable constraint set sufficient to determine required P0/P1 elements. Candidate dimensions are not individually mandatory merely because they were generated.

CHECK dimensions are retained intentionally even when mathematically redundant.

## 9. Drawing profiles

### ARCHITECTURAL_FLOOR_PLAN
Property/setback, envelope overall, grid, major wall/partition set-out, stair/core, shaft, critical openings and governed clearances.

### MECHANICAL_PLAN
Only necessary architectural context plus construction-critical Mechanical targets such as risers/stacks, drains, cleanouts, sleeves, penetrations, mechanical openings, pumps, tanks and fixed equipment.

Architecture dimensions are never repeated wholesale.

### PARKING_PLAN
Parking bay, aisle, ramp, structural obstacle, core, maneuvering and governed clearance requirements. Targets must come from explicit semantic parking data; visual similarity is not authority.

### ROOF_PLAN
Overall/grid/core/shaft context plus explicit drains, penetrations, parapet/fixed geometry and roof equipment.

### DETAIL
Only dimensions relevant to the explicit detail scope.

## 10. Source reconciliation

Every important source dimension is reconciled as:

`Source Dimension <-> Recognized Geometry <-> Planha Intent`

States are VERIFIED, REGENERATED, PRESERVED_AS_EVIDENCE, SUPPRESSED_IN_VIEW, CONFLICT or UNKNOWN/HUMAN_REVIEW_REQUIRED.

Displayed text is never calculation authority. Non-numeric source text remains evidence. Material numeric contradictions remain conflicts.

## 11. Redundancy and checks

Exact semantic SETOUT duplicates are removed.

Mathematical derivability alone is not grounds for removal. Intentional CHECK, overall verification and datum-class-compatible chain closure dimensions may remain.

Contradictory values for the same semantic reference pair fail closed.

## 12. Placement

Placement is downstream from engineering intent.

The solver considers text boxes, dimension line occupancy, existing obstacles, board/title areas and tier hierarchy. Global hierarchy is local set-out -> grid -> overall/check -> site/property.

If no collision-free placement is found, the intent remains unchanged and the result becomes HUMAN_REVIEW_REQUIRED. Engineering values/references may never be altered to solve graphics.

## 13. Construction Determinacy Gate

The gate detects:

- under-determined P0/P1 geometry
- unstable/missing semantic references
- critical source conflicts
- unit ambiguity
- semantic duplicates
- contradictory pair definitions
- datum-class-aware chain closure failures
- governed rule identity failures
- unresolved placement
- source information loss

Grid chains are never closed against envelope-face overall dimensions unless they explicitly share the same datum class.

## 14. Code-controlled dimensions

A CODE_CLEARANCE requires an explicit Rule ID, stable references, actual geometry and canonical minimum.

Repeated values in historical drawings never become a hidden regulation or design default.

## 15. Ambiguous imported geometry

Unproven Grid, Wall, Property, Shaft, Opening or Structural classification must emit HUMAN_REVIEW_REQUIRED rather than confident production dimensioning.

## 16. Synthetic regression corpus

`tests/test_dimension_engine_v2.py` and `standards/test-suites/dimension-v2-regression.json` govern 25 project-agnostic scenarios including complex envelopes, rotated/aligned geometry, wrong units, overrides, parking, roof, penetrations, duplicates, missing datums, collisions and multi-plan isolation.

Private customer DXFs stay outside Git and are comparison-only.

## 17. Shadow mode and promotion

V2 runs alongside v1 and reports:

- v1/v2 counts by purpose
- additions/removals
- determinacy defects
- reconciliation findings
- placement findings

Shadow mode never changes visible output.

Promotion to visible v2 output requires:
1. all v1 protected regressions PASS;
2. all v2 positive/destructive tests PASS;
3. no unresolved P0/P1 determinacy defect in the promotion cohort;
4. six-DXF benchmark complete;
5. exact-file v2 renderer QA PASS;
6. owner-approved staging test after implementation closure.

Production deployment remains separately owner-approved.
