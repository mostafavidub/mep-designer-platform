# ADR — Architecture Owner Program 2.0

## Status

Accepted for offline implementation only. Runtime activation, customer migration,
Generator use, merge and deployment require separate approval.

## Context

Owner Program 1.0 stores a useful spatial program, while the v1 Generation Input
stores unit types, site geometry and authority data separately. Neither contract
preserves provenance for each material value. Treating either payload as a complete
generation input could silently promote an owner preference, legacy value or stale
authority reference.

## Decision

Planha separates two contracts:

1. `OwnerProgramDraft` stores owner requirements and preferences, one canonical unit
   program and explicit per-field provenance. It may be `DRAFT_VALID` without site or
   local-rule data.
2. `ResolvedGenerationInput` references the exact draft hash and canonical unit-program
   hash, and binds immutable site, national-ruleset and local-profile identities,
   versions and source hashes. Missing authority fails closed; changed authority yields
   `STALE_BINDING`.

Draft validity and resolution readiness are separate gates. An incomplete migrated
unit program remains saveable as `DRAFT_VALID`, but resolution requires a complete
canonical unit program, verified field-level material provenance with compatible
authority, independently supplied current binding records, and evidence-backed geometry
feasibility. A caller-supplied `VERIFIED` flag is never sufficient by itself.

Resolved project/program identity is compared directly with the source draft. Stored
resolution status is compared with an independently recomputed result, and questionnaire
answers are bound to their content hash. Both public validators apply the additive JSON
contract and return structured fail-closed findings for malformed payloads.

Owner Program 1.0 remains unchanged. Its adapter preserves the complete source payload,
uses `UNKNOWN_LEGACY_SOURCE` rather than invented provenance, and reports absent unit
program evidence. The v1 Generation Input may supply the unit program only through the
explicit migration adapter.

## Alternatives rejected

- Destructively replacing v1: breaks existing readers and loses auditability.
- Copying unit-program data into every downstream contract: creates competing writable
  truths.
- Treating a structurally valid draft as generator-ready: confuses requirements capture
  with authority and geometric feasibility.
- Filling legacy provenance or local rules with defaults: fabricates engineering
  authority.

## Compatibility and migration

V2 is additive. V1 read/write behavior and the 58-question Persian questionnaire remain
unchanged. Migration is deterministic and non-destructive, records the legacy content
hash and original payload, and emits structured findings. No database migration occurs.

## Risks and controls

- Split-brain unit program: the v2 draft is canonical; resolved inputs store only its
  hash and adapters expose derived views.
- Stale authority: identity, version and hash are all compared.
- False approval: runtime remains disabled and structural validation does not prove
  feasibility, regulatory approval or professional review.
- Self-attested authority: current binding records and geometry evidence are required
  independently from the flags embedded in the candidate payload.

## Rollback

Revert the additive commit. Because no production consumer or stored data is migrated,
v1 continues unchanged.

## Future activation gates

Licensed Rulebook review, ARCH-P0.5 local-rule contract, consumer migration, full schema
and integration qualification, owner merge approval, and separate staging/production
authorization remain required.
