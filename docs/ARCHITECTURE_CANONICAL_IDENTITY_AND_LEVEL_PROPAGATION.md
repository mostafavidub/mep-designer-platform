# Architecture Canonical Identity and Level Propagation

## Scope

This standard defines deterministic identity for the experimental Planha Canonical Architecture v2 contract. It changes no recognition geometry, wall admission threshold, portal inference, or production consumer.

## Identity boundary

Canonical identity is the hash of a schema-aware semantic projection. It includes source revision, frame and level ownership, world-space geometry, stable entity identity, source provenance, authority/status, topology graphs, unresolved engineering meaning, and release state.

Runtime diagnostics are deliberately outside canonical identity: timestamps, elapsed time, parse time, host paths, temporary filenames, process identity, and presentation-only ordering cannot make the same architecture appear different. Exact serialized-content hashes may still be retained for audit, but they are not architectural authority.

Set-like arrays are normalized and entity collections are ordered by stable entity ID. Geometry arrays keep their geometric order. Unicode text is normalized to NFC and finite integral floats normalize consistently with integers.

## Entity identity

Wall identity includes the frame, canonicalized world-space centerline, sorted source handles, and sorted paired-wall constituents. Endpoint reversal and source iteration order therefore do not change identity, while two geometrically equal but differently placed walls cannot collide. Nested INSERT instances remain distinct through transformed world-space placement and provenance.

Evidence identity includes its owning entity and evidence payload. Duplicate Wall, Portal, Dimension, evidence, or unresolved-item identity is a hard validator failure. References to missing evidence also fail closed.

## Levels and Persian title evidence

One frame can represent one, several, or no proven building levels. The additive v2 fields are:

- `represented_level_ids`: every level explicitly represented by the frame title.
- `primary_level_id`: the single primary level only when one is proven.
- `level_relationship`: `SINGLE`, `TYPICAL`, `ROOF`, `ROOF_HEADROOM`, or `UNRESOLVED`.
- `title_evidence`: raw title text, normalized interpretation, represented levels, source handles, and provenance.

Typical-floor titles such as «پلان طبقات اول تا پنجم» preserve all represented levels without duplicating geometry. «پلان بام» and «پلان خرپشته» remain distinct. Unknown titles remain unresolved and never collapse into a false level.

## Authority invariant

Status and authority are independent dimensions but must be consistent. `AMBIGUOUS`, `INPUT_REQUIRED`, `CONFLICT`, and `REJECTED` entities cannot grant material geometry, Wall, Portal, Access, routing, or release authority. The adapter neutralizes invalid legacy grants; the independent validator rejects invalid canonical combinations.

## Review and snapshot identity

Review authority fingerprints include source, scope, governed object, geometry, evidence, allowed decisions, and declared effects. Advisory recommendation text and other presentation metadata do not stale a decision. Any governed evidence or geometry change does.

Snapshot identity is derived from the qualified canonical model, validator report, review manifest, decisions, and stable engine identity. Creation time remains immutable audit metadata but is not part of the snapshot ID.

## Migration

Correcting collision-prone IDs is an intentional one-time identity migration. Reviews tied to changed governed identity become stale, and snapshots tied to changed canonical meaning become superseded. Production activation requires a separate migration decision; this task keeps the v2 path experimental/internal.
