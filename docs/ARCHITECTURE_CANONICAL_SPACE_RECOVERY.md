# Architecture canonical-space recovery

## Private-safe scope

- dependency: PR #326 at `151ac57af5c22e69f0e08c8de6199aad1b51010c`
- DXF SHA-256: `43c696a6e2703ce746d22b169b90108f0a6a44d3873e56e32f80124793fe1d70`
- ZIP SHA-256: `9558194ee53c09293c3b2fa49e2d94cdd4ecdee38162e94964ce4aa6df55a653`
- private bytes, filenames and crops are not committed

## Envelope rejection cascade

### Roof — `FRAME-9360E6D9B40B0E64`

The frame admits 206 architectural segments and reconstructs 105 canonical
walls. Polygonization produces 42 cycles. The dominant cycle is valid, has
area 217.797453 m2, 52 boundary walls, 45 internal partitions, 58.7566 m of
internal-wall support, 65.38% double-face boundary support and 65.38% known
boundary thickness. A separate 15.621632 m2 lightwell cycle is geometrically
contained by it; the 25.501811 m2 backyard cycle is disjoint.

The former rejection occurred because all labels covered by the dominant
cycle were flattened into one semantic set (`elevator`, `lightwell`). The
semantic conflict then vetoed the independently source-supported shell.

The corrected rule permits a shell only when exactly one candidate has every
exterior interval covered by either an occupied source-backed canonical-wall
material interval or an explicitly governed non-material continuity closure,
source-backed internal partition topology, and double-face plus known-thickness support distributed
over at least two non-parallel boundary directions. A single strong fragment
cannot authorize an otherwise weak perimeter. No percentage or area-dominance
threshold is used. Closure evidence remains separately identified and never
becomes wall material or geometry authority. Site/semi-exterior semantics disqualify the candidate, and
any second qualifying shell leaves the frame ambiguous. Semantics grant no
geometry authority.

Source polygon rings and independently classified source void candidates are
then composed under a separate fail-closed contract. Equivalent rings are
deduplicated with both provenances retained; invalid, exterior-crossing,
overlapping or touching holes reject the composition. The combined polygon
must itself be valid, non-empty and positive-area. No snap, buffer or
`make_valid` repair changes the authoritative geometry.

Result under the strengthened contract: the candidate remains
`INPUT_REQUIRED`. All 52 boundary walls are source-backed; 34 have DOUBLE_FACE
and known-thickness evidence distributed over both orthogonal directions, and
21 governed non-material closures remain explicitly separate. Six critical
exterior intervals are still unsupported by either material or governed
continuity. The 21 source rings and one classified void also conflict rather
than forming a valid deduplicated hole set. Correct fail-closed behavior
therefore restores the Roof legacy candidate path; no shell authority is
granted merely to preserve the earlier recovery result.

### Typical — `FRAME-1B3A64CDA62034FE`

The frame admits 328 segments and reconstructs 152 canonical walls.
Polygonization produces 55 cycles. The largest cycle is a 25.080797 m2
backyard with 12 boundary walls, zero internal partitions and zero internal
wall length. No candidate satisfies the geometric-shell proof. The frame
therefore remains `CANONICAL_BUILDING_ENVELOPE_UNPROVEN` and uses the legacy
fail-closed candidate path. The former “two interior semantic categories”
heuristic is not used to promote any geometry.

## Boundary mismatch audit

The unresolved intervals form four evidence classes:

| Group | Evidence | Classification | Action |
|---|---|---|---|
| 9–18 mm small-cell intervals | accepted source handles lie about 8 mm from candidate boundaries | `REPRESENTATION_ERROR` suspected, not yet proven to common lineage | remain blocked; no metric-tolerance patch |
| 0–0.744 m small candidates | several accepted source segments intersect or lie within 0–8 mm | mixed `REPRESENTATION_ERROR` / `WRONG_CANDIDATE` | separate source-lineage task |
| 11.37–13.02 m backyard intervals | admitted walls mixed with obstacle/reference exclusions | `WRONG_CANDIDATE` / scope | Roof corrected by proven envelope; Typical remains diagnostic and blocked |
| nested `xth` vicinity | admitted wall lines plus excluded nested primitives | `WRONG_SOURCE_ROLE` until aperture evidence is independently proven | no Portal or boundary closure |

No `SOURCE_GEOMETRY_GAP` is declared merely from a distance measurement. The
required source-handle/transform lineage is not yet carried far enough through
the candidate-boundary proof to reconcile these intervals safely.

## Candidate integrity taxonomy

| Physical Space | Evidence-backed taxonomy after replay |
|---|---|
| `PS-19C780D56F3802FE` | `SITE_EXTERIOR`; removed from Physical Space authority by the Roof envelope |
| `PS-A96199E13045BD8B` | `SITE_EXTERIOR`, but retained as unresolved legacy candidate because Typical envelope remains unproven |
| `PS-1F939EAE61E6F73A`, `PS-B9A4B5B46459232D` | `VERTICAL_SERVICE_SPACE` (elevator) |
| `PS-E02E763AAE77D0EA` | `VERTICAL_SERVICE_SPACE` (duct) |
| `PS-26D9AD7AC5C49BD8` | `INTERIOR_PHYSICAL_SPACE` (closet) |
| `PS-4F99B329F248800D` | `LIGHTWELL_OR_VOID`; geometry bounded, semantics still input-required |
| `PS-A1E5972161FE10AA` | `UNRESOLVED`; 0.0075 m2 alone is not grounds for deletion |
| `PS-01E8C246831B2E4F`, `PS-1BA12DAA5B1783F2`, `PS-1DE125B858049D9B`, `PS-320D2B73A6450192`, `PS-7F4FFF6993FC4561`, `PS-8D26DA7B20435557`, `PS-9424BBEE050132E4`, `PS-9B7BC86F38A49D2D`, `PS-D35D329B45E188BC`, `PS-D9E6F76F7519A015`, `PS-F8357BC261AE654F` | `UNRESOLVED`; insufficient evidence for a narrower taxonomy |

Candidate Cell, Physical Space, Void and Exterior Region remain distinct. No
area-only filter was added.

## Opening diagnostics

Each governed frame reports 64 raw arcs and 16 radius-plausible swing arcs,
but produces zero pre-envelope opening evidence items and zero Portals. The
inventory lacks source handles for these arcs. Source inspection shows NEWS
reference arcs contaminate the radius-only count and nested `xth` assemblies
are excluded from boundary authority. This PR deliberately makes no opening
change: material aperture, host wall and two-side binding remain mandatory.

## Authority diff

The earlier provisional promotion of the Roof shell is withdrawn by the
strengthened proof. `PS-19C780D56F3802FE` therefore remains an
`INPUT_REQUIRED` legacy Physical Space candidate instead of being removed as a
site diagnostic. The result returns from 18 to 19 Physical Spaces, while the 4
verified spaces and all 257 wall IDs remain unchanged. No geometry, semantic
or topology authority is promoted. Mechanical release remains blocked.

## Deferred independent defects

1. resolve or explicitly govern the six Roof exterior intervals and the
   overlapping classified-void/source-ring topology;
2. carry exact source primitive/transform lineage into boundary-interval proof;
3. qualify Typical envelope or prove source insufficiency;
4. classify the sliver through wall-material topology rather than area;
5. filter reference arcs and preserve nested opening provenance without
   granting Portal authority;
6. regenerate/group human review only after those deterministic fixes.
