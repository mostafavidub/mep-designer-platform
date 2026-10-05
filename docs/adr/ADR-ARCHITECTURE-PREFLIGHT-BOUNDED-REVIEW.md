# ADR: Bounded Architecture Review and Independent Qualification

## Status

Accepted for the experimental Canonical Architecture v2 foundation.

## Context

Raw and structured architecture inputs can contain bounded semantic ambiguities as well as missing engineering geometry, invalid topology, or internal contract defects. Treating every validator issue as a human question would invite fabricated geometry, duplicate questions, review loops, and accidental release-authority promotion.

## Decision

Human review is a bounded source-interpretation mechanism, not a geometry-authoring mechanism. The Architecture Preflight Review Engine classifies issue reviewability and impact, groups common root causes, generates a deterministic minimal question set, validates stale-safe decisions, and applies an allowlisted interpretation overlay. Engineering status and human review status remain separate.

Only the logically independent Architecture Validator may qualify the reviewed candidate. Snapshot creation requires its current `PASS` report. Missing material evidence, cross-level topology, invalid canonical references, contradictory authority, and unresolved source identity cannot be repaired by review. Unknown is a safe answer and grants no authority.

## Consequences

- Critical unresolved topology cannot be hidden to improve automation metrics.
- Review can classify existing spaces, apertures, motifs, and void boundaries but cannot create Walls, apertures, Portals, Voids, coordinates, or Access edges.
- Decisions are untrusted, fingerprint-bound, idempotent, and automatically stale when material identity changes.
- Repeated identical decisions that do not clear a blocker are not asked again.
- Harmless diagnostics remain visible without blocking engineering.
- UI, persistence, and package integration can consume stable plans and registries later without embedding engineering logic.
- Existing production paths and `MEP-ARCH-RECOG-001` remain unchanged and fail closed.
