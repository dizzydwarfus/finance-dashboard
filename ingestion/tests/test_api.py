from datetime import timedelta
import uuid
from fastapi.testclient import TestClient
from sec_ingestion.app import create_app
from sec_ingestion.store import now


def client(store, settings, issuer):
    store.db.registry.insert_one({"_id": "tickers", "entries": [{"symbol": issuer["symbol"], "cik": issuer["cik"], "name": issuer["name"]}], "updatedAt": now()})
    return TestClient(create_app(settings, store, start_runner=False))


def test_jobs_contract_no_implicit_registry_fetch_and_duplicate_admission(store, settings, issuer):
    c = client(store, settings, issuer)
    assert c.get('/api/v1/sec/companies?q=DEMO').json()['meta']['suggestions'][0]['symbol'] == 'DEMO'
    assert c.get('/api/v1/sec/companies/DEMO').status_code == 404
    body = {'symbol': 'demo'}
    submitted = c.post('/api/v1/sec/jobs', json=body, headers={'Idempotency-Key': str(uuid.uuid4())})
    assert submitted.status_code == 202
    job = submitted.json()['data']
    assert job['status'] == 'queued' and job['cik'] == '0000000001'
    assert c.post('/api/v1/sec/jobs', json=body, headers={'Idempotency-Key': str(uuid.uuid4())}).json()['data']['id'] == job['id']
    assert c.get('/api/v1/sec/jobs/' + job['id']).status_code == 200
    assert c.post('/api/v1/sec/jobs/' + job['id'] + '/cancel', json={}).json()['data']['status'] == 'cancelled'
    assert c.post('/api/v1/sec/jobs/' + job['id'] + '/retry', json={}).json()['data']['id'] == job['id']
    assert c.post('/api/v1/sec/jobs', json={'symbol': '???'}, headers={'Idempotency-Key':'12345678'}).status_code == 422
    assert c.post('/api/v1/sec/jobs', json={'symbol': 'DEMO', 'selection': 'range', 'fromDate': '2008-01-01', 'toDate': '2025-01-01'}, headers={'Idempotency-Key':'12345678'}).status_code == 422
    assert c.post('/api/v1/sec/jobs', content='{}').status_code == 415
    assert c.post('/api/v1/sec/jobs', content='x'*33000, headers={'Content-Type':'application/json'}).status_code == 413


def test_published_generation_only_and_dimensions_filter(store, settings, issuer):
    c = client(store, settings, issuer)
    store.db.issuers.insert_one({'_id': issuer['cik'], **issuer})
    store.db.filings.insert_one({'_id':'0000000001-25-000001','cik':issuer['cik'],'generation':'good','filingDate':'2025-01-01'})
    store.db.facts.insert_many([
        {'_id':'good','accession':'0000000001-25-000001','generation':'good','ordinal':0,'concept':'Revenue','value':'100.10','dimensions':[]},
        {'_id':'segment','accession':'0000000001-25-000001','generation':'good','ordinal':1,'concept':'Revenue','value':'50','dimensions':[{'axis':'ProductAxis','member':'Hardware'}]},
        {'_id':'unfinished','accession':'0000000001-25-000001','generation':'staging','ordinal':0,'concept':'Revenue','value':'900','dimensions':[]},
    ])
    path='/api/v1/sec/filings/0000000001-25-000001/facts'
    result=c.get(path).json()
    assert result['meta']['total'] == 2
    assert c.get(path+'?dimension=consolidated').json()['meta']['total'] == 1
    assert c.get(path+'?dimension=Hardware').json()['data'][0]['value'] == '50'
    assert c.get(path+'?limit=1&offset=1').json()['data'][0]['value'] == '50'
    assert c.get('/api/v1/sec/companies').json()['data'][0]['imported'] is True


def test_missing_schema_requires_explicit_bootstrap(store, settings):
    store.db.schema.delete_many({})
    c=TestClient(create_app(settings,store,start_runner=False))
    assert c.get('/healthz').status_code == 200
    assert c.get('/readyz').json()['error']['code'] == 'schema_setup_required'
    assert store.db.schema.count_documents({}) == 0


def test_completed_fresh_request_never_contacts_sec_again(store,settings,issuer):
    c=client(store,settings,issuer)
    response=c.post('/api/v1/sec/jobs',json={'symbol':'DEMO'},headers={'Idempotency-Key':str(uuid.uuid4())})
    job=response.json()['data']
    store.finish(job['id'],'completed')
    store.db.registry.delete_many({})
    # The original persisted request, not registry freshness or today's parser version, owns a fresh scrape.
    from dataclasses import replace
    c=TestClient(create_app(replace(settings,allow_live=False),store,start_runner=False))
    duplicate=c.post('/api/v1/sec/jobs',json={'symbol':'DEMO'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert duplicate.status_code==200
    assert duplicate.json()['data']['id']==job['id']


def test_identity_missing_and_explicit_lookup_block_recovery(store,settings,issuer):
    from dataclasses import replace
    c=TestClient(create_app(replace(settings,user_agent=''),store,start_runner=False))
    assert c.post('/api/v1/sec/jobs',json={'symbol':'DEMO'},headers={'Idempotency-Key':str(uuid.uuid4())}).json()['error']['code']=='ingestion_not_configured'
    c=client(store,settings,issuer)
    store.db.control.update_one({'_id':'sec_budget'},{'$set':{'blocked':True,'blockedUntil':now()+timedelta(minutes=10)}})
    response=c.post('/api/v1/sec/jobs',json={'symbol':'DEMO','retryAccess':True},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert response.status_code==409
    store.db.control.update_one({'_id':'sec_budget'},{'$set':{'blockedUntil':now()-timedelta(seconds=1)}})
    assert c.post('/api/v1/sec/jobs',json={'symbol':'DEMO','retryAccess':True},headers={'Idempotency-Key':str(uuid.uuid4())}).status_code==202
    assert not store.db.control.find_one({'_id':'sec_budget'})['blocked']


def test_global_block_is_visible_and_queued_job_can_explicitly_resume(store,settings,issuer):
    c=client(store,settings,issuer)
    row=c.post('/api/v1/sec/jobs',json={'symbol':'DEMO'},headers={'Idempotency-Key':str(uuid.uuid4())}).json()['data']
    path='/api/v1/sec/jobs/'+row['id']
    store.db.control.update_one({'_id':'sec_budget'},{'$set':{'blocked':True}})
    assert c.get(path).json()['data']['accessBlocked'] is True
    assert c.post(path+'/retry',json={}).json()['data']['status']=='queued'
    assert not c.get(path).json()['data'].get('accessBlocked')


def test_first_import_accepts_compressed_robots_and_registry(store,settings):
    import gzip
    import httpx
    import json
    from sec_ingestion.transport import SECClient
    from .test_transport import Clock
    clock=Clock()
    def handler(request):
        content=b'User-agent: *\nAllow: /\n' if request.url.path=='/robots.txt' else json.dumps({'0':{'ticker':'DEMO','cik_str':1,'title':'Synthetic issuer'}}).encode()
        compressed=gzip.compress(content)
        return httpx.Response(200,headers={'Content-Encoding':'gzip','Content-Length':str(len(compressed))},stream=httpx.ByteStream(compressed))
    def factory(store,settings,**kwargs):
        return SECClient(store,settings,http=httpx.Client(transport=httpx.MockTransport(handler)),clock=clock.now,sleep=clock.sleep,**kwargs)
    c=TestClient(create_app(settings,store,client_factory=factory,start_runner=False))
    result=c.post('/api/v1/sec/jobs',json={'symbol':'DEMO'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert result.status_code==202
    assert result.json()['data']['status']=='queued'
    assert store.db.registry.find_one({'_id':'robots'})
    assert store.db.registry.find_one({'_id':'tickers'})['entries'][0]['symbol']=='DEMO'


def test_unexpected_errors_are_sanitized_json_instead_of_plain_text(store,settings,caplog):
    class BrokenClient:
        def __init__(self,*args,**kwargs):pass
        def json(self,*args,**kwargs):raise RuntimeError('sensitive diagnostic must never be exposed')
    c=TestClient(create_app(settings,store,client_factory=BrokenClient,start_runner=False))
    result=c.post('/api/v1/sec/jobs',json={'symbol':'DEMO'},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert result.status_code==500
    assert result.headers['content-type'].startswith('application/json')
    assert result.json()['error']['code']=='internal_error'
    assert result.headers['cache-control']=='private, no-store'
    assert 'sensitive diagnostic' not in result.text+caplog.text
