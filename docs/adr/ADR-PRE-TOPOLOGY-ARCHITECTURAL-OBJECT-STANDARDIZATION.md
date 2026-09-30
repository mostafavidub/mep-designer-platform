# ADR: Pre-Topology Architectural Object Standardization

## Status

Accepted for staging qualification.

## Context

Source preservation and architectural-space reconstruction previously used separate classifications. A source entity could be correctly preserved as a column, grid or stair graphic while its exploded linework independently entered wall admission and polygonization. Geometry repetition alone could therefore promote a non-enclosure object into a wall or physical-space boundary.

## Decision

A deterministic object-standardization stage runs after DXF extraction and before wall admission, candidate topology, envelope inference and polygonization.

Each source record receives a stable identity and three independent attributes:

- object class;
- domain (`SHEET_DOMAIN`, `ARCHITECTURAL_DOMAIN` or `OUTSIDE_ARCHITECTURAL_DOMAIN`);
- topology role.

The canonical classes cover sheet frames, dimensions, grids, columns, stairs, windows, doors, double doors, open passages, dining-table assemblies, vehicles, parking bays, section cuts, generic non-enclosure objects, enclosure candidates and unknown records. Every decision retains positive and negative evidence.

Classification never grants enclosure authority. Sheet references, datums, opening symbols, obstacles, furniture, vehicles and presentation graphics are excluded before wall admission. An enclosure candidate must still pass the independent multi-evidence wall engine. Unknown and contradictory records fail closed and retain diagnostics.

Opening Evidence remains distinct from Portal and Access Edge. Object footprint remains distinct from Physical Space. Column and obstacle footprints may be consumed by later obstacle modelling, but cannot create physical spaces.

## Consequences

- Non-enclosure source geometry cannot be promoted merely by recurring parallel lines or a closed footprint.
- Source handles and deterministic classifier IDs remain available for review and audit.
- The contract is additive to the canonical architecture model.
- Private evaluation geometry and project-specific coordinates are forbidden in code and committed tests.
- Staging deployment is permitted only after targeted, full regression, SWCIS and protected CI gates pass. Production deployment and merge are not authorized by this ADR.

## Rollback

Redeploy the previous approved staging Git SHA. No database deletion or schema rollback is required because the model additions are additive.
