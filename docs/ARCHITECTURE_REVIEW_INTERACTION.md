# Architecture review interaction contract

The customer review canvas has two explicit modes. Selecting a detected or new
space always activates **boundary selection**; left-clicking a blue CAD snap
node adds that immutable node ID. **Plan movement** is opt-in through the
toolbar and never consumes a boundary click. Zoom and fit do not silently
change modes.

Functional relationship and master-suite identity are inferred from the space
type and label. Ordinary spaces, including elevators, are independent. Master
components receive a deterministic proposed `MASTER-NN` identity; customers
may override these values under optional specialist settings.

The review graph may supplement semantic wall topology with a source-rendered
straight jamb only when both endpoints touch the existing authoritative wall
graph. Standalone furniture, dimensions, annotations and long presentation
lines are not promoted. Every stored boundary still consists solely of server
recognized node IDs and is resolved on the server wall graph.

For an existing detected space the canvas shows snap nodes only inside a padded
neighborhood of that space (plus nodes already chosen). When a detected item
has no reliable bounds yet, its source label point defines the local review
neighborhood. This keeps dense plans legible without removing any server-side
node or changing the stored geometry.
