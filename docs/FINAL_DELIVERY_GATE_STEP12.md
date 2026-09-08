# Step 12 — Non-Destructive Final Delivery Acceptance

Step 12 closes the last post-generation fail-open path in the mechanical release chain.

The legacy v17 final-isolation layer can remove modelspace entities or empty paper-space layouts before validating the resulting file. That behaviour remains available for legacy compatibility, but a v19 release candidate is no longer allowed to pass **because** that cleanup happened.

## Release contract

A candidate may pass Step 12 only when all of the following are true:

- the legacy final-delivery isolation stage itself reports `PASS`;
- `entities_removed == 0`;
- `entities_before == entities_after` and mutation accounting is consistent;
- `empty_layouts_removed` is empty;
- post-v17 architecture preservation, exact final-delivery QA, and exact-reopen montage QA are all `PASS`;
- the exact DXF independently passes `validate_final_delivery` again;
- the SHA-256 of the exact DXF is unchanged across the Step 12 check.

Missing mutation evidence returns `INPUT_REQUIRED`. Any recorded entity/layout deletion or final-delivery contradiction returns `FAIL`.

## Why this is fail-closed

Step 12 does not repair, save, sanitize, trim, or delete anything. If an upstream composer emits geometry outside approved boards, or relies on a cleanup pass to remove it, the v19 adapter rolls the candidate back to the previous known artifact (or removes a newly created candidate). The correct fix must therefore happen upstream in generation/composition rather than by hiding evidence at release time.

## Relation to Steps 10 and 11

Step 10 proves the exact DXF is readable, auditable, hash-stable, and transactionally safe. Step 11 proves the strict seven-project Golden result is based on sealed, build-bound evidence rather than a status token. Step 12 is the final artifact-delivery acceptance: neither of those earlier gates may be followed by a post-hoc cleanup that changes what is being released.

This step does **not** claim that the real seven-project production Golden run, raw projects 102/103 regeneration, or production upload-to-download E2E has already occurred. Those remain mandatory release evidence before merge/deploy.
