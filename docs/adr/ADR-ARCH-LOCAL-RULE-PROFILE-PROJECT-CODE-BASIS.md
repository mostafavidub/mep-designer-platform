# ADR — Local Rule Profile and Project Code Basis

## Status

Accepted for isolated offline implementation only. Runtime, Generator, Golden,
staging, production and professional-certification authority remain disabled.

## Context

Generation Input 1.0 can carry location, plot and a precomputed envelope, while
Owner Program 2.0 can bind a local-profile identity. Neither contract expresses
the complete chain from official municipal sources through parcel-specific
applicability to reproducible constraints and derived envelope geometry.

## Decision

Planha uses two separate additive contracts:

1. `LocalRuleProfile` records jurisdiction-level documents and rules with explicit
   spatial and temporal scope. It contains no parcel geometry or owner preference.
2. `ProjectCodeBasis` binds national and local profiles to one project, parcel,
   Site Model, Owner Program and effective date. It stores applicability decisions,
   parcel conditions, derived constraints, conflicts and bounded review bindings.

National code, local code, site evidence, owner requirement and human decision are
separate authority dimensions. A content hash establishes identity only. It does
not establish authenticity, applicability, interpretation or professional approval.

## Geometry decision

The offline envelope calculator supports only valid convex parcel polygons in metres
with an explicit coordinate reference system and a traceable setback for every parcel
edge. It clips the parcel against inward edge half-planes and independently checks the
result with polygon validity, containment and area checks. Concave/complex parcels,
missing edge bindings, impossible intersections and unit ambiguity fail closed.

Calculated geometry is labelled `CALCULATED_NOT_PROFESSIONALLY_APPROVED`. It cannot
become an approved project envelope without separately scoped professional review.

## Compatibility

The change is additive. Generation Input 1.0 and Owner Program 1.0/2.0 are unchanged.
A legacy precomputed envelope remains readable but does not gain new source authority;
it must be rebound and revalidated before future use by this contract.

## Source intake

V1 uses hybrid intake: official document, existing Source Registry, candidate
extraction, human verification, deterministic validation, then project binding.
No nationwide crawler or trusted production registry is implemented.

## Rejected alternatives

- City-name defaults: parcel and district conditions differ.
- Owner-supplied `VERIFIED`: preference cannot create legal authority.
- One combined site/rule object: geometry and regulation have different identity and
  invalidation rules.
- Reusing an envelope by proximity or equal hash: identity and provenance must match.
- Supporting arbitrary polygons by silent repair: ambiguous geometry requires review.

## Rollback

Revert the additive branch. No database or production data is migrated, and all prior
contracts remain unchanged.
