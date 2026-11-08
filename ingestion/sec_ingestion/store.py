from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import time
import uuid
from pymongo import MongoClient, ReturnDocument, ASCENDING
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern
from .models import Problem, TERMINAL, ACTIVE

UTC = timezone.utc
SCHEMA_VERSION = 1
COLLECTIONS = ("schema", "issuers", "requests", "jobs", "job_filings", "filings", "facts", "contexts", "units", "labels", "relationships", "company_facts", "registry", "control")


def now():
    return datetime.now(UTC)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def public(value):
    if isinstance(value, dict):
        return {("id" if k == "_id" else k): public(v) for k, v in value.items() if k not in {"leaseOwner", "leaseUntil", "generation", "payloadHash", "idempotencyKey", "activeCik"}}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


class Store:
    def __init__(self, database):
        if database.name != "SECIngestion":
            raise ValueError("Ingestion can write only to SECIngestion")
        self.db = database
        self.permissions_verified = False

    @classmethod
    def connect(cls, settings):
        if not settings.uri:
            raise Problem(503, "ingestion_not_configured", "SEC ingestion is not configured")
        client = MongoClient(settings.uri, tz_aware=True, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=10000, maxPoolSize=10)
        return cls(client[settings.database].with_options(write_concern=WriteConcern("majority"), read_concern=ReadConcern("majority"), read_preference=ReadPreference.PRIMARY))

    def verify_permissions(self):
        if self.permissions_verified:
            return
        auth = self.db.command("connectionStatus", showPrivileges=True).get("authInfo", {})
        roles = auth.get("authenticatedUserRoles", [])
        privileges = auth.get("authenticatedUserPrivileges")
        if privileges is None:
            # Older servers may omit expanded privileges; only a known scoped built-in role is safe.
            scoped = bool(roles) and all(role.get("role") in {"read", "readWrite"} and role.get("db") == "SECIngestion" for role in roles)
            scoped = scoped and any(role.get("role") == "readWrite" for role in roles)
        else:
            required = {"find", "insert", "update", "remove", "createCollection", "createIndex", "listCollections", "listIndexes"}
            administrative = {"anyAction", "createUser", "dropUser", "createRole", "dropRole", "grantRole", "revokeRole", "setAuthenticationRestriction"}
            scoped, actions = bool(privileges), set()
            for privilege in privileges:
                resource = privilege.get("resource", {})
                granted = set(privilege.get("actions", []))
                if resource.get("db") != "SECIngestion" or resource.get("cluster") or resource.get("anyResource") or granted & administrative:
                    scoped = False
                if resource.get("db") == "SECIngestion" and resource.get("collection") == "":
                    actions.update(granted)
            scoped = scoped and required.issubset(actions)
        if not scoped:
            raise Problem(503, "writer_role_not_scoped", "The ingestion user needs readWrite-equivalent permissions confined to SECIngestion; broader credentials are refused")
        self.permissions_verified = True

    def bootstrap(self):
        """Explicit setup only. Normal application startup never creates collections/indexes."""
        self.verify_permissions()
        for name in COLLECTIONS:
            if name not in self.db.list_collection_names():
                self.db.create_collection(name)
        self.db.requests.create_index([("cik", ASCENDING)], unique=True, name="one_fresh_request_per_cik")
        self.db.jobs.create_index([("idempotencyKey", ASCENDING)], unique=True, sparse=True)
        self.db.jobs.create_index("activeCik", unique=True, sparse=True, name="one_active_job_per_cik")
        self.db.jobs.create_index([("status", ASCENDING), ("createdAt", ASCENDING)])
        self.db.job_filings.create_index([("jobId", ASCENDING), ("accession", ASCENDING)], unique=True)
        self.db.filings.create_index([("cik", ASCENDING), ("filingDate", ASCENDING)])
        for name in ("facts", "contexts", "units", "labels", "relationships"):
            self.db[name].create_index([("accession", ASCENDING), ("generation", ASCENDING)])
        self.db.facts.create_index([("accession", ASCENDING), ("generation", ASCENDING), ("ordinal", ASCENDING)])
        self.db.company_facts.create_index([("cik", ASCENDING), ("generation", ASCENDING), ("ordinal", ASCENDING)])
        self.db.requests.create_index("symbols")
        self.db.issuers.create_index([("symbols", ASCENDING)])
        for key in ("runner", "admission", "sec_budget", "maintenance"):
            self.db.control.update_one({"_id": key}, {"$setOnInsert": {"leaseUntil": datetime(1970, 1, 1, tzinfo=UTC), "blockedUntil": datetime(1970, 1, 1, tzinfo=UTC), "nextAt": datetime(1970, 1, 1, tzinfo=UTC), "enabled": False}}, upsert=True)
        self.db.schema.update_one({"_id": "ingestion"}, {"$set": {"version": SCHEMA_VERSION, "updatedAt": now()}}, upsert=True)

    def ready(self):
        self.db.command("ping")
        self.verify_permissions()
        if not self.db.schema.find_one({"_id": "ingestion", "version": SCHEMA_VERSION}):
            raise Problem(503, "schema_setup_required", "SEC ingestion requires the explicit database bootstrap command")

    @contextmanager
    def admission(self):
        token = str(uuid.uuid4())
        deadline = time.monotonic() + 5
        while not self.db.control.find_one_and_update({"_id": "admission", "leaseUntil": {"$lte": now()}}, {"$set": {"leaseOwner": token, "leaseUntil": now() + timedelta(seconds=15)}}):
            if time.monotonic() > deadline:
                raise Problem(503, "admission_busy", "Please retry this request")
            time.sleep(.03)
        try:
            yield
        finally:
            self.db.control.update_one({"_id": "admission", "leaseOwner": token}, {"$set": {"leaseUntil": now()}})

    def get_job(self, job_id):
        row = self.db.jobs.find_one({"_id": job_id})
        if not row:
            raise Problem(404, "job_not_found", "Scraping job not found")
        return row

    def submit(self, issuer, payload, key, parser_version):
        cik = str(issuer["cik"]).zfill(10)
        payload_hash = digest(payload)
        with self.admission():
            if self.db.control.find_one({"_id": "maintenance", "enabled": True}):
                raise Problem(503, "ingestion_maintenance", "SEC ingestion is temporarily paused for deployment")
            existing = self.db.jobs.find_one({"idempotencyKey": key})
            if existing:
                if existing["payloadHash"] != payload_hash:
                    raise Problem(409, "idempotency_conflict", "This request key was already used for different inputs")
                return existing, False
            request = self.db.requests.find_one({"_id": cik})
            if payload["action"] == "scrape" and request:
                return self.get_job(request["freshJobId"]), False
            if payload["action"] == "refresh" and not request:
                raise Problem(404, "company_not_imported", "Scrape this issuer before requesting a refresh")
            if request and request.get("activeJobId"):
                active = self.get_job(request["activeJobId"])
                if active["status"] not in TERMINAL:
                    return active, False
            job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "sec-fresh:" + cik)) if payload["action"] == "scrape" else str(uuid.uuid4())
            job = {"_id": job_id, "cik": cik, "activeCik": cik, "symbol": payload["symbol"], "issuer": issuer,
                   "request": payload, "payloadHash": payload_hash, "idempotencyKey": key,
                   "parserVersion": parser_version, "status": "pending", "stage": "queued", "createdAt": now(), "updatedAt": now(),
                   "completed": 0, "total": 0, "failures": [], "warnings": [], "throttleRetries": 0, "attempt": 1}
            try:
                self.db.jobs.update_one({"_id": job_id}, {"$setOnInsert": job}, upsert=True)
            except DuplicateKeyError:
                active = self.db.jobs.find_one({"activeCik": cik})
                if active:
                    if active["status"] == "pending":
                        self.reconcile()
                    return self.get_job(active["_id"]), False
                raise Problem(503, "admission_busy", "The issuer changed state; please retry") from None
            if not request:
                try:
                    self.db.requests.insert_one({"_id": cik, "cik": cik, "freshJobId": job_id, "activeJobId": job_id,
                                                 "symbols": issuer["symbols"], "history": [job_id], "createdAt": now(), "lastUpdated": now()})
                except DuplicateKeyError:
                    return self.get_job(self.db.requests.find_one({"cik": cik})["freshJobId"]), False
            else:
                self.db.requests.update_one({"_id": cik}, {"$set": {"activeJobId": job_id, "lastUpdated": now()}, "$push": {"history": job_id}})
            self.db.jobs.update_one({"_id": job_id, "status": "pending"}, {"$set": {"status": "queued"}})
            return self.get_job(job_id), True

    def reconcile(self):
        for job in self.db.jobs.find({"status": "pending"}):
            request = self.db.requests.find_one({"_id": job["cik"]})
            if not request:
                if job["request"]["action"] != "scrape":
                    continue
                try:
                    self.db.requests.insert_one({"_id": job["cik"], "cik": job["cik"], "symbols": job["issuer"]["symbols"],
                        "freshJobId": job["_id"], "activeJobId": job["_id"], "history": [job["_id"]], "createdAt": job["createdAt"], "lastUpdated": now()})
                except DuplicateKeyError:
                    pass
                request = self.db.requests.find_one({"_id": job["cik"]})
            active_id = request.get("activeJobId")
            if active_id != job["_id"]:
                if active_id and self.get_job(active_id)["status"] not in TERMINAL:
                    continue
                claimed = self.db.requests.update_one({"_id": job["cik"], "activeJobId": active_id}, {
                    "$set": {"activeJobId": job["_id"], "lastUpdated": now()}, "$addToSet": {"history": job["_id"]}})
                if not claimed.matched_count:
                    continue
            self.db.jobs.update_one({"_id": job["_id"], "status": "pending"}, {"$set": {"status": "queued"}})

    def retry_access(self):
        # Explicit user action for a block during ticker lookup, before a CIK job can exist.
        with self.admission():
            if self.db.control.find_one({"_id": "maintenance", "enabled": True}):
                raise Problem(503, "ingestion_maintenance", "SEC ingestion is paused for deployment")
            budget = self.db.control.find_one({"_id": "sec_budget"})
            if budget.get("blockedUntil", now()) > now():
                raise Problem(409, "cooldown_active", "Wait for the SEC request cooldown before retrying", retryAt=public(budget["blockedUntil"]))
            self.db.control.update_one({"_id": "sec_budget"}, {"$set": {"blocked": False}})

    def retry(self, job_id, parser_version):
        with self.admission():
            if self.db.control.find_one({"_id": "maintenance", "enabled": True}):
                raise Problem(503, "ingestion_maintenance", "SEC ingestion is paused for deployment")
            job = self.get_job(job_id)
            budget = self.db.control.find_one({"_id": "sec_budget"})
            if job["status"] in ACTIVE and budget.get("blocked"):
                if budget.get("blockedUntil", now()) > now():
                    raise Problem(409, "cooldown_active", "Wait for the SEC request cooldown before retrying", retryAt=public(budget["blockedUntil"]))
                self.db.control.update_one({"_id": "sec_budget"}, {"$set": {"blocked": False}})
                return job
            if job["status"] not in {"failed", "partial_failed", "blocked", "cancelled"}:
                return job
            if job["parserVersion"] != parser_version:
                raise Problem(409, "parser_version_changed", "Refresh this issuer with the current parser instead of resuming this job")
            request = self.db.requests.find_one({"_id": job["cik"]})
            active_id = request.get("activeJobId")
            if active_id and active_id != job_id and self.get_job(active_id)["status"] not in TERMINAL:
                return self.get_job(active_id)
            budget = self.db.control.find_one({"_id": "sec_budget"})
            if budget.get("blockedUntil", now()) > now():
                raise Problem(409, "cooldown_active", "Wait for the SEC request cooldown before retrying", retryAt=public(budget["blockedUntil"]))
            self.db.control.update_one({"_id": "sec_budget"}, {"$set": {"blocked": False}})
            try:
                self.db.jobs.update_one({"_id": job_id}, {"$set": {"activeCik": job["cik"], "status": "queued", "stage": "queued", "cancelRequested": False, "throttleRetries": 0, "failures": [], "updatedAt": now()}, "$inc": {"attempt": 1}})
            except DuplicateKeyError:
                return self.db.jobs.find_one({"activeCik": job["cik"]})
            self.db.requests.update_one({"_id": job["cik"]}, {"$set": {"activeJobId": job_id, "lastUpdated": now()}})
            return self.get_job(job_id)

    def cancel(self, job_id):
        job = self.get_job(job_id)
        if job["status"] not in TERMINAL:
            self.db.jobs.update_one({"_id": job_id}, {"$set": {"cancelRequested": True, "updatedAt": now()}})
            if job["status"] != "running":
                self.finish(job_id, "cancelled")
        return self.get_job(job_id)

    def update_job(self, job_id, **values):
        self.db.jobs.update_one({"_id": job_id}, {"$set": {**values, "updatedAt": now()}})

    def finish(self, job_id, status, **values):
        job = self.get_job(job_id)
        self.db.jobs.update_one({"_id": job_id}, {"$set": {"status": status, "stage": status, **values, "updatedAt": now()}, "$unset": {"activeCik": ""}})
        updates = {"lastUpdated": now()}
        if status == "completed":
            updates["lastSuccessfullyScrapedAt"] = now()
        self.db.requests.update_one({"_id": job["cik"], "activeJobId": job_id}, {"$set": {**updates, "activeJobId": None}})
        if status in {"completed", "partial_failed"}:
            self.db.issuers.update_one({"_id": job["cik"]}, {"$set": {"lastUpdated": now(), **({"lastSuccessfullyScrapedAt": now()} if status == "completed" else {})}})

    def maintenance(self, enabled):
        with self.admission():
            if enabled and self.db.jobs.count_documents({"status": {"$in": list(ACTIVE)}}):
                raise Problem(409, "ingestion_busy", "Finish or cancel accepted imports before deploying the scraper")
            self.db.control.update_one({"_id": "maintenance"}, {"$set": {"enabled": enabled}})
        return {"maintenance": enabled}

    def queue_state(self):
        budget = self.db.control.find_one({"_id": "sec_budget"}) or {}
        pending = self.db.jobs.count_documents({"status": {"$in": list(ACTIVE)}})
        return {"pending": pending, "blocked": budget.get("blocked", False), "retryAt": public(budget.get("blockedUntil")), "maintenance": bool(self.db.control.find_one({"_id": "maintenance", "enabled": True}))}
