# Architectural Boundary Separator Evidence and Authority

Status: implemented and source-witness qualified under SWCIS-2026-0298.

## Problem

Geometric boundary coverage previously became VERIFIED geometry and material
Physical Space authority without independent physical-separator interpretation.
Layer context, accepted wall classification, recurring or local parallelism and
polygonization are not independent separator truth. Eight simple geometric
predicates damaged legitimate positive recall; double faces, junctions, wall
membership and layer context are not universal acceptance rules.

## Decision

Use the hybrid architecture: source evidence owns role; boundary intervals refer
to exact source witnesses; canonical evidence_registry carries durable provenance.
Geometric boundary support does not imply physical separator authority.
Geometry, separator, semantic, topology, human-review and release dimensions remain
separate. Canonical 3.0 is a breaking semantic contract: v2 qualification is not
inherited. The existing Preflight/review engine owns bounded interpretation.

RAW DXF may require source-role review. Explicit structured input may provide
source-bound profile assertions; no structured adapter is implemented here.
Human answers classify existing evidence, never create or repair geometry.
Region-level answers remain region-level interpretations and never classify all
surrounding lines. Interval reviews can be reused only for the same source fact.

The independent validator checks interval geometry, role provenance, source and
review binding without invoking producer acceptance. Current validation and review
manifest are required for snapshots. Unresolved critical separator evidence fails
closed; Q02 and other architecture blockers remain independent.

## Consequences and limits

Automatic qualification may decrease; report AUTO, REVIEW_RESOLVED, INPUT_REQUIRED
and NEGATIVE separately. Geometric candidates remain available for diagnostics.
Existing source-role decisions are not finer-grained interval evidence by fiat.
No certified profiles, IFC adapter, plugin, production package lifecycle, Mechanical
migration, synthetic walls, closures, Portals or Access are introduced.

The current implementation accepts direct source witnesses only. A derived axis or
existing nonmaterial closure without a supported direct interval remains unresolved;
its role is not silently converted into material fabric. This limitation prevents
qualification if applicable positive references lack sufficient role evidence.

See the canonical-v3 migration record for regeneration, stale decisions and rollback.

## Qualification checkpoint

Controlled development replay preserves every current candidate geometry across
seven sources. Original negative controls remain0/19; expanded reviewed negatives
become0/22. All nine historical answers remain at region scope. Three current
nonspaces are rejected only when their exact reviewed region fingerprint matches;
this cannot classify shared boundary lines or newly changed regions. Eight positive
references retain their geometry but still need separator-role interpretation.
Therefore status remains ARCHITECTURE_SEPARATOR_EVIDENCE_PARTIAL.

Full governed suite:1393 tests and14 subtests PASS on Python3.12.13. Official CI
is tracked against the published final SHA in the stacked PR; no merge or deploy.
