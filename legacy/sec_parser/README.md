# SEC parser reference

This experimental Python parser is retained to inform the future Go SEC ingestion port. It is not imported, executed, packaged, or deployed by the new application. The original parsing algorithms and mappings are preserved; UI notifications use the existing logger.

The parser has known limitations across filing formats and older filings; see `design-notes.md`. This is reference material, not a supported ingestion service. Database writers, email alerts, notebooks, and the old web application were removed. No scheduled SEC calls run in v1.

Optional investigation from the repository root: create a separate Python environment, install this directory's requirements, and import `legacy.sec_parser.sec_class`. Supply a real SEC requester identity before any network requests. The future Go implementation must add centralized request limits, retries, durable job tracking, and fixture-based filing tests.
