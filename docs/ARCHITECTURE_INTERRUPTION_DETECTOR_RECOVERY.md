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
- Sixteen internal gaps appeared to be drafting trims at orthogonal wall
  junctions. Thirteen bind an existing canonical Double Face wall. Final
  authority review found that the remaining three raw face pairs conflict with
  incompatible canonical pairings and therefore remain explicit
  `MULTIPLE_VALID_FACE_PAIRINGS` input requirements.
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
4. before host-gap binding, their separation matches an independently observed
   wall-thickness cluster and their projection overlap satisfies the canonical
   face-pair contract;
5. their source handles and lineage are retained;
6. neither face participates in an incompatible canonical Double Face wall;
7. their separation then binds the interruption width within the existing
   geometry tolerance; and
8. competing equal bindings do not exist.

Canonical Double Face walls are preferred. Retained source faces may recover
the proof only when both are `CONFIRMED_WALL` and accepted and they independently
satisfy the same thickness/overlap contract. Host-gap width is never face-pair
proof. Proximity, orthogonality, a single face, rejected reference geometry,
labels, symbols, or project-specific dimensions never grant continuity.

The three frozen raw cases use source-handle pairs `431081/431089`,
`431107/43110A`, and `430FDE/430FE2`. In each case at least one face is already
used by a canonical Double Face wall with a different mate. The raw alternative
may be geometrically plausible, but the two interpretations cannot silently
share authority. They are classified `CANONICAL_VS_RAW_FACE_PAIR_CONFLICT` and
receive no continuity role.

The resulting closure is non-material and carries:

- `material = false`
- `material_geometry = NONE`
- `wall_authority = NONE`
- `portal_authority = NONE`
- `routing_authority = NONE`
- `access_authority = NONE`

## Frozen-source qualification

The 24 rows requalify as eight discarded out-of-material pairing diagnostics,
thirteen canonical source-backed junction fragmentations, and three explicit
face-pair ambiguities. Remaining deterministic detector defects in that frozen
set are zero; the three demoted rows remain fail-closed input requirements.
No raw fallback is authoritative in the frozen source. Wall and Physical Space
identities, Dimension result, and all Portal/Access authority remain governed
by the final frozen-source replay.

Both building envelopes and both canonical subdivisions remain
`INPUT_REQUIRED`. Architecture and Mechanical release remain blocked. This
result removes known deterministic defects without treating ambiguity removal
as a numerical target.
