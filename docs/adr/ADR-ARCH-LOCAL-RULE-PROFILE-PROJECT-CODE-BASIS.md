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

Schema validity proves only shape and required content. Fixture disclaimer markers are
optional schema properties; repository fixtures must carry the exact three disclaimers,
and their presence caps the result at `STRUCTURALLY_VALID`. Their absence grants no
authority. Embedded reviewer claims and caller-supplied source snapshots are also
untrusted. A future independently governed resolver must verify canonical source
identity/revision/hash, reviewer identity and professional qualification, exact review
scope, decision identity and evidence. This change defines the interface but deliberately
does not provide a production registry, credential service or authority-granting path.

## Geometry decision

The offline envelope calculator supports only valid convex parcel polygons in metres
with an explicit coordinate reference system and a traceable setback for every parcel
edge. It clips the parcel against inward edge half-planes and independently checks the
result with polygon validity, containment and area checks. Concave/complex parcels,
missing edge bindings, impossible intersections and unit ambiguity fail closed.
Non-finite coordinates or setbacks, negative setbacks, duplicate consecutive vertices,
zero-length edges and invalid dependency fingerprints are rejected before clipping.
No geometry is repaired, snapped or inferred.

Calculated geometry is labelled `CALCULATED_NOT_PROFESSIONALLY_APPROVED`. It cannot
become an approved project envelope without separately scoped professional review.

## Compatibility

The change is additive. Generation Input 1.0 and Owner Program 1.0/2.0 are unchanged.
A legacy precomputed envelope remains readable but does not gain new source authority;
it must be rebound and revalidated before future use by this contract.
Draft 1.0 records must be revalidated under the hardened semantics. Marker-free records
remain schema-compatible; prior `AUTHORITY_QUALIFIED` claims become
`AUTHORITY_REVIEW_REQUIRED` until an independently approved provider exists.

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
