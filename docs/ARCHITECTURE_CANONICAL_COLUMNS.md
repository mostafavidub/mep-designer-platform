# Canonical structural columns

Planha Canonical Architecture 3.2 adds `structural_obstacles` as an additive,
source-backed collection. A `COLUMN` row preserves the native closed footprint,
world occurrence, block/INSERT lineage, transform, source handle and stable
geometry identity. Recognition remains deterministic evidence from the existing
pre-topology classifier; this collection does not run a second detector.

The collection is intentionally diagnostic. Its authority flags for material
geometry, Wall, Portal, Access, routing, envelope and release are always false.
The legacy `columns` projection remains empty until its downstream routing
contract is separately qualified. This prevents newly persisted identity from
silently changing Mechanical behavior.

The recognition preview draws the exact source footprint in a distinct column
style with `DIAGNOSTIC_ONLY` authority metadata. It does not imply structural
design, capacity, reinforcement, height or approval.

## Identity and provenance

Stable identity binds the source SHA, world occurrence, handle, block path,
INSERT ancestry, transform and an orientation/start-point-normalized footprint.
Handles alone are insufficient because transformed block occurrences may reuse
one definition handle. Reversing polygon orientation or source enumeration does
not change the semantic identity.

## Validation

The independent validator requires a valid nonzero polygon, source occurrence,
geometry fingerprint, valid frame reference when supplied, `COLUMN` type and
`OBSTACLE_EVIDENCE_ONLY` classification. Any Wall, envelope, routing or release
grant is a hard error.

## Compatibility

This is a reader-before-writer migration. Existing Wall admission exclusions,
Physical Space reconstruction, legacy Mechanical obstacle inputs and release
gates are unchanged. Consumers may read the collection only after their own
separately governed contract qualification.
