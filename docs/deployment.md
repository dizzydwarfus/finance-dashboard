# Production deployment

The dashboard has one deployment: [dizzydwarfus.com](https://dizzydwarfus.com). Cloudflare Access protects the gateway Worker, which routes to separate Go API and React/Nginx containers, plus a private Python SEC ingestion Worker/container. MongoDB Atlas remains the system of record.

## Configuration

Keep the existing repository-root `.env.production` for local deployment commands and the GitHub environment named `production` for Actions. Both use these same twelve keys. Store each parsed key/value pair as an individual GitHub **Environment Secret**, without dotenv quotes. No GitHub Variables are needed.

| Key | Value |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Deployment token scoped for Workers, Containers/registry, Durable Objects, and routing |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| `CLOUDFLARE_HOSTNAME` | `dizzydwarfus.com`, without scheme or path |
| `ACCESS_TEAM_DOMAIN` | Access team domain, e.g. `yourteam.cloudflareaccess.com` |
| `ACCESS_AUD` | Audience tag for the Access application covering all production paths |
| `MONGODB_URI` | Read-only Atlas URI; single-quote it in the env file |
| `MONGODB_DATABASE` | `FinanceApp` |
| `CF_ACCESS_CLIENT_ID` | Access service-token client ID authorized for smoke tests |
| `CF_ACCESS_CLIENT_SECRET` | Matching Access service-token secret |
| `SEC_MONGODB_URI` | Separate Atlas writer restricted to `readWrite` on `SECIngestion` only |
| `SEC_MONGODB_DATABASE` | `SECIngestion` (required exact name) |
| `SEC_USER_AGENT` | Application name and real, monitored contact email |

Local deployment commands load only `.env.production`; it overrides stale shell settings. Missing keys fail validation. In CI (`CI=true`), env files are ignored and injected GitHub Secrets are used. Values are literal, without `${VARIABLE}` interpolation; percent-encode MongoDB URI credentials where required. Credential files stay ignored by Git and excluded from images. Existing staging files and cloud resources are no longer used by the application workflows; removing them is separate account cleanup.

Workers Paid, Containers, a managed domain, an Access application allowing your identity and the smoke-test service token, and Atlas network access are required. Keep the Atlas application user restricted to read access. Rotate any live credentials formerly committed in legacy configuration; deleting files does not remove Git history.

## Deploy

In **GitHub → Actions → Validate and deploy dashboard → Run workflow**, select `main` and run it manually. The workflow runs backend/integration tests, frontend/browser tests, gateway checks, and all three container builds. After they pass, the manual run deploys to production using the existing `production` Secrets and runs authenticated smoke tests. Pushes to `main` and pull requests run checks only; they never deploy. Production deployments run one at a time. Missing Secrets fail the release rather than skipping it.

The equivalent CLI trigger is `gh workflow run ci.yml --ref main`. Deployment is restricted to manual runs from `main`.

For a local deployment with Docker running:

```sh
npm ci --prefix infra
node scripts/deploy.mjs --check
node scripts/deploy.mjs
node scripts/smoke.mjs
```

From `infra/`, the equivalent shortcuts are `npm run deploy` and `npm run smoke`. `node scripts/deploy.mjs --dry-run` validates the bundle and builds images without deploying. The internal Wrangler environment stays named `production` to preserve the existing Worker and container identities; command-line environment selection is unnecessary.

The script builds three Linux AMD64 images, deploys the private ingestion Worker followed by the gateway Worker, installs their separate secrets through stdin, and removes its temporary configuration. Logs are redacted. Only Go receives `MONGODB_URI`; only ingestion receives `SEC_MONGODB_URI` and `SEC_USER_AGENT`. Bootstrap the SEC database explicitly before the first release; see [SEC setup](sec-ingestion.md). Nginx runs one worker and writes errors through its existing stderr descriptor. The gateway records requests.

Dashboard containers start on demand as `lite`; ingestion uses one `standard-1` instance and sleep after ten minutes of inactivity. Readiness polling is bounded to 25 seconds; startup failures return retryable 503 responses. The lifecycle code replaces containers when their deployed image or runtime configuration changes. Container state is disposable; MongoDB holds the data.

The smoke test confirms unauthenticated API requests are denied, then checks the frontend, process health, database readiness, and existing ticker data through Access. Also check a known company's statements and price chart after a release.

The release refuses scraper replacement while accepted imports are queued, running, or cooling down. A maintenance lock prevents new imports during replacement. See [SEC deployment/recovery](sec-ingestion.md). Deployment never starts scraping.

## Rollback

For the quickest rollback, open **Cloudflare → Workers & Pages → finance-dashboard-production → Deployments**, select a known-good version, and choose **Rollback**. Choose the final version of a successful release, after its database secret was installed. See [Cloudflare's rollback instructions](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/).

Or use its Cloudflare Worker version ID (a UUID, not a Git commit SHA):

```sh
node scripts/deploy.mjs --rollback VERSION_ID
node scripts/smoke.mjs
```

From `infra/`, use `npm run rollback -- VERSION_ID`. This loads `.env.production`, restores the selected Worker version and its named container images without rebuilding, and does not upload a new database secret. Retain the older images in Cloudflare's registry so they can restart. Verify credentials still work if they changed since that release. MongoDB data and external resources are not restored by code rollback.

Revert the bad commit in Git and push the revert so the next deployment keeps the fix, then manually run the workflow when ready. For changes to Durable Object classes or bindings that prevent a Cloudflare version rollback, redeploy the reverted source through the manual workflow.

Ingestion rolls back independently using `node scripts/deploy.mjs --rollback-sec INGESTION_VERSION_ID`, with the idle-only lock. It preserves collected records and provenance.

## Local development and troubleshooting

Local Go/Vite development uses `.env.local`, falling back to `.env`; it needs only `MONGODB_URI`, with `MONGODB_DATABASE` defaulting to `FinanceApp`. Optional `LISTEN_ADDR` defaults to `127.0.0.1:8080`; `API_PROXY_TARGET` defaults to `http://127.0.0.1:8080`. These are not required cloud Secrets. Use `docker compose --env-file .env.local up --build`, or `docker compose --profile fixtures up --build` for disposable fixtures. Inside Compose, a fixture URI uses hostname `mongo`.

- 401: check the Access team domain, audience, and identity/service-token policy.
- 503: inspect container logs, readiness, Atlas network rules, TLS/SRV DNS, and read permissions. `/healthz` checks the process; `/readyz` checks MongoDB. Both require Access in production.
- DNS failures immediately after creating a domain route: allow propagation, then rerun the failed Actions job.
- Token source-location rejection: update the token's permitted deployment context; the scripts do not change its restrictions.
- Local Podman disk exhaustion: prune unused untagged images with `podman image prune -f` and build with `podman-compose --parallel 1`; VM disk space is separate from available macOS disk space. See [local SEC setup](sec-ingestion.md).
- Local Podman: set `WRANGLER_DOCKER_BIN` to the absolute path of `scripts/podman-docker.mjs` and keep its VM running. CI uses Docker.
