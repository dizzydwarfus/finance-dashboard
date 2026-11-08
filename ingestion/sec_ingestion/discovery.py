from datetime import timedelta
from urllib.parse import quote
from .models import Problem
from .store import now

REGISTRY_URL = "https://www.sec.gov/files/company_tickers.json"
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


class Discovery:
    def __init__(self, store, client):
        self.store, self.client = store, client

    def refresh_registry(self):
        rows = self.client.json(REGISTRY_URL)
        if not isinstance(rows, dict):
            raise Problem(503, "invalid_registry", "SEC returned an unexpected ticker registry")
        entries = []
        for row in rows.values():
            if isinstance(row, dict) and row.get("ticker") and str(row.get("cik_str", "")).isdigit():
                entries.append({"symbol": row["ticker"].upper(), "cik": str(row["cik_str"]).zfill(10), "name": row.get("title", row["ticker"])})
        if not entries:
            raise Problem(503, "invalid_registry", "SEC returned an empty ticker registry")
        # Keep the last good snapshot when a download or validation fails.
        self.store.db.registry.update_one({"_id": "tickers"}, {"$set": {"entries": entries, "updatedAt": now(), "source": getattr(self.client, "last_source", None)}}, upsert=True)
        return entries

    def resolve(self, symbol):
        snapshot = self.store.db.registry.find_one({"_id": "tickers"})
        if not snapshot or snapshot["updatedAt"] < now() - timedelta(days=1):
            entries = self.refresh_registry()
        else:
            entries = snapshot["entries"]
        candidates = [row for row in entries if row["symbol"] == symbol]
        if not candidates:
            raise Problem(404, "sec_symbol_not_found", "This exact ticker is not in the SEC registry")
        ciks = {row["cik"] for row in candidates}
        if len(ciks) != 1:
            raise Problem(409, "ambiguous_issuer", "SEC lists more than one issuer for this ticker; the import was not started")
        return {**candidates[0], "symbols": sorted({row["symbol"] for row in entries if row["cik"] in ciks})}

    def filings(self, issuer, request, job_id):
        cik = issuer["cik"]
        submissions = self.client.json(f"https://data.sec.gov/submissions/CIK{cik}.json", job_id=job_id)
        if str(submissions.get("cik", "")).zfill(10) != cik:
            raise Problem(422, "issuer_mismatch", "SEC submissions did not match the requested issuer")
        recent = submissions.get("filings", {}).get("recent", {})
        groups = [recent]
        historical = submissions.get("filings", {}).get("files", [])
        for file in historical:
            if request["selection"] == "range":
                if file.get("filingTo", "") < request["fromDate"] or file.get("filingFrom", "") > request["toDate"]:
                    continue
            else:
                recent_forms = {form for group in groups for form in group.get("form", [])}
                required = {"10-K", "10-Q"} if request["selection"] in {"latest", "company-facts"} else {request["selection"]}
                if required.issubset(recent_forms):
                    break
            name = file.get("name", "")
            if "/" in name or not name.endswith(".json") or not name.startswith("CIK"):
                raise Problem(422, "invalid_submissions_reference", "SEC supplied an invalid historical submissions reference")
            groups.append(self.client.json(f"https://data.sec.gov/submissions/{quote(name)}", job_id=job_id))
        selected = {}
        for group in groups:
            for i, accession in enumerate(group.get("accessionNumber", [])):
                row = {key: values[i] for key, values in group.items() if isinstance(values, list) and len(values) > i}
                if row.get("form") not in FORMS:
                    continue
                if request["selection"] == "range" and not request["fromDate"] <= row.get("filingDate", "") <= request["toDate"]:
                    continue
                row.update({"accession": accession, "cik": cik, "folderUrl": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"})
                row["sourceUrl"] = row["folderUrl"] + quote(row.get("primaryDocument", ""))
                selected[accession] = row
        rows = list(selected.values())
        if request["selection"] != "range":
            families = {"10-K", "10-Q"} if request["selection"] in {"latest", "company-facts"} else {request["selection"]}
            chosen = []
            for family in families:
                base = sorted((r for r in rows if r["form"] == family), key=lambda r: r["filingDate"], reverse=True)
                if base:
                    chosen.append(base[0])
                    chosen.extend(r for r in rows if r["form"] == family + "/A" and r.get("reportDate") == base[0].get("reportDate"))
            rows = chosen
        if not rows and request["selection"] != "company-facts":
            raise Problem(422, "unsupported_issuer", "No supported US 10-K or 10-Q filings are available for this selection")
        if len(rows) > 25:
            raise Problem(422, "too_many_filings", "More than 25 filings match; choose a shorter date range")
        issuer.update({"name": submissions.get("name", issuer["name"]), "exchanges": submissions.get("exchanges", []), "sic": submissions.get("sic"), "sicDescription": submissions.get("sicDescription", "")})
        return sorted(rows, key=lambda r: (r["filingDate"], r["accession"]), reverse=True)

    def entrypoint(self, filing, job_id):
        index = self.client.json(filing["folderUrl"] + "index.json", job_id=job_id)
        names = [entry.get("name", "") for entry in index.get("directory", {}).get("item", [])]
        names = [name for name in names if name and "/" not in name and not name.startswith(".")]
        extracted = sorted(name for name in names if name.endswith("_htm.xml"))
        if extracted:
            return filing["folderUrl"] + quote(extracted[0])
        instances = [name for name in names if name.endswith(".xml") and not name.endswith(("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")) and name not in {"FilingSummary.xml", "Financial_Report.xlsx", "R1.xml"} and not name.startswith("R")]
        if instances:
            # Only accept a real xbrl instance, never assume the first XML is one.
            for name in sorted(instances):
                url = filing["folderUrl"] + quote(name)
                response = self.client.get(url, job_id=job_id)
                if b"<xbrl" in response.content[:5000] or b":xbrl" in response.content[:5000]:
                    return url
        if filing.get("isInlineXBRL") or filing.get("isXBRL"):
            return filing["sourceUrl"]
        raise Problem(422, "no_xbrl", "This filing has no supported XBRL facts (some amendments contain only text)")
