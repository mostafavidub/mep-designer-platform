# Architecture Understanding Completion

## Decision

The customer review must never use the simplified wall graph as the visual
representation of the uploaded drawing.  Every confirmed plan owns two
coincident but independent projections:

1. `source-faithful/1` visual underlay: the complete drawable source evidence.
2. engineering topology: selected/noded wall, opening, shaft and room evidence.

Only topology participates in boundary selection and downstream engineering.
The underlay exists so the customer and QA can see what the source actually
contained.  Both retain source handle, effective layer, nested block path and
global transformed coordinates.

## Source coverage

The underlay expands nested INSERTs with translation, scale and rotation,
inherits the parent layer for block children on layer 0, expands presentation
entities through their virtual primitives, flattens ARC/CIRCLE/ELLIPSE/SPLINE
and HATCH curves at a bounded tolerance, and preserves source text/attributes.
Unsupported entity types are counted; unresolved INSERT, DIMENSION, leader,
MLINE, proxy, image or wipeout evidence fails the underlay rather than
disappearing. Unbound XREFs and empty/broken block references are also explicit
failures. POINT entities and bulged polylines remain visible evidence.

The engineering topology consumes the same transformed block geometry but
explicitly excludes presentation entities.  It may therefore be simpler than
the underlay without misleading the reviewer.

## Review contract and migration

`architecture-review/2` requires `visual_underlay_contract=source-faithful/1`.
Persisted reviews from the former wall-only presentation are rebuilt from the
same source hash and cannot remain confirmed merely because the uploaded file
did not change.  This is an intentional fail-closed migration: a confirmation
made against incomplete visual evidence is not authoritative.

Each level must have a canonical frame, a non-empty underlay and underlay
status `PASS` before final confirmation is enabled.  High-confidence rooms can
still bypass manual boundary editing; unresolved spaces remain exception-only
review items.

## UI and interaction

The source underlay is rendered first.  Engineering walls, confirmed room
polygons and selected CAD nodes are overlays in the identical coordinate
system.  Zoom, pan and fit affect only the viewport and never engineering
coordinates or saved node identities.

## Verification

- Positive: nested layer-0 block walls and arcs appear in the underlay and can
  close an evidence-backed room.
- Negative: unsupported entities are inventoried instead of silently dropped.
- Destructive: unbound XREF and empty INSERT fixtures fail closed.
- Contract: old review state is invalidated unless it carries the new underlay
  contract.
- Regression: architecture reconstruction, review, checkout and downstream
  architecture-preservation tests remain green.
- Live: reanalyse project 40 on Staging and compare every level against the
  uploaded plan before accepting the rollout.

## Rollback

Rollback is deployment of the prior approved Staging Git commit.  No Production
deployment is authorized by this change.  Review state created under schema 2
is retained but older code will continue to fail closed rather than reinterpret
it as an approved wall-only review.
