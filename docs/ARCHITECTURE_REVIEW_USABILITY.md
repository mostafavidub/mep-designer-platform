# Architecture Review Usability

## Contract delta

The architecture-review data and audit contracts are unchanged. Presentation
keeps full Persian names in the numbered inspector list and suppresses labels
over CAD geometry, so long names cannot cover the plan. CAD snap nodes are hidden until the customer
selects a space, preventing unrelated nodes from obscuring the plan.

The review screen exposes a four-step workflow, non-empty Persian fallbacks for
unnamed detections, numbered space rows, fit and zoom controls, and contextual
instructions that change as points are selected. The final boundary remains
restricted to immutable CAD node IDs and is still validated server-side.

After zooming, customers can pan the plan with mouse or touch. Dragging changes
only the local viewport, never the engineering coordinates or selected nodes;
the fit control resets both zoom and pan.

## Migration and rollout

No schema or data migration is required. Existing review state, revisions and
audit events render through the improved UI. Deploy the protected Staging
commit and verify project 40 at full-plan view, after selecting a space, and
after selecting several snap nodes. Production remains unchanged without
explicit owner approval.

## Rollback

Redeploy the preceding approved Staging commit. Review data and audit history
need no rollback because this change writes no new persistent format.

## Evidence

- Labels use a bounded fraction of the current plan extent.
- Snap nodes do not render before a space is selected.
- Existing exact-node and boundary-closure validations remain covered.
- Architecture, geometry reconstruction and checkout regression suites pass.
