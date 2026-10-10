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

The preview viewBox is the union of all detected frame bounds. Emitted polygon
count is only a serialization diagnostic; visual qualification additionally
requires the polygon to lie inside that union. This prevents columns assigned
to a later frame from being clipped by the first frame's bounds.

## Identity and provenance

Stable identity binds the source SHA, world occurrence, handle, block path,
INSERT ancestry, transform and an orientation/start-point-normalized footprint.
Handles alone are insufficient because transformed block occurrences may reuse
one definition handle. Reversing polygon orientation or source enumeration does
not change the semantic identity.

Only a column assigned to exactly one non-reference architectural frame enters
the canonical collection. Reference-only, unassigned and multiply assigned
occurrences remain in source-role diagnostics with exclusion counts; they do
not become qualified architectural obstacles. On the frozen source this bounds
118 recognized diagnostic occurrences to 19 canonical columns: 12 on the
Typical frame and 7 on the Roof frame, with 99 reference-only occurrences.

## Validation

The independent validator requires a valid nonzero polygon, source occurrence,
valid qualified-frame reference, `COLUMN` type and `OBSTACLE_EVIDENCE_ONLY`
classification. It independently normalizes and reconciles the canonical
footprint, world coordinates, lineage footprint and geometry fingerprint, and
reconstructs the stable identity when the complete canonical lineage is
present. This detects contract tampering without claiming to reread the DXF.
Any Wall, envelope, routing or release grant is a hard error.

All Canonical Architecture 3.2 column-lineage keys are mandatory. A partial
lineage produces `COLUMN_SOURCE_LINEAGE_KEYS_MISSING` with the exact missing
keys; it cannot bypass identity reconciliation. Nonnumeric, malformed-point or
nonfinite coordinates are never repaired: projection excludes them with an
`invalid_geometry` diagnostic count, while independent validation returns a
structured `STRUCTURAL_OBSTACLE_GEOMETRY_INVALID` hard error.

## Compatibility

This is a reader-before-writer migration. Existing Wall admission exclusions,
Physical Space reconstruction, legacy Mechanical obstacle inputs and release
gates are unchanged. Consumers may read the collection only after their own
separately governed contract qualification.
