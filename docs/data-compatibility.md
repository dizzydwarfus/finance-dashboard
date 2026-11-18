# SEC financial mapping

The Go API reads published XBRL generations from `SECIngestion`. It uses the accession and generation together to look up facts, contexts, and units. This prevents incomplete reparses from becoming visible and lets existing imports feed the analysis without re-scraping. No normalized copy is written. A request reads at most 100 published filings and 50,000 matching facts or contexts per issuer. The old FinanceApp inspection metadata remains in [mongodb-schema.json](mongodb-schema.json) for reference.

| View | US GAAP facts |
| --- | --- |
| Income | Revenue (contract revenue excluding assessed tax, then Revenues, SalesRevenueNet, or contract revenue including assessed tax), operating income, net income attributable to parent, and diluted EPS |
| Balance | Assets, liabilities, and stockholders’ equity attributable to parent |
| Cash flow | Operating cash flow, capital expenditure reported as an outflow magnitude, and free cash flow (operating cash flow minus capital expenditure) |
| Metrics | The above, plus operating and net income margins |

- Use non-dimensional contexts belonging to the filer for normalized statements. The importer keeps original qualified names, reported decimal values, nils, and dimensions. Currency must be an ISO 4217 XBRL measure. Diluted EPS requires currency per share. No currency conversion or unit inference.
- Group reported duration facts by exact start and end dates. Use the filing report date and matching prior-year comparative columns. Annual ranges, standalone quarters, and longer year-to-date ranges remain separate. Use point-in-time contexts for balance rows and show verified DEI fiscal labels when available. Older saved generations fall back to actual report dates. No subtraction of year-to-date values to manufacture a quarter or Q4.
- Prefer the filing for the reporting period over a later comparative disclosure and the most recent amendment when it reports that field. Use a documented standard-tag priority within the filing. Conflicting duplicate values or currency units from the selected filing produce a blank with provenance. Derived values require matching units and valid inputs. YoY requires a comparable period from the previous year and a nonzero prior value.
- Segment trends begin from a selected fact. Match its issuer, concept, complete dimension combination, unit, and period type. A canonical US GAAP concept can match across taxonomy release namespaces. Exact issuer-specific concepts and dimension values keep their qualified names. Six- and nine-month totals form separate histories.
- Monetary calculations and CSVs use decimal values. Chart plotting uses display precision. Each normalized cell links to its source accession, including all inputs for a calculation. A facts CSV uses the active filters and a single published generation, with a limit of 10,000 matching rows.

Reference validation uses Apple’s [2026 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm) and [June 2026 10-Q](https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/aapl-20260627.htm), with synthetic amendment, conflict, and interrupted-publication cases in the offline fixture.
