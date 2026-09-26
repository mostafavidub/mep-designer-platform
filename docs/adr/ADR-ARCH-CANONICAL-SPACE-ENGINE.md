# ADR: Canonical Architectural Space Understanding Engine

## Status

Proposed — implementation and evidence tracked by SWCIS-2026-0284.

## Decision

Planha will use one canonical, deterministic-first architectural model. A
`PhysicalSpace` represents connected geometry; zero or more `FunctionalZone`
records describe uses inside it. Downstream disciplines consume this model and
must not independently re-detect rooms.

The pipeline order is source validation, frame classification, calibration,
primitive extraction, object and wall/opening reconstruction, cell generation,
semantic zoning, dimension association, optional vision reconciliation, evidence
fusion, completeness evaluation and targeted human review.

Vision is accessed through an adapter and is invoked only for unresolved regions.
Its evidence is advisory until reconciled with CAD. Critical ambiguity fails
closed. Stable identities are content-derived from source, frame, level and
normalized geometry.

## Consequences

- Open plans are no longer represented by invented walls.
- Missing labels do not imply missing geometry.
- Unknown areas cannot silently disappear.
- Existing PMM consumers receive a compatibility projection during migration.
- More drawings will truthfully stop at `INPUT_REQUIRED` until evidence or a
  focused human decision resolves the ambiguity.
