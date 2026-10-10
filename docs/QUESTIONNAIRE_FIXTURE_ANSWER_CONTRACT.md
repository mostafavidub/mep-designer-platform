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

