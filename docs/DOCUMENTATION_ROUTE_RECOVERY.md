# Documentation route evidence recovery

Change request: SWCIS-2026-0048. SWCIS 3.0.3.

## Failure and cause

Staging deployment eaab8ad returned HTTP 422 at documentation_enhancement_gate on 2026-09-08 at 20:35:38 UTC. Its log independently confirms architecture preservation PASS with zero missing entities. The failing stage's nested evidence was omitted by the web diagnostic summary.

The actual-source local compositor report has no pipeline/engineering payload. The documentation adapter reads those absent keys and sees zero routes. Even when supplied, production routes use plan_id, while the riser adapter expects level/floor. This reproduces zero-branch INPUT_REQUIRED for WATER, SANITARY_VENT, HEATING and GAS. It is not a missing questionnaire answer.

## Repair and scope

The existing producer now retains documentation_inputs containing actual route/equipment evidence and architecture plan-to-level mapping, excluding heavy source text/entity caches. The adapter resolves absent route levels only from one unambiguous authoritative plan mapping and retains route identity. It neither invents routes nor changes geometry, sizing, pressure, scope or release thresholds. Unmapped riser routes now remain explicit reconciliation failures instead of disappearing from expected-branch counts. Legacy explicit level/floor input is supported.

Server diagnostics preserve bounded status/errors/missing-inputs for the failed documentation stage, including riser and detail validation, without logging the documentation package or source geometry.

The existing reference-parity module was unclassified by SWCIS. SWCIS 3.0.3 adds it to detail/riser ownership and drawing-output impact classification; release rules are unchanged.

## Evidence and limits

89 focused documentation, negative-evidence, error-surface and governance tests PASS. On the actual uploaded source, replaying documentation against the generated compositor artifact changes INPUT_REQUIRED to PASS: WATER 7, GAS 3, HEATING 12, SANITARY_VENT 10 actual plan branches; 17/17 materialized details pass exact DXF reopen. These are local reproduction counts, not a read of the staging project database.

The first canonical full-pipeline run passed documentation, all v17 hardening gates, preservation after sanitization, exact final delivery and montage, then correctly rejected generated_dxf_integrity_gate: missing ODU plan entities and D-WS-01 materialization. Its sanitizer had removed 18,582 original modelspace entities and 20 empty generated layouts, which would also block Step 12. These failures were investigated rather than deployed.

Additional repairs restore existing declared content: plan-local ODU placements now receive actual outdoor blocks/callouts when no authoritative roof exists; the already-declared D-WS-01 is included in the materialized water-detail register. The composer imports selected architectural entities with their resources into an unreferenced source block in a new destination, then clones exact transformed copies onto issued boards. The original source is never edited, original remote modelspace is never put into issued modelspace, and blank per-sheet layouts are no longer generated. No sanitizer or gate is weakened. The final canonical rerun completed with status PASS / PRE_SUBMISSION, including generated DXF integrity, exact DXF health and Step12. The exact output contains 5,253 modelspace entities before and after isolation, zero removed entities and zero removed layouts. Architecture preservation passes both before and after final composition with zero missing entities; ezdxf reports zero audit errors.

Output SHA-256: 1dd68270293738f80ae7025d54a8bc3f79300eaef6314f5e2e7c57104bcf6d6f (1,199,031 bytes). This is internal test evidence, not a customer release. Direct engine invocation did not include the authenticated workflow's approved drawing manifest, so approved_manifest_qa and plan_board_population_qa are SKIPPED in this reproduction. Dedicated positive/negative manifest tests passed, but this does not substitute for live workflow approval and upload-to-download E2E.

89 focused tests PASS: 45 documentation/adapter/source-import/governance tests, 22 integrity/Step12/manifest tests and 22 existing hardening/board tests. Pytest is unavailable in the runtime; the latter existing plain test functions were invoked through unittest FunctionTestCase with isolated temporary Path fixtures. No test was skipped or rewritten to force PASS. No upload-to-download success, seven-project Golden acceptance, deployment or release acceptance is claimed here.

No customer drawings are checked into Git. The source SHA-256 is 08b2e3f2a16a90727e1ef44e8dbc96455a57a553a6f7ef6b2d0800dcadeb13ca. Reproduction uses the uploaded source and the previously restated project answers; exact current staging database answers were not accessible.

## Consumer closure

- cad_designer: preserves compact actual engineering evidence, constructs issued geometry in a new document, and draws already-planned outdoor equipment.
- detail_riser: consumes real routes and authoritative levels; no synthetic branches.
- qa: positive, missing-evidence and ambiguous/unmapped-plan negatives.
- ui_api: bounded server diagnostics; HTTP rejection remains fail-closed.
- manifest: approved sheet manifest unchanged; context is additive.
- migration: no database migration; regenerate design to acquire documentation evidence.
- versioning: automatic Git build identity; SWCIS patch 3.0.3 classifies adapter.
- docs/governance: this record, one change request, classification and tests.
- deployment: blocked while required product/release evidence is incomplete. Preserve ephemeral staging data before any future deployment. Production unchanged.

Rollback uses the previously deployed Git commit eaab8ad; no gate bypass or runtime copy.

## 10-step governance impact

1. not affected — project source contract unchanged.
2. not affected — locked capabilities unchanged.
3. not affected — Golden baseline unchanged; full real regression unavailable.
4. added — positive and destructive route-handoff, source immutability, block-resource and plan-local equipment tests.
5. verified — route IDs and source geometry retained; no engineering numeric edits.
6. changed — SWCIS documentation adapter classification.
7. verified — zero branches and unknown route levels remain blocking.
8. not affected — no release snapshot declared.
9. not affected — no merge/CI bypass.
10. changed — SWCIS-2026-0048 records this repair.

SWCIS impact validation and runtime-version guard PASS on this change. This is structural/change validation, not a claim that missing real seven-project release evidence is PASS.
