# Step 10 — Exact DXF Reopen / Audit / Transactional Release Integrity

Step 10 makes the exact generated DXF an immutable release candidate. A successful upstream design is not releasable until the exact bytes at the release path can be reopened, audited cleanly, proven unchanged by the gate, and reopened again.

## Release invariants

1. The release path must exist, be a regular non-empty file, and be hashable before validation.
2. The exact candidate path is reopened with `ezdxf.readfile`; a parse/reopen exception is a hard release failure.
3. Modelspace must be accessible and contain at least one entity. An empty generated modelspace is not a valid mechanical artifact.
4. `doc.audit()` runs read-only as a validator. Any reported audit error is release-blocking.
5. The Step 10 gate never repairs, fixes, saves, or rewrites the DXF to make audit errors disappear.
6. SHA-256 is calculated before and after audit. The hashes must be identical, proving the validator itself did not mutate the release candidate.
7. The exact same path is reopened a second time after audit/hash validation. Failure of the second reopen is release-blocking.
8. Step 10 runs after the existing generated-mechanical-integrity gate and Step 9 exact required-scope proof; it is the final artifact-health barrier before the adapter stamps a successful release state.
9. Release is transactional. If lower-layer generation fails, generated integrity fails, required-scope artifact proof fails, Step 10 fails, or an unexpected exception occurs, the previous known artifact is restored. If there was no previous artifact, the failed candidate is removed.
10. A successful gate exposes `exact_dxf_health_qa` including file size, SHA-256, entity count, audit-error count, first/second reopen states, and read-only hash preservation.

## Status policy

- `PASS`: non-empty exact file, first reopen succeeds, modelspace is non-empty, audit reports zero errors, file hash is unchanged, and second reopen succeeds.
- `FAIL`: any one of those conditions fails.

This gate is deliberately stricter than a single successful save. It validates the bytes that would actually be delivered and refuses to auto-repair evidence at release time.
