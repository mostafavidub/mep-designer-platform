# Planha Architecture Understanding Benchmark

The benchmark compares Canonical Architecture v2 predictions with independent
`planha-architecture-truth/1.0` artifacts. Cohorts are `DEVELOPMENT`,
`VALIDATION`, and `EVALUATION_HELD_OUT`. Held-out truth may be compared only after
blind output is sealed, consistent with `REFERENCE_TRUTH_SET_STANDARD.md`.

Truth supports levels/frames, physical spaces and semantics, optional functional
zones and walls, doors/windows/open passages, voids/ducts/shafts, adjacency,
enclosure/access, reviewed dimensions, and genuine source ambiguities. It stores
source SHA, review source/version, and does not manufacture certainty.

Metrics include level precision/recall; space precision/recall, area error, IoU,
and boundary distance; semantic accuracy; relevant-wall recall and false walls;
portal precision/recall by type; void geometry; graph accuracy; false authority;
review workload; and repeat-run hash identity.

Hard gates always dominate aggregate metrics: false authoritative material
geometry, false portal, false access, false shaft/void, illegal space overlap,
cross-level topology, and unsupported downstream release must all be zero.
Synthetic fixtures drive CI. Private customer sources are optional development
diagnostics only and are never required CI inputs. Project-specific constants
and tuning against held-out truth are forbidden.
