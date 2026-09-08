# Step 5 — Equipment Integrity Contract

Step 5 moves equipment contradictions upstream instead of relying only on the exact generated-DXF release gate.

## Release invariants

1. Physical equipment coordinates must be finite and traceable to their owning source/plan authority.
2. Coordinate collapse is evaluated inside one `source_file + level/plan authority + equipment kind` scope. Equal coordinates in separate DXF files are not merged and do not contaminate each other.
3. Four or more same-kind objects with fewer than half as many spatial clusters are a hard coordinate-collapse failure.
4. A generated split indoor unit requires a physical outdoor-unit entity and an explicit pair (`ODU.serves`, `IDU.odu_id`, or `IDU.odu_tag`). Nearest-neighbour pairing is forbidden.
5. An IDU and its ODU cannot occupy the same representative point. A schedule `odu_tag` or destination note is not evidence that the outdoor entity exists in the plan.
6. Project HVAC proposal placement must produce distinct ODU points. If a distinct in-plan proposal point cannot be supported, the HVAC design fails closed rather than stacking equipment at one coordinate.
7. When physical equipment geometry is supplied to the v19 pipeline, equipment integrity runs before manufacturer selection. Invalid or unresolved geometry cannot be legitimized by selecting a manufacturer model.
8. The exact generated-DXF integrity gate remains a defense-in-depth release gate and still blocks IDU-without-ODU, schedule/plan contradictions, and severe equipment coordinate collapse.

## Status policy

- `PASS`: geometry and required split pairing are explicit and non-degenerate.
- `INPUT_REQUIRED`: required physical evidence is missing or a coordinate is invalid; no geometry is guessed.
- `FAIL`: contradictory evidence exists (duplicate IDs, ambiguous/orphan pair, coincident pair, severe coordinate collapse).

The contract is additive and preserves legacy representation calls that do not provide physical entity geometry. Once physical entities are provided, they are authoritative and must pass the Step 5 checks.
