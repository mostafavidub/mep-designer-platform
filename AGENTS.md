# Repository delivery rules

## Mandatory System-Wide Change Impact Standard

Before any repository change, read `docs/SYSTEM_WIDE_CHANGE_IMPACT_STANDARD.md` and `standards/swcis/version_manifest.yaml`, create or update exactly one versioned `changes/<change-id>.yaml`, and run:

`python tools/swcis_validate.py --base <base-ref> --change-request changes/<change-id>.yaml`

Implement and verify the complete affected-module closure reported by the validator. No Work/chat may claim completion, merge, or deploy while any SWCIS gate is not `PASS`. The repository files are the canonical source of truth; chat summaries are not policy. Every handoff must name the SWCIS version, change request, affected modules, evidence, and gate result.

All mechanical design work follows `standards/mechanical-design-governance-v1.json`.

- Never weaken, delete, skip, or bypass a `LOCKED` capability or release gate.
- A capability change requires its positive test, destructive/negative test, golden regression, impact-matrix update, and changelog entry.
- Required gates are fail-closed: `FAIL`, `SKIPPED`, missing, or unknown all block release.
- Project inputs, answers, allowed/forbidden references, manifest, and design basis belong in a versioned project contract.
- Approved output semantics must not fall below the golden baseline without an explicitly approved contract migration.
- Every task handoff must include a section named `10-step governance impact` listing items 1 through 10 as `changed`, `added`, `verified`, or `not affected`.
- Never commit private source drawings or generated customer DXFs. Store hashes, semantic baselines, and reproducibility metadata instead.
