# Owner-bound questionnaire background jobs

Architecture reconstruction can legitimately exceed an interactive proxy
request budget. The panel therefore starts one deterministic background job
per customer, file content, discipline and occupancy, then polls its state.

Both start and status endpoints require the internal panel token and the
customer's signed session. Job metadata stores the internal customer id and a
different customer receives `404`, preventing disclosure. Inputs and results
remain on the Staging data volume. Repeated starts reuse the same running or
completed job instead of multiplying CPU work.

`POST /internal/panel/questionnaire/start` is the single canonical start route.
It returns `202` while processing and a stable `ready` or `failed` state after
completion. The panel polls `GET /internal/panel/questionnaire/{job_id}` only
while the state is `processing`. Invalid input and authorization/not-found
responses are terminal. Infrastructure-style analysis failures use at most
three attempts with backoff; exhaustion becomes a stable, customer-safe failed
state and must never be presented as ongoing analysis.

The customer upload is stored in panel object storage before the job starts.
Closing the page does not discard it; the saved project can resume polling
without another upload. Production is outside this change. Staging deployment
also requires explicit owner approval after the branch and tests are ready.
