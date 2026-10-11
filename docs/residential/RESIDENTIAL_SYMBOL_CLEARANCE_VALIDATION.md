# Residential symbol clearance and placement validation

## Status and boundary

This is an **offline, read-only, non-authoritative** Architecture capability. It
extends the one canonical `residential_symbols` implementation and adds one
independent validator. It is not a Generator, CAD insertion path, whole-plan QA,
professional approval, or runtime entrypoint.

Executable identity remains the Git commit plus automatic content/dependency
hashes. Schema `1.0` identifiers describe data contracts and never select an
executable engine.

## Contracts

`architecture-clearance-profile/1.0` represents one source-bound clearance:

- `OBJECT_FOOTPRINT`
- `USAGE_CLEARANCE`
- `ACCESS_CLEARANCE`
- `MAINTENANCE_CLEARANCE`
- `CODE_REQUIRED_CLEARANCE`

Profiles carry symbol identity/category, one or more local polygons, operating
configuration, coexistence policy, authority class, source revision/hash,
rule/clause reference, verification state and a content fingerprint. Mandatory
profiles require independently resolved national/local evidence. An embedded
`AUTHORITY_QUALIFIED` string, source hash or review field grants no authority.

`architecture-symbol-placement/1.0` binds the exact symbol parameter and geometry
fingerprints to project, Physical Space, coordinate frame, optional host,
transformation, clearance profiles, relevant Owner Program subset and
ProjectCodeBasis. Material changes make the placement stale. Unrelated owner
preferences are deliberately excluded.

`architecture-placement-scene/1.0` supplies the authoritative Physical Space,
current hosts, profiles, placements, explicit obstacles and bounded access checks.
The validator never discovers or repairs any of these objects.

## Validation semantics

The result keeps these dimensions separate:

1. structural geometry validity;
2. placement validity;
3. functional usability;
4. regulatory compliance;
5. professional review.

Footprints must remain within a current verified material Physical Space. Positive
area overlap between object footprints or an explicitly supplied physical obstacle
is a collision; boundary contact alone is permitted. Door operating envelopes
require exact host evidence and cannot intersect another footprint or physical obstacle. Clearance
overlap follows the profile's `PROHIBITED`, `PERMITTED`, or
`CONDITIONAL_REVIEW` policy. Unresolved simultaneous-use semantics produce human
review, not an assumed pass/fail.

Bounded access checking erodes the supplied room by half the required width,
expands explicit obstacles by the same amount, and verifies that both endpoints
belong to one remaining connected component. It makes no whole-building egress or
Code 246 claim. A mandatory path without independent applicable authority remains
`INPUT_REQUIRED`.

Canonical-symbol freshness compares symbol-local geometry to placement-local
geometry; translated or rotated display geometry is never compared across coordinate
spaces. Invalid nested profiles are rejected before any Shapely traversal.

Regulatory compliance begins as `NOT_EVALUATED`, not `PASS`. It becomes `PASS`
only when an applicable mandatory profile is independently source/rule-qualified
and its geometry is actually evaluated. Missing applicability, synthetic evidence,
self-asserted authority, or an unavailable independent resolver remains fail-closed.
Professional review remains a separate `NOT_REVIEWED` dimension. Successful geometry
therefore remains `REVIEW_REQUIRED`; it never means professional approval.

## Compatibility

All 41 symbol IDs and the existing call signature remain valid. Existing footprint,
usage-envelope and SVG behavior is preserved. Optional height and geometry identity
are additive. Legacy `usage_clearance_m` becomes an explicitly `UNVERIFIED`
heuristic region; it is never promoted to code authority.

Owner Program 1.0/2.0 and ProjectCodeBasis are unchanged. They are current-binding
dependencies only. No production runtime imports this validator.

## Evidence gaps

No production clearance value is added. Qualified manufacturer operating regions,
Iranian code clearances, local parking/access requirements and licensed review are
still required per project. Test distances carry all three fixture disclaimers and
cannot become defaults or Golden truth.
