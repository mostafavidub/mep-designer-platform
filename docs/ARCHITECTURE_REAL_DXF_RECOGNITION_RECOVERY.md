# Architecture real-DXF recognition recovery

## Scope and immutable evidence

This diagnostic uses a private development source without committing its bytes,
name, or crops.  The governed identities are:

- ZIP SHA-256: `9558194ee53c09293c3b2fa49e2d94cdd4ecdee38162e94964ce4aa6df55a653`
- DXF SHA-256: `43c696a6e2703ce746d22b169b90108f0a6a44d3873e56e32f80124793fe1d70`
- Dependency engine SHA: `3da0e1dadf814277051007caa782973081307937`
- frozen canonical hash: `aee0d167ce8cc90c69d742ca909c544ad3a80f3c55ffc5ff677284478c3302b1`
- frozen validator-report hash: `05aefaff0762655745ac782c9848f665f7a652f47ba2ce2d00f7dc4dceec622b`

The replay was isolated and did not update either customer project record.

## Candidate inventory

| Physical Space | Frame | Area m2 | Geometry | Semantic | Topology | Coverage | Finding |
|---|---|---:|---|---|---|---:|---|
| PS-01E8C246831B2E4F | FRAME-1B3A64CDA62034FE | 0.3961 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9578 | accepted source segments coincide with reported gap |
| PS-19C780D56F3802FE | FRAME-9360E6D9B40B0E64 | 25.5348 | INPUT_REQUIRED | VERIFIED | INPUT_REQUIRED | 0.5586 | backyard/scope candidate; mixed admitted and excluded source evidence |
| PS-1BA12DAA5B1783F2 | FRAME-1B3A64CDA62034FE | 0.4313 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9966 | 9 mm numerical boundary mismatch beside accepted source line |
| PS-1DE125B858049D9B | FRAME-1B3A64CDA62034FE | 0.3449 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9924 | 18 mm numerical boundary mismatch beside accepted source lines |
| PS-1F939EAE61E6F73A | FRAME-9360E6D9B40B0E64 | 2.3761 | VERIFIED | VERIFIED | VERIFIED | 1.0000 | elevator; false dimension conflict fixed |
| PS-26D9AD7AC5C49BD8 | FRAME-1B3A64CDA62034FE | 0.8047 | VERIFIED | VERIFIED | VERIFIED | 1.0000 | verified closet |
| PS-320D2B73A6450192 | FRAME-1B3A64CDA62034FE | 0.8693 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.8067 | accepted source segments coincide with reported gaps |
| PS-4F9D74A6100447C9 | FRAME-9360E6D9B40B0E64 | 14.1777 | VERIFIED | INPUT_REQUIRED | VERIFIED | 1.0000 | bounded lightwell semantic review only |
| PS-7F4FFF6993FC4561 | FRAME-1B3A64CDA62034FE | 0.3450 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.7651 | accepted source segments lie within tolerance of gap |
| PS-8D2E752937EBA46A | FRAME-9360E6D9B40B0E64 | 0.6432 | VERIFIED | INPUT_REQUIRED | VERIFIED | 1.0000 | bounded semantic review only |
| PS-9424BBEE050132E4 | FRAME-1B3A64CDA62034FE | 0.3450 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9923 | accepted source segments lie within tolerance of gap |
| PS-9B7BC86F38A49D2D | FRAME-1B3A64CDA62034FE | 1.8600 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9211 | source-backed nested door motif is excluded; no aperture authority granted |
| PS-A1E5972161FE10AA | FRAME-1B3A64CDA62034FE | 0.0075 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 1.0000 | sliver candidate; separator role unresolved |
| PS-A96199E13045BD8B | FRAME-1B3A64CDA62034FE | 25.0885 | INPUT_REQUIRED | VERIFIED | INPUT_REQUIRED | 0.6136 | backyard/scope candidate; mixed admitted and excluded source evidence |
| PS-B9A4B5B46459232D | FRAME-1B3A64CDA62034FE | 2.3761 | VERIFIED | VERIFIED | VERIFIED | 1.0000 | elevator; false dimension conflict fixed |
| PS-D35D329B45E188BC | FRAME-1B3A64CDA62034FE | 0.6432 | VERIFIED | INPUT_REQUIRED | VERIFIED | 1.0000 | bounded semantic review only |
| PS-D9E6F76F7519A015 | FRAME-1B3A64CDA62034FE | 0.3450 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9923 | accepted source segments lie within tolerance of gap |
| PS-E02E763AAE77D0EA | FRAME-1B3A64CDA62034FE | 0.8082 | VERIFIED | VERIFIED | VERIFIED | 1.0000 | verified duct void relation |
| PS-F8357BC261AE654F | FRAME-1B3A64CDA62034FE | 0.4313 | INPUT_REQUIRED | INPUT_REQUIRED | INPUT_REQUIRED | 0.9966 | 9 mm numerical boundary mismatch beside accepted source lines |

## Root-cause classification

| Blocker family | Count before | Classification | Evidence and disposition |
|---|---:|---|---|
| ENGINEERING_DIMENSION_CONFLICT | 1 family / 2 rows | ENGINE_LIMITATION_OR_DEFECT | DIMTYPE 33 returned zero from `get_measurement()` although source `actual_measurement` and witness distance both equal 1.396687 m. Fixed using the source value only when the two independent source facts agree. |
| CANONICAL_TOPOLOGY_REQUIRED | 2 | ENGINE_LIMITATION_OR_DEFECT | 206 and 328 wall segments are admitted in the two governed frames, but envelope proof rejects all canonical cells through semantic-envelope heuristics. No source deficiency is asserted. |
| SEPARATOR_ROLE_REQUIRED | 38 review items | HUMAN_REVIEWABLE | Closed answer set classifies existing `SOURCE_BOUNDARY_SUPPORT`; review cannot create geometry. |
| SEPARATOR_INPUT_REQUIRED | 12 | ENGINE_LIMITATION_OR_DEFECT for the measured near-line cases; mixed/unclassified for exterior-scope candidates | Gap audit finds accepted source segments at 0–8 mm for the small candidates. The large backyard candidates also contain excluded obstacle evidence and require candidate-scope correction before source blame. |
| UNRESOLVED_SPACE | 15 | dependent blocker | Summary consequence of the separator/semantic findings, not an independent request for 15 new rooms. |
| ARCHITECTURAL_GEOMETRIC_COVERAGE_INCOMPLETE | 1 | dependent blocker | Aggregate consequence; it must not independently request source correction. |

No `GENUINE_CONFLICT` remains after the dimension extraction correction.  No
wall, room, portal, void, level, or access edge was synthesized.

## Dimension correction contract

For linear/aligned dimensions only, a near-zero library measurement may be
replaced by the source `actual_measurement` when both are non-zero and agree
with the two source witness points within the governed tolerance.  A mismatch
remains unresolved; it is never averaged or silently accepted.  The record
retains raw type, raw measurement, source measurement, witness distance, and
the selected measurement basis.

The unchanged source replay moves dimension reconciliation from `CONFLICT` to
`PASS`.  Physical-space count (19), stable IDs, wall count (257), and all
fail-closed separator/topology gates remain unchanged.

## Remaining bounded work

Before any customer review, the engine must correct canonical envelope/cell
selection and numerical boundary support so false candidates are not converted
into human questions.  After that correction, only surviving bounded semantic
or separator-role questions may be presented.  Mechanical release remains
blocked until independent validation passes.
