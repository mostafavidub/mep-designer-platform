# Architecture → PMM fail-closed gate

Planha may start downstream Mechanical engineering only when the independently
validated canonical architecture is `AUTO_VALIDATED` and both canonical release
flags are true. A missing persisted Preflight record is not evidence of a valid
architecture.

The RAW DXF path now materializes the existing Canonical Architecture 3.1 model
and Review Engine result after reconstruction. Existing projects are upgraded
without a database migration by adapting their persisted
`canonical-architectural-model/1.0` evidence on first access. This operation is
deterministic and cannot promote geometry, topology, semantics, or release
authority.

The same gate is enforced at three boundaries:

1. customer quote/payment, before any debit, paid marker, revision, or DesignJob;
2. DesignJob execution, before restoring input or calling the CAD service; and
3. authoritative network construction, before typed-level or route inference.

`ARCHITECTURE_INPUT_REQUIRED` means that bounded human interpretation cannot
legally create the missing source geometry. `QUICK_REVIEW_REQUIRED` exposes only
the bounded review items produced by the Review Engine. Neither ordinary design
questions nor Mechanical topology may invent a floor, room, wall, aperture,
portal, void, or access edge.

Deterministic input deficiencies are recorded as `input_required` on the project,
revision, and job. They are not retried until evidence or review state changes.
Already-paid projects keep their single checkout and single DesignJob; controlled
replay reuses that record and never charges again.
