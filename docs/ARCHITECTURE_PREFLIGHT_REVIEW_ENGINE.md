# Planha Architecture Preflight Review Engine

## Purpose and boundary

The experimental backend closes the controlled loop between Canonical Architecture v2, independent validation, bounded source interpretation, safe replay, revalidation, and an immutable snapshot. It is not a geometry editor, production API, or release authority. The Independent Architecture Validator is the only component that may establish architectural validity.

## Workflow

1. Validate the canonical candidate independently.
2. Normalize raw validator and unresolved-item evidence without discarding the raw codes.
3. Classify each issue as `REVIEWABLE_SOURCE_INTERPRETATION`, `SOURCE_INPUT_REQUIRED`, `ENGINE_DEFECT_OR_CONTRACT_ERROR`, `NONCRITICAL_DIAGNOSTIC`, or `ALREADY_RESOLVED`.
4. Group reviewable issues by their source-backed root-cause identity.
5. Emit the smallest deterministic set of bounded questions that covers every reviewable critical issue.
6. Validate decisions as untrusted input and apply only allowlisted interpretation overlays.
7. Re-run the independent validator.
8. Create a snapshot only from a validator `PASS` report whose integrity and model hash are current.

The preflight state is exactly one of `AUTO_VALIDATED`, `QUICK_REVIEW_REQUIRED`, `ARCHITECTURE_INPUT_REQUIRED`, or `CONFLICT`.

## Reviewability and impact

A reviewable item must already have an existing bounded object or region, source identity, geometry and evidence fingerprints, closed candidate interpretations, closed allowed answers, and an effect that needs no geometry creation. Missing walls, polygons, apertures, coordinates, scale, level geometry, source handles, or valid topology are not review questions.

Impact is classified as `RELEASE_CRITICAL`, `DOWNSTREAM_CRITICAL`, `REVIEW_CRITICAL`, or `NONCRITICAL_DIAGNOSTIC`. A harmless drafting ambiguity does not create a blocking question, but remains traceable. Internal reference failures, duplicate identities, and contradictory authoritative evidence are software/contract conflicts and are never delegated to users.

## Minimal deterministic planning

Issues are grouped by source, frame/level, object or region, geometry fingerprint, evidence fingerprint, review scope, and root-cause group. One decision can therefore cover several dependent validator codes. Items are ordered by impact and domain: source/frame, space, wall/enclosure, void, portal/access, semantics, dimensions, diagnostics. Stable content hashes produce stable item IDs, fingerprints, ordering, coverage, and metrics.

Every item declares its covered raw issue IDs, evidence summary, permitted effects, prohibited effects, and a UI-independent crop request. The future UI must render this specification rather than invent engineering crop or question logic.

## Authority and replay

`HUMAN_CONFIRMED` is not an engineering geometry status. Engineering status remains separate from `review_status=CONFIRMED` and `review_authority=HUMAN_SOURCE_INTERPRETATION`. Review never grants `HUMAN_CREATED_GEOMETRY`.

Replay verifies the source SHA, frame or level, object or region, geometry fingerprint, evidence fingerprint, scope, allowed answer, identity fingerprint, and governed review fingerprint. Any mismatch yields `STALE_REVIEW_DECISION` or a precise rejection. Review payloads cannot change source identity, coordinates, geometry, walls, apertures, Portals, Voids, Access edges, or unrelated fields.

Examples:

- `DOOR` may classify an existing valid aperture/Portal motif; it cannot cut a wall or create a Portal.
- `WINDOW` never creates Access.
- `DUCT` may classify an existing closed Void boundary; it cannot construct a polygon from a label.
- `SAME_PHYSICAL_SPACE` may confirm an existing bounded Open Plan candidate; it cannot create or remove a wall.
- `UNKNOWN` grants no authority and leaves a critical issue unresolved.

Applying the same valid decision twice is idempotent. A different decision for the same fingerprint conflicts. If the same current decision has been applied and the same blocker remains, the engine does not repeat the question; it escalates to source input or an engine/contract defect.

## Source-input-required guidance

Each non-reviewable source blocker identifies the frame/location, affected object, missing evidence, downstream impact, and correction type. Guidance must be specific, for example: “A Door motif exists at this boundary, but no source-backed aperture exists; correct the opening geometry or use a future governed symbolic-Portal workflow.”

## Revalidation and snapshots

The Review Engine cannot self-pass. After every accepted overlay it invokes the independent validator and retains the complete raw report. `planha-validated-architecture-snapshot/1.0` creation requires a current, integrity-verified `PASS` report. An automatic snapshot contains no review manifest. A reviewed snapshot records the manifest hash and accepted decision IDs. Source, model, validator report, review manifest, or decision-identity changes make the snapshot stale.

## Integrity and quality controls

Review decisions are schema-checked untrusted input. The canonical model hash, validator report hash, review fingerprint, immutable geometry, and registry history are independently verified. Hard targets are zero hidden critical issues, stale authority, duplicate questions, repeated-question loops, validator bypasses, manual geometry creation, and synthetic Walls, Portals, Voids, or Access edges.

The registry serializes generated items, accepted/rejected/stale decisions, decision history, post-decision validation, resolved/unresolved issues, attempts, and convergence state. It is suitable for future `.planha` packaging and persistence, but neither integration is activated here.

## Fasihi diagnostic scope

The whole-model development baseline spans nine frames and contains four Physical Spaces and two Voids. Ground (`FRAME-C7C5B4F856993D8A`) contains two Physical Spaces and one Duct Void; the additional Space/Void records belong to other frames. The count difference is scope, not a v2 mapping discrepancy. A Toilet Door motif without a source-backed material aperture is `ARCHITECTURE_INPUT_REQUIRED`: asking whether it looks like a Door cannot legally create Portal or Access authority.

## Production status

This engine is experimental/internal. It adds no public route, UI, database migration, production package ingestion, Mechanical migration, or deployment. Existing `MEP-ARCH-RECOG-001` recognition and release gates remain authoritative after preflight.
