# Step 6 — Riser Integrity / Plan Reconciliation Contract

Step 6 moves the historical `BRANCHES=0` contradiction upstream. A riser register can no longer report `PASS` merely because no expected plan branches were recorded.

## Release invariants

1. Every active riser represented in the documentation graph must have at least one real `PLAN_BRANCH` edge derived from project routing evidence.
2. `BRANCHES=0` is never a passing state. Missing branch evidence is `INPUT_REQUIRED`; no synthetic branch is created to satisfy the gate.
3. Existing plan/riser reconciliation must also pass. Missing or orphan mappings are contradictions and remain `FAIL`.
4. A `PLUMBING_RISER` board without a riser graph is `INPUT_REQUIRED` rather than an empty or falsely passing register.
5. The Step 6 check runs before any documentation entity is written to the DXF. A failing Step 6 result leaves the exact file unchanged.
6. A riser register may write `STATUS: PASS` only after all represented risers have non-zero branch evidence and reconciliation is clean.
7. The generated-DXF integrity gate remains defense in depth and still rejects any `BRANCHES=0` plus passing-status contradiction that reaches the exact artifact.

## Status policy

- `PASS`: every represented riser has real plan-branch evidence and reconciliation is clean.
- `INPUT_REQUIRED`: a represented riser has zero branch evidence or a riser board has no graph evidence.
- `FAIL`: reconciliation is contradictory or an orphan plan branch is present.

The contract does not infer missing routes, duplicate a nearby branch, or create zero-length/synthetic geometry merely to make a riser pass.