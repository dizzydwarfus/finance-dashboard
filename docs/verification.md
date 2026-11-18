# Verification

The SEC analysis build uses the existing published filing generations. A disposable MongoDB fixture confirms separation of annual, standalone quarterly and year-to-date values, exact decimal calculations, amendment precedence, source attribution, scoped read-only access, and exclusion of unpublished generations. Its representative annual and quarterly values are documented in the [financial mapping notes](data-compatibility.md). Local browser tests cover navigation, coverage-based default tabs, CSV filters, and the saved import flow.
