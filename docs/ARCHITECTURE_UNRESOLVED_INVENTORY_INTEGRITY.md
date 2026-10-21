# Architecture unresolved-inventory integrity

An Architecture source-review item is `ACTIVE` only when the current Preflight
plan binds it to the current Canonical Architecture model. Historical ledgers,
canonical identifiers and review membership are audit evidence; none of them
can establish current membership by themselves.

The current-membership check requires one current project/model key, the exact
current source SHA, a current frame or level, a current Canonical evidence
registry record, matching evidence and geometry fingerprints, exact source
handle and segment scope, and at least one covered issue in the current
Preflight issue set. Review fingerprint is the unique unresolved identity.

Current records that fail this check are excluded from the human-review queue,
retained as `STALE_REFERENCE`, and make inventory integrity `FAIL` with a
software-reconciliation requirement. This prevents a malformed current plan
from making a material blocker disappear. Duplicate current fingerprints emit
one active blocker and preserve the duplicate as `SUPERSEDED` audit evidence.

Historical records are never promoted directly. They remain `INVALIDATED`,
`SUPERSEDED`, `AMBIGUOUS_REBIND`, or `STALE_REFERENCE`. Rebinding across a
canonical-ID change is audit-only and requires the same source SHA, frame,
level, and exact source-handle set. Nearest geometry and semantic similarity
are not identity evidence.

Inventory reconciliation does not modify the Canonical model, source geometry,
review registry, validator result, authority, or snapshot state. Material input
remains fail-closed until the underlying current review item is resolved and
the model is independently revalidated.
