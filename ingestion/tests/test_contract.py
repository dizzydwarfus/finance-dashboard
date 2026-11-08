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
