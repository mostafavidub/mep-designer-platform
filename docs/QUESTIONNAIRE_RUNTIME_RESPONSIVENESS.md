# Questionnaire runtime responsiveness

## Incident

Architecture questionnaire analysis performed CPU-heavy DXF reconstruction on
the FastAPI asyncio event loop.  A single real upload could therefore prevent
health, customer-session and panel API requests from being served until the
reconstruction completed.  The panel surfaced the downstream session timeout
as a misleading file-storage failure.

## Runtime contract

The canonical questionnaire endpoint remains synchronous for its caller and
returns the same questionnaire payload.  Blocking DXF reconstruction and
questionnaire inference execute through `asyncio.to_thread`; health, session
and status requests remain schedulable on the web event loop while analysis is
running.  No engineering inference, provenance, input or output semantics are
changed.

## Verification

- The endpoint contract and invalid-ZIP destructive test remain unchanged.
- A focused regression asserts that blocking analysis is offloaded.
- The complete repository regression suite must pass before Staging rollout.
- After rollout, `/system-health` and the panel session endpoint must respond
  while a real architecture file is being analysed.

## Rollout and rollback

Deploy only to the Staging web service from the approved Git commit. Production
is untouched. Roll back by redeploying the prior approved Staging commit; do
not restore a version-named runtime copy.
