import json
from pathlib import Path
from copy import deepcopy
from jsonschema import Draft7Validator
from fastapi.testclient import TestClient
from sec_ingestion.app import create_app
from sec_ingestion.store import public
from .test_runner import ready_job


def validator(name):
    contract=json.loads((Path(__file__).parents[2]/'docs/openapi.json').read_text())
    def convert(value):
        if isinstance(value,list): return [convert(item) for item in value]
        if not isinstance(value,dict): return value
        row={key:convert(item) for key,item in value.items() if key!='nullable'}
        if value.get('nullable'): return {'anyOf':[row,{'type':'null'}]}
        return row
    schema=convert(contract['components']['schemas'][name])
    schema['components']=convert(contract['components'])
    return Draft7Validator(schema)


def test_published_http_responses_follow_shared_openapi(store,settings,issuer):
    runner,job,filing=ready_job(store,settings,issuer)
    runner.process(job)
    c=TestClient(create_app(settings,store,start_runner=False))
    for path,schema in [('/companies','SECCompanyPage'),('/companies/DEMO','SECCompanyResponse'),('/companies/DEMO/filings','SECFilingPage'),('/filings/'+filing['accession']+'/facts','SECFactPage'),('/jobs/'+job['_id'],'SECJobResponse')]:
        response=c.get('/api/v1/sec'+path)
        assert response.status_code==200
        validator(schema).validate(response.json())


def test_csv_exports_use_the_published_generation_and_escape_text(store, settings, issuer):
    from csv import DictReader
    from io import StringIO

    runner, job, filing = ready_job(store, settings, issuer)
    runner.process(job)
    accession = filing["accession"]
    published = store.db.filings.find_one({"_id": accession})["generation"]
    changed = store.db.facts.find_one({"accession": accession, "generation": published, "ordinal": 0})
    store.db.facts.insert_one({**changed, "_id": "interrupted", "generation": "incomplete", "value": "1"})
    store.db.facts.update_one({"_id": changed["_id"]}, {"$set": {"label": "  =not a formula"}})
    c = TestClient(create_app(settings, store, start_runner=False))

    filings = c.get("/api/v1/sec/companies/DEMO/filings?format=csv")
    assert filings.status_code == 200
    assert list(DictReader(StringIO(filings.text)))[0]["sourceUrl"] == filing["sourceUrl"]

    facts = c.get(f"/api/v1/sec/filings/{accession}/facts", params={
        "format": "csv", "concept": "Revenue", "dimension": "consolidated", "limit": 1,
    })
    assert facts.status_code == 200
    assert facts.headers["content-type"].startswith("text/csv")
    assert 'attachment' in facts.headers["content-disposition"]
    rows = list(DictReader(StringIO(facts.text)))
    assert len(rows) == 2
    assert rows[0]["label"] == "'  =not a formula"
    assert rows[0]["value"] == "123456789012345678.00"
    assert rows[0]["end_date"] == "2025-09-27"
    assert rows[0]["unit"].endswith("USD")
