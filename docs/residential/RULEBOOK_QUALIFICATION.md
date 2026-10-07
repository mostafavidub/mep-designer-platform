# Architecture Rulebook Qualification Report

**Status:** `ARCHITECTURE_RULEBOOK_BLOCKED`

**Generator readiness:** `NOT_READY`

## Decision

All 32 M4 candidates were inspected individually and normalized. They are national mandatory candidates with eventual BLOCK behavior, but remain SOURCE_GAP and release-disabled because current edition/amendment status, exceptions, and cross-authority conflicts are not fully established. No new numeric value was introduced.

## Root causes

- source currency not established
- applicability model previously prose-only
- mandatory and release authority previously coupled
- source gaps represented as placeholder rules

## Source gaps

| Gap | Severity | Current evidence | Required action |
|---|---|---|---|
| ARCH-SG-001 — site inputs | HIGH | PROJECT_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-002 — urban/local planning rules | HIGH | RESOLVED_LOCAL_RULE_MODEL | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-003 — buildable envelope | HIGH | PROJECT_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-004 — access | HIGH | SOURCE_MISSING | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-005 — fire/egress | CRITICAL | SOURCE_MISSING | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-006 — elevator | HIGH | SOURCE_MISSING | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-007 — parking | HIGH | RESOLVED_LOCAL_RULE_MODEL | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-008 — unit entry | MEDIUM | HUMAN_EXPERT_REVIEW_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-009 — dining | MEDIUM | OWNER_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-010 — master bedroom | MEDIUM | OWNER_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-011 — laundry | MEDIUM | OWNER_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-012 — storage | MEDIUM | OWNER_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-013 — terrace/balcony | MEDIUM | HUMAN_EXPERT_REVIEW_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-014 — acoustics | MEDIUM | SOURCE_MISSING | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-015 — energy | HIGH | PROJECT_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-016 — windows/daylight | HIGH | HUMAN_EXPERT_REVIEW_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-017 — shafts | HIGH | PROJECT_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-018 — wet-core coordination | MEDIUM | RESOLVED_HEURISTIC | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-019 — security/protective requirements | MEDIUM | SOURCE_MISSING | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-020 — furniture fit | MEDIUM | HUMAN_EXPERT_REVIEW_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-021 — MEP coordination | HIGH | PROJECT_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-022 — structural coordination | HIGH | PROJECT_INPUT_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-023 — drawing conventions | MEDIUM | HUMAN_EXPERT_REVIEW_REQUIRED | Obtain the current authoritative document/parcel input and perform clause-level independent review. |
| ARCH-SG-024 — owner preference | MEDIUM | RESOLVED_HEURISTIC | Obtain the current authoritative document/parcel input and perform clause-level independent review. |

## Owner decisions

The 58 questions remain explicit owner choices with no defaults: 13 KEEP at program freeze and 45 DELAY until their applicable stage. None is silently derived from geometry, precedent, or AI.

## QA boundary

The original 104 generator scenarios remain planned and unexecuted. Thirty-two static qualification guards are executed by the targeted contract test. No Human Golden case exists yet; the eight-case matrix is only a collection plan.

## Impact

- Architecture Generator: no runtime activation.
- Validator and Canonical Architecture: unchanged.
- Questionnaire: additive disposition metadata only.
- MEP/Electrical/Structural: no consumer or authority change.
- UI/API/database: unchanged.
- Rollback: revert this stacked qualification commit.

## Source research note

The official public search confirmed current M19 transition notices, but did not yield a complete official current M4 edition/amendment register. That absence is recorded as a gap, not converted into authority. Private source bytes remain outside Git.
