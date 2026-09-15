# System-Wide Change Impact Standard (SWCIS)

**Canonical version:** 4.43.20

**Status:** LOCKED

**Effective:** 2026-09-09

Exact-file visual QA may use the complete copied architectural extent after the
composer has already fitted an outlier-trimmed source envelope only when the
independent robust extent supports at least half of that area. Isolated remote
geometry cannot inflate a visual PASS.

A confirmed browser level profile supplies level identity, while a unique local
print frame containing its sealed title anchor supplies the geometry boundary.
Coarse browser evidence windows must not be used for sheet fitting when this
independent exact-frame reconciliation is available.

Pre-Submission family disclosures are resolved through the composition manifest
from the public sheet code to the internal board identity. Both identities remain
available to exact-file gates; final/submission-ready runs receive no exception.

Private runtime diagnostics for a blocked CAD transaction retain the exact gate
name, status, error codes and bounded aggregate metrics needed to reproduce the
failure. They exclude project geometry, credentials and customer source contents;
customer-visible errors remain separately sanitized.

Exact-file titleblock-overlap failures are attributed to bounded per-sheet and
per-layer counts. This evidence is diagnostic only: any overlap still blocks
release, and entity coordinates or customer source contents are not logged.

After the uniform plan transform, every paper-space route segment is clipped to
the approved plan area before it is drawn. Fully outside segments are omitted
and explicitly disclosed in Pre-Submission; source graph identity, engineering
length and sizing remain unchanged, and any titleblock intersection still fails.

Version 4.43.13 separates the source ownership frame from the authoritative
drawable-content envelope for every architectural plan. Architecture, routes
and equipment use one reversible uniform transform derived from the robust
graphical envelope; text, mechanical overlays and isolated outliers cannot
inflate visual-fit evidence. Exact-file QA independently rejects a tiny,
collapsed or outlier-authorized architectural underlay.

Version 4.43.8 permits a disclosed preliminary room-type load proxy only when a recognized room has a calculation row but lacks closed-enclosure area; absent calculations and explicit zero-area/zero-load evidence remain fail-closed.

Version 4.43.7 plans heating and cooling independently so a non-Split cooling choice cannot suppress an explicitly selected package-radiator system or its calculation-linked terminals and routes.

Version 4.43.6 scopes equipment-linkage disclosure to the exact non-final sheet/family explicitly pending because the canonical pipeline is blocked at `target_design_packages`; final, unrelated and undisclosed boards remain fail-closed.

Version 4.43.5 materializes the canonical water-service mode at the production CAD entry point so authority calculations, enrichments and release QA consume one locked basis.

Version 4.43.4 deterministically maps the existing Persian/English water-source questionnaire choices to `break_tank_pump`, `inline_booster` or `direct_city`, while leaving ambiguous text unresolved and preserving explicit engineering overrides. Version 4.43.3 applies the same same-family disclosure rule to optional roof-rainwater, exhaust and split-roof enrichments and recovers only zero-architecture-loss jobs stopped by the former release-input mismatch. Version 4.43.2 performs a one-condition startup recovery for preserved paid jobs carrying the exact former `semantic_qa` + `missing_family_specific_content` + `target_design_packages_missing` fingerprint; generic semantic and final QA failures remain stopped. Version 4.43.1 reconciles the semantic-sheet gate with the governed Pre-Submission profile. A non-blank family sheet whose missing final geometry is explicitly disclosed on that same sheet may be delivered only when the canonical pipeline is blocked at `target_design_packages`; final outputs, unrelated blockers, title-only sheets and blank sheets remain fail-closed. Version 4.43.0 completes phase-one calculation-to-CAD linkage: room heating/cooling results drive equipment duties with retained calculation identities, and water-service head exposes served-floor, critical-route, friction, residual and service-mode components. Final manufacturer and Submission Ready gates remain unchanged.

This document is the human-readable canonical reference for every repository change. The versioned machine contracts in `standards/swcis/` are authoritative for automation. If prose and automation disagree, merging is blocked until both are reconciled and versioned together.

Version 4.42.2 enlarges the canonical wall-mounted Split AC symbol so horizontal and rotated instances satisfy the unchanged exact-file plotted-legibility threshold on dense sheets. Version 4.42.1 prevents a reserved Pre-Submission system sheet from demanding an invented riser before that system has authoritative calculation/network records; Submission Ready target-design requirements remain unchanged. Version 4.42.0 normalizes contracted drawing manifests before PMM registration, collapses duplicate aggregate identities, resolves overlapping system names by their most-specific family, and requires actionable Plan/Riser/Schedule reconciliation diagnostics. Version 4.41.3 removes hand-maintained component versions from every active product surface and replaces them with stable semantic identities, Git commit identity and content hashes. Schema/governance revisions and external file-format revisions remain explicit compatibility metadata. Version 4.41.0 added locked rule `MEP-UNIFIED-MODEL-001`: individual rooms, network edges, calculations, plans, risers and schedules must be projections of one graph-native engineering model. Connected endpoints with zero plan branches, orphan calculations or divergent Plan/Riser/Schedule identities fail closed.

## Non-negotiable rule

No change may merge or deploy until SWCIS classifies every changed path, computes every transitive downstream dependency, and verifies that the change request contains the required implementation, tests, documentation, version, migration, traceability, semantic/artifact diff, golden-regression, review, and rollback evidence. Missing, skipped, unknown, or `INPUT_REQUIRED` evidence is not PASS.

This applies to the Rule Book, PMM, questionnaire, planner, CAD designer, routing, sizing, equipment, manufacturer selector, detail/riser generation, QA, manifests, UI/API, documentation, versioning, migrations, CI/CD, and deployment.

## Single Living System release philosophy

SWCIS enforces one production implementation and canonical path per component.
Executable release identity is derived from Git commit and content hashes, never
hand-edited component version strings. Parallel versioned runtimes are forbidden;
compatibility snapshots may exist only in explicit archived/test-fixture locations
and may not be imported by production. Schemas and configuration contracts keep
semantic revisions and tested migrations. Every artifact carries the complete
automatic build identity. Rollback redeploys an approved Git commit or tag.

## Canonical artifacts

- `system_dependency_graph.yaml`: module ownership, path classification, and dependency graph.
- `rule_traceability_matrix.yaml`: mandatory Rule ID → PMM field → engine → drawing family/sheet → QA rule → regression test → documentation chain.
- `change_impact_matrix.yaml`: change categories and required evidence.
- `release_contract.yaml`: locked gates, risk, waiver, migration, diff, merge, and deployment policy.
- `golden_regression_manifest.yaml`: project-agnostic regression-suite and synthetic-negative-test requirements.
- `version_manifest.yaml`: canonical version and coordinated bump rules.

All `.yaml` contracts use the JSON-compatible subset of YAML so the validator is deterministic and has no third-party parser dependency.

## PMM and reference-truth governance

The PMM implementation (`app/project_mechanical_model.py`) is an explicit `pmm`/schema-governed component. A PMM schema change therefore propagates through every transitive consumer and cannot be treated as an isolated application-file edit.

Private reference drawings remain outside Git. Reviewed semantic facts and privacy-safe reference-corpus metadata may be recorded under governed Golden/test artifacts only when provenance, cryptographic identity, non-claims, and generation-leakage policy are explicit. A semantic reference truth set is comparison/calibration evidence; it must never become a hidden generation input. Missing exact source hashes remain `INPUT_REQUIRED` rather than being guessed.

For upgraded mechanical traceability the required identity chain is:

`PMM Entity ID -> Calculation ID -> Plan ID = Riser ID = Schedule ID -> QA`

An orphan calculation, an output without a calculation, duplicate calculation identity, or identity divergence is a blocking engineering defect.

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

## Regression governance

Owner-authorized publication policy, 2026-09-08: private reference projects are optional comparison material, not publication prerequisites. Automated regression and synthetic negative tests remain mandatory. Missing optional reference files are not a failed publication gate and must not be represented as a successful comparison. Per-project engineering output checks remain unchanged. Live browser verification follows rollout.

SWCIS defines how regression suites are selected, sealed, compared, and accepted; it does not contain project or customer identifiers. Concrete test-project inventories belong in versioned test-suite configuration outside `standards/swcis/`. Risk-selected representative tests and synthetic negative tests are mandatory. Required categories cover missing authoritative input, dependency or route conflict, external-data no-match, schema compatibility, and locked-semantic removal. Private source drawings never enter Git; only hashes, reproducibility metadata, and semantic baselines may be stored.

The owner-supplied mechanical corpus registered on 2026-09-09 is governed by `docs/MECHANICAL_REFERENCE_CORPUS_STANDARD.md` and `standards/test-suites/mechanical-reference-corpus.json`. Its development/validation/evaluation split prevents future tuning leakage but does not create a retroactive claim of strict blindness because the supplied references were inspected for corpus classification. Reference recurrence is not engineering authority: no observed numeric value may become a global engine default without applicable code/standard/manufacturer authority or explicit authoritative project input. Evaluation-only references may be scored after a change is frozen but may not be used to tune that change.

## Waivers

There is no inline or manual bypass. A waiver is allowed only where `release_contract.yaml` permits it and only as a versioned file under `standards/swcis/waivers/` containing scope, reason, risk, independent reviewer, approval date, expiry (maximum 30 days), and compensating controls. Critical risk cannot be waived. Expired, self-approved, broad, or incomplete waivers fail CI. A waiver does not convert failed engineering evidence into PASS; it documents a narrowly approved temporary exception.

## Enforcement boundaries

Repository CI plus protected-branch settings can enforce repository changes. A repository cannot technically modify or govern every existing or future ChatGPT conversation. The replacement mechanism is repo-as-source-of-truth: root `AGENTS.md` instructs every repository-aware Work to read this versioned standard first, use a versioned change request, run impact analysis, and include the result in handoff. Conversations without repository context must be given the short instruction below.

## Short instruction for every future chat/Work

> Before changing anything, read the current SWCIS version in `docs/SYSTEM_WIDE_CHANGE_IMPACT_STANDARD.md` and `standards/swcis/version_manifest.yaml`; create/update `changes/<id>.yaml`; run `python tools/swcis_validate.py --base <base-ref> --change-request changes/<id>.yaml`; implement the full affected-module closure; do not merge/deploy unless every applicable SWCIS and product gate is PASS. Private reference files are not publication prerequisites and reference values are never hidden generation defaults.

## Calculation reasonableness release gate

Every submission-ready mechanical artifact must pass an independent calculation
reasonableness evaluation after graph-native sizing and plan/riser/schedule
reconciliation and before CAD materialization.  The evaluation must verify:

- explicit canonical units and drawing scale, with no cross-frame route length;
- finite, system-specific physical and project/code limits;
- an independent recomputation or identity-backed reconciliation for critical values;
- conservation of branch/main loads and absence of orphan consumers;
- exact calculation/plan/riser/schedule identities;
- equipment capacity and permitted oversizing against calculated demand;
- bounded sensitivity cases for area, endpoint, height, length and supply-pressure changes;
- formula, input, unit, source, intermediate-result and engine-version provenance; and
- calculation IDs covered by evidence from an independent mechanical-engineer review.

`WARNING` may support preliminary design only. `INPUT_REQUIRED` and `FAIL` block
submission-ready output, and no aggregate score may mask a critical failure.

## All-sheet visual QA release gate

Every approved mechanical board is reopened from the exact issued DXF and rendered
independently in color, monochrome, overview and content-zoom profiles. The gate
reconciles board identities with the approved manifest and checks frame/scale,
architecture and mechanical visibility, plotted text, annotation overlap, visual
density, plan/support-sheet content, baseline regression and exact-file immutability.
It cross-links (and never replaces) routing, symbol/linkage, clearance, calculation,
detail, riser, schedule and documentation gates. A critical defect on any individual
sheet blocks release; a package average cannot hide it. Submission-ready status also
requires evidence that every sheet received independent visual review.

Every geometry-producing mutation must finish before this gate. Network and
annotation materialization must use one reversible uniform architectural transform,
publish per-board scale/offset/round-trip evidence, and reject degenerate or
out-of-board geometry. The exact saved DXF is then reopened and must repeat all
applicable preservation, composition, linkage, completeness and visual checks;
earlier pre-materialization evidence cannot authorize delivery.

For the architecture-only Pre-Submission profile, a missing final target-design
package may never be represented by invented family geometry. The exact affected
board must instead contain a machine-verifiable, visible disclosure naming its
sheet and family. This exception applies only to the canonical
`TARGET_DESIGN_PACKAGES_MISSING` input blocker, never authorizes a Submission Ready
claim, and does not relax blank-sheet, final-family-content or exact-file gates.

Count-only questionnaire fixtures must be placed at deterministic, room-bounded
service points distinct from wet-core or shaft aggregation nodes. A persisted
drawable graph whose complete plan path has zero length is stale execution data:
it must be rebuilt from the saved architecture and approved answers, while the
final materializer continues to reject any remaining degenerate route.

## Architecture reconstruction and preservation release gate

Every issued architectural-plan board must pass the locked eighteen-control
`MEP-ARCH-PRESERVE-001` contract in
`docs/ARCHITECTURE_PRESERVATION_100_STANDARD.md`. It seals document/entity
structure, validates frame/level and coordinate evidence, checks typed geometry
and topology, prohibits unauthorized mutation, cross-links all-sheet visual QA,
and reopens the exact issued file. Only 100/100 with all controls explicitly true
permits delivery.

## Drawing scope release gate

Before calculations, routing or CAD generation, the proposed Mechanical drawing
set must pass all eighteen controls in locked rule `MEP-DRAWING-SCOPE-001` and
`docs/DRAWING_SCOPE_100_STANDARD.md`. The gate inventories and classifies source
drawings, binds levels and Typical groups, derives an evidence-backed
level-by-system matrix, separates output roles, freezes a deterministic manifest,
and requires exact output parity. Any ambiguity, unsupported addition, required
omission, reference-derived generation input, missing control or score below
100 blocks approval and generation.

## Topology and routing release gate

Every Mechanical network must pass all eighteen controls in locked rule
`MEP-ROUTE-001` and `docs/TOPOLOGY_ROUTING_100_STANDARD.md`. The gate reconciles
typed and hosted endpoints, per-system connectivity, real shafts, vertical
continuity, orthogonal routes, penetrations, applicable coordination,
engineering constraints, constructability, equipment envelopes and exact
Plan/Riser/Calculation/Schedule/CAD identity. Only an explicit 100/100 with all
controls `PASS` allows delivery.

## Equipment selection and placement release gate

Every required Mechanical equipment item must pass all eighteen controls in
locked rule `MEP-EQUIP-002` and
`docs/EQUIPMENT_SELECTION_PLACEMENT_100_STANDARD.md`. Selection reconciles
calculated demand with immutable official manufacturer evidence; placement must
be architecture-hosted, accessible, safe, connected and identical across Plan,
Riser, Schedule and the exact reopened DXF. Only 100/100 with all controls
`PASS` permits a Submission Ready claim.

## Final engineering and issue-readiness release gate

Every Mechanical package that claims Submission Ready must pass all eighteen
controls in locked rule `MEP-FINAL-ISSUE-001` and
`docs/FINAL_ENGINEERING_RELEASE_100_STANDARD.md`. The gate requires a governed
submission checklist, complete drawing scope, the current approved architecture,
cross-sheet and Plan/Riser/Calculation identity, system-specific HVAC, water,
sanitary/vent and gas evidence, equipment, coordination, executable details,
documentation, all-sheet visual QA, exact-file technical QA, closed independent
engineering review and an immutable release package. Only 100/100 with every
control `PASS` permits a Submission Ready claim. Software acceptance never
replaces the legally required responsible-engineer review, signature or stamp.

## Architecture space and equipment recognition release gate

Every Mechanical submission must bind its PMM to an architecture-only recognition
report satisfying all eighteen controls in locked rule `MEP-ARCH-RECOG-001` and
`docs/ARCHITECTURE_SPACE_EQUIPMENT_100_STANDARD.md`. The gate verifies the exact
approved source, calibration, frame and level separation, typed geometry, closed
spaces, multilingual labels, use classification, shafts, multi-signal fixture and
equipment evidence, status/confidence, host/port identity, deduplication, semantic
consistency and visual overlays. Mechanical reference drawings are forbidden as
recognition inputs. Only 100/100 with every control `PASS` permits Submission Ready.

## Documentation-content release gate

Every Mechanical submission must pass all eighteen controls in locked rule
`MEP-DOC-CONTENT-001` and `docs/DOCUMENTATION_CONTENT_100_STANDARD.md`.
Project-specific executable details, model-derived schedules, standards-backed
notes and used-symbol-only legends must remain readable, coordinated and identical
across plans, risers, calculations, sheets and the exact reopened output. Only
100/100 with every control `PASS` permits Submission Ready.

## Questionnaire and immutable design-basis release gate

Every Mechanical run must satisfy all eighteen controls in locked rule
`MEP-BASIS-002` and `docs/QUESTIONNAIRE_DESIGN_BASIS_100_STANDARD.md`.
Architecture facts, user answers and calculated values remain explicitly
attributed; cross-project reuse requires owner authorization; numeric values carry
units and bounds; system scope, dependencies and contradictions are checked. The
approved summary is bound to architecture and rules revisions by a content hash.
Only an immutable 100/100 basis permits a Submission Ready claim.

## Administration and branch protection

CODEOWNERS provides the repository-level owner mapping. At the sole owner's explicit request on 2026-09-08, this single-owner repository accepts the owner's recorded release approval instead of an independent pull-request approval. This fulfils owner review in the workflow above; an additional person is not mandatory. Keep pull requests and mandatory `swcis-governance` checks, no force pushes, no branch deletion and no administrator bypass. This does not waive engineering evidence, failing tests, golden/E2E checks or waiver restrictions. CI configuration alone cannot enable branch protection.
