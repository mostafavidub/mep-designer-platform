# Mechanical Drawing Set Planning Standard

## Mandatory pre-generation stage

Mechanical CAD generation must not start before Drawing Set Planning and explicit user approval.

Flow:

Architecture Upload -> Architecture Analysis -> Mechanical Questions -> Effective-Level Analysis -> Typical-Floor Consolidation -> Deliverable Sheet Composition -> Drawing Set Proposal -> User Approval -> CAD Generation

## Customer-facing count semantics

The number displayed to the customer MUST equal the number of CAD sheets expected to be delivered.

Internal system scopes MUST NOT be summed as if every system were a separate deliverable sheet. When multiple systems are intentionally composed on one CAD sheet, they count as one deliverable sheet.

The proposal therefore keeps two concepts separate:

- System Scope Count: engineering traceability only; not customer-facing.
- Deliverable Sheet Count: the exact count shown to the customer and used for approval.

## Effective Levels

A system is active only on levels where that system has a real design requirement. The planner must determine Effective Levels per system from architecture and resolved project inputs.

Examples:

- Cooling: conditioned levels only.
- Heating: heated levels only.
- Water Supply: levels with plumbing consumers.
- Sanitary/Vent: levels with sanitary fixtures/drainage scope.
- Ventilation: levels requiring mechanical ventilation/exhaust.
- Gas: levels with gas consumers when gas is enabled.
- Roof Drainage: required only where roof drainage scope exists.
- Riser: required when vertical systems span multiple levels.

No level may be counted merely because it exists architecturally if the relevant system has no scope on that level.

## Typical Floor Consolidation

Before counting deliverable sheets, Effective Levels must be grouped by unique mechanical pattern.

Floors may be consolidated into one Typical Floor sheet only when the architecture/mechanical analysis identifies them as the same relevant pattern. The grouping must consider, as available:

- architectural geometry and room arrangement;
- wet-core positions;
- shafts and vertical references;
- fixture/consumer distribution;
- equipment/load positions;
- system-specific scope.

A Typical Floor group produces one deliverable sheet for that sheet family. Levels not belonging to a verified typical group remain separate sheets. The planner must never silently drop uncovered levels.

## Deliverable sheet composition

The customer-facing proposal must mirror the current CAD Designer composition rules.

### M-P — Plumbing + Gas

One sheet per unique effective level pattern containing:

- cold water;
- hot water;
- gas, when enabled.

### M-S — Sanitary + Vent + Rainwater

One sheet per unique effective sanitary level pattern containing:

- sanitary drainage;
- vent;
- rainwater information when applicable.

Rainwater does not create a second customer-counted sheet unless the CAD Designer explicitly requires a dedicated roof sheet.

### M-H — Heating + Cooling + Condensate

One sheet per unique effective HVAC level pattern containing:

- heating;
- cooling;
- condensate drainage where applicable.

### M-V — Ventilation + Exhaust

One sheet per unique effective ventilation level pattern containing ventilation/exhaust scope.

### M-RISER-CALC — Riser + Calculations + Legend

When vertical systems exist, the current deliverable uses one combined riser/calculation/legend sheet unless a future CAD rule explicitly splits it.

## Calculation principle

For each deliverable family:

1. determine active systems;
2. determine that family's union of Effective Levels;
3. consolidate verified Typical Floor groups;
4. count one sheet per remaining unique mechanical level pattern;
5. add required combined riser/calculation sheet;
6. add only those special sheets that the CAD Designer will actually generate.

Customer Deliverable Sheet Count = number of composed family sheets + required combined special sheets.

This value MUST be the same semantic quantity as the final delivered CAD layout count, excluding non-deliverable Model/paper helper layouts.

## Proposal contract

The proposal must expose:

- deliverable sheet families;
- sheet code/family;
- level or Typical Floor pattern represented by each sheet;
- exact deliverable sheet count;
- internal system scope separately for traceability;
- approval state.

The UI must display the Deliverable Sheet Count, never the raw sum of system scopes.

## Approval Gate

The customer must review and approve the exact deliverable drawing list before mechanical CAD generation can start.

If the proposed deliverable list changes, approval must be obtained again before generation.
