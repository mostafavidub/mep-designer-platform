# Architecture boundary-lineage recovery

## Scope and private-source governance

- dependency: PR #327 at `3c5db2ea5b5112d5247a89a3281a03efcc267591`
- private DXF identity: SHA-256 `43c696a6e2703ce746d22b169b90108f0a6a44d3873e56e32f80124793fe1d70`
- no private bytes, filename, screenshot, or crop is committed

## Root cause

Canonical face pairing used overlap relative to the shorter face. A short face
could therefore consume a much longer admitted source line. The resulting
canonical centerline spanned the union of both faces while its occupied
material interval correctly retained only their overlap. Envelope
polygonization nevertheless used the full centerline, creating cycles over
non-material axis extensions. The six Roof intervals are manifestations of
this `WALL_FACE_TO_AXIS_MAPPING_DEFECT`, not proven source gaps or INSERT
transform defects. Their witnesses are top-level entities with identity
transform ancestry.

## Governed correction

Canonical pairing remains a topology identity and explicitly records material
only over the overlap of its two source faces. Envelope candidates are
polygonized only from those occupied material intervals and
explicitly governed non-material continuity closures. Full canonical axes are
never treated as material. Boundary proof retains deterministic material
interval IDs and source lineage: source handle, fragment, INSERT handle, block
path, source transform when available, and primitive-geometry fingerprint.

Candidate relationships (`CONTAINS`, `WITHIN`, `OVERLAPS`, `TOUCHES`, and
`DISJOINT`) are emitted as diagnostics only and grant no authority.

Internal-partition proof and its reported length follow the same contract.
Only the portion of an identified `MATINT-*` interval applicable to the shell
may prove an internal source partition or contribute to
`internal_wall_length`. Each proof record retains the Wall ID, MATINT ID,
source handles and lineage, material geometry, applicable material length, and
its relationship to the candidate shell. A full-axis representative point has
no material authority.

The semantic-interior-union fallback likewise associates exterior Wall IDs
only when occupied material is at the resulting boundary. Full axes remain
permitted solely for topology-only endpoint-closure discovery; those closures
are explicitly non-material and retain `wall_authority = NONE`.

## Roof interval classification

All six former unsupported intervals are classified
`WALL_FACE_TO_AXIS_MAPPING_DEFECT`. Three decisive paired axes combined face
extents of approximately 13.0/1.90 m, 19.747/1.597 m, and 19.747/1.45 m.
Accepted top-level source witnesses exist around the intervals; no nested block
or transform-chain discrepancy is present. The correction removes the false
candidate-axis premise rather than widening distance tolerance.

## Typical rejection cascade

The persisted baseline contains 328 accepted segments, 152 canonical walls,
and 55 full-axis cycles. Its 25.08 m2 largest cycle is site/backyard scope with
no internal partition evidence. Reconstructing from occupied material after
the pairing correction yields only small local cycles and no proven building
shell. Thus the apparent footprint did not survive source-material
polygonization; it was split/discontinuous rather than a candidate that merely
lost semantic approval. Typical remains fail-closed unless every required
interval obtains independent source or governed-continuity support.

## Sliver

The approximately 0.0075 m2 sliver is not changed. Current evidence does not
prove that the corrected long/short face-pairing defect is its sole cause, so
area-based removal or reclassification would exceed this task.

## Final private replay

The final implementation was replayed once against the frozen source identity
above. Compared with the qualified dependency artifact, it preserved all 257
canonical Wall IDs in order, all 19 Physical Space IDs in order, 4 verified
Physical Spaces, 37 input requirements, 15 review decisions, and Dimension
reconciliation `PASS` with zero conflicts. Downstream engineering and release
remain disabled, and Vision calls remain zero.

Roof candidate enumeration changed from 42 full-axis cycles to 5 local
material cycles; the former 217.797453 m2 candidate and its six unsupported
intervals no longer exist because their non-material axis extensions are no
longer polygonized. Typical changed from 55 full-axis cycles to 19 local
material cycles; its former 25.080797 m2 site/backyard cycle likewise does not
survive material polygonization. Both frames remain `INPUT_REQUIRED`: removal
of a false candidate is not proof of a building envelope.

The rejected intermediate hypothesis of narrowing canonical face pairing was
also replayed during diagnosis. It changed Wall/Space authority and introduced
a Dimension conflict, so it was reverted and is not part of this change. The
final replay above validates the narrower material-polygonization correction.

The follow-up internal-partition authority audit was replayed once after its
targeted regressions passed. Relative to the prior qualified artifact it
preserved candidate counts (Roof 5, Typical 19), zero canonical cells for both
frames, every Wall and Physical Space ID in order, and every global authority
metric listed above. Maximum candidate internal material length remained zero
for both frames. Both envelopes therefore remain `INPUT_REQUIRED` without any
new or withdrawn architectural authority.
