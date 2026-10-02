# `.planha` package prototype

The non-production prototype is one deterministic ZIP-compatible file containing
`manifest.json`, `architecture.json`, `snapshot.json`, `validation.json`, and
`review.json`. Entry order, JSON serialization, permissions, and timestamps are
fixed, enabling byte-identical round trips.

The raw source is not embedded in v1. The manifest stores its SHA-256 reference.
This is the lowest-complexity safe default for privacy, customer-data governance,
storage cost, and future object-storage deduplication. Offline source embedding
requires a later explicit encrypted/source-retention policy.

Opening a package verifies the exact file set, schema versions, every payload
hash, source identity, and snapshot identity. Corruption and schema substitution
fail closed. No upload route, database change, object-storage change, public API,
or user-visible input switch is included.
