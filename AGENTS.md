# Repository delivery rules

All mechanical design work follows `standards/mechanical-design-governance-v1.json`.

- Never weaken, delete, skip, or bypass a `LOCKED` capability or release gate.
- A capability change requires its positive test, destructive/negative test, golden regression, impact-matrix update, and changelog entry.
- Required gates are fail-closed: `FAIL`, `SKIPPED`, missing, or unknown all block release.
- Project inputs, answers, allowed/forbidden references, manifest, and design basis belong in a versioned project contract.
- Approved output semantics must not fall below the golden baseline without an explicitly approved contract migration.
- Every task handoff must include a section named `10-step governance impact` listing items 1 through 10 as `changed`, `added`, `verified`, or `not affected`.
- Never commit private source drawings or generated customer DXFs. Store hashes, semantic baselines, and reproducibility metadata instead.

