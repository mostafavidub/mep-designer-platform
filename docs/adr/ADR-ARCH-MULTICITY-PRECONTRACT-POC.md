# ADR (Proposed): Architecture MVP minimal brief and multi-city rule resolution

**Status:** PROPOSED — OFFLINE POC ONLY. Not approved for core implementation, Rulebook qualification, migration, merge, or deploy.

**Baseline:** main `fc76bc08299130297e2ed2de54e9166676c57164`; SWCIS 5.4.0; change request `SWCIS-2026-0360`.
**Product authority:** [Planha Architecture PRD v0.8](https://docs.google.com/document/d/1S1Rv6s-ugQmMkiAfbOAZNEaicgDnRKK7GpyeqyxRMK8/edit).

## Decision problem

The approved public brief is limited to city, rectangular north/south width, east/west length, customary northern/southern site type, and one to four requested units. Bedrooms and a physical program are automatically derived. No floor count, apartment schedule, parcel-specific setbacks, survey, parking, elevator, or roof input is solicited in this MVP.

Existing draft contracts require substantially more inputs:

- [PR #316](https://github.com/mostafavidub/mep-designer-platform/pull/316) `generation-input.schema.json` requires `location.parcel_id`, `plot.survey_hash`, `plot.north_deg`, `authority.envelope`, `program.unit_types`, and `typical_floors.floor_ids`.
- [PR #331](https://github.com/mostafavidub/mep-designer-platform/pull/331) `owner-program-draft-v2.schema.json` requires `floor_count` and `unit_types` and per-field provenance.
- [PR #333](https://github.com/mostafavidub/mep-designer-platform/pull/333) `LocalRuleProfile` and `ProjectCodeBasis` provide an offline fail-closed municipal and parcel evidence boundary. Neither is a trusted source/permit authority.
- [PR #338](https://github.com/mostafavidub/mep-designer-platform/pull/338) residential symbol clearance remains offline and is not a qualified regulatory validator.

The product also requires one nationwide Rulebook architecture with national rules and scoped province/city/municipality/parcel profiles. Four or five cities may be qualified first; expanding later must not require changing the layout solver.

## Proposed architectural boundaries (not implemented by this PR)

1. **PublicUserBrief:** exact public fields, type and range validation, site interpretation notes, stable content hash. It is not a complete legal project basis.
2. **Location/Rulebook Registry:** national core + jurisdiction-scoped rule packs; each pack has official issuer, source, edition, effective range, geographic zone, exceptions, applicability, review authority, source hash, and immutable identity.
3. **RuleSetSnapshot:** independently resolves qualified applicable sources, detects conflicting precedence or overlapping jurisdiction, records unknown requirements and source fingerprints; never substitutes Tehran or a default rule for missing city data.
4. **ResolvedProjectBasis:** combines geometry facts and RuleSetSnapshot with actual parcel/permit evidence when available. Unknown buildable envelope, daylight rights, floor-dependent elevator/egress rules, or legal setbacks remain unknown rather than guessed.
5. **AutoProgram:** computes per-unit rooms and bedrooms from *validated* usable geometry and qualified constraints; cannot infer a guaranteed bedroom count from city and plot area alone. Geometric infeasibility, search-budget exhaustion, and missing authority are distinct outcomes.
6. **Generated-origin model:** generated walls, openings, rooms, stairs and dimensions have their own origin/provenance. They cannot masquerade as existing source-backed DXF elements.
7. **Independent validator:** hard geometry/access/egress and rule status checks must be independent of generator and LLM score; unknown hard applicability does not yield PASS.

The current offline PoC in `tests/test_architecture_multicity_poc.py` exercises only a **synthetic test-local subset** of the above. Every Rule ID starts with `TEST:` and every profile bears `NON_REGULATORY_TEST_DATA`; no statutory result can be qualified by the fixture.

## Actual test-only scope

- No production, API, architecture, geometry, or Rulebook module edits.
- No real Iranian legal requirements, numerical setbacks, or regulatory minima.
- No user-project mutation, persistence, generated DXF, live model invocation, paid provider, or web deployment.
- The PoC intentionally does **not** derive bedrooms or a legally buildable area. It reports their unresolved status.
- The PoC does **not** implement official-source verification, signed reviewer authority, or municipality-level overlays.

## Risks and compatibility

- **City leakage:** same resolver interface must not apply city A rules to city B. The offline synthetic test verifies isolation.
- **Legal overclaim:** input validation or geometric correctness cannot claim construction/permit compliance. Synthetic profile claims of regulatory qualification are rejected.
- **Scope and time:** changed profile fingerprint, version, project effective date, or rule applicability invalidates cached outcomes. Unknown parcel requirements fail closed.
- **Existing consumers:** no changes to DXF recognition or Mechanical are made. Production migration requires a separately reviewed contract and explicit approval.
- **North/south semantics:** customary north/south site label is not independent evidence of geographic rotation, legal frontage or confirmed road-facing edge; the fixture deliberately leaves those unestablished.
- **Cost:** the existing product LLM cap is $2 per project; this PoC makes zero LLM calls and does not claim budget accounting exists.
- **Rulebook rollout:** targeting all provinces and cities is a schema/architecture requirement. The first four or five city packs require independently qualified primary sources, not synthetic fixtures.

## Review gates before implementation

1. Approve or revise this ADR **for a later high-impact core schema/algorithm change**; do not infer approval from offline test completion.
2. Decide the product's legally acceptable claim for projects without parcel-specific planning instructions (conceptual-only vs code-qualified).
3. Produce a versioned migration/compatibility map for PR #316/#331/#333, downstream recognition/MEP consumers and all retained project data.
4. Qualify statutory sources for initial cities and independent architect-sealed Golden cases; until then no city is permit-grade active.
5. Prove source authority, stale invalidation, location scoping, negative rule tests and separate CAD exact-file QA in later branches.

## Ten-step governance impact

1. Rulebook authority — **verified/not affected**: no real Rulebook data or operative rule changes.
2. PMM and persistence — **not affected**: no schema, writes or migration.
3. Questionnaire — **not affected**: test-local brief only.
4. Planner — **not affected**: no planner contract imported.
5. CAD/geometry — **not affected**: no generator, source adapter or model changes.
6. Routing/sizing/equipment — **not affected**: no downstream consumer call.
7. Detail/riser/output — **not affected**: no DXF materialization or generated artifact.
8. QA — **added**: test-local synthetic positive and destructive cases.
9. UI/API — **not affected**: no served route, authentication or UI change.
10. Governance/deployment — **added/verified**: one scoped change request, draft PR only, no merge/deploy.

## Verification record

Local isolated Python `unittest`: **15 tests PASS**; `python -m py_compile`: **PASS**. The file was executed outside a project checkout; its tests are self-contained and run solely against synthetic fixtures. This is **not** evidence of repository-wide regression, SWCIS, or official CI PASS. Official tests and SWCIS must be separately checked for the exact PR SHA. No Golden tests were run.

**Rollback:** revert or close the test-only Draft PR. No runtime rollback, data restoration or change to deployment is necessary because no merge or activation is authorized.

## Product decision approved on 2026-11-06: two distinct output tiers

The owner approved **both** (A) *Conceptual Floor Plan* based on the minimal public brief and (B) *Controlled-Compliance Floor Plan* only when each materially necessary rule and parcel/source dependency is supported by qualified evidence. This approval is a **product requirement**; it is not approval to change the core engineering algorithm, merge PRs, migrate database schemas, or deploy a release.

**A. CONCEPTUAL_PLAN:** minimal user fields, generated bedroom/program geometry where verifiable, independent hard geometry validation, and a permanent visible disclaimer on preview and DXF: no parcel-specific permit, setback, daylight rights, or full building compliance claim. Missing parcel authority evidence does not itself forbid a conceptual layout, but missing essential geometry data does.

**B. CONTROLLED_COMPLIANCE:** source-qualified national/local rules scoped by project city/jurisdiction, permit/design effective date, and verified parcel evidence where needed. Each applicable rule must return rule ID, source edition and clause, scope, bound inputs, checker version, PASS/FAIL/NOT_APPLICABLE/INPUT_REQUIRED/CONFLICT and evidence hash. An unavailable mandatory rule or source keeps the check unresolved, rather than becoming PASS; it does not retroactively invalidate a separately valid conceptual outcome.

**Independent dimensions:** `geometry_status`, `compliance_status`, and `design_quality_score` are not interchangeable. A high quality score cannot override a hard validation failure. `CHECKED_IN_SCOPE` requires that all mandatory in-scope rules actually passed, with no unresolved applicability; it is never equivalent to a permit or professional stamp.

**Persistence:** retain the tier label, checked scope, raw findings, rulebook snapshot/version, geometry provenance, artifact version/identity, warnings and authorized re-download. A later Rulebook update cannot silently promote an old conceptual artifact.

**Test-only extension:** `classify_two_tier_policy` is intentionally embedded in `tests/test_architecture_multicity_poc.py` and accepts only synthetic fixtures. The controlled branch **cannot** return a verified compliance result, even for forged `QUALIFIED_IN_SCOPE` inputs. This is a negative safety proof for policy status mapping, not an implementation of the actual Rulebook resolver or independent geometry checker. Eight additional test cases cover no-parcel concept, required parcel evidence, synthetic/forged authority, invalid geometry, conflict/coverage, and invalid public inputs.

**Remaining high-impact checkpoint:** approve the future production-grade `GeneratedPlanInput` / `RuleSetSnapshot` schema, provenance/migration strategy, and source qualification before editing runtime. The release scope for four or five initial cities remains conditional on legal source review and expert QA.
