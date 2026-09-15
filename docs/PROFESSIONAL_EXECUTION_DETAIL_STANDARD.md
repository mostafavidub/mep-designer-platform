# Professional Mechanical Execution Detail Standard

## Outcome

Every required mechanical detail is a project-specific, executable projection of the same Plan–Riser–Calculation–Schedule model. A title, note, block name, or copied typical detail is not evidence of completion.

## Required workflow

1. Build a requirement matrix from active systems, actual interfaces, levels, hosts, equipment, shafts and exceptional conditions.
2. Select only governed detail families; unsupported conditions stop for an explicit engineering input.
3. Bind every detail to a plan, PMM object, calculation, network/equipment owner and schedule row.
4. Resolve sizes, slopes, clearances, materials and component choices from project calculations and approved manufacturer evidence; never invent missing values.
5. Generate real CAD primitives, dimensions, leaders and section/detail callouts—not text-only placeholders.
6. Specify fittings and assembly order, supports and anchors, penetrations/sleeves/firestopping, insulation/corrosion protection and access/service clearances.
7. Reconcile flow direction and slope, vertical continuity, architectural/structural/RCP clashes and installation sequence.
8. Create bidirectional callouts between the owning plan entity and detail identity.
9. Render every detail at plotted scale and independently check clipping, overlap and minimum text height.
10. Reopen the immutable final DXF and verify executable entity identities and numeric parity before release.

## Acceptance

All eighteen controls in `cad_engine.professional_execution_details` must score 100/100. Missing project facts are `INPUT_REQUIRED`; contradictions are `FAIL`. Neither state is Submission Ready. Reference mechanical drawings remain evaluation-only and cannot supply hidden design values.

The contract covers scope, system coverage, unique and owner identity, plan callouts, calculation and schedule parity, executable geometry, dimensions, assembly, supports, penetrations, protection, access, slope/flow, coordination, print QA and exact-DXF parity.
