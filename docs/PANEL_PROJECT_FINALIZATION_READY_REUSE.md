# Panel project finalization after questionnaire READY

## Symptom and evidence

On 2026-10-07 questionnaire job `d6b7fbc72ebbac269bd36a723db30a4d`
reached `ready`, proving the uploaded architecture source was analyzable. The
subsequent `POST /internal/panel/projects` remained open for about 113 seconds
and returned 500. Railway capacity was not exhausted. The request path itself
called `analyze_project_job()` synchronously, creating a second analysis path.

The exact first exception is not present in the historical runtime log. The
persisted project association and `last_error` require read-only Staging data
inspection before they can be attributed to project 45; timing alone is not
identity evidence.

## Canonical state machine

The only accepted flow is:

`stored source -> questionnaire job -> durable READY authority -> finalization`

The private authority artifact binds:

- owner identity;
- source SHA-256 and stored source path;
- discipline and occupancy;
- questionnaire version and result identity;
- canonical analysis and its deterministic SHA-256.

Finalization resolves this server artifact by `analysis_job_id`. Browser copies
of `analysis` remain resume/display data and never become engineering authority.
The trusted source already stored by the questionnaire job is copied into the
engine project; the browser does not upload it again.

## Failure and replay semantics

- missing, non-ready, wrong-owner or malformed job identity fails closed;
- source, discipline, occupancy, result or analysis hash mismatch fails closed;
- a legacy READY job without the new private authority artifact requires
  reanalysis and is never reinterpreted;
- a completed finalization returns the same project;
- an in-progress finalization returns 202;
- an existing failed finalization returns 409 and cannot masquerade as success;
- drawing-set proposal creation remains at the existing quote/payment boundary,
  outside project creation.

Every rejected or failed finalization logs a phase, tracking ID, bounded source
hash prefix, project/job identities, elapsed time and exception class. Customer
responses contain only safe Persian text plus the tracking ID.

## Site request control

The Site transports only `analysisJobId` during finalization. Draft imports use
one in-flight request, merge updates by project ID, and skip an identical
successfully persisted fingerprint. The latest material state is preserved;
response hydration cannot multiply identical imports.

## Compatibility and rollout

No database schema changes. The backend and Site source are a coordinated
Staging candidate and must not be rolled out independently. No Staging or
Production deployment is authorized by this change request. Rollback restores
backend `ab3a6c970e4083d62325d9d568d5ec0644327a51` and Site version 31.

Architecture 3.1 authority, Q02, Portal/Wall semantics, Mechanical algorithms,
Commercial Measurement and pricing are unchanged.
