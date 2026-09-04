# System-Wide Change Impact Standard (SWCIS)

**Canonical version:** 1.0.0

**Status:** LOCKED

**Effective:** 2026-09-04

This document is the human-readable canonical reference for every repository change. The versioned machine contracts in `standards/swcis/` are authoritative for automation. If prose and automation disagree, merging is blocked until both are reconciled and versioned together.

## Non-negotiable rule

No change may merge or deploy until SWCIS classifies every changed path, computes every transitive downstream dependency, and verifies that the change request contains the required implementation, tests, documentation, version, migration, traceability, semantic/artifact diff, golden-regression, review, and rollback evidence. Missing, skipped, unknown, or `INPUT_REQUIRED` evidence is not PASS.

This applies to the Rule Book, PMM, questionnaire, planner, CAD designer, routing, sizing, equipment, manufacturer selector, detail/riser generation, QA, manifests, UI/API, documentation, versioning, migrations, CI/CD, and deployment.

## Canonical artifacts

- `system_dependency_graph.yaml`: module ownership, path classification, and dependency graph.
- `rule_traceability_matrix.yaml`: mandatory Rule ID → PMM field → engine → drawing family/sheet → QA rule → regression test → documentation chain.
- `change_impact_matrix.yaml`: change categories and required evidence.
- `release_contract.yaml`: locked gates, risk, waiver, migration, diff, merge, and deployment policy.
- `golden_regression_manifest.yaml`: projects 1, 3, 4, 6, 7, 8, 10 and synthetic cases.
- `version_manifest.yaml`: canonical version and coordinated bump rules.

All `.yaml` contracts use the JSON-compatible subset of YAML so the validator is deterministic and has no third-party parser dependency.

## Required workflow

1. Create one `changes/<change-id>.yaml` from `.github/CHANGE_REQUEST_TEMPLATE.yaml` before implementation.
2. List the intended change types and initial modules. Run `python tools/swcis_validate.py --base <base-ref> --change-request changes/<change-id>.yaml`.
3. Use the reported affected-module closure as the minimum checklist. Update every consumer or explicitly prove it is unaffected in evidence reviewed by its owner.
4. For every rule change, update the complete traceability chain. A blank link fails validation.
5. Add positive, negative/destructive, focused, contract, and applicable golden tests. Generate outputs blind, seal input/output hashes before reference comparison, then produce strict semantic and artifact diffs.
6. For schema changes, add a versioned migration with forward plan, rollback, validation, consumer inventory, compatibility order, and deprecation window.
7. Apply semantic versioning: major for breaking/destructive changes, minor for backward-compatible capability/rule/schema additions, patch for behavior-preserving fixes or clarification.
8. Compute risk as `likelihood × severity × detectability`, each 1–5. Follow the review requirements in `release_contract.yaml`.
9. Complete the PR checklist and attach or link every evidence item. CI recalculates impact; declarations do not override its result.
10. Merge only with the required `SWCIS Governance / swcis-governance` check passing and required owners approving. Deploy only the resulting protected merged commit after product tests pass.

## Semantic and artifact diff contract

The comparison must inventory files, sheets, drawing families, entities, labels, units, geometry bounds, and QA status. Numeric tolerance must be linked to a Rule ID. Removed locked semantics, omitted dimensions, hash-after-comparison, or baseline updates produced by the candidate itself fail closed. Baseline acceptance and candidate generation must be separately reviewable.

## Golden regression

Projects 1, 3, 4, 6, 7, 8, and 10 are mandatory inventory. Private source drawings never enter Git; store hashes, reproducibility metadata, and semantic baselines. Projects whose authoritative input or sealed baseline is unavailable remain `INPUT_REQUIRED` and block any change requiring their full coverage. Synthetic cases cover missing RCP, route collision, manufacturer no-match, old-schema compatibility, and locked-semantic removal.

## Waivers

There is no inline or manual bypass. A waiver is allowed only where `release_contract.yaml` permits it and only as a versioned file under `standards/swcis/waivers/` containing scope, reason, risk, independent reviewer, approval date, expiry (maximum 30 days), and compensating controls. Critical risk cannot be waived. Expired, self-approved, broad, or incomplete waivers fail CI. A waiver does not convert failed engineering evidence into PASS; it documents a narrowly approved temporary exception.

## Enforcement boundaries

Repository CI plus protected-branch settings can enforce repository changes. A repository cannot technically modify or govern every existing or future ChatGPT conversation. The replacement mechanism is repo-as-source-of-truth: root `AGENTS.md` instructs every repository-aware Work to read this versioned standard first, use a versioned change request, run impact analysis, and include the result in handoff. Conversations without repository context must be given the short instruction below.

## Short instruction for every future chat/Work

> Before changing anything, read `docs/SYSTEM_WIDE_CHANGE_IMPACT_STANDARD.md` and `standards/swcis/version_manifest.yaml`; create/update `changes/<id>.yaml`; run `python tools/swcis_validate.py --base <base-ref> --change-request changes/<id>.yaml`; implement the full affected-module closure; do not merge/deploy unless every SWCIS and product gate is PASS.

## Administration and branch protection

CODEOWNERS provides the repository-level owner mapping currently possible. A GitHub administrator must configure the default branch to require pull requests, required CODEOWNER review, dismissal of stale approvals, no force pushes, no branch deletion, no administrator bypass, and the exact check `SWCIS Governance / swcis-governance`. CI configuration alone cannot enable repository branch-protection settings.
