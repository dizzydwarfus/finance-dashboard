# Cloudflare deployment

Architecture: browser → Access → gateway Worker → two Durable Object bindings → Go API or React/Nginx container. Only the API opens a MongoDB connection. This is not a hosted Docker Compose stack; Compose is local development only.

## Prerequisites

1. Workers Paid with Containers enabled, an account ID, and a Cloudflare-managed domain.
2. Create separate Access self-hosted applications for staging and production hostnames, covering **all paths**. Allow only your identity. Record the team domain (`team.cloudflareaccess.com`) and each application's audience tag.
3. For CI smoke tests, add an Access service-token policy limited to the test token; store its client ID/secret in the corresponding GitHub environment.
4. Create a new Atlas user with only the `read` role on `FinanceApp`. Verify its connection URI and permitted network access from the intended deployment. Do not broaden Atlas network rules automatically. The container needs outbound Internet access for MongoDB TCP/TLS and SRV DNS; an HTTP-only egress proxy cannot carry this traffic.
5. Rotate live MongoDB/provider credentials formerly stored in the deleted tracked configuration. A local ignored `.local/legacy-secrets.toml` backup exists in the migration workspace for transition only; it is not packaged or uploaded. Remove that local backup after rotation. Historical commits still require separate repository-history cleanup if desired.

The repository has no cloud account ID, hostname, Access application ID, or live database secret hard-coded. A domain or auth misconfiguration fails closed. Never enable an unauthenticated public backend.

## Deploy staging

Install `infra` dependencies, then create repository-root `.env.staging` and `.env.production` with the nine keys below. Actual env files are ignored by Git and excluded from both images. Do not overwrite an existing credential file.

Both cloud files require these **same nine keys**. Create an individual GitHub **Environment Secret** for every pair, with the exact key and value: `.env.staging` → environment `staging`; `.env.production` → environment `production`. GitHub Variables are not used.

| Key | Value in each environment |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Deployment token accepted from your machine/CI, scoped for Workers, Containers/registry, Durable Objects, and routing |
| `CLOUDFLARE_ACCOUNT_ID` | Target Cloudflare account ID |
| `CLOUDFLARE_HOSTNAME` | That environment’s hostname, e.g. `staging.finance.example.com` or `finance.example.com`, with no scheme/path |
| `ACCESS_TEAM_DOMAIN` | Access team domain, e.g. `yourteam.cloudflareaccess.com`, with no scheme/path |
| `ACCESS_AUD` | Audience tag for the Access application protecting that environment’s hostname |
| `MONGODB_URI` | Read-only MongoDB URI for that environment; single-quote it in the env file |
| `MONGODB_DATABASE` | `FinanceApp`, or the intended database name |
| `CF_ACCESS_CLIENT_ID` | Access service-token client ID authorized for that environment’s smoke tests |
| `CF_ACCESS_CLIENT_SECRET` | Matching Access service-token secret |

Use literal values, without `${VARIABLE}` interpolation. In GitHub, enter the parsed value **without dotenv quotes**. MongoDB usernames/passwords in the URI must be percent-encoded where required. The two files use the same names but environment-specific values; never copy production’s hostname/audience into staging accidentally.

```sh
# Create and fill in .env.staging and .env.production using the keys above.
# Edit existing files without overwriting their credentials.
node scripts/deploy.mjs staging --check
node scripts/deploy.mjs staging
```

Local deployment reads only the selected cloud file, never the generic `.env` or the other cloud environment. Cloud files are required for local cloud commands and are authoritative: values override stale shell settings, and missing keys fail validation rather than inheriting another environment’s exported credentials. In CI (`CI=true`), files are ignored and injected GitHub Secrets are used. No credentials are printed by preflight validation.

The optional npm shortcuts use the same loader: `npm run deploy:staging` or `npm run deploy:production` from `infra/`.

### Local application settings

`.env.local` needs only `MONGODB_URI`; `MONGODB_DATABASE` defaults to `FinanceApp`. Optional `LISTEN_ADDR` defaults to `127.0.0.1:8080`; optional `API_PROXY_TARGET` defaults to `http://127.0.0.1:8080`. Neither local setting is a required cloud Secret. Go and Vite select `.env.local`, falling back to `.env` only when `.env.local` does not exist. Go does not automatically read cloud credential files, and deployed containers use runtime environment variables.

For local container deployment, use `docker compose --env-file .env.local up --build`. An Atlas URI works directly; a local fixture MongoDB URI must use hostname `mongo` inside Compose, rather than `127.0.0.1`. For fixture-only development with no custom file, use `docker compose --profile fixtures up --build`.

The script generates a temporary public configuration, deploys both images and the Worker, sends the MongoDB secret through stdin to Wrangler, and removes the temporary configuration. Wrangler output is buffered and redacted against the selected file values, including abbreviated identifiers and MongoDB credential fragments. Secret updates create a new Worker version. The short interval before the initial secret is installed returns 503 for API traffic, with Access authentication still enforced. Use `--dry-run` to validate deployment configuration without a token or database secret.

Wrangler builds Linux AMD64 images. The frontend contains only static assets and Nginx; the backend contains a Go binary and system CA certificates. Both listen on port 8080 as non-root users. Nginx uses one worker and writes errors to its existing stderr descriptor; reopening `/dev/stdout` or `/dev/stderr` fails in the Cloudflare runtime. Request logs are recorded at the gateway. The MongoDB secret is supplied only to the API container at runtime.

Each service uses a fixed Durable Object name, so the application creates one instance per service. Both start on demand, use `lite`, and sleep after ten minutes of inactivity. Container readiness polling is bounded to 25 seconds, with retryable 503 responses if startup or database connectivity fails. Warm API requests have an eight-second query deadline. A database outage does not prevent the frontend container from starting.

The Durable Object policy does not automatically replace a running instance when its named image changes. The lifecycle code compares the active image digest and a hash of its runtime configuration with the deployed settings, destroys stale instances, and starts the selected image. Instance-local state is disposable; MongoDB holds application data. See [Cloudflare scheduling](https://developers.cloudflare.com/containers/configuration/scheduling-policy/) and [the Container API](https://developers.cloudflare.com/containers/api/durable-object-container/).

## Validate before promotion

The smoke command reads the same environment file (or injected CI Secrets), including the service-token pair. Its HTTPS origin is derived from `CLOUDFLARE_HOSTNAME`, so no separate `DASHBOARD_ORIGIN` key is needed:

```sh
node scripts/smoke.mjs staging
```

It checks that unauthenticated API access is denied, then authenticates and verifies the frontend, health, database readiness, and nonempty ticker data. Also open the dashboard, check a known company's statements/prices, and repeat a request after idle sleep. Local lifecycle tests cover cold start concurrency, stale-image replacement, restart after sleep, readiness timeout, and recovery; deployed behavior still needs a real smoke test.

Cloudflare logs contain structured API request durations and sanitized failures. `/healthz` checks the process; `/readyz` checks MongoDB. Both are protected by Access in the deployed gateway. Do not log MongoDB URIs, Access tokens, cookies, or provider credentials. Watch startup failures, readiness failures, 503 rates, and request latency in Workers observability.

## CI and production

Configure GitHub environments named `staging` and `production`, each with the nine **Environment Secrets** above, matching its env file. No repository variable or deployment-enable key is needed. Tests and image builds run without cloud secrets on pull requests.

On a `main` push, the staging job checks its injected Secrets. If all nine are absent, deployment is skipped; a partially populated configuration fails with missing key names. A complete configuration enables deployment and authenticated smoke tests. Configure production environment reviewers if desired.

The **Promote validated release** workflow takes a full commit SHA. It checks that this exact SHA has a successful CI run and successful staging deployment job whose actual deploy step ran, rebuilds from that source and its lockfiles, deploys production, and runs authenticated smoke tests. This promotes the validated source revision; images are rebuilt rather than copied across environments. Do not use a moving branch name for promotion.

For a manual initial deployment, use `node scripts/deploy.mjs production` only after the equivalent staging smoke tests pass.

## Rollback and troubleshooting

- Roll back the Worker with `npx wrangler rollback --env production` from `infra`, selecting the prior validated version. Its named-image map is restored; lifecycle code replaces a stale running container on the next request. Confirm the previous images remain in the Cloudflare registry and run smoke tests again. Secrets are managed separately and are not restored by code rollback.
- 401: verify the Access team domain, audience, application policy, and token issuer. Do not bypass JWT verification.
- 503 during startup: inspect image logs, startup/readiness failures, Atlas access rules, TLS/SRV DNS, and read-role permissions. Do not log raw driver errors.
- Cloudflare API rejects a token's source location: use an appropriately scoped token/authentication context accepted from this machine or CI. The migration does not alter token restrictions.
- Container build unavailable locally: Docker is required by Wrangler; For local Podman, point `WRANGLER_DOCKER_BIN` at the absolute path of `scripts/podman-docker.mjs`; the adapter removes Docker-only build flags and preserves image health checks. Keep the compatible VM running for the duration of the build. CI uses Docker on Linux.
- No data: inspect the configured database and collection names, query a known uppercase symbol, and run `go run ./cmd/inspect`. Missing profile timestamps are normal in the sampled legacy data.
