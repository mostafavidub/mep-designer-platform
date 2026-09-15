# Single Living System Standard

**Status:** LOCKED
**Canonical runtime:** `cad_engine.main:app`

Production has one living implementation per component. Git commits and approved tags are the only executable history and the only rollback source. Runtime filenames, imports, launchers, externally visible routes, workflow display names, or deployment settings must not encode release numbers.

For Mechanical, the only production-facing identities are `Mechanical Authority`, `Mechanical Network Authority`, `Mechanical Coordination`, `Mechanical Governance`, and runtime identity `mechanical`. A suffix such as `v15`, `v17`, `v19`, or `v1` must never identify an active engine, workflow, route, deployment entrypoint, or production-facing module. Schema revisions, PMM revisions, standards revisions, and SWCIS revisions are data/governance contract revisions and are not parallel runtime engines.

Every produced artifact carries the Git commit SHA, immutable build timestamp, PMM schema revision/hash, rulebook hash, manufacturer database hash, compliance-profile hash, dependency hashes, and one derived build-identity hash. Only schema and configuration contracts retain semantic revisions.

Merge requires SWCIS impact closure, applicable migration evidence, compile/unit/contract/integration success and the runtime-version guard. By explicit owner instruction on 2026-09-08, publication is not dependent on the seven private reference projects. Their comparison suite is optional and must never be reported as passed unless executed. Automated regression and synthetic negative checks remain required. Verify deployed user journeys after rollout; per-artifact engineering checks are unchanged.

Existing version-named internal modules are compatibility debt, not approved production entrypoints. They may remain temporarily only while behavior-preserving retirement tests depend on them; they must never be configured as deployment entrypoints and no new production-facing dependency may be added to them. The canonical `cad_engine.main` import surface must be unversioned. Their inventory must monotonically decrease. Archived compatibility snapshots may exist only under `archived_compatibility/` or test fixtures and must never be imported by production.

Mechanical CI workflow filenames and visible workflow names are canonical and unversioned. Historical test filenames may retain old revision identifiers while they verify migration behavior; those identifiers are test-history labels, not active engine identities.

`main` is deployable only after every required GitHub check is green and required reviews are complete. Rollback means deploying a prior approved Git commit/tag; copying or reactivating a historical runtime module is forbidden.

For this single-owner repository, recorded owner approval fulfils the human review requirement under SWCIS. An independent reviewer is not required; automated and engineering gates remain mandatory.

Mechanical dimensions are produced only by the canonical unversioned
`cad_engine.mechanical_dimensioning` capability.  A submission-ready artifact
must use calibrated architectural units, a uniform board transform, stable
source geometry and owner-linked dimension identities.  The final exact DXF is
reopened after the last mutation; missing, guessed, zero, duplicated, orphaned,
mis-scaled, unreadable or out-of-board required dimensions fail closed.

Independent floor and roof ownership is produced only by the canonical
`cad_engine.independent_level_model_gate` capability. Every source entity has
one level-model owner; typical instances are explicit and roof support views
attach only to a confirmed architectural roof base. Submission Ready requires
all eighteen `MEP-LEVEL-MODEL-001` controls to pass at 100/100.
