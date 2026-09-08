# Step 7 — Detail Materialization Contract

Step 7 removes the historical condition in which a project-specific detail could appear in the Detail Register without executable drawing content in the issued DXF.

## Release invariants

1. Every detail ID written to a project-specific Detail Register must also be materialized on a `GENERAL_DETAIL` board in the exact issued DXF.
2. Materialization requires both real non-text geometry and readable ID tags on `ENGITOOLS-M-DETAIL`; duplicated register text alone is not evidence.
3. Each materialized detail is validated in its own deterministic cell after reopening the exact DXF. A cell requires at least 12 non-text geometry entities and at least two detail-layer ID tags.
4. All selected detail IDs are written and materialized. The previous `[:18]` register truncation is forbidden.
5. Details are assigned to the applicable PLUMBING, HVAC, or GAS detail board using their rule identity. An unmatched detail falls back only to an existing approved detail board; no new sheet or project scope is invented.
6. A `GENERAL_DETAIL` board with no project-specific selected detail is `INPUT_REQUIRED` before the DXF is mutated.
7. Step 7 schematic geometry contains no inferred pipe size, equipment capacity, pressure, rainfall, clearance, manufacturer dimension, or other unverified project number. The exact drawing explicitly requires final project/manufacturer values where applicable.
8. Step 6 riser integrity remains upstream. Detail materialization cannot run around a zero-branch or contradictory riser condition.
9. The existing exact-artifact integrity gate and `validate_detail_library` remain defense in depth after Step 7; they are not replaced by the new upstream materialization proof.

## Status policy

- `PASS`: every registered project-specific detail has exact-file geometry and tags in its own detail cell.
- `INPUT_REQUIRED`: a detail board exists without a supported project-specific detail selection.
- `FAIL`: exact-file reopen fails, a detail ID lacks its materialized tags/geometry, or the number of passing materialized details differs from the expected selection.
- `NOT_APPLICABLE`: the approved output package has no `GENERAL_DETAIL` board.

The contract does not manufacture technical dimensions or duplicate a nearby detail merely to satisfy a count. Geometry is schematic and traceable to the selected detail rule; project/manufacturer values remain unresolved unless supported by project evidence.