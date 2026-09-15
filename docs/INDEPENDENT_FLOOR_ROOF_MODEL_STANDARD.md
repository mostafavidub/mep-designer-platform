# Independent Floor and Roof Model Standard

**Status:** LOCKED  
**Rule:** `MEP-LEVEL-MODEL-001`

The sealed architectural DXF is the only source for floor and roof geometry.
Mechanical references are prohibited during generation. Each confirmed floor,
explicit typical-floor group, and roof owns one deterministic model identity,
one source frame, reversible local coordinates, and every entity inside that
frame exactly once.

Typical floors must list every represented level explicitly. Reuse is forbidden
unless the source drawing itself identifies the view as typical. A roof model
may exist only when a confirmed architectural roof base exists; slope and
drainage views may supplement that model but may not replace or fabricate it.

Vertical shafts are reconciled through source-bound normalized coordinates.
Unresolved units, level identity/order, overlapping ownership, unapproved
duplicate geometry, missing drawable geometry, or an unsupported roof blocks
Submission Ready output. The following eighteen controls must all pass:

1. immutable source identity;
2. calibrated units;
3. confirmed frame inventory;
4. drawing-type classification;
5. unique plan identity;
6. normalized level identity;
7. vertical level order;
8. unique entity ownership;
9. reversible local/source transform;
10. independent drawable geometry;
11. room-to-level binding;
12. shaft-to-level binding;
13. equipment-to-level binding;
14. explicit typical-floor evidence;
15. source-only roof evidence;
16. vertical-core graph;
17. zero cross-level geometry;
18. deterministic model fingerprint.

The final DXF is independently reopened. Every source-backed mechanical plan
must retain its level-model and level-instance identity through plans, routes,
risers, calculations, schedules and exact-file QA. A result below 18/18 and
100/100 is not Submission Ready.
