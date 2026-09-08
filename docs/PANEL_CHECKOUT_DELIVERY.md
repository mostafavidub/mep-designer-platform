# Panel checkout and wallet — candidate, not released

Change: SWCIS-2026-panel-checkout. Governance: SWCIS 3.1.0.

## Contract delta

Prepare no longer queues a job. Only authoritative checkout queues after payment.
Public handoff stores a hashed, expiring token bound on claim to one panel account.
Phone-only login remains by explicit user instruction; phone ownership is NOT verified.
Customer, admin and legacy admin-data readers use the same server Wallet records.
Admin adjustments require the existing admin cookie at the Sites proxy, same-origin
requests, the private bridge credential, a positive integer amount, a reason and an
idempotency key. Negative resulting balances are rejected. Ledger entries are immutable.
The browser is not a source of financial truth and cannot supply the price.

`PANEL_DEMO_PAYMENTS=1` explicitly enables simulated bank checkout and simulated
wallet top-up as requested by the owner. Default is disabled. Simulation is labelled
in both interfaces/transactions and does not claim a real bank charge. Simulated
project payment does not debit the wallet. All queue and payment changes commit
atomically. Simulated top-ups are distinguishable in the activity history. Reconcile
test credits before enabling real payments; do not silently promote them to bank funds.

## Migration / rollout

Migration ID: panel-checkout-additive. From: legacy panel bridge. To: shared checkout.
Additive SQLAlchemy tables: panel_handoffs, panel_checkouts, panel_wallet_ledger,
panel_customer_profiles, panel_account_activity. Existing Wallet rows are retained.
No customer source drawing or credential is deleted. No D1 table is altered.
Consumer inventory: public assistant JS, panel prepare/upload proxies, customer
session/checkout proxy, admin accounts and legacy admin-data proxy, user/admin UI.
Deploy backend reader/routes first, then panel writers, then explicitly enable demo
payments. During the maintenance window verify row counts, foreign-key ownership,
balance deltas, one ledger/job per paid project, and idempotent replay. Historical
browser/D1 balances are not imported as real money without an approved reconciliation.
Existing legacy data remains stored; its account mapping/migration requires review.
Deprecation: retain legacy records through reconciliation; no deletion scheduled.
Rollback: disable new writes, retain additive tables and ledger, deploy an approved
Git revision with compatible readers. Do not replay paid jobs or roll back debits by
restoring an old DB. Any compensation needs a new audited adjustment.

## Impact closure

- ui_api: changed handoff, quote, checkout, admin wallet operations.
- qa: positive/negative transactional tests added; CAD release gates unchanged.
- manifest: generation uses existing proposal approval; no output manifest semantics changed.
- docs: contract, simulation, compatibility and rollout documented here.
- versioning: 3.1.0 records explicit sole-owner release authorization; engineering gates unchanged.
- migration: additive tables and legacy account reconciliation described above.
- governance: same change request; owner explicitly replaces independent human review, not automated checks.
- deployment: NOT released; protected PR, release checks and browser E2E remain required.

## Evidence and remaining gates

Tests in tests/test_panel_checkout.py exercise real SQLite HTTP flows: shared admin
and customer balances, retry deduplication, concurrent debits, insufficient funds,
rollback on queue failure, cross-account rejection, demo on/off and no-wallet demo checkout.
Other focused tests cover questionnaire, commercial flow, resumable upload and delivery.
Panel TypeScript/build and frontend tests are run in the sibling admin-app checkout.
This document is NOT evidence of a completed browser checkout/download or full golden
release run. Owner authorization was received on 2026-09-08. Full backend pytest:
581 passed (48.13 seconds); frontend tests, TypeScript and build passed. Browser
checkout/download and live deployment verification remain outstanding.

## 10-step governance impact

1. verified — existing project answers retained on handoff.
2. not affected — locked capabilities unchanged.
3. not affected — golden baseline unchanged; full run not claimed.
4. added — wallet and handoff positive/negative tests.
5. not affected — CAD semantic/numeric baselines unchanged.
6. changed — impact closure recorded in the change request.
7. verified — existing design gates not bypassed; release still blocked until checks pass.
8. not affected — no release snapshot published.
9. changed — owner approval replaces independent review; required CI, PR and no-force/no-delete protection remain.
10. changed — documented contract delta and additive migration.
