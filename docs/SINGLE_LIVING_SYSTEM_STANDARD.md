# Single Living System Standard

**Status:** LOCKED
**Canonical runtime:** `cad_engine.main:app`

Production has one living implementation per component. Git commits and approved tags are the only executable history and the only rollback source. Runtime filenames, imports, launchers, routes, or deployment settings must not encode release numbers.

Every produced artifact carries the Git commit SHA, immutable build timestamp, PMM schema revision/hash, rulebook hash, manufacturer database hash, compliance-profile hash, dependency hashes, and one derived build-identity hash. Only schema and configuration contracts retain semantic revisions.

No merge is permitted without SWCIS impact closure, migration evidence where applicable, compile/unit/contract/integration/golden/E2E success, and the runtime-version guard. Projects 1, 3, 4, 6, 7, 8, and 10 plus every required synthetic negative category are release-blocking.

Existing version-named internal modules are compatibility debt, not approved production entrypoints. They are inventoried by `tools/runtime_version_guard.py`; adding a new one under production paths fails CI. Each retirement must preserve behavior, include migration tests, and reduce that inventory. Archived compatibility snapshots may exist only under `archived_compatibility/` or test fixtures and must never be imported by production.

`main` is deployable only after every required GitHub check is green and required reviews are complete. Rollback means deploying a prior approved Git commit/tag; copying or reactivating a historical runtime module is forbidden.
