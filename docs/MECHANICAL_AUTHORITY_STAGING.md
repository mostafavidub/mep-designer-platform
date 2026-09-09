# Mechanical Authority Staging

This branch is intended for isolated validation of the PMM v3 / v19 mechanical runtime authority change before any production release.

Runtime acceptance criteria:

- PMM schema is `project-mechanical-model/v3`.
- Traceability policy is `NO_ORPHAN_ENGINEERING_OUTPUT`.
- Calculation identities and the network graph are present before CAD materialization.
- Graph-derived riser and calculation-output reconciliation passes with zero mismatch.
- The v19 pipeline is the engineering authority.
- Legacy v17 may run only as `CAD_MATERIALIZER_ONLY` after authority checks pass.
- Missing authority or coordination evidence fails closed; no architecture-only engineering bypass is permitted.
- Staging uses isolated ephemeral data and must never reuse the production database or persistent volume.
- Production merge/deployment requires explicit owner authorization after staging verification.
