# Architecture Interruption Detector Recovery

This change resolves the deterministic detector limitations that remained
after the material-continuity and aperture-authority qualification. It does not
force a building envelope, Physical Space, Portal, or release decision.

## Root-cause inventory

The frozen diagnostic set contained 24 `ENGINE_DETECTOR_LIMITATION` rows, all
on the Typical frame. Source-lineage review found three related deterministic
defects:

- Eight projected face gaps were outside, or only at one boundary of, the
  common paired-material intervals. They were pairing diagnostics rather than
  internal material interruptions.
- Sixteen internal gaps were exact drafting trims at independently
  source-backed orthogonal wall junctions. Thirteen could bind an existing
  canonical Double Face wall; three required the retained accepted source-face
  lineage because greedy canonical pairing had consumed one face elsewhere.
- Overlapping but unequal two-face gaps used their intersection as the
  material interruption. Because paired material exists only where both faces
  exist, the correct interruption is the union of those face gaps.

No record established a true source-geometry deficiency. The six previously
tracked opening-evidence-required relations were not absorbed into this
change.

## Authority contract

An interruption may become `GOVERNED_DRAFTING_FRAGMENTATION` only when:

1. source-backed host material exists on both interruption boundaries;
2. two distinct accepted source wall faces bind the exact gap boundaries;
3. the faces are mutually parallel and perpendicular to the interrupted wall;
4. their separation matches the interruption width within the existing
   geometry tolerance;
5. their source handles and lineage are retained; and
6. competing equal bindings do not exist.

Canonical Double Face walls are preferred. Retained source faces may recover
the proof only when both are `CONFIRMED_WALL` and accepted. Proximity,
orthogonality, a single face, rejected reference geometry, labels, symbols, or
project-specific dimensions never grant continuity.

The resulting closure is non-material and carries:

- `material = false`
- `material_geometry = NONE`
- `wall_authority = NONE`
- `portal_authority = NONE`
- `routing_authority = NONE`
- `access_authority = NONE`

## Frozen-source qualification

The 24 rows requalify as eight discarded out-of-material pairing diagnostics
and sixteen exact source-backed junction fragmentations. Remaining detector
limitations in that frozen set are zero. Wall and Physical Space identities,
verified-space count, input requirements, review decisions, Dimension result,
and all Portal/Access authority remain unchanged.

Both building envelopes and both canonical subdivisions remain
`INPUT_REQUIRED`. Architecture and Mechanical release remain blocked. This
result removes known deterministic defects; it does not equate `24 -> 0` with
release.
