# Ledger · Finance dashboard

A private company-research dashboard: **Go API**, **React + TypeScript**, **MongoDB Atlas**, a separate **Python/Arelle SEC ingestion service**, and three **Cloudflare Containers** behind a Cloudflare Access gateway.

Browse stored company profiles, financial statements, metrics, year-over-year growth, candlestick prices, volume, and stock splits. The Go financial API remains read-only. Explicitly import a missing ticker from SEC, follow the saved job, and explore filing facts and segment dimensions in the SEC view. Prices and profiles are stored snapshots. DCF and mapping SEC facts into legacy financial tables are deferred.

## Run locally

Prerequisites: Go 1.26, Node.js 24+, and an accessible MongoDB database. Docker with Compose is needed for container development. The existing `.nvmrc` is preserved.

Create `.env.local` in the repository root with `MONGODB_URI` set to your read-only MongoDB URI. The Go API automatically reads `.env.local` (or `.env` if no `.env.local` exists), including when launched from `backend/`. Vite reads the same file for its optional proxy setting. Existing credential files are never overwritten.

```sh
# Create or edit .env.local with MONGODB_URI before starting the API.
cd backend
go run ./cmd/api
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open [the dashboard](http://127.0.0.1:5173). Vite proxies financial requests to port 8080 and SEC requests to port 8081. See [SEC setup and local development](docs/sec-ingestion.md) to start ingestion. Local servers bind to loopback and do not use Cloudflare Access; deployed traffic always requires validated Access authentication.

For **synthetic data** with no Atlas connection:

```sh
docker compose --profile fixtures up -d --build
docker compose exec -T ingestion python -m sec_ingestion bootstrap
```

Open [the containerized dashboard](http://127.0.0.1:3000/companies/DEMO). This creates a disposable local database with `DEMO` and `EMPTY`, plus a read-only application user. Keep `MONGODB_URI` unset to use the Compose default. To run the containers with your local Atlas configuration:

```sh
docker compose --env-file .env.local up --build
```

For a fixture database with the API running directly on your host, start `docker compose --profile fixtures up mongo` and set `MONGODB_URI` to `mongodb://dashboard:local-fixture-only@127.0.0.1:27017/FinanceApp?authSource=FinanceApp`. For the API inside Compose, use an Atlas URI or change the URI host to `mongo`; `127.0.0.1` inside the API container refers to that container itself.

## Structure

- `backend/`: Go HTTP handlers, domain services, read-only MongoDB repository, schema inspector, and fixtures/tests.
- `frontend/`: React dashboard, generated API types, ECharts visualizations, and browser tests.
- `ingestion/`: Python 3.14, offline Arelle parser, shared SEC transport, persistent queue/checkpoints, FastAPI API, and tests.
- `infra/`: Access validation, routing, container lifecycle, Wrangler configuration, and gateway tests.
- `docs/`: [API contract](docs/openapi.json), [data compatibility](docs/data-compatibility.md), and [deployment runbook](docs/deployment.md).
- `legacy/sec_parser/`: experimental parser reference; excluded from all runtime images.

## Checks

```sh
cd backend
go test -race ./...
go vet ./...
go run ./cmd/inspect
```

The inspector requires `MONGODB_URI` and prints only field types and index keys. Optional `MONGODB_SMOKE_URI` enables a read-only Atlas smoke test. `MONGODB_TEST_URI` enables the separate integration test that creates and drops a randomly named test database; use only a disposable MongoDB instance with authentication and user-admin permissions.

```sh
cd frontend
npm ci
npm run generate:api
npm run build
npx playwright install chromium
npm test
```

```sh
cd infra
npm ci
npm run typecheck
npm test
npx wrangler deploy --dry-run --env production
```

Frontend types are generated from the OpenAPI contract; CI rejects stale generated types. CI also runs authenticated MongoDB integration tests and builds/tests all three Linux AMD64 images.

## Deploy

Keep `.env.production` for local deployment commands and the existing GitHub `production` environment’s **Secrets**. Both use the same twelve keys listed in the deployment runbook; no GitHub Variables are needed. Run `node scripts/deploy.mjs` to deploy locally and `node scripts/smoke.mjs` to verify.

Follow the [deployment runbook](docs/deployment.md) to configure Access, a read-only Atlas user, secrets, and hostnames. Workers Paid is required. The production gateway manages the dashboard containers and uses a private service binding to the separate ingestion Worker/Durable Object. The gateway denies requests if Access configuration is missing; `workers.dev` and preview URLs are disabled.

GitHub Actions runs checks automatically on pushes to `main` and pull requests. To deploy, manually run **Validate and deploy dashboard** from `main` in GitHub Actions (`workflow_dispatch`); it deploys only after checks pass, then runs authenticated smoke tests. Restore a known-good Cloudflare version with `node scripts/deploy.mjs --rollback VERSION_ID`, or revert a commit and manually deploy the revert. MongoDB data and schemas are not changed during deployment.

## Migration status

The application has no Streamlit dependency. Python is isolated in the new ingestion container; Go and frontend runtime images remain free of Python. The retained experimental SEC parser is reference material only. Old secret configuration was removed from tracked source; any live credentials previously committed must be rotated in their provider accounts. Deleting files does not remove them from Git history.

SEC privacy, fair access, limits, recovery, and reuse rules: [SEC access policy](docs/sec-access-policy.md). The [ingestion runbook](docs/sec-ingestion.md) describes database/user setup and the first live rollout checks.

License: [MIT](LICENSE); parser/plugin licenses are documented separately in the SEC policy.
