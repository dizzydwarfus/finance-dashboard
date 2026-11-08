from contextlib import asynccontextmanager
import logging
import re
from typing import Annotated
from fastapi import FastAPI, Query, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from .config import Settings
from .discovery import Discovery
from .models import JobRequest, Problem, TERMINAL, ACTIVE
from .runner import Runner
from .store import Store, public
from .transport import SECClient


def create_app(settings=None, store=None, client_factory=SECClient, start_runner=True):
    settings = settings or Settings.load()
    state = {"store": store, "runner": None}

    def database():
        if state["store"] is None:
            state["store"] = Store.connect(settings)
        return state["store"]

    def ready_store():
        result = database()
        result.ready()
        return result

    def wake():
        if start_runner:
            if not state["runner"]:
                state["runner"] = Runner(database(), settings, client_factory)
            state["runner"].wake()

    @asynccontextmanager
    async def lifespan(app):
        # No schema initialization, registry download, or new scrape on startup.
        yield
        if state["runner"]:
            state["runner"].shutdown()
        if state["store"]:
            state["store"].db.client.close()

    app = FastAPI(title="Ledger SEC ingestion", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.service = state

    @app.middleware("http")
    async def bounds(request: Request, call_next):
        if request.method == "POST":
            if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                return JSONResponse({"error": {"code": "invalid_content_type", "message": "Send application/json"}}, status_code=415)
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 32768:
                    return JSONResponse({"error": {"code": "request_too_large", "message": "Request exceeds 32 KiB"}}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        try:
            response = await call_next(request)
        except Exception as error:
            logging.getLogger(__name__).error("Ingestion request failed (%s)", type(error).__name__)
            response = JSONResponse({"error": {"code": "internal_error", "message": "The SEC service encountered an unexpected error. Please retry."}}, status_code=500)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(Problem)
    async def problem(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message, **public(error.details)}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({"error": {"code": "invalid_request", "message": "Invalid request fields, dates, symbol, or pagination"}}, status_code=422)

    @app.exception_handler(PyMongoError)
    async def mongo_error(request, error):
        return JSONResponse({"error": {"code": "database_unavailable", "message": "SEC data is temporarily unavailable; try again"}}, status_code=503)

    @app.get("/healthz")
    def health():
        return {"data": {"status": "ok"}}

    @app.get("/readyz")
    def readiness():
        ready_store()
        return {"data": {"status": "ready", "parserVersion": settings.parser_version}}

    @app.get("/_internal/state")
    def queue_state():
        return {"data": ready_store().queue_state()}

    @app.post("/_internal/wake")
    def wake_queue():
        result = ready_store().queue_state()
        wake()
        return {"data": result}

    @app.post("/api/v1/sec/maintenance")
    def maintenance(payload: dict):
        if set(payload) != {"enabled"} or not isinstance(payload["enabled"], bool):
            raise Problem(422, "invalid_request", "Specify enabled as a boolean")
        return {"data": ready_store().maintenance(payload["enabled"])}

    @app.get("/api/v1/sec/companies")
    def companies(q: str = Query(default="", max_length=100), limit: int = Query(default=100, ge=1, le=2000)):
        db = ready_store().db
        pattern = re.escape(q.strip())
        query = {"$or": [{"symbols": {"$regex": pattern, "$options": "i"}}, {"name": {"$regex": pattern, "$options": "i"}}]} if q else {}
        imported = list(db.issuers.find(query).sort("name", 1).limit(limit))
        result = []
        for row in imported:
            for symbol in row.get("symbols", [row.get("symbol")]):
                if symbol and (not q or q.lower() in symbol.lower() or q.lower() in row.get("name", "").lower()):
                    result.append({"symbol": symbol, "cik": row["_id"], "name": row["name"], "imported": True, "coverage": ["sec_filings"], "lastUpdated": row.get("lastUpdated"), "lastSuccessfullyScrapedAt": row.get("lastSuccessfullyScrapedAt")})
        # Cached registry suggestions are separate from stored navigation. Reads never fetch SEC.
        snapshot = db.registry.find_one({"_id": "tickers"})
        suggestions = []
        if q and snapshot:
            seen = {r["symbol"] for r in result}
            suggestions = [r for r in snapshot["entries"] if r["symbol"] not in seen and (q.upper() in r["symbol"] or q.lower() in r["name"].lower())][:20]
        return {"data": public(result[:limit]), "meta": {"suggestions": suggestions, "registryUpdatedAt": public(snapshot.get("updatedAt")) if snapshot else None}}

    def issuer_for(symbol):
        normalized = symbol.strip().upper()
        row = ready_store().db.issuers.find_one({"symbols": normalized})
        if not row:
            raise Problem(404, "sec_company_not_found", "No successfully imported SEC data exists for this ticker")
        return row

    @app.get("/api/v1/sec/companies/{symbol}")
    def company(symbol: str):
        row = issuer_for(symbol)
        row["cik"] = row["_id"]
        row["coverage"] = ["sec_filings"]
        request = ready_store().db.requests.find_one({"_id": row["_id"]}) or {}
        row["activeJobId"] = request.get("activeJobId")
        row["freshJobId"] = request.get("freshJobId")
        row.pop("companyFactsGeneration", None)
        return {"data": public(row)}

    @app.get("/api/v1/sec/companies/{symbol}/filings")
    def filings(symbol: str, limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100000)):
        row = issuer_for(symbol)
        db = ready_store().db
        query = {"cik": row["_id"], "generation": {"$exists": True}}
        rows = list(db.filings.find(query).sort([("filingDate", -1), ("_id", -1)]).skip(offset).limit(limit))
        return {"data": public(rows), "meta": {"total": db.filings.count_documents(query), "offset": offset, "limit": limit}}

    def fact_page(collection, query, concept, dimension, offset, limit):
        if concept:
            query["$or"] = [{"concept": {"$regex": re.escape(concept), "$options": "i"}}, {"label": {"$regex": re.escape(concept), "$options": "i"}}]
        if dimension == "consolidated":
            query["dimensions"] = []
        elif dimension:
            pattern = {"$regex": re.escape(dimension), "$options": "i"}
            query["dimensions"] = {"$elemMatch": {"$or": [{"axis": pattern}, {"member": pattern}, {"typedValue": pattern}]}}
        rows = list(collection.find(query).sort("ordinal", 1).skip(offset).limit(limit))
        return {"data": public(rows), "meta": {"total": collection.count_documents(query), "offset": offset, "limit": limit}}

    @app.get("/api/v1/sec/filings/{accession}/facts")
    def facts(accession: str, concept: str = Query(default="", max_length=200), dimension: str = Query(default="", max_length=200), offset: int = Query(default=0, ge=0, le=1000000), limit: int = Query(default=100, ge=1, le=500)):
        db = ready_store().db
        filing = db.filings.find_one({"_id": accession, "generation": {"$exists": True}})
        if not filing:
            raise Problem(404, "filing_not_found", "Imported SEC filing not found")
        result = fact_page(db.facts, {"accession": accession, "generation": filing["generation"]}, concept, dimension, offset, limit)
        units = {u["unitRef"]: {"numerator": u["numerator"], "denominator": u["denominator"]} for u in db.units.find({"accession": accession, "generation": filing["generation"]})}
        for row in result["data"]:
            row["unit"] = units.get(row.get("unitRef"))
        return result

    @app.get("/api/v1/sec/companies/{symbol}/company-facts")
    def company_facts(symbol: str, concept: str = Query(default="", max_length=200), offset: int = Query(default=0, ge=0, le=1000000), limit: int = Query(default=100, ge=1, le=500)):
        row = issuer_for(symbol)
        if not row.get("companyFactsGeneration"):
            return {"data": [], "meta": {"total": 0, "offset": offset, "limit": limit}}
        return fact_page(ready_store().db.company_facts, {"cik": row["_id"], "generation": row["companyFactsGeneration"]}, concept, "", offset, limit)

    @app.post("/api/v1/sec/jobs")
    def submit(payload: JobRequest, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]):
        store = ready_store()
        previous = store.db.jobs.find_one({"idempotencyKey": idempotency_key})
        if previous:
            job, _ = store.submit(previous["issuer"], payload.model_dump(mode="json"), idempotency_key, settings.parser_version)
            wake()
            return JSONResponse({"data": public(job)}, status_code=200 if job["status"] in TERMINAL else 202)
        # Persistent aliases let repeated fresh requests attach without contacting SEC again.
        request = store.db.requests.find_one({"symbols": payload.symbol}) if payload.action == "scrape" else None
        if request:
            original = store.get_job(request["freshJobId"])
            job, created = store.submit(original["issuer"], payload.model_dump(mode="json"), idempotency_key, settings.parser_version)
            wake()
            return JSONResponse({"data": public(job)}, status_code=202 if job["status"] not in TERMINAL else 200)
        try:
            settings.require_identity()
        except ValueError:
            raise Problem(503, "ingestion_not_configured", "Configure SEC_USER_AGENT with an application name and monitored contact email") from None
        if payload.retryAccess:
            store.retry_access()
            wake()
        client = client_factory(store, settings, timeout=5, attempts=1)
        try:
            issuer = Discovery(store, client).resolve(payload.symbol)
        finally:
            if hasattr(client, "http"):
                client.http.close()
        job, created = store.submit(issuer, payload.model_dump(mode="json"), idempotency_key, settings.parser_version)
        wake()
        return JSONResponse({"data": public(job)}, status_code=202 if created or job["status"] not in TERMINAL else 200)

    @app.get("/api/v1/sec/jobs/{job_id}")
    def job(job_id: str):
        store = ready_store()
        row = store.get_job(job_id)
        budget = store.db.control.find_one({"_id": "sec_budget"})
        if budget.get("blocked") and row["status"] in (ACTIVE | {"blocked"}):
            row["accessBlocked"] = True
            row["accessRetryAt"] = budget.get("blockedUntil")
        return {"data": public(row)}

    @app.post("/api/v1/sec/jobs/{job_id}/cancel")
    def cancel(job_id: str, payload: dict):
        if payload:
            raise Problem(422, "invalid_request", "Cancellation expects an empty JSON object")
        return {"data": public(ready_store().cancel(job_id))}

    @app.post("/api/v1/sec/jobs/{job_id}/retry")
    def retry(job_id: str, payload: dict):
        if payload:
            raise Problem(422, "invalid_request", "Retry expects an empty JSON object")
        row = ready_store().retry(job_id, settings.parser_version)
        wake()
        return {"data": public(row)}

    return app


app = create_app()
