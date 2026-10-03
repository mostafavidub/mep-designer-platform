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

Canonical identity uses the governed semantic projection defined in
`ARCHITECTURE_CANONICAL_IDENTITY_AND_LEVEL_PROPAGATION.md`. Diagnostic runtime
metadata and presentation ordering are excluded, while represented levels,
world-space placement, authority and topology meaning remain identity-bearing.
Snapshot creation time is immutable audit metadata, not part of snapshot ID.

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

Multi-level frame metadata is additive. A typical-floor frame carries every
`represented_level_id` without duplicating its geometry; roof and roof-headroom
titles remain distinct and unknown titles remain unresolved.

## Source-role and physical-evidence correction (SWCIS 4.65.0)

The RAW DXF producer now classifies source roles before granting topology or
material authority. Reusable column, furniture, detail and reference evidence
vetoes incompatible wall/void interpretation. A nearby duct label cannot turn a
column into a void, and detail/reference geometry cannot become a material wall.
Classifications and negative evidence remain traceable in the corrected model.

Physical spaces carry separate geometry and semantic status. Local source
segments, supported occupied wall intervals and proven enclosure closures form
`geometry_evidence`; labels do not prove enclosure. Missing boundary support or
unresolved interior wall evidence prevents verified physical geometry. Exact
semantic hosts must be unique. Ambiguous boundary labels and unproven local
service labels remain unresolved, and their functional zones and legacy room
projections retain the unresolved status. Valid closed boundary geometry can
remain valid while a room's semantic interpretation still needs input.

The independent validator recomputes coverage of the entire polygon boundary,
including holes, from evidence segments. It does not accept a claimed VERIFIED
status in place of geometry or accept contradictory negative evidence. Claimed
reconstruction tolerance is capped at the existing four-times-0.05-metre bound
(converted through source scale); it does not confer new closure authority.
Source roles also independently prohibit COLUMN-as-VERIFIED-VOID and
DETAIL/REFERENCE_ONLY material walls. Explicit semantic-only legacy evidence
cannot acquire a source-geometric origin through adaptation.

The v2 schema retains its identifier and adds optional role/proof fields, so
source-backed legacy structured inputs remain readable. New evidence changes
semantic hashes when geometry, authority or provenance changes. Existing review
fingerprints and snapshot identity checks therefore invalidate affected old
qualifications naturally. Regeneration and rollback are defined in
`standards/swcis/migrations/architecture-false-authority-evidence.json`.

### Verification and remaining boundary

The focused validator suite passed 23 tests; foundation, identity and preflight
review suites passed 53 tests; preflight UI passed 11 tests. These executed
results do not substitute for full regression, private corpus comparison or CI.
An initial full run reported 1235 passed plus 14 subtests; the final rerun after
latest additions remains pending. Seven private development pilots were replayed
twice with equal canonical/validator/preflight identities and no duplicate IDs.
The preliminary comparison records intentional geometry/count changes and three
false column void removals; unclassified removals are not presumed correct. Its
first candidate run preceded later positive-recall safeguards, so this is not a
held-out or final recall claim. Final replay and CI remain pending in change
request SWCIS-2026-0295. No private drawing geometry, handles or labels are
stored in these contracts.

The reconstructed furniture-plus-room-label negative test demonstrates that
legacy room projection does not restore VERIFIED status and the mechanical
completeness gate remains closed. `run_engineering_pipeline` checks completeness
before calculations and routing. Existing migration debt remains: some legacy
room/profile consumers trust aggregate completeness and do not independently
validate each room, while the app's model aggregator derives completeness from
collected issue lists. Malformed or old aggregate inputs with missing issues
require separate consumer migration; this change does not claim to eliminate
that existing trust boundary or activate v2 production consumers. Snapshot
creation continues to require an independently validated PASS.
