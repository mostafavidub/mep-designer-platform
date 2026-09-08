# Generated Mechanical Integrity Gate

This gate is the final exact-artifact engineering integrity check for mechanical DXF generation. It complements planner, calculation, routing, manifest and presentation QA; it does not replace them.

## Fail-closed rules

A generated mechanical artifact must not be released when any of the following is detected:

1. More than one occupied/roof level identity appears inside one issued plan board.
2. A support drawing such as detail, section, elevation, parking, slope, lintel, door/window or floor-finish plan is mixed into an occupied plan authority board.
3. A primary water, sanitary/vent, gas or exhaust board contains only marker-scale/degenerate geometry rather than a substantive route network.
4. Equipment coordinates collapse so that repeated instances represent duplicated detection rather than distinct physical placement.
5. Split-AC indoor units or schedule rows exist without a real outdoor-unit entity.
6. A riser reports zero branches while reconciliation is marked TRUE/PASS.
7. A detail register promises detail IDs that are not materially represented in the drawing set.
8. A numeric utility water pressure is used when no traceable project pressure answer exists.
9. Explicit project scope requires septic or fire-water content but the generated artifact contains no corresponding system evidence.
10. Exact DXF reopen/audit reports any error.

The gate never repairs unknown architecture and never invents project facts. A failed artifact is restored to the previous safe output when one exists, otherwise the unreleasable generated file is removed.

## Level authority

Only occupied-floor or explicit roof evidence may become active level authority. Detail, section, elevation, parking, slope and other support drawings remain diagnostic inputs and cannot become floors. A generic slope-plan title alone is not sufficient to create an authoritative roof level; independent roof evidence is required.

## Typical grouping

Typical grouping remains system-specific. A floor group is allowed only when architecture and the relevant system fixture/equipment evidence agree. Uncertainty keeps floors separate.

## Network validity

Entity/layer presence is insufficient. Applicable primary systems must produce substantive network geometry consistent with the project graph. Marker-only squares, zero-length segments and near-zero route spans are release-blocking.

## Equipment, riser and detail reconciliation

Plan entities, schedule rows, riser branches, calculation segments and detail-register entries must describe the same physical design. Contradictory counts or absent materialized entities block release.

## Evidence and calculation policy

Unverified utility or manufacturer values remain unresolved/pre-submission facts. The generated artifact may display a design envelope or explicit verification note, but it may not silently use an unverified numeric value as final engineering evidence.

## Regression policy

Changes to this gate require focused negative tests, the representative Golden Regression suite, blind sealing before any approved-reference comparison, semantic/artifact diff review and production E2E verification before deployment.
