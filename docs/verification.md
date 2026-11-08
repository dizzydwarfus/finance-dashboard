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

## Production deployment

Production was deployed on 2026-11-07 to [finboard.dizzydwarfus.com](https://finboard.dizzydwarfus.com) using GitHub Actions, after [CI and database/container checks passed](https://github.com/dizzydwarfus/finance-dashboard/actions/runs/42377789269). The [production workflow](https://github.com/dizzydwarfus/finance-dashboard/actions/runs/42378129255) passed its authenticated smoke test on retry after initial DNS propagation. A production Chromium check passed company deep links, metrics, statements, historical prices, and absence of runtime errors.

The 2026-11-08 configuration simplifies future releases to one production deployment, manually triggered through `workflow_dispatch` from `main` after checks pass. Pushes and pull requests run checks only. Local deploy/smoke/rollback commands read `.env.production`.

DCF, provider downloads, and uploads remain deferred. SEC ingestion is added separately below.

## SEC ingestion implementation · 2026-11-08

Local implementation checks passed:

- Python tests pass, including real offline Arelle XML/inline parsing, exact decimals, explicit/typed dimensions, extensions, nils, conflicting duplicates, fallback labels, SEC transforms, amendments/range selection, and shared OpenAPI response validation.
- Real authenticated MongoDB 7 integration: concurrent submissions attach to one CIK job, unique active jobs, recoverable checkpoints, idempotent generations, corrected-source publication, and scoped user permissions. Writes/reads to the two legacy databases were denied for the fixture ingestion user. Broader roles are rejected before bootstrap/readiness.
- Durable rate-budget tests cover spacing across clients/redirects/retries, persisted cooldowns, the single automatic `429` retry, `403` blocking, robots exceptions, isolated headers, exact JSON decimals, and source allowlisting/path validation. Tests prohibit live HTTP transport.
- Browser regression scenarios pass, covering existing dashboard behavior and SEC import/progress, deep-link reload, cancellation, partial success, blocked messages, search errors, explicit refresh, pagination/filtering, and unknown-company/mobile behavior. The original live-Atlas smoke remains opt-in.
- One additional browser test passed against the real three-container local stack with a synthetic SECX issuer. Desktop/mobile screenshots were inspected; the facts table scrolls within its panel on mobile, and legacy financial navigation still works.
- Go race tests, real disposable-MongoDB integration, and vet pass. Gateway type checks, 20 gateway/lifecycle/alarm tests, and 14 environment/deployment guard tests pass. Actionlint accepts the workflow; deployment still requires manual dispatch from main.
- Linux AMD64 ingestion and frontend images build; runtime users are unprivileged. Nginx routes to the separate Python/Go services. Ingestion readiness changes to 503 during a disposable database outage and recovers to 200 after reconnection.
- Both Wrangler production dry runs pass, including the private ingestion service binding and separate container/DO. No public ingestion hostname, preview endpoint, or workers.dev endpoint is configured.
- A scan of tracked/candidate source files found no supplied production credentials. Environment files remain ignored.

Production settings were revalidated after the user updated the local file and GitHub production Secrets. Contact format and Atlas connectivity pass. The supplied custom role has readWrite-equivalent effective permissions confined to SECIngestion; Atlas denied read probes against FinanceApp and SECRawData. Permission validation now accepts equivalent scoped custom roles while rejecting cross-database, cluster, and user/role administration grants; its regression tests pass. The explicit bootstrap created SECIngestion collections/indexes, and database readiness passed. No legacy database was modified, no SEC requests/imports were started, and no deployment was performed. Changes remain local pending commit and manual production release. Cloudflare-to-SEC access, a real filing import, idempotency, and cold-start recovery remain [live rollout checks](sec-ingestion.md).

### Local compressed-response fix · 2026-11-08

The first live-import attempt exposed a downloader bug: HTTPX had already decoded streamed gzip data, but the buffered response retained Content-Encoding and attempted a second decompression. Buffered responses now remove wire encoding/length headers, retain the decoded-size bound, and treat corrupt compression as a retryable upstream error. Denial/cooldown status codes are processed without downloading or decoding error bodies.

Unexpected API exceptions now return sanitized JSON. Both frontend API clients distinguish service failures and malformed responses from actual 401/Access-login responses. A completion refresh also cancels stale initial company requests so a late 404 cannot hide newly published results.

Regression checks passed: 39 offline Python tests, the frontend production build, and 18 browser tests (two fixture/live checks remain opt-in). Cases cover gzip/deflate streams, compressed ticker lookup and job admission, damaged compression, malformed denial bodies, sanitized 500 errors, genuine 401 errors, and delayed initial company responses. The local ingestion/frontend images were rebuilt and services restarted; the browser was reloaded into the corrected SEC view. The user chose to perform the live AAPL import retry themselves.

### Offline filing-reference fix · 2026-11-08

The user's first import downloaded both AAPL filings but failed because the local dependency bundle omitted `link:roleRef` and `link:arcroleRef` targets. Arelle consequently reported missing local role schemas and company extension references. The bundle now discovers and rewrites those references through the same host allowlist and shared transport budget, while the parser remains offline.

Temporary diagnostic copies of the exact failed filings now parse successfully: `0000320193-26-000026` yields 1,068 numeric facts and `0000320193-26-000020` yields 762. Existing temporary taxonomy copies were reused to limit downloads. These diagnostics did not retry the import, publish facts, or change the failed job's status.

All 42 offline ingestion tests pass, including new custom-role/arcrole dependency fixtures and missing-dependency diagnostics. Parser failures now carry bounded error codes and controlled messages, without raw Arelle logs, filesystem paths, source contents, or exception messages. The OpenAPI contract and generated types describe these diagnostic codes. The user retains control of the live import retry.
