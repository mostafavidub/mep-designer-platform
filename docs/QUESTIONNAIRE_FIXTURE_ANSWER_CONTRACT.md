# Mechanical fixture questionnaire answer contract

The `fixture_schedule` checkpoint is a fail-closed evidence gate. It is shown
when the architecture analysis identifies a wet level but cannot establish a
reliable fixture schedule from the source drawing.

## Presentation and acceptance

The project page and `/projects/{id}/flow` use the same presentation adapter.
The checkpoint is a Persian text input with a quantified example; it does not
offer generic confirmations or a global “no fixtures” choice. A valid answer
must contain an explicit quantity and a recognized fixture category. Rejected
answers return a structured `422` response from the JSON endpoint and remain on
the current question. The legacy HTML endpoint applies the same validation and
redirects back with the persisted error message.

Successful JSON responses explicitly carry `answer_persisted=true`. An exact
retry for an already-persisted question is an idempotent success. A malformed or
different stale submission returns `409`. Persistence verification failure
returns `500`; the browser only retries network/server failures and never
reports success without the persisted-success signal.

## Authority boundary

This contract does not derive fixture quantities, create fixtures, change
architectural level identity, or suppress roof drainage scope. The existing
global fixture schedule cannot safely express owner-confirmed zero fixtures for
one particular level, so an unscoped zero answer remains rejected. A future
level-scoped owner-confirmation contract would require separate engineering
review and contradiction handling.

The observed roof evidence conflict—residential room labels associated with a
roof while `roof_scope_reliable=false`—is not corrected here. Without the
original matching persisted evidence, changing frame/level authority would be
unsafe. The questionnaire therefore remains fail-closed and the architectural
level-assignment concern remains an independent investigation.

## Known level-scope limitation

The current predicate considers `سینک ۰` quantified because it contains both a
recognized fixture name and a number. A single global `fixture_schedule` answer
also resolves every `wet_level_without_detected_fixture` diagnostic associated
with that project. Consequently, a quantified but unscoped answer can overstate
resolution when multiple wet levels are unresolved. This bug-fix does not alter
that mechanical authority contract: the UI no longer advertises a zero shortcut,
but a future level-scoped schedule must bind quantities (including explicit
zero) to stable level identities and reject contradictions before it can grant
fixture-evidence resolution.

## Replay integrity

`mechanical_shaft_route` carries an approval object with its original raw answer,
source and `recorded_at`. Normalizing a new explicit answer intentionally creates
a new timestamp, so replay comparison must not compare a newly generated
approval object with the persisted one. Exact replay is now checked against the
persisted canonical strategy and original raw approval evidence. It is
idempotent without rewriting the approval; changed raw evidence or strategy is a
stale submission.

