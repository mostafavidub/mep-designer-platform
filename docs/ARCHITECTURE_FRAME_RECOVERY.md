# Source-frame recovery and preservation diagnostics

Change request: SWCIS-2026-0047. Governance version: SWCIS 3.0.2.

## Defect

The web analyzer assigned all reconstructed geometry to the nearest accepted
floor title. This partition has no outer boundary. Remote drawing details and
construction geometry therefore inflated the authoritative floor bounds, which
the CAD composer correctly treated as the requested source region.

On the user-supplied source, the first-floor bounds expanded to approximately
217.88 by 28.808 drawing units; the ground-floor bounds expanded to approximately
2308.956 by 9496.842. Each explicit architectural print frame is 21 by 29.7.
These are source drawing units, not asserted physical building dimensions.

## Change

Reuse the existing print-frame detector. An accepted floor profile can use a
frame only when its title is physically inside exactly one frame of the same
source file/container and compatible architectural role. Assign rooms and
primitives inside that frame and preserve the complete frame envelope. Do not
promote support drawings to floors. Drawings without an unambiguous frame retain
their existing reconstruction behavior. No source or output entities are deleted
by this fix and no preservation tolerance or release gate is weakened.

The web rejection logger now retains bounded, geometry-free per-sheet summaries
from preservation QA. The CAD API also maps the initial preservation stage to
its existing failed_stage_qa field. Detailed source geometry remains excluded
from the web log.

## Verification and limits

Focused tests cover remote-geometry exclusion, foreign-file/support-frame
rejection, correct ownership despite a closer adjacent title, existing unframed
reconstruction, and geometry-free failure logging. Existing preservation tests
continue to verify destructive failures and rollback.

Real-source before/after execution reproduced the defect. Before repair,
preservation failed visibility on six sheets (M-101, M-111, M-131, M-141,
M-161, M-171), with three clipped records per sheet. After frame recovery,
preservation PASS: no failed sheets, no critical/important/all missing entities.
Both compositions passed their pipeline, engineering, DXF and semantic checks.

Source SHA-256 (identical in both runs):
`08b2e3f2a16a90727e1ef44e8dbc96455a57a553a6f7ef6b2d0800dcadeb13ca`.
Before output SHA-256:
`5e9b3a3dcd476ef55228ff0c3d222c09824d3baa56888e05a6c2f2c2b1ac9ecc`.
After output SHA-256:
`cf286bd2b9bed0fcfb7d973e121685e9e6113070216c483512c5c067c4832605`.

43 focused tests passed. A direct CAD invocation
without site-derived authoritative profiles passed preservation before the fix;
it is not equivalent to the original site job. The original stored answers and
analysis were not recovered; the local reproduction uses user-restated answers
and the installed web analyzer. This isolates the v15 compositor/v16 gate boundary;
it does not prove downstream v17/v19 acceptance. No seven-project release regression or complete
upload-to-download E2E success is claimed.

Deployment remains blocked until applicable release evidence passes. Do not
redeploy the existing ephemeral staging service before preserving its database
and user inputs. Production and PR 63 are unchanged.

## 10-step governance impact

1. changed: source-region provenance is additive; private customer data excluded.
2. verified: locked capabilities and preservation tolerances unchanged.
3. not affected: approved golden baseline unchanged; real regression pending.
4. added: positive and negative reconstruction/diagnostic regressions.
5. not affected: no accepted semantic/numeric baseline rewritten.
6. verified: affected-module closure recorded in the SWCIS request.
7. verified: non-PASS preservation continues to block delivery.
8. not affected: immutable release snapshots unchanged.
9. not affected: no merge, branch protection or deployment bypass.
10. added: one versioned change request for this repair.
