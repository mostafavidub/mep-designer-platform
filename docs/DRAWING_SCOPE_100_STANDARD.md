# Mechanical Drawing Scope 100 Standard

**Rule:** `MEP-DRAWING-SCOPE-001`
**Status:** LOCKED

Mechanical calculations and CAD generation may start only from a frozen drawing
manifest whose scope report is `PASS`, whose score is exactly `100`, and whose
evidence uses architectural analysis plus explicit owner answers only. A
mechanical reference drawing is never a scope input.

The gate executes these eighteen controls in order:

1. Inventory every architectural drawing candidate, level and intended output.
2. Classify floor plan, roof, section, elevation, detail, schedule, calculation and notes roles.
3. Bind each accepted drawing to one or more canonical levels.
4. Consolidate Typical floors only from explicit, non-overlapping evidence.
5. Establish each system from architectural need and an explicit owner decision.
6. Reject unsupported or cross-discipline systems.
7. Reject omission of any required level/system combination.
8. Keep floor, roof, riser, equipment, schematic, detail and calculation roles separate.
9. Build the complete deterministic `level × system` matrix.
10. Hash the ordered scope matrix and the generated manifest.
11. Reconcile manifest count, codes, families, types and level coverage exactly.
12. Preserve one family/level identity across plan, riser, calculation, schedule and detail roles.
13. Fail closed on duplicate, conflicting, unknown or unresolved scope evidence.
14. Complete scope approval before calculations or routing begin.
15. Freeze the approved manifest; post-approval mutation invalidates it.
16. Require exact generated-board parity with the frozen manifest.
17. Cover positive and destructive omission, addition, ambiguity, Typical and tamper cases.
18. Reopen the exact issued artifact; reference comparison is allowed only after blind generation and sealing.

## Scoring and release

The weights are 10 inventory, 10 classification, 10 level binding, 5 Typical
evidence, 15 system evidence, 5 unsupported-system rejection, 5 omission
rejection, 5 role separation, 10 matrix completeness, 5 deterministic identity,
5 reconciliation, 5 cross-document identity, 3 ambiguity handling, 2
pre-calculation ordering, 2 output-parity contract, and one point each for
destructive regression, reference isolation and exact reopen. Every control is
independently blocking. An aggregate score below 100, a missing control, or an
unknown status is `FAIL`.

Existing schema `3.1` proposals are stale. They must be recalculated as schema
`3.2`; no database rewrite is required.
