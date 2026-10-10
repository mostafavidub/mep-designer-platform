# Legacy material-local boundary proof

## Scope

This change closes two false-authority paths in legacy Physical Space boundary
verification. It does not change canonical Wall reconstruction, opening rules,
envelope reconstruction, or downstream release gates.

## Original defect

`physical_boundary_evidence()` admitted both a complete canonical `face_a` or
`face_b` and the corresponding complete classified source primitive. A canonical
DOUBLE_FACE wall can legitimately retain a long source face while its paired
physical material occupies only a short `wall_solid.occupied_intervals` range.
Either admission path could therefore bridge a known material absence and inflate
boundary coverage to one.

## Governing contract

A source line proves that geometry exists in the source. It does not prove paired
wall material over its complete extent. For a source occurrence represented by a
canonical DOUBLE_FACE wall, physical boundary support is limited to the
intersection of the original face's axis projection with the wall's occupied
material intervals. The accepted subsegment is mapped back onto the original face;
the centerline is never substituted for the face.

An accepted source occurrence not represented by a DOUBLE_FACE wall retains the
existing source-geometric recognition path. That path does not independently grant
material or separator authority. Exact `segment_id` or complete occurrence identity
governs mapping; source handle alone is insufficient. Ambiguous mappings fail
closed.

After this correction, legacy `geometry_status = VERIFIED` means the complete
candidate boundary is covered by qualified source-backed geometry: material-local
paired-wall faces, independently admissible source geometry, or an existing governed
non-material closure. It does not mean that every contributing source line is wall
material, and separator authority remains a separate contract.

## Provenance and residuals

Original source witness geometry is retained for provenance. Each witness separately
records qualified boundary-support subsegments and unsupported residual geometry.
Only a fully accounted mapped occurrence enters `boundary_fragment_ids`; partial
support cannot consume the remaining source primitive. Separator evidence binds to
qualified subsegments and cannot reconstruct coverage from the original full witness.

## Validation and rollback

Negative tests cover long-face/short-material authority, raw-source laundering,
handle-only aliasing, residual accounting, and centerline offset. Positive tests
preserve fully and partially paired walls, independent source-only geometry, nested
source occurrences, and input-order determinism. Private replay evidence is recorded
only as hashes and aggregate authority results.

Rollback is a Git revert of this change. No schema, database, source-file, or stored
review migration is required.
