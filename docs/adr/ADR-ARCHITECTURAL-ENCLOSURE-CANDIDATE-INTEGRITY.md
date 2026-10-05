# Source-supported enclosure candidate integrity

Status: accepted design; local governed regression PASS under SWCIS-2026-0296. Exact committed replay and official CI are recorded in the task report and PR.

## Context

Removing symbolic object-internal lines correctly prevents false boundaries but
can expose an upstream wall-face reconstruction defect or a downstream candidate
selection gap. A building envelope or containing polygon is not a Physical Space
merely because a room label falls inside it. Restoring excluded graphics, choosing
polygons by area alone, or reducing boundary coverage would restore false authority.

## Decision

Correct paired wall-axis placement using signed normal separation from a common
face origin. Preserve independently admitted source faces for bounded enclosure
candidate generation. Endpoint projection may only use existing local tolerance;
it must retain source provenance and cannot invent material walls or openings.

Represent candidates and their containment/overlap relationships deterministically.
Paired occupied material is limited to the common occupied span of both source
faces; union-length axes do not manufacture material beyond that evidence. Empty
common spans retain the original source walls.

Record candidate role, source evidence and selection disposition separately from
Physical Space authority. Prefer independently source-supported regions according
to geometry and hierarchy evidence; semantic labels cannot supply missing walls.
Do not blindly select the smallest/largest polygon or use a project-specific area.

Keep hard excluded furniture, fixtures, columns, detail/reference geometry and
symbolic internal lines outside recovery and boundary evidence. Retain rejected
weak-candidate diagnostics with the actual failing support predicate. Boundary support keeps the existing distance envelope; nonzero uncovered lengths
now fail closed rather than accepting a residual gap up to that envelope. A wall
merely touching a boundary at its endpoint cannot hide an interior partition.
The independent validator rejects authoritative parent/nonphysical candidates
without duplicating candidate reconstruction.

## Consequences

Recognition and candidate identities may change when previously lost boundaries
are recovered. Review fingerprints and snapshots must be regenerated from the
new model and independently validated. Optional diagnostics retain the canonical
architecture schema identifier; no production lifecycle or mechanical migration
is introduced. Real source insufficiency remains INPUT_REQUIRED.

## Independent follow-up

A pre-existing development polygon is valid before serialization but contains a
near-zero-width floating-point interior ring. Six-decimal coordinate quantization
collapses that ring into repeated points, producing an invalid serialized hole.
This precision/serialization defect is independent of enclosure recall. It remains
fail-closed: invalid serialized candidates are retained as diagnostics, not Physical Spaces, and are not repaired opportunistically here. A separate fix must retain
ring diagnostics, validate serialized geometry, preserve real holes and justify
any below-precision topology normalization through bounded area/topology evidence;
generic buffer(0) repair is not acceptable.

## Validation

Required controls cover unequal/reversed/rotated wall faces, source-supported
fragmented enclosures, hard excluded symbols and furniture, real diagonal walls,
parent/child selection, invalid/nonphysical authority, deterministic repeated
models and existing Foundation/Preflight/Snapshot protections. The exact seven
private development sources and frozen human truth provide development regression,
not held-out qualification. Final results belong in CR0296 and the task report.

New candidate integrity also retains pre-filter motif context. Congruent adjacent
cell arrays with competing wall-face spacings cannot gain independent room authority
when material-face families are missing or conflicting; a generic wall layer is
insufficient to override that ambiguity. Material strips use
both recurring and local measured thickness families. These are bounded geometric
negative controls, not area thresholds or semantic label inference.

Source-face candidates also fail closed when occupied wall material contradicts
their interior, or the evidence distance bands leave no resolvable interior.
Boundary coverage cannot excuse residual unsupported lengths.

## Source-truth preservation qualification

Old VERIFIED output is a comparison baseline, never a positive truth inventory.
Every baseline region must retain all source/frame/provenance-linked comparison
relations, including splits, merges, disappearance and parent/child replacement.
Overlap and shared handles identify comparison candidates; neither proves truth.
An unchanged output remains SOURCE_AMBIGUOUS unless independent source evidence
establishes its enclosing material role. Human interpretation may classify existing
source evidence but cannot create missing material geometry or release authority.

A demonstrated numerical failure occurs when complementary source wall faces
form a real inner enclosure but nonidentical floating endpoint coordinates prevent
source polygonization. Canonical centerline cells may then have unsupported corner
residuals. Restoring their old aggregate coverage allowance is forbidden. Instead,
source topology reconciles transverse endpoints within one millionth of the existing
drawing tolerance. Each cluster must be a complete mutual neighborhood; parallel
faces, weak endpoints and transitive chains are rejected. The deterministic shared
endpoint is an existing source point. Movement, original coordinates and provenance
are diagnostic; no material Wall, Portal, Access or closure entity is generated.
Physical boundary validation still uses original unmodified source geometry.

This is numerical representation reconciliation, not an architectural drafting-gap
policy. Larger endpoint gaps remain unresolved. Positive tests cover translation,
rotation, reversed segments, input ordering and the full extraction/adapter/validator
path. Negative controls cover real gaps, parallel lines, weak/hard-excluded sources
and transitive drift. Existing material occupancy, residual coverage, hierarchy and
invalid serialization guards remain mandatory.

Below-precision ring quarantine is unchanged. A geometrically related invalid parent
is not proof that its repeated child is a real room. Precision repair requires an
independently adjudicated positive loss; ambiguous repeated arrays require bounded
human source interpretation first. No blanket polygon repair is authorized.


## Owner source review continuation (2026-10-04)

Six source-hash-bound local cards were reviewed by the owner: five adjoining
source groups (30 baseline regions) are stair/landing drawing subdivisions, not
independent enclosed Physical Spaces; the additional non-baseline compartment is
a real enclosed duct. Private source geometry and review images remain outside Git.
Human interpretation is comparison evidence only; no source-specific allow/deny
list is loaded into reconstruction. This supersedes the earlier ambiguity counts.

The existing array detector already identifies recurring source cells with an
unproven or competing material-face family. A legacy/canonical subdivision origin
must not bypass that negative evidence. Candidates wholly covered by those source
cells, within the existing numerical area residue, remain diagnostic regardless
of origin or merging/tiling. Store the witnessing source candidate IDs and outside
area. Do not buffer the array into neighboring rooms, infer a stair category,
remove an adjacent landing, or reject a surrounding container just by proximity.
Independent, unambiguous paired-wall families retain their existing protection.

This bounded correction is not a complete stair/landing classifier. Remaining
owner-confirmed landing positives block qualification even if the original 19-case
negative gate stays green. Track that historical gate separately from newly
adjudicated false positives. Subprecision ring quarantine stays unchanged.
A rotated un-noded crossing grid also exposes an upstream source-topology noding
limitation; the cross-origin metamorphic test uses explicitly noded source rails
to isolate this rule. No general topology repair is introduced by this change.
