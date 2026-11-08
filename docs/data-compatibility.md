# MongoDB compatibility

The six `FinanceApp` collections were inspected read-only against Atlas on 2026-11-06. Metadata from five sample records per collection is recorded in `mongodb-schema.json`. `backend/testdata/observed-shapes.json` preserves observed BSON shapes with all source values replaced; `financeapp.json` adds synthetic edge cases. No collection, index, or source record was modified.

| Collection | Observed representation | API |
| --- | --- | --- |
| `income_statement` | String dates/year/period/currency, BSON Int64 amounts, double ratios/EPS | `statements/income` |
| `balance_sheet` | String dates/year/period/currency, Int64/integer amounts | `statements/balance` |
| `cash_flow_statement` | String dates/year/period/currency, Int64/integer amounts | `statements/cash-flow` |
| `company_profile` | Double prices, Int64 market cap, string employee count; sampled records have no update timestamp | Company summary |
| `historical` | BSON datetime and double OHLCV | Prices |
| `stock_split` | BSON datetime and integer numerator/denominator | Splits |

Observed indexes were `_id` and `index_id`, without a `symbol` index. This migration creates no indexes. Symbol queries may scan collections; inspect production query latency before adding an explicitly reviewed administrative index. Each company/collection read is capped at 20,000 records; larger datasets return a clear error instead of silently omitting data. Public response limits are independently bounded.

## Mapping rules

- Only known statement financial fields are exposed, including all numeric statement fields seen in the inspection. Private/internal keys, source URLs, MongoDB `_id`, and `index_id` are not returned.
- Legacy integer, double, Decimal128, and numeric-string values become JSON numbers. Invalid/missing/non-finite values become null. Values use IEEE-754 precision for analytical display, not accounting or trading settlement; source BSON remains unchanged.
- Dates become UTC `YYYY-MM-DD`; profile timestamps use RFC3339 when available. No timestamp is inferred from an IPO date or ObjectId.
- Records are ordered using recognized update/acceptance dates, then ObjectId as a deterministic tie-breaker. Statements are deduplicated by date, fiscal period, and currency; prices/splits by date. Output is explicitly sorted by reporting date.
- Missing profiles return a symbol-only summary if any other collection contains the company. Missing datasets return empty arrays. Unknown symbols return 404; database failures return 503 with no driver details.
- Fiscal period and reported currency are never collapsed into calendar-year-only keys. Missing legacy periods default to FY. The UI starts with annual data, with separate quarter selectors.
- Growth is `(current - previous) / abs(previous)`, comparing the same period and currency in consecutive fiscal years. Missing/zero denominators and gaps yield null. Working capital is current assets minus current liabilities; free cash flow per share uses diluted shares. Neither value is synthesized when required inputs are missing.
- Price history is stored OHLCV without split adjustment. Split events are displayed separately. The API uses stored profile currency when available; missing currency is not an assertion of USD.

## Future work

DCF will need a new documented calculation model and financial validation fixtures. SEC ingestion now uses the separate Python/Arelle service described in [the SEC runbook](sec-ingestion.md), with its own database, throttling, and durable jobs. Mapping those facts into legacy financial statements remains deferred. Dashboard reads never start ingestion.
