# Build Identity and Semantic Revision Matrix

This file distinguishes the production contract from immutable release history.
Executable identity is automatic and sourced from `cad_engine/build_identity.py`.

| Component | Active version |
|---|---|
| Platform and CAD API | Git commit SHA |
| Production CAD entrypoint | `cad_engine.main:app` |
| Mechanical pipeline | Git commit SHA |
| Split-AC visual gate | `split-ac-visual-legibility-v18.1` |
| Mechanical Rule Book | 5.0 |
| Mechanical site manifest | 12.1 |
| Fixture/equipment detection | `2.4-fixture-equipment-approved-symbols` |
| Ten-step governance | `mechanical-governance-v1.0` |

## Historical and compatibility modules

Files named `main_v15.py`, `main_v17.py`, earlier mechanical pipeline modules,
versioned release documents, golden baselines, and project snapshots remain in
the repository for regression, traceability, and backward compatibility. They
are not production entrypoints. Historical snapshots are immutable and retain
the version that produced them.

New runtime-version files are forbidden. Compatibility debt is audited and must
only decrease; schema/config revisions remain semantic.

## Permanent synchronization policy

`cad_engine/version_manifest.py` is the only writable source for active component
versions. The website health endpoint, CAD version endpoint, application Rule
Book, deploy-time Rule Book generator, release record and this matrix must derive
from or be validated against that manifest. Every pull request and every push to
`main` runs the fail-closed active-version synchronization gate. A missing,
stale, unknown or skipped check blocks merge and deployment.
