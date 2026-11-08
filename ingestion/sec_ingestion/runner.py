from datetime import timedelta
from pathlib import Path
from threading import Event, Thread, Lock
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pymongo import ReturnDocument
from pymongo.errors import BulkWriteError
from .bundle import build_bundle
from .discovery import Discovery
from .models import Problem, ACTIVE
from .parse_diagnostics import PARSE_MESSAGES, diagnostic_codes
from .store import now, digest
from .transport import SECClient, RatePause


class Runner:
    def __init__(self, store, settings, client_factory=SECClient):
        self.store, self.settings, self.client_factory = store, settings, client_factory
        self.owner = str(uuid.uuid4())
        self.stop_event, self.lease_lost = Event(), Event()
        self.thread = None
        self.lock = Lock()

    def wake(self):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = Thread(target=self.loop, name="sec-queue", daemon=True)
                self.thread.start()

    def shutdown(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def cancelled(self, job_id):
        job = self.store.db.jobs.find_one({"_id": job_id})
        return self.stop_event.is_set() or self.lease_lost.is_set() or not job or bool(job.get("cancelRequested"))

    def assert_owned(self):
        if not self.store.db.control.find_one({"_id": "runner", "leaseOwner": self.owner, "leaseUntil": {"$gt": now()}}):
            self.lease_lost.set()
            raise Problem(409, "lease_lost", "The ingestion lease was reassigned; this process stopped")

    def heartbeat(self, finished):
        while not finished.wait(5):
            try:
                result = self.store.db.control.update_one({"_id": "runner", "leaseOwner": self.owner}, {"$set": {"leaseUntil": now() + timedelta(seconds=30)}})
                if not result.matched_count:
                    self.lease_lost.set()
                    return
            except Exception:
                self.lease_lost.set()
                return

    def loop(self):
        try:
            self.store.ready()
            self.store.reconcile()
            if self.store.db.control.find_one({"_id": "maintenance", "enabled": True}):
                return
            budget = self.store.db.control.find_one({"_id": "sec_budget"})
            if budget.get("blocked") or budget.get("blockedUntil", now()) > now():
                return
            owned = self.store.db.control.find_one_and_update(
                {"_id": "runner", "leaseUntil": {"$lte": now()}},
                {"$set": {"leaseOwner": self.owner, "leaseUntil": now() + timedelta(seconds=30)}, "$inc": {"epoch": 1}}, return_document=ReturnDocument.AFTER)
            if not owned:
                return
            self.lease_lost.clear()
            finished = Event()
            pulse = Thread(target=self.heartbeat, args=(finished,), daemon=True)
            pulse.start()
            try:
                while not self.stop_event.is_set():
                    self.assert_owned()
                    if self.store.db.control.find_one({"_id": "maintenance", "enabled": True}):
                        return
                    job = self.store.db.jobs.find_one({"status": {"$in": ["queued", "running", "paused_rate_limit"]}}, sort=[("createdAt", 1)])
                    if not job:
                        return
                    if job["parserVersion"] != self.settings.parser_version:
                        self.store.finish(job["_id"], "failed", error={"code": "parser_version_changed", "message": "Refresh this issuer using the current parser version"})
                        continue
                    self.process(job)
                    budget = self.store.db.control.find_one({"_id": "sec_budget"})
                    if budget.get("blocked") or budget.get("blockedUntil", now()) > now():
                        return
            finally:
                finished.set()
                pulse.join(timeout=1)
                self.store.db.control.update_one({"_id": "runner", "leaseOwner": self.owner}, {"$set": {"leaseUntil": now()}})
        except Exception:
            # The durable coordinator retries queue wake-up. Never print raw Mongo/HTTP exceptions.
            return

    def process(self, job):
        job_id = job["_id"]
        if self.cancelled(job_id):
            if self.stop_event.is_set() or self.lease_lost.is_set():
                return
            self.store.finish(job_id, "cancelled")
            return
        self.store.update_job(job_id, status="running", stage="company_lookup", error=None, retryAt=None)
        client = self.client_factory(self.store, self.settings, cancelled=lambda: self.cancelled(job_id))
        discovery = Discovery(self.store, client)
        try:
            issuer = dict(job["issuer"])
            if job["request"]["selection"] == "company-facts":
                self.company_facts(job, issuer, client)
                return
            filings = job.get("filingPlan")
            if filings is None:
                filings = discovery.filings(issuer, job["request"], job_id)
                self.store.update_job(job_id, total=len(filings), filingPlan=filings, issuer=issuer)
            failures, warnings, completed = [], [], 0
            for filing in filings:
                if self.cancelled(job_id):
                    raise Problem(409, "cancelled", "Scraping was cancelled")
                self.assert_owned()
                checkpoint_id = job_id + ":" + filing["accession"]
                checkpoint = self.store.db.job_filings.find_one({"_id": checkpoint_id, "status": {"$in": ["completed", "skipped"]}})
                if checkpoint:
                    completed += 1
                    continue
                self.store.update_job(job_id, stage="downloading", currentAccession=filing["accession"], completed=completed)
                try:
                    with tempfile.TemporaryDirectory(prefix="sec-filing-") as directory:
                        entry = discovery.entrypoint(filing, job_id)
                        bundle = build_bundle(client, entry, directory, job_id)
                        source_manifest = [{k: v for k, v in source.items() if k != "file"} for source in bundle["sources"]]
                        generation = digest({"sources": sorted(({k: v for k, v in source.items() if k not in {"retrievedAt", "availability"}} for source in source_manifest), key=lambda s: s["url"]), "parser": self.settings.parser_version})
                        self.store.db.job_filings.update_one({"_id": checkpoint_id}, {"$set": {"jobId": job_id, "accession": filing["accession"], "status": "downloaded", "sources": source_manifest, "generation": generation, "parserVersion": self.settings.parser_version, "updatedAt": now()}}, upsert=True)
                        old = self.store.db.filings.find_one({"_id": filing["accession"]})
                        if not old or old.get("generation") != generation:
                            self.store.update_job(job_id, stage="parsing")
                            result = self.parse(directory, bundle, job_id)
                            self.store.update_job(job_id, stage="saving")
                            self.publish(job, issuer, filing, result, source_manifest, generation)
                            warnings.extend(result.get("warnings", []))
                        else:
                            self.store.db.filings.update_one({"_id": filing["accession"]}, {"$set": {"lastCheckedAt": now(), "sourceAvailability": "available"}})
                        self.store.db.job_filings.update_one({"_id": checkpoint_id}, {"$set": {"jobId": job_id, "accession": filing["accession"], "status": "completed", "updatedAt": now()}}, upsert=True)
                        completed += 1
                        self.store.update_job(job_id, completed=completed)
                except RatePause:
                    raise
                except Problem as error:
                    if error.code in {"cancelled", "lease_lost", "sec_blocked"}:
                        raise
                    if error.code == "no_xbrl" and filing["form"].endswith("/A"):
                        warnings.append(f"{filing['accession']}: amendment has no XBRL; original filing retained")
                        self.store.db.job_filings.update_one({"_id": checkpoint_id}, {"$set": {"jobId": job_id, "accession": filing["accession"], "status": "skipped", "updatedAt": now()}}, upsert=True)
                        completed += 1
                        self.store.update_job(job_id, completed=completed, warnings=sorted(set(warnings))[:100])
                        continue
                    failures.append({"accession": filing["accession"], "code": error.code, "message": error.message, **error.details})
                    if error.code == "source_unavailable":
                        self.store.db.filings.update_one({"_id": filing["accession"]}, {"$set": {"sourceAvailability": "unavailable", "lastCheckedAt": now()}})
                    self.store.db.job_filings.update_one({"_id": checkpoint_id}, {"$set": {"jobId": job_id, "accession": filing["accession"], "status": "failed", "error": failures[-1], "updatedAt": now()}}, upsert=True)
                    self.store.update_job(job_id, failures=failures, warnings=sorted(set(warnings))[:100])
            self.assert_owned()
            if self.cancelled(job_id):
                raise Problem(409, "cancelled", "Scraping was cancelled")
            status = "partial_failed" if failures and completed else "failed" if failures else "completed"
            self.store.finish(job_id, status, failures=failures, warnings=sorted(set(warnings))[:100], completed=completed)
        except RatePause as error:
            if self.stop_event.is_set() or self.lease_lost.is_set():
                return
            self.assert_owned()
            self.store.update_job(job_id, status="paused_rate_limit", stage="paused_rate_limit", retryAt=error.retry_at, error={"code": error.code, "message": error.message})
        except Problem as error:
            if error.code == "lease_lost" or self.lease_lost.is_set() or self.stop_event.is_set():
                return
            self.assert_owned()
            self.store.finish(job_id, "cancelled" if error.code == "cancelled" else "blocked" if error.code == "sec_blocked" else "failed", error={"code": error.code, "message": error.message, **error.details})
        except Exception:
            if self.stop_event.is_set() or self.lease_lost.is_set():
                return
            self.assert_owned()
            self.store.finish(job_id, "failed", error={"code": "ingestion_failed", "message": "The import could not complete; completed filings were preserved. Retry to resume."})

        finally:
            if hasattr(client, "http"):
                client.http.close()

    def parse(self, directory, bundle, job_id):
        bundle_file, result_file = Path(directory) / "bundle.json", Path(directory) / "result.json"
        bundle_file.write_text(json.dumps(bundle))
        child_env = {key: value for key, value in os.environ.items() if not any(word in key for word in ("MONGODB", "ACCESS", "TOKEN", "SECRET", "SEC_USER_AGENT"))}
        child_env["XDG_CACHE_HOME"] = str(Path(directory) / "cache")
        with subprocess.Popen([sys.executable, "-m", "sec_ingestion.parser", str(bundle_file), str(result_file)], env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
            deadline = time.monotonic() + 300
            while child.poll() is None:
                if self.cancelled(job_id) or time.monotonic() > deadline:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                    if self.cancelled(job_id):
                        raise Problem(409, "cancelled", "Scraping was cancelled")
                    raise Problem(422, "parse_timeout", "This filing exceeded the five-minute parser limit")
                time.sleep(.1)
            if child.returncode or not result_file.exists():
                detail = {}
                if result_file.exists():
                    try:
                        detail = json.loads(result_file.read_text()).get("error", {})
                    except (ValueError, AttributeError):
                        pass
                code = detail.get("code") if isinstance(detail, dict) else None
                code = code if code in PARSE_MESSAGES else "parse_failed"
                codes = detail.get("diagnostics", []) if isinstance(detail, dict) else []
                raise Problem(422, code, PARSE_MESSAGES[code], diagnostics=diagnostic_codes(codes) if isinstance(codes, list) else [])
        return json.loads(result_file.read_text())

    def publish(self, job, issuer, filing, result, sources, generation):
        self.assert_owned()
        accession = filing["accession"]
        for collection in ("facts", "contexts", "units", "labels", "relationships"):
            rows = result[collection] if collection == "facts" else sorted(result[collection], key=digest)
            records = ({**row, "_id": digest([accession, generation, collection, ordinal]), "accession": accession,
                        "cik": job["cik"], "generation": generation} for ordinal, row in enumerate(rows))
            self.write_generation(collection, records, job["_id"])
        self.assert_owned()
        # Publication is a single-document pointer switch; staging rows are never returned by readers.
        self.store.db.filings.update_one({"_id": accession}, {"$set": {**filing, "generation": generation, "parserVersion": self.settings.parser_version,
            "sources": sources, "factCount": len(result["facts"]), "lastUpdated": now(), "lastCheckedAt": now(), "sourceAvailability": "available"}}, upsert=True)
        self.store.db.issuers.update_one({"_id": job["cik"]}, {"$set": {**{k: v for k, v in issuer.items() if k != "symbols"}, "lastUpdated": now()}, "$addToSet": {"symbols": {"$each": issuer["symbols"]}}}, upsert=True)

    def company_facts(self, job, issuer, client):
        self.store.update_job(job["_id"], stage="downloading", total=1)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{job['cik']}.json"
        data = client.json(url, job_id=job["_id"])
        if str(data.get("cik", "")).zfill(10) != job["cik"]:
            raise Problem(422, "issuer_mismatch", "Company facts did not match the requested issuer")
        generation = digest({"data": data, "parser": self.settings.parser_version})
        records = []
        for taxonomy, concepts in data.get("facts", {}).items():
            for concept, detail in concepts.items():
                for unit, observations in detail.get("units", {}).items():
                    for observation in observations:
                        count = len(records)
                        records.append({"_id": digest([job["cik"], generation, count]), "cik": job["cik"], "generation": generation, "ordinal": count,
                               "concept": f"{taxonomy}:{concept}", "label": detail.get("label", concept), "value": str(observation["val"]) if observation.get("val") is not None else None, "nil": observation.get("val") is None,
                               "unitRef": unit, "dimensions": [], "startDate": observation.get("start"), "endDate": observation.get("end"), "instant": observation.get("end") if not observation.get("start") else None,
                               "accession": observation.get("accn"), "form": observation.get("form"), "filed": observation.get("filed"), "fiscalYear": observation.get("fy"), "fiscalPeriod": observation.get("fp"), "frame": observation.get("frame"), "sourceUrl": url})
        self.write_generation("company_facts", iter(records), job["_id"])
        count = len(records)
        self.assert_owned()
        self.store.db.issuers.update_one({"_id": job["cik"]}, {"$set": {"companyFactsGeneration": generation, "companyFactsCount": count, "companyFactsUpdatedAt": now(), "companyFactsParserVersion": self.settings.parser_version, "companyFactsSource": getattr(client, "last_source", {"url": url})}})
        self.store.finish(job["_id"], "completed", completed=1, factCount=count)

    def write_generation(self, collection, records, job_id):
        # Immutable generation rows: duplicate IDs are checkpointed writes from the same source/parser.
        from itertools import islice
        iterator = iter(records)
        while batch := list(islice(iterator, 500)):
            self.assert_owned()
            if self.cancelled(job_id):
                raise Problem(409, "cancelled", "Scraping was cancelled")
            try:
                self.store.db[collection].insert_many(batch, ordered=False)
            except BulkWriteError as error:
                if error.details.get("writeConcernErrors") or any(item.get("code") != 11000 for item in error.details.get("writeErrors", [])):
                    raise
