# Migration verification · 2026-11-07

## Passed

- Read-only Atlas schema inspection: five samples from each of the six FinanceApp collections; only schema metadata and anonymized shapes retained.
- Go driver live smoke: discovered 66 stored symbols and read all six collection paths for an existing symbol, without writes.
- Go unit/HTTP/OpenAPI schema tests, race detector, and `go vet`.
- Real disposable MongoDB integration: normalized records, statements, metrics, prices, ticker coverage, and read-role enforcement. An attempted write using the test application's read-only account was rejected; source record counts were unchanged.
- Five browser regression scenarios: navigation/deep links/history/search, statement filters/empty periods, charts/splits/date validation/theme persistence, isolated price failures, and mobile overflow.
- One live browser smoke scenario through React → Go → Atlas: company overview, financial tables, and price history. Preview saved in the ignored `frontend/test-results/live-dashboard.png` artifact.
- Gateway TypeScript checks and eleven authentication/routing/lifecycle tests, including service-token JWTs, concurrent cold starts, secret/image changes, readiness timeout, and restart recovery.
- Both Linux AMD64 runtime images built and started as non-root users. API/Nginx health responses, an API database read, and a React deep link returned 200.
- Real database outage recovery: paused only the disposable MongoDB container, observed API readiness 503, resumed MongoDB, and observed readiness 200 without restarting the API.
- Full Wrangler staging deployment dry run passed, building both final images and bundling the Worker with both Durable Object bindings. Both images were subsequently deployed to staging (see below).
- GitHub Actions workflows passed actionlint. New source and frontend build output were checked for copies of the removed legacy API keys and MongoDB passwords; none found.
- Retained Python parser syntax verified, with no UI imports. It is excluded from both runtime images.

## Staging deployment

Deployed both container images and the authenticated gateway to [staging.dizzydwarfus.com](https://staging.dizzydwarfus.com) on 2026-11-07, using `.env.staging`. Production was not deployed.

- Authenticated frontend, `/healthz`, `/readyz`, and `/api/v1/tickers` returned 200. Unauthenticated API requests were rejected before container routing.
- The deployed Go API read Atlas successfully: 66 symbols; the AAPL profile, 10 income statement records, metrics, 365 daily prices, and five split records returned 200.
- A deployed Chromium browser check passed the AAPL deep link, metrics chart, statement table, historical price chart, and absence of runtime errors. A screenshot is saved in the ignored `frontend/test-results/staging-dashboard.png` artifact.
- Both services started on demand. Fixed the lifecycle timeout ordering and Nginx log descriptor configuration found during deployment; regression tests pass.
- Podman's compressed registry digest differs from its local manifest digest. The optional adapter records the digest returned by the push for Wrangler image preparation, with bounded upload retries.
- Post-idle restart recovery and a human Access sign-in remain manual release checks; production promotion is pending.

The migration did not rotate provider credentials or create a production Atlas user. Staging uses the user-supplied read-only credential. Rotate live credentials previously committed and follow `deployment.md` before production promotion. The ignored local legacy-secret backup is for transition only and must be removed after rotation.

DCF, provider downloads, uploads, and SEC ingestion remain outside v1 by agreement.
