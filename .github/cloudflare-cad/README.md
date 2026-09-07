# Cloudflare CAD runtime

This deployment runs the canonical `cad_engine.main:app` image in Cloudflare
Containers. It uses `standard-2` (6 GiB RAM, 1 vCPU) because the sealed
production regression peaks near 1 GiB and needs meaningful headroom.

`POST /design` is protected at the Worker edge by `CAD_SERVICE_TOKEN` using the
`x-cad-service-token` header. `/health` and `/version` remain public for health
checks and release-identity verification. No secret is stored in this repository.

Deploy from the repository root:

1. Sign in with `npx wrangler login`.
2. Set the edge secret with `npx wrangler secret put CAD_SERVICE_TOKEN --config .github/cloudflare-cad/wrangler.jsonc`.
3. Set `GIT_COMMIT_SHA` to the exact commit being deployed with the same command;
   it is passed into the Container so the panel and CAD build identities match.
4. Deploy with `npx wrangler deploy --config .github/cloudflare-cad/wrangler.jsonc`.
5. Set the panel's `COBUILT_CAD_DESIGNER_URL` to the resulting Worker URL and
   set the same value in `COBUILT_CAD_SERVICE_TOKEN`.
6. Verify `/health`, `/version`, an unauthorized `/design`, and one complete
   authenticated design before removing the Railway CAD fallback.

Rollback is configuration-only: restore `COBUILT_CAD_DESIGNER_URL` to
`http://web.railway.internal:8080` and redeploy the panel.
