# Customer-panel questionnaire polling and resume

## Serving topology

`staging.planha.com` is the custom domain of the ChatGPT Sites project
`appgprj_6aa55c8daab481919bb0b0d2f7f6fd08`. Cloudflare routes the hostname to
the Sites Worker `site---6aa55c8daab481919bb0b0d2f7f6fd08`; it is not a
Railway custom domain.

The Site's server-side bridge targets
`https://web-app-staging-production.up.railway.app`, the Railway
`web-app-staging` service. Railway also exposes the same backend directly at
`https://stage.planha.com`. These are intentionally different layers:

- `staging.planha.com`: customer-panel UI and same-origin Site API routes;
- `stage.planha.com`: direct Railway backend domain;
- `web-app-staging-production.up.railway.app`: backend origin used by the Site
  bridge.

The customer panel source is maintained in the Site source repository on its
`main` branch. The backend remains in `mostafavidub/mep-designer-platform` on
the integration branch.

## Root cause

The panel accepted the initial `202 processing` response and retained the file
key in component state, but returned from the upload action before starting the
canonical status loop. The status loop ran only after a second click on
`ادامه تحلیل فایل ذخیره‌شده`. In addition, the durable customer-project
allowlist removed the file key and questionnaire job identity, so a refresh
could not reliably resume the same job.

The single lifecycle remains:

1. `POST /internal/panel/questionnaire/start` returns `202` and `job_id`.
2. The panel persists the owner-bound file key and `job_id`.
3. The panel polls `GET /internal/panel/questionnaire/{job_id}` at bounded
   cadence through its same-origin bridge.
4. `processing` remains an informational state; `ready` advances to the next
   step and `failed` displays the backend-safe error.
5. Refresh/reopen restores the same job identity. A legacy draft without a job
   identity may call start once; backend content-addressed deduplication returns
   the existing job.

Stored-file recovery verifies the signed customer identity through the
lightweight `POST /internal/panel/customer/identity` contract. It deliberately
does not load the full account/project snapshot, so architecture CPU load
cannot turn a resume ownership check into a polling timeout.

No second analysis lifecycle, engineering rule, architecture authority, or
questionnaire producer is introduced.

## Integrity and rollback

The backend accepts a persisted file key only under the authenticated
customer's `projects/CUST-<id>/` prefix. Questionnaire job IDs must be the
canonical 32-character lowercase UUID hex identities. Checkout and resume
states are closed enumerations.
Cross-owner file references fail with `403`.

Rollback is the coordinated redeployment of the prior Site version and prior
approved integration commit. Existing uploaded objects and questionnaire job
workspaces are retained, so rollback does not delete customer files or jobs.

## Verification

- Site state-machine tests cover `POST 202 -> GET 202 -> GET 200 ready`.
- Site refresh/resume tests begin with the persisted job and prove no duplicate
  start or upload.
- Backend tests prove the job identity and file key survive a customer-state
  round trip and reject cross-owner file keys.
- Existing real DXF, real ZIP, deduplication, terminal-state, and owner-isolation
  tests remain mandatory.

The one observed `499` on `customer/state` is classified as a client-closed
request unless correlated evidence shows it altered questionnaire state. It is
not part of the questionnaire job lifecycle and is not the root cause.
