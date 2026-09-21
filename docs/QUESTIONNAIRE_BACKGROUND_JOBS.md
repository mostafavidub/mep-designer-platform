# Owner-bound questionnaire background jobs

Architecture reconstruction can legitimately exceed an interactive proxy
request budget. The panel therefore starts one deterministic background job
per customer, file content, discipline and occupancy, then polls its state.

Both start and status endpoints require the internal panel token and the
customer's signed session. Job metadata stores the internal customer id and a
different customer receives `404`, preventing disclosure. Inputs and results
remain on the Staging data volume. Repeated starts reuse the same running or
completed job instead of multiplying CPU work.

The customer upload is stored in panel object storage before the job starts.
Closing the page does not discard it; the saved project can resume polling
without another upload. Production is outside this rollout.
