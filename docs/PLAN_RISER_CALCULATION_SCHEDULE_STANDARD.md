# Plan–Riser–Calculation–Schedule Reconciliation Standard

**Status:** LOCKED  
**Rule:** `MEP-PRCS-001`

Plan, riser, calculation and schedule are distinct projections of one canonical
network graph. Their representation IDs must be distinct and deterministic;
they are related through the same `network_edge_id` and `calc_id`. String
equality between document IDs is a compatibility alias, not reconciliation.

Every graph edge owns exactly one calculation and one network-schedule row.
Every drawable edge owns exactly one exact-file plan representation. Every edge
owns one graph-derived riser representation, including a branch or explicit
vertical role. Size, material, slope, downstream load, load unit, levels and
endpoint nodes come from the calculation/graph authority and may not be edited
independently in any projection.

Submission Ready requires all eighteen controls at 100/100: authoritative
graph; unique edge identity; one calculation per edge; reverse calculation
coverage; calculation provenance; complete plan, riser and schedule
projections; unique plan, riser and schedule representation identities; size,
material, slope and load parity; level/node parity; zero orphan outputs; and
independent exact-DXF identity verification.

The exact issued DXF is reopened after its last mutation. Each canonical route
must occur exactly once with governed XDATA containing its edge, calculation,
three representation IDs, system, size, material, slope, load, unit, endpoint
nodes and levels. Missing, duplicate, unknown, malformed or numerically
divergent records fail closed.
