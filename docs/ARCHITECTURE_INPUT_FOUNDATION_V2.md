# Planha Architecture Input Foundation v2

## Strategy and current impact map

The current producer is `cad_engine.architectural_space_engine.reconstruct_architecture`.
The upload/runtime path passes through `app/main_auto.py` and architecture
reconstruction/segmentation projections, then into canonical input and PMM /
Mechanical consumers, routing, output, and QA. Existing compatibility layers
still project rich canonical evidence into older room/profile structures and
some downstream components can re-derive proximity topology. This is the main
authority-loss debt; it is documented for a later production migration, not
changed by this experimental foundation.

V2 supplies a single model for future RAW DXF, Certified DXF, `.planha`, and IFC
adapters. Only RAW DXF is implemented, as an experimental mapper of the current
engine result. Every adapter returns a candidate, diagnostics, source identity,
and authority provenance. Structured inputs never bypass validation.

## Contract and authority

`planha-canonical-architecture/2.0` covers source identity, levels/frames,
walls, physical spaces, functional zones, apertures/portals, voids/shafts/ducts,
dimensions, provenance-bearing graphs, unresolved items, evidence, review,
traceability, and release state.

Authority has independent geometry, semantic, topology, review, and release
dimensions. Origins include source-explicit, source-geometric,
source-semantic, structured input, deterministic derivation, human confirmation,
and vision-support-only. Evidence cannot silently promote authority. Approximate
functional zones have no material authority. Routing authority for a shaft is
separate from its geometric identity.

## Independent validator and MEP-ARCH-RECOG-001

`cad_engine/architecture_validator.py` deep-copies and hashes its input and
never mutates producer output. Hard errors cover source identity, invalid or
overlapping space geometry, dangling references, false portal/access authority,
cross-level topology, label/vision-derived void geometry, stale review authority,
and integrity mismatches. Bounded missing evidence becomes `INPUT_REQUIRED`.
Critical hard gates cannot be hidden by an aggregate score.

MEP-ARCH-RECOG-001 remains the release-level architecture recognition rule.
V2 implements its canonical identity, geometry, topology, traceability, and
fail-closed controls. Sheet/equipment presentation controls remain downstream;
legacy projections remain compatibility-only until explicit migration.

## Snapshot and review

`planha-validated-architecture-snapshot/1.0` freezes canonical model hash,
source revision, adapter/engine/validator identities, validator report hash,
review hash, time, and lifecycle. Source/model/review/validator changes make the
snapshot stale. `SUPERSEDED` snapshots have no current authority.

`planha-architecture-review/1.0` allows bounded classification of existing
source-supported evidence. AI recommendations are advisory only. Human authority
is source interpretation only; it cannot fabricate arbitrary geometry. Changed
source, object, geometry, or evidence fingerprints invalidate the decision.

## Trust and migration boundaries

- RAW DXF: reconstruction plus validation.
- Certified DXF: future stronger semantics plus validation.
- `.planha`: hash/schema/freshness verification plus validation.
- IFC: future structured adapter plus validation; BIM remains optional.

Production routes and consumers are unchanged. Future independent tasks should
cover the review engine/UI, Certified DXF profile, production package I/O,
AutoCAD plugin, IFC adapter, production V2 migration, and held-out qualification.
Constraint reasoning and targeted vision tie-breakers remain separate research.
