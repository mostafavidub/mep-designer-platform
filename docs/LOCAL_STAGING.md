# Local Staging

Planha's default release path is local-first: run the production image with an
isolated PostgreSQL database, then rely on GitHub CI and governance checks.
Online Staging is exceptional infrastructure, not an ordinary PR dependency.

## Prerequisites

- Docker Engine 24 or newer
- Docker Compose v2 (`docker compose version`)
- 8 GB of free memory recommended for the combined web and CAD runtime
- ports `8080` free on loopback

The application image is the repository `Dockerfile`; the application process
is the same `start_services.sh` used by Railway. PostgreSQL 18 matches the
currently observed Railway Staging database image.

## Commands

From the repository root:

```bash
# Build and start; schema creation runs during canonical application startup.
docker compose -f docker-compose.local-staging.yml up --build -d --wait

# Health and representative smoke checks.
curl --fail http://127.0.0.1:8080/system_health
curl --fail http://127.0.0.1:8080/

# Follow logs.
docker compose -f docker-compose.local-staging.yml logs -f app

# Stop while retaining local test data.
docker compose -f docker-compose.local-staging.yml down

# Reset only the isolated Local Staging containers and named volumes.
docker compose -f docker-compose.local-staging.yml down --volumes

# Targeted contract tests.
python3 -m pytest -q tests/test_local_staging_environment.py
```

Local URL: `http://127.0.0.1:8080`

### Customer Site / API bridge

In the companion Sites repository, run the production Worker build against the
local backend:

```bash
npm run staging:local
```

The Site is then available at `http://localhost:8787`. The build injects only
the local backend URL and a local-only bridge token into Wrangler's local
bindings. It does not alter the deployed Site or its cloud bindings. Keep the
backend command running while testing the panel. Stop the Worker with `Ctrl-C`.

## Safety and environment variables

The Compose definition deliberately supplies a fixed local-only database URL
whose host is the Compose service `postgres`. It does not read `DATABASE_URL`,
`S3_*`, `PUBLIC_SITE_URL`, or panel tokens from the host shell, so exported
Railway or Production values cannot be inherited accidentally. The port binds
only to loopback. No actual secret is required or committed.

Runtime variable names represented locally are `DATABASE_URL`, `DATA_DIR`,
`RULEBOOK_PATH`, `CAD_DESIGNER_URL`, `COBUILT_CAD_IN_PROCESS`,
`PUBLIC_SITE_URL`, `PANEL_PUBLIC_URL`, `CANONICAL_REDIRECT_HOSTS`,
`TEMPORARY_NOINDEX_HOSTS`, `SESSION_SECRET`, `PANEL_BRIDGE_TOKEN`,
`PANEL_DEMO_PAYMENTS`, and `PORT`. Provider credentials and production values
must never be placed in this file.

## Database and migration behavior

The database is PostgreSQL 18 in the named volume
`planha-local-staging_planha-local-staging-postgres`. The canonical FastAPI
startup imports the SQLAlchemy models and runs `Base.metadata.create_all`, which
is the repository's current deployment schema-initialization contract. Resetting
with `down --volumes` deletes only locally named Compose volumes.

## Storage

`S3_*` is intentionally unset. The existing application fallback stores
artifacts in the isolated database/local `/data` volume. This validates the
file workflow and fallback retention but does not validate Cloudflare R2
signatures, permissions, latency, or egress. Use a temporary online environment
only when an R2-specific change genuinely requires it.

## Authentication and HTTPS

Current session authentication works on loopback HTTP and has no OAuth callback
dependency in the reviewed runtime. Local Staging does not attempt to reproduce
Cloudflare TLS, Railway networking, domain cookies, or third-party callbacks.

## Troubleshooting

- `docker: 'compose' is not a docker command`: install/enable the Compose v2
  plugin supplied for your Docker installation.
- health remains `starting`: inspect `docker compose -f
  docker-compose.local-staging.yml logs app postgres`; the first image build and
  Rule Book generation can take several minutes.
- port already allocated: stop the process using local port 8080. Do not change
  the public URL without changing the bound port consistently.

## Restore online Staging when genuinely required

1. In Railway project `mep-designer-platform-staging` (project id
   `c7eb44c0-149c-41da-9048-f10f785d3abd`), restore compute for `Postgres`,
   `web-app-staging`, and `web-app-authority-staging` without deleting or
   replacing their retained volumes/bucket.
2. Confirm `web-app-staging` is sourced from
   `feature/architecture-stack-integration`, uses the repository Dockerfile and
   starts with `./start_services.sh`.
3. Restore automatic deployment only if continuous Staging is intentionally
   needed. Otherwise deploy an exact approved SHA manually.
4. Preserve the custom `stage.planha.com` domain and the DNS-only CNAME while
   compute is off; no DNS change is required to restore.
5. Verify `/system_health`, then the customer panel bridge and one synthetic
   upload-to-payment flow. Never copy Production customer data into Staging.
