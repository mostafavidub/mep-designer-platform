# Mechanical Topology and Routing 100 Standard

**Rule:** `MEP-ROUTE-001`  
**Contract:** `topology-routing/1`  
**Status:** LOCKED

## Acceptance

The canonical Mechanical authority evaluates topology and routing after graph
construction and explicit segment execution, and again against the exact
reopened DXF. Release requires all eighteen controls to be explicit `PASS`, a
weighted score of exactly 100, and `release_allowed=true`. Missing, unknown,
skipped or failed evidence blocks CAD delivery; an average cannot mask a defect.

## Eighteen controls

1. Typed space and level graph (6).
2. Hosted endpoint and port inventory (7).
3. Per-system graph separation (5).
4. Authoritative source/destination and unique edge identity (5).
5. Every required endpoint port served with exactly one terminal incidence (8).
6. Continuous branches, mains and system termination (7).
7. Architectural shaft authority; provisional shafts forbidden (5).
8. Consecutive vertical level continuity (7).
9. Aligned shafts or explicitly declared offsets (5).
10. Finite orthogonal plan routes (5).
11. Zero intermediate-wall crossings and bounded terminal sleeves (5).
12. Zero critical Structural/RCP clashes when coordination is applicable (7).
13. Explicit size, material and positive gravity-slope evidence (7).
14. Bounded deterministic route detour (4).
15. Constructability, installation and service access (5).
16. Route-sensitive equipment envelope validation (4).
17. Exact Plan/Riser/Calculation/Schedule identity (5).
18. Deterministic graph plus exact reopened-output edge parity (3).

Weights total 100. No control is optional in the report; an inapplicable check
passes only with a truthful empty-applicability state, never fabricated evidence.

## Ordering and authority

Inputs are limited to the owner questionnaire, typed architectural/PMM evidence,
explicit project design bases and applicable authoritative Structural/RCP or
manufacturer data. Mechanical reference drawings are forbidden generation
inputs. The accepted chain is:

`evidence -> graph -> routes -> executed segments -> QA 100 -> CAD -> exact reopen`

Any graph, route, calculation or artifact mutation invalidates the evidence hash
and requires regeneration. Existing projects must be regenerated to receive this
contract. Rollback uses a previously approved Git commit, never a gate bypass.
