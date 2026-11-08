"""The only live download path. Arelle is run offline against its output."""
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from decimal import Decimal
import random
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
import httpx
from pymongo import ReturnDocument
from .models import Problem
from .store import now

SEC_HOSTS = {"www.sec.gov", "data.sec.gov", "xbrl.sec.gov"}
HOSTS = SEC_HOSTS | {"xbrl.fasb.org", "fasb.org", "www.xbrl.org", "xbrl.org", "www.w3.org"}
MAX_DOWNLOAD = 50 * 1024 * 1024


def safe_url(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise Problem(422, "unsupported_source", "Invalid filing source URL") from None
    decoded_path = unquote(unquote(parsed.path))
    if "\\" in decoded_path or any(part in {".", ".."} for part in decoded_path.split("/")):
        raise Problem(422, "unsupported_source", "Filing source paths cannot traverse directories")
    if parsed.scheme not in {"https", "http"} or parsed.hostname not in HOSTS or parsed.username or parsed.password or port not in {None, 80, 443}:
        raise Problem(422, "unsupported_source", "A filing references an unsupported source host")
    if parsed.hostname == "data.sec.gov" and not (parsed.path.startswith("/submissions/") or parsed.path.startswith("/api/xbrl/companyfacts/")):
        raise Problem(422, "unsupported_source", "Unsupported SEC API path")
    if parsed.hostname == "www.sec.gov" and not (parsed.path.startswith("/Archives/edgar/data/") or parsed.path == "/files/company_tickers.json" or parsed.path == "/robots.txt"):
        raise Problem(422, "unsupported_source", "Unsupported SEC archive path")
    return urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, ""))


class RatePause(Problem):
    def __init__(self, retry_at):
        super().__init__(503, "sec_rate_limited", "SEC requests are cooling down", retryAt=retry_at.isoformat())
        self.retry_at = retry_at


class SECClient:
    def __init__(self, store, settings, *, http=None, sleep=time.sleep, clock=now, cancelled=lambda: False, timeout=30, attempts=4):
        self.store, self.settings, self.sleep, self.clock, self.cancelled = store, settings, sleep, clock, cancelled
        self.attempts = attempts
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout,10)), follow_redirects=False, trust_env=False)

    def permit(self):
        while True:
            if self.cancelled():
                raise Problem(409, "cancelled", "Scraping was cancelled")
            budget = self.store.db.control.find_one({"_id": "sec_budget"})
            current = self.clock()
            if budget.get("blocked"):
                raise Problem(503, "sec_blocked", "SEC access is blocked; review settings and explicitly retry")
            if budget.get("blockedUntil", current) > current:
                raise RatePause(budget["blockedUntil"])
            if budget.get("nextAt", current) > current:
                self.sleep(min(.5, (budget["nextAt"] - current).total_seconds()))
                continue
            claimed = self.store.db.control.find_one_and_update(
                {"_id": "sec_budget", "nextAt": budget["nextAt"], "blockedUntil": budget["blockedUntil"], "blocked": {"$ne": True}},
                {"$set": {"nextAt": current + timedelta(milliseconds=501)}}, return_document=ReturnDocument.AFTER)
            if claimed:
                return

    def _robots_allowed(self, url):
        """Apply longest matching SEC Allow/Disallow rule, including specific archive exceptions."""
        if urlsplit(url).hostname != "www.sec.gov" or urlsplit(url).path == "/robots.txt":
            return
        cached = self.store.db.registry.find_one({"_id": "robots"})
        if not cached or cached["expiresAt"] < self.clock():
            response = self.get("https://www.sec.gov/robots.txt", check_robots=False)
            text = response.content.decode("utf-8", errors="replace")
            self.store.db.registry.update_one({"_id": "robots"}, {"$set": {"text": text, "expiresAt": self.clock() + timedelta(hours=24)}}, upsert=True)
        else:
            text = cached["text"]
        path = urlsplit(url).path
        active, matches = False, []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = [x.strip() for x in line.split(":", 1)]
            if key.lower() == "user-agent":
                active = value == "*"
            elif active and key.lower() in {"allow", "disallow"} and value:
                pattern = re.escape(value).replace(r"\*", ".*").replace(r"\$", "$")
                if re.match(pattern, path):
                    matches.append((len(value.replace("*", "")), key.lower() == "allow"))
        if matches and not max(matches)[1]:
            raise Problem(422, "robots_disallowed", "This SEC resource is excluded by robots.txt")

    def get(self, url, *, validators=None, job_id=None, check_robots=True):
        self.settings.require_identity()
        if not self.settings.allow_live:
            raise Problem(503, "offline_mode", "Live SEC requests are disabled")
        current_url = safe_url(url)
        if check_robots:
            self._robots_allowed(current_url)
        for attempt in range(self.attempts):
            for redirect in range(6):
                self.permit()
                headers = {"User-Agent": self.settings.user_agent if urlsplit(current_url).hostname in SEC_HOSTS else "Ledger taxonomy downloader", "Accept-Encoding": "gzip, deflate"}
                if validators and not redirect:
                    if validators.get("etag"):
                        headers["If-None-Match"] = validators["etag"]
                    if validators.get("lastModified"):
                        headers["If-Modified-Since"] = validators["lastModified"]
                try:
                    with self.http.stream("GET", current_url, headers=headers) as streamed:
                        chunks, size = [], 0
                        # Error/redirect bodies are unnecessary. Their encoding must not mask
                        # a 403 block or 429 cooldown with a decompression failure.
                        if 200 <= streamed.status_code < 300:
                            if int(streamed.headers.get("content-length", "0")) > MAX_DOWNLOAD:
                                raise Problem(422, "source_too_large", "A filing source exceeds the 50 MiB download limit")
                            for chunk in streamed.iter_bytes(chunk_size=65536):
                                size += len(chunk)
                                if size > MAX_DOWNLOAD:
                                    raise Problem(422, "source_too_large", "A filing source exceeds the 50 MiB download limit")
                                chunks.append(chunk)
                        # iter_bytes already decoded compression. Carrying the original
                        # encoding into a buffered Response would decode the body twice.
                        decoded_headers = streamed.headers.copy()
                        for name in ("content-encoding", "content-length", "transfer-encoding"):
                            decoded_headers.pop(name, None)
                        response = httpx.Response(streamed.status_code, headers=decoded_headers, content=b"".join(chunks), request=streamed.request)
                except (httpx.TransportError, httpx.DecodingError):
                    response = None
                if response is None:
                    break
                if response.status_code in {301, 302, 303, 307, 308}:
                    current_url = safe_url(urljoin(current_url, response.headers.get("location", "")))
                    if check_robots:
                        self._robots_allowed(current_url)
                    continue
                if response.status_code == 403:
                    self.store.db.control.update_one({"_id": "sec_budget"}, {"$set": {"blocked": True}})
                    raise Problem(503, "sec_blocked", "SEC denied access; review the requester identity and Cloudflare egress before retrying", sourceUrl=current_url, httpStatus=403)
                if response.status_code == 429:
                    retry_at = self.clock() + timedelta(minutes=10)
                    retry_after = response.headers.get("retry-after", "")
                    try:
                        retry_at = max(retry_at, self.clock() + timedelta(seconds=int(retry_after)))
                    except ValueError:
                        try:
                            retry_at = max(retry_at, parsedate_to_datetime(retry_after).astimezone(timezone.utc))
                        except (ValueError, TypeError, OverflowError):
                            pass
                    self.store.db.control.update_one({"_id": "sec_budget"}, {"$set": {"blockedUntil": retry_at}})
                    if job_id:
                        job = self.store.db.jobs.find_one_and_update({"_id": job_id}, {"$inc": {"throttleRetries": 1}}, return_document=ReturnDocument.AFTER)
                        if job and job["throttleRetries"] > 1:
                            self.store.db.control.update_one({"_id": "sec_budget"}, {"$set": {"blocked": True}})
                            raise Problem(503, "sec_blocked", "SEC throttled this job again; wait for the cooldown and explicitly retry")
                    raise RatePause(retry_at)
                if response.status_code == 304 or 200 <= response.status_code < 300:
                    return response
                if response.status_code not in {408, 500, 502, 503, 504}:
                    raise Problem(422, "source_unavailable", "An SEC source is unavailable", httpStatus=response.status_code)
                break
            else:
                raise Problem(422, "too_many_redirects", "An SEC source exceeded the redirect limit")
            if attempt < self.attempts - 1:
                self.sleep((2 ** attempt) + random.uniform(0, .25))
        raise Problem(503, "sec_unavailable", "SEC is temporarily unavailable; retry this job later")

    def json(self, url, **kwargs):
        response = self.get(url, **kwargs)
        self.last_source = {"url": str(response.request.url), "checksum": sha256(response.content).hexdigest(), "retrievedAt": self.clock().isoformat(), "availability": "available"}
        try:
            return json.loads(response.text, parse_float=Decimal)
        except ValueError:
            raise Problem(503, "invalid_sec_response", "SEC returned an unexpected response") from None
