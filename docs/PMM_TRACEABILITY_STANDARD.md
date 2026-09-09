# PMM Engineering Traceability Standard

## Purpose

The Project Mechanical Model (PMM) is the canonical machine-readable source of truth for project mechanical entities and their provenance. Downstream calculations and documentation must remain traceable to PMM identities rather than creating disconnected local identifiers.

## Identity chain

The required engineering chain is:

`PMM Entity ID -> Calc ID -> Plan ID = Riser ID = Schedule ID -> QA`

No orphan engineering output is issuable.

## PMM identity rules

- PMM v3 adds a deterministic `identity_registry` while retaining the existing PMM fields.
- IDs are generated from canonical semantic fingerprints, not process order alone where a natural identifier exists.
- Rebuilding the same PMM from the same approved inputs must reproduce the same identity registry.
- Duplicate PMM IDs invalidate the PMM.
- Legacy aliases such as equipment IDs and drawing sheet codes may resolve to canonical PMM entity IDs through `alias_to_entity_id`.

## Calculation rules

- Every room/system calculation row receives a deterministic `calc_id`.
- A design-basis numeric override may change a numerical result but must not change the calculation identity if the same room/system engineering object is being recalculated.
- When source object aliases exist in PMM, calculation rows carry resolved `source_pmm_ids`.
- Missing authoritative project values remain explicit in the existing basis/status contracts; traceability must never turn an assumption into a project fact.

## Drawing/riser/schedule reconciliation

For each documented network segment, the calculation identity is reused as the Plan, Riser, Calculation, and Schedule identity. `reconcile_calculation_outputs` must fail closed when:

- calculation IDs are missing or duplicated;
- a calculation has no corresponding documented output;
- an output has no calculation;
- Plan/Riser/Calculation/Schedule IDs diverge.

## Production truth-gate boundary

The customer-facing mechanical generation path is workflow-bound by an approved drawing manifest and PMM v3. Before the legacy CAD composer may release an artifact, production v19 must independently verify the actual engineering pipeline chain `topology -> route -> sizing calculation` and reject missing routes, missing sizing, invalid route geometry, duplicate same-system geometry, and exact hot/cold or sanitary/vent overlays. This gate is independent of Structural/RCP coordination: architecture-only work may remain `PRE_SUBMISSION`, but missing coordination does not bypass PMM/network truth checks.

Support-sheet identifiers are never architectural levels. `DETAIL-*`, `CALC-*`, `SCHEDULE-*`, and `SERVICE*` values are forbidden from the production riser level set. The production documentation context must be rebuilt from actual architectural floor plans and routed engineering content. A vertical mechanical system with zero mapped plan branches is a blocking reconciliation defect rather than a successful empty riser.

The v19 production adapter may reuse the existing legacy composer only after this truth gate passes. After composition, generated v17 documentation-layer entities are rebuilt from the actual engineering pipeline, the exact file is reopened, and final-delivery QA is rerun. A failed post-composition reconciliation removes/blocks the candidate artifact rather than returning it to the web application.

## Compatibility

PMM v3 is an additive schema change. Existing PMM fields are retained. Consumers that do not yet use the identity registry continue to read legacy fields, while upgraded consumers may enforce the new traceability chain. No destructive migration is introduced by this change.

## QA rule

A locally correct calculation or drawing is insufficient if its identity cannot be reconciled across the complete chain. Release QA must treat traceability mismatch as a blocking engineering defect rather than a documentation warning.
