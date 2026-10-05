# Architectural Text Evidence and Semantic Authority

Status: implemented for qualification under SWCIS-2026-0301.

## Problem

Planha previously extracted `TEXT`, `MTEXT`, `ATTRIB`, titles and room labels in
several paths. Those projections did not consistently preserve block-instance
identity, and a repeated `ATTDEF` could be confused with an instance value.
Title metadata and room semantics could also share unbounded lexical paths.

## Decision

Canonical Architecture 3.1 contains one durable exact-text evidence contract.
Every occurrence retains source SHA, entity handle, INSERT instance path, nested
block path, transform and position fingerprints. `ATTRIB` values are occurrences;
`ATTDEF` values are templates unless separately proven constant/default semantics
are introduced and tested.

Text is semantic or document evidence. It cannot grant material geometry, wall,
separator, void, aperture, Portal, Access, routing-obstacle, engineering scale or
north authority. Title/document roles bind to a frame. Space labels bind to an
already reconstructed Physical Space through exact containment; nearest-centroid
association is not authoritative. Compatible labels in one space form functional
composition and never create extra Physical Spaces.

Exact CAD text precedes OCR or Vision. Visual text remains a low-authority hint.
Human review interprets an existing text fact and is bound to source SHA, frame,
entity/INSERT identity, position/provenance/host fingerprints and question scope.
Review cannot create or alter geometry. Changed bindings are stale.

The independent validator reads the evidence and provenance itself. Producer
success flags do not establish authority. Extraction, role, host, semantics and
title-block accuracy are reported separately against independently curated truth;
there is no combined accuracy score.

## Compatibility and migration

3.1 is an additive representation with stronger authority semantics. A 3.0
artifact is not silently accepted as 3.1. Text-, title-, level- or semantic-based
claims require deterministic regeneration or bounded revalidation. Independent
3.0 geometry and separator evidence remain reusable and are not invalidated merely
because text evidence changed. Existing snapshots whose release-critical claims
depend on affected semantics are stale; no production artifact is rewritten.

Future Certified DXF, IFC and AutoCAD inputs may provide stronger structured text
roles through the same evidence dimensions. This decision adds no such adapter.

## Rejected alternatives

- treating layer names, room words, scale strings or `NORTH` text as engineering truth;
- treating `ATTDEF` as a repeated instance value;
- nearest-label hosting;
- a second title or Semantic Scout truth system;
- OCR/Vision promotion over exact CAD evidence;
- broad invalidation of geometry and separator claims during 3.0 to 3.1 revalidation.
