# Architecture Reconstruction and Preservation 100 Standard

**Rule:** `MEP-ARCH-PRESERVE-001`
**Status:** LOCKED

An issued mechanical drawing may receive an architecture-preservation score of
100 only when all eighteen controls below are explicitly `PASS`. A missing,
unknown or failed control blocks delivery; an average may never mask a critical
loss.

1. Seal entities, layers, blocks, xrefs, layouts, units, insertion base and bounds.
2. Establish units, scale, origin, rotation and target bounds from coordinate evidence.
3. Separate plans, elevations, sections, details, tables and title blocks; ambiguity fails closed.
4. Bind every issued plan to one real level or declared typical range.
5. Preserve/reconstruct wall geometry and thickness evidence, not only its bounds.
6. Preserve typed doors, windows, openings, columns, stairs, lifts, ramps and penetrations.
7. Retain closed-room identity, name, area, type and level whenever detected.
8. Distinguish evidenced shafts/wet cores from proposed mechanical locations.
9. Deduplicate only proven duplicate copies; preserve uncertain geometry.
10. Prohibit deletion or mutation of critical/important architecture.
11. Generate on a separate work/output file; keep the upload immutable.
12. Use reversible transactions and restore/remove output on failure.
13. Diff identity, geometry, length, area, coordinates, layer, block and text.
14. Preserve topology, connectivity and critical typed-object counts.
15. Verify architectural visibility independently on every applicable sheet.
16. Pass graphical QA for clipping, text, collision, scale, color and title zones.
17. Pass positive and destructive rotation, frame, xref, layer and typical-floor regressions.
18. Reopen and re-evaluate the exact issued file; seal private real-project runs separately.

Weights are geometry/topology 30, frame/level 20, layers/blocks/text 15,
underlay visibility 15, unauthorized change/collision 10 and exact reopen/diff
10. Only `100/100` is `PASS`.

Mechanical references are forbidden during generation. Comparison begins only
after the generated artifact and its hash are sealed.
