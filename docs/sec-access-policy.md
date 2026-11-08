# SEC access policy

Reviewed **2026-11-08**. Review again before changing downloader behavior, starting a backfill, or enabling another deployment that shares the requester identity. This records published guidance and application choices; the SEC can change its policy or block requests below its published ceiling.

| Published SEC guidance | Application control (our defaults) |
| --- | --- |
| Automated requests should declare an organization and contact in `User-Agent`. [Access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) | Require `SEC_USER_AGENT` with an application name and real, monitored email. Reject the legacy placeholder. HTTPX derives `Host` from each destination. |
| At most **10 requests/second per user across machines**; minimize downloads. [Developer Resources](https://www.sec.gov/about/developer-resources) | Use a MongoDB-backed budget of **2 requests/second, without bursts**. All hosts, redirects, retries, registry reads, and parser dependencies share it. Other programs using the same identity must share this budget or reserve capacity independently. |
| Excessive access can be limited; SEC describes recovery after ten minutes below its threshold. [Security policy](https://www.sec.gov/about/privacy-information) | On `429`, persist at least a ten-minute cooldown, extended by `Retry-After`. Retry once per job; another `429` blocks automatic work. `403` stops automatic retries immediately. These are conservative app rules, not a promise that access resumes after ten minutes. |
| Access-denied troubleshooting is available through the webmaster. [FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions) | Preserve a blocked status and source/status diagnostics. Verify Cloudflare egress before rollout. Never rotate proxies, IPs, or identities to evade a block. |
| Archive access is documented; specific crawler exclusions are published. [Access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), [robots.txt](https://www.sec.gov/robots.txt) | Use the ticker registry, submissions APIs, and filing-directory indexes. Cache and apply SEC robots rules, including specific archive exclusions. Do not crawl search pages. |
| Public data APIs need no API key; `data.sec.gov` does not support CORS. Aggregated facts cover non-custom concepts applying to the entire issuer. [API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Download server-side. Parse filings for extensions and dimensions. Company-facts refresh is a separate snapshot, not a substitute. Never forward browser cookies, Access tokens, service-token headers, or MongoDB credentials to SEC. |
| Corrections/removals occur; ticker associations and availability are not guaranteed. [Access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) | Identify issuers by CIK and filings by accession. Revalidate on explicit refresh. Record unavailable sources without interpreting a single failure as confirmed deletion or erasing successful data. |
| SEC automatically collects request/client information, including network and timing information. [Privacy policy](https://www.sec.gov/about/privacy-information) | Requests are identifiable. Use a dedicated monitored contact address. Redact the header in deployment output; application access logs are disabled in ingestion. Store financial facts/provenance, not downloaded people/contact datasets. |
| Public filing reuse is permitted, with exceptions for some site material and restrictions on branding. [Reuse FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions), [dissemination policy](https://www.sec.gov/about/privacy-information) | Keep filing/source links. No SEC artwork, seals, or implied endorsement. Parser and taxonomy licenses are separate; see below. |

No daily request allotment was specified in these reviewed sources. That does **not** make access unlimited. The published rate is a ceiling, not a service-level agreement. Browser polling only reads our database; searching, viewing, CI, startup, bootstrap, and deployment do not start imports. Registry downloading happens only after an explicit scrape request; searches use its last good cached snapshot.

## Timing and future bulk imports

The SEC describes typical submissions API delay below one second and XBRL API delay below a minute after dissemination, with longer delays at peak times. Nightly `submissions.zip` and `companyfacts.zip` are the efficient option for large API backfills; archives are normally refreshed around 3 a.m. ET. [API update/bulk guidance](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The webmaster FAQ describes filing-document availability often taking 1–3 minutes from the EDGAR timestamp, without a guarantee. [Availability FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions) Filing indexes update on their own schedule and corrections can arrive later. [Archive guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) A missing just-filed document should therefore be retried deliberately later, not polled aggressively.

No scheduled backfill is included. Any future bulk pipeline needs a separate capacity/retention review and the same shared requester budget.

## Block recovery

1. Stop automatic SEC work. Completed filings remain readable. A durable global blocked flag or cooldown survives container restarts.
2. Inspect the job's code, source URL, HTTP status, cooldown time, and configured contact identity without copying credentials into logs. Confirm SEC is reachable from the deployed Cloudflare container, not only a laptop.
3. For `429`, wait until the persisted cooldown ends. Respect a longer `Retry-After`. For `403`, diagnose identity, robots rules, request volume, and egress before retrying.
4. If necessary, contact `webmaster@sec.gov` with the error message and egress IP as requested by the [SEC FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions). Do not send application credentials.
5. Use **Retry saved import** explicitly after correction. It resumes checkpoints and clears the application block only when the cooldown has expired. Queued jobs remain accepted; they do not bypass the block.

Source downloads are temporary and capped at 50 MiB each, 250 dependency files, and 200 MiB per filing. Parsing has a five-minute timeout. These resource safeguards are our choices, not SEC limits. Failure preserves the previously published generation. Checksums, URLs, retrieval times, availability, and parser versions remain; exact reproduction is not promised if SEC later changes a source.

## Licenses

[Arelle](https://arelle.readthedocs.io/en/latest/license.html) is distributed under Apache-2.0 with its bundled third-party notices; the locked package retains them in the runtime image. The vendored SEC inline transforms are from [Arelle/EDGAR](https://github.com/Arelle/EDGAR) at the commit/checksums recorded in `ingestion/sec_ingestion/vendor/sec_transform/UPSTREAM.json`, with its CC0 license retained alongside the code.

Taxonomies have their own notices, including [FASB taxonomy legal notices](https://xbrl.fasb.org/resources/annualrelease/2025/GAAP_Financial_Reporting_Taxonomy_and_Data_Quality_Committee_Rules_Taxonomy_Technical_Guide.pdf) and [XBRL International intellectual-property policy](https://www.xbrl.org/the-consortium/about/legal/). SEC filing reuse permission does not replace those licenses. We download only dependencies needed to interpret a requested filing and do not publish a standalone taxonomy mirror. Preserve upstream notices when redistributing parser resources or adding persistent taxonomy caching.
