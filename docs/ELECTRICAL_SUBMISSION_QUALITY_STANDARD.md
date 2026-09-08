# Electrical Submission Quality Standard

This standard defines presentation and cross-sheet completeness requirements for the active Electrical living runtime. It does not create project engineering facts.

## Structured title block

Every generated Electrical sheet must carry a machine-detectable submission band containing at least:

- discipline = Electrical,
- project identity,
- sheet identifier,
- drawing/evidence status,
- composed scale field,
- optional administrative fields when explicitly supplied.

Missing owner, address, designer, case number or similar administrative facts are rendered as `INPUT REQUIRED`; the renderer must not invent them.

## Cross-sheet traceability

Generated design objects must remain traceable across representations:

`load/device -> circuit -> panel -> route/riser -> schedule -> detail reference`

The release gate fails when:

- a circuit references a missing panel,
- a panel references a missing circuit,
- a route references an unknown circuit,
- a panel schedule drifts from circuit topology,
- a detail link references a missing sheet or detail.

This is a structural contract and therefore can be enforced even when numeric project data remain preliminary.

## Construction detail interaction

Submission quality does not replace the Construction Detail Gate. Both must pass independently. A visually complete title block cannot compensate for sparse detail geometry, missing project evidence, or broken engineering topology.

## Release policy

`SUBMISSION_TITLEBLOCK_AUTHORITY` and `CROSS_SHEET_TRACEABILITY_AUTHORITY` are mandatory authority gates. A score threshold never overrides either hard blocker.
