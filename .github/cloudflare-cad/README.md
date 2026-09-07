# Cloudflare CAD runtime

This deployment runs the canonical `cad_engine.main:app` image in Cloudflare
Containers. It uses `standard-2` (6 GiB RAM, 1 vCPU) because the sealed
production regression peaks near 1 GiB and needs meaningful headroom.

Both design mutations, `POST /design` (Mechanical/shared compatibility) and
`POST /design-electrical` (Electrical authority), are protected at the Worker
edge by `CAD_SERVICE_TOKEN` using the `x-cad-service-token` header. `/health`,
`/version`, `/mechanical/status`, and `/electrical/status` remain public for
health, contract, and release-identity verification. No secret is stored in this
repository.

The container runs with `CAD_ISOLATED_SERVICE=1`. Each design request is sent to
a disposable Python worker. Electrical requests use the explicit
`design-electrical` worker operation and do not pass through the Mechanical
`/design` route. Remote Electrical output is returned in a compressed transfer
envelope because the Cloudflare Container filesystem is not shared with the web
service.

Deploy from the repository root:

1. Sign in with `npx wrangler login`.
2. Set the edge secret with `npx wrangler secret put CAD_SERVICE_TOKEN --config .github/cloudflare-cad/wrangler.jsonc`.
3. Set `GIT_COMMIT_SHA` to the exact commit being deployed with the same command;
   it is passed into the Container so the panel and CAD build identities match.
4. Deploy with `npx wrangler deploy --config .github/cloudflare-cad/wrangler.jsonc`.
5. Set the panel's `COBUILT_CAD_DESIGNER_URL` to the resulting Worker URL and
   set the same value in `COBUILT_CAD_SERVICE_TOKEN`.
6. Verify `/health`, `/version`, unauthorized `/design` and `/design-electrical`
   requests, then one complete authenticated Mechanical design and one complete
   authenticated Electrical design before removing the Railway CAD fallback.

Rollback is configuration-only: restore `COBUILT_CAD_DESIGNER_URL` to
`http://web.railway.internal:8080` and redeploy the panel.
