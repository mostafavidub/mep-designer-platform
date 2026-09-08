# Single Living System Standard

**Status:** LOCKED
**Canonical runtime:** `cad_engine.main:app`

Production has one living implementation per component. Git commits and approved tags are the only executable history and the only rollback source. Runtime filenames, imports, launchers, routes, or deployment settings must not encode release numbers.

Every produced artifact carries the Git commit SHA, immutable build timestamp, PMM schema revision/hash, rulebook hash, manufacturer database hash, compliance-profile hash, dependency hashes, and one derived build-identity hash. Only schema and configuration contracts retain semantic revisions.

Merge requires SWCIS impact closure, applicable migration evidence, compile/unit/contract/integration success and the runtime-version guard. By explicit owner instruction on 2026-09-08, publication is not dependent on the seven private reference projects. Their comparison suite is optional and must never be reported as passed unless executed. Automated regression and synthetic negative checks remain required. Verify deployed user journeys after rollout; per-artifact engineering checks are unchanged.

Existing version-named internal modules are compatibility debt, not approved production entrypoints. They are inventoried by `tools/runtime_version_guard.py`; adding a new one under production paths fails CI. Each retirement must preserve behavior, include migration tests, and reduce that inventory. Archived compatibility snapshots may exist only under `archived_compatibility/` or test fixtures and must never be imported by production.

`main` is deployable only after every required GitHub check is green and required reviews are complete. Rollback means deploying a prior approved Git commit/tag; copying or reactivating a historical runtime module is forbidden.

For this single-owner repository, recorded owner approval fulfils the human review requirement under SWCIS 3.1.0. An independent reviewer is not required; automated and engineering gates remain mandatory.
