# Active Version Matrix

This file distinguishes the production contract from immutable release history.
The executable source of truth is `cad_engine/version_manifest.py`.

| Component | Active version |
|---|---|
| Platform and CAD API | 18.2.0 |
| Production CAD entrypoint | `cad_engine.main_v18:app` |
| Mechanical pipeline | `mechanical-authority-site-pipeline-v18.2` |
| Split-AC visual gate | `split-ac-visual-legibility-v18.1` |
| Mechanical Rule Book | 4.1 |
| Mechanical site manifest | 12.1 |
| Fixture/equipment detection | 2.4 |
| Ten-step governance | `mechanical-governance-v1.0` |

## Historical and compatibility modules

Files named `main_v15.py`, `main_v17.py`, earlier mechanical pipeline modules,
versioned release documents, golden baselines, and project snapshots remain in
the repository for regression, traceability, and backward compatibility. They
are not production entrypoints. Historical snapshots are immutable and retain
the version that produced them.

Any change to an active version must update the central manifest, this matrix,
runtime entrypoints, and version-contract tests in one pull request. Drift is a
release-blocking failure.
