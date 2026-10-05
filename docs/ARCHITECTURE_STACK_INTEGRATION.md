# Architecture stack integration qualification

Status: ARCHITECTURE_STACK_INTEGRATION_PARTIAL. No merge or deployment authorized.

## Approved tree and integration-only changes

Approved main: `9876f3fb0cb63e17055ff2d30e621fa2c9325939`.
Approved source: `c87df375cfe6c0388176de4599c4c0b689c94f24` (#311).
Initial tree: `15fe60340a61637d513f539a785c930b1d689c10`, exactly equal
between source and candidate. All 65 commits preserved. No cherry-picking.
Side branches #296–#298 remain excluded. SWCIS-2026-0299 governs this integration.

1. Governance: main comparison changes 14 historical CRs, so the previous
   exactly-one-file selector failed. CR0298 also omitted cumulative deployment
   and UI/API change types. A sealed historical-CR manifest plus one current
   integration CR preserves history and validates the complete current closure.
   Missing/unlisted/mutated history, changed base/tree and invalid ancestry fail.
2. Snapshot: `_load_state` preferred stored snapshot even after fresh validation;
   the idempotent POST path reused it too. Server responses now use only the
   snapshot returned by current independent Preflight validation. Persisted
   historical payloads are not mutated by GET and cannot supply fallback authority.
   Valid current models may regenerate a current snapshot; unresolved/old-schema
   models return no snapshot under the existing Preflight states.
3. Review evidence: source-region decisions stay region-scoped. No interval role
   is inferred from room/region answers. Local provenance audit quarantines any
   interval whose full display/answer scope cannot be proven. Original records
   remain immutable. Partial owner statements cannot become unconditional grants.

## Compatibility and artifact handling

DB schema: NO IMPACT. No production mutation. Stored project JSON and reviews:
REVALIDATION REQUIRED. Cached architecture: REGENERATABLE. Old snapshot payloads:
REVALIDATION REQUIRED, never a current fallback. Canonical2.x remains incompatible
with current3.0 qualification. Existing source geometry and valid scoped review
may be reprocessed deterministically; no version relabeling. Missing source is
INPUT_REQUIRED. Prototype `.planha` retains version/hash checks and requires
independent snapshot validation; no production package lifecycle activation.

## Validation and evidence limits

Generalized tests cover sealed cumulative governance, stale backend/API/template
snapshot behavior, unresolved/old-schema fail-closed responses, ordinary CR policy,
and adversarial history changes. Main-target official workflows run naturally;
filters are unchanged. Record exact final SHA and results in the Integration PR.
Original19 and expanded22 negative sets must remain separate. Positive geometry
preservation is distinct from valid reviewed separator authority. Q02 remains
INPUT_REQUIRED. Review uncertainty blocks MERGE_READY; green tests do not erase it.

## Rollback and historical PR disposition

One future integration merge commit is the rollback unit (first-parent revert in
an independently reviewed PR). Old readers must not consume new3.0 artifacts as
qualified; retain them stale and regenerate/revalidate with compatible code.
No data deletion or irreversible migration. No rollback/deployment is executed.
Only after an owner-approved actual integration merge should #295,#299–#311 be
considered superseded, with a link to the integration commit/PR. #296–#298 remain
independent. Do not close, retarget or merge historical PRs during qualification.

## 10-step governance impact

1. verified — Rule Book authority dependencies; no new design rule.
2. verified — PMM/legacy completeness consumers require cumulative regression.
3. verified — questionnaire/source-review scope remains bounded.
4. verified — planner dependencies, no feature change.
5. verified — CAD reconstruction tree preserved.
6. verified — routing/sizing/equipment dependency closure, no migration.
7. verified — detail/riser/preservation regression scope.
8. changed — current-only snapshot response; QA tests and evidence.
9. changed — UI/backend stale-artifact boundary and compatibility documentation.
10. changed — SWCIS5.1.0 cumulative policy, CR0299; no deployment.
