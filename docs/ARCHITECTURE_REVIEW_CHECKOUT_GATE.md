# Architecture Review Checkout Gate

## Contract delta

Architectural ambiguity is one server-side invariant shared by every design
entry point. A project requires review when its stored architecture review is
not `CONFIRMED`, or when the architecture model is `INPUT_REQUIRED` for plan
frame, room-boundary or shaft-boundary geometry.

Payment may complete while review is pending, but no design Revision or Job is
created. Paid retry has the same behavior and never charges again. The queue
consumer repeats the invariant immediately before claiming a design Job; a
legacy or future direct Job insert is stopped with
`ARCHITECTURE_REVIEW_REQUIRED` and the project returns to
`architecture_review`.

After the customer confirms every required space, shaft and level frame, the
existing reviewed model becomes the authoritative architecture input and the
normal design flow may enqueue exactly one Job.

## Migration and rollout

No schema or data migration is required. Existing analysis and audit records
remain authoritative. On rollout, projects whose stored review is incomplete
are moved to `architecture_review` the next time payment, retry or queue claim
is attempted. Previously generated artifacts are not rewritten or represented
as reviewed.

Deploy the protected Staging commit, verify an ambiguous paid project is held
without a Job, complete its review, and verify only then that design can start.
Production remains unchanged without explicit owner approval.

## Rollback

Redeploy the preceding approved Git commit. No database rollback is needed.
Paid markers, ledger rows, architectural analysis and review audit history are
not deleted or altered by rollback.

## Evidence

- Positive: a project with no architectural ambiguity retains the existing
  atomic payment-to-single-Job behavior.
- Negative: `REVIEW_REQUIRED` blocks both first payment enqueue and paid retry.
- Defense in depth: the queue consumer refuses any directly inserted design
  Job whose architecture review remains incomplete.
- Engineering scope: calculations and CAD materialization are unchanged; this
  change prevents them from running against unconfirmed geometry.
