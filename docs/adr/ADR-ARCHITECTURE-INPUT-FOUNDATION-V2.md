# ADR — Architecture Input Foundation v2

Status: Accepted as experimental/internal foundation; production migration deferred.

## Decision

Planha is an architectural model compiler. `RAW_DXF`, future `CERTIFIED_DXF`, a
portable `.planha` package, and future `IFC` adapters converge on exactly one
`planha-canonical-architecture/2.0` model. An independent, read-only validator
must run before an immutable validated snapshot can become a downstream input.
Bounded review is permitted between validation and snapshot qualification, but
never fabricates material geometry.

The sequence is:

`input → adapter → canonical model → independent validator → bounded review → validated snapshot → disciplines`.

No input kind bypasses validation. Authority is separated into geometry,
semantic, topology, review, and release dimensions. `VISION_SUPPORT_ONLY` is
advisory and cannot independently grant wall, material, portal, access, routing,
or release authority.

## Rationale

The Iranian market is DXF-heavy, so RAW DXF reconstruction remains essential.
BIM cannot be required. Certified DXF and IFC may provide stronger structured
semantics later, but their structure is not presumed correct and they remain
subject to the same validation. `.planha` is a deterministic portable container,
not an alternate truth model.

## Consequences

- Existing `reconstruct_architecture` remains the active RAW DXF producer.
- V2 is additive and experimental; production consumers are unchanged.
- Future migration removes downstream reinterpretation only in a separately
  governed reader-before-writer task.
- IFC parsing, Certified DXF, plugins, UI, and production package routes are
  explicitly unimplemented here.
