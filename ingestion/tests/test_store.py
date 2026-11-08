from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid
import pytest
from sec_ingestion.models import JobRequest, Problem
from sec_ingestion.store import now


def payload(symbol="DEMO", action="scrape"):
    return JobRequest(symbol=symbol, action=action).model_dump(mode="json")


def submit(store, issuer, action="scrape", symbol="DEMO"):
    return store.submit(issuer, payload(symbol, action), str(uuid.uuid4()), "arelle-v1")[0]


def test_concurrent_fresh_import_aliases_return_one_persisted_request(store, issuer):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: submit(store, issuer, symbol="DEMO.A" if i % 2 else "DEMO"), range(12)))
    assert len({r["_id"] for r in results}) == 1
    assert store.db.requests.count_documents({"cik": issuer["cik"]}) == 1
    assert store.db.jobs.count_documents({}) == 1
    store.finish(results[0]["_id"], "completed")
    assert submit(store, issuer)["_id"] == results[0]["_id"]
    assert submit(store, issuer)["status"] == "completed"


def test_refresh_attaches_concurrent_requests_but_preserves_fresh_request(store, issuer):
    fresh = submit(store, issuer)
    assert submit(store, issuer, "refresh")["_id"] == fresh["_id"]
    store.finish(fresh["_id"], "completed")
    with ThreadPoolExecutor(max_workers=5) as pool:
        refreshed = list(pool.map(lambda _: submit(store, issuer, "refresh"), range(10)))
    assert len({r["_id"] for r in refreshed}) == 1
    assert refreshed[0]["_id"] != fresh["_id"]
    assert submit(store, issuer)["_id"] == fresh["_id"]
    assert len(store.db.requests.find_one({})["history"]) == 2


def test_other_issuers_are_queued_and_only_one_global_lease_is_available(store, issuer):
    first = submit(store, issuer)
    second = submit(store, {**issuer, "cik": "0000000002", "symbol": "OTHER"}, symbol="OTHER")
    assert first["status"] == second["status"] == "queued"
    from sec_ingestion.runner import Runner
    from sec_ingestion.config import Settings
    runners = [Runner(store, Settings()), Runner(store, Settings())]
    def no_work(job):
        store.finish(job["_id"], "completed")
    for runner in runners:
        runner.process = no_work
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda r: r.loop(), runners))
    assert store.db.jobs.count_documents({"status": "completed"}) == 2


def test_failed_import_is_not_implicitly_restarted_and_retry_resumes_same_id(store, issuer):
    job = submit(store, issuer)
    store.finish(job["_id"], "failed")
    assert submit(store, issuer)["status"] == "failed"
    resumed = store.retry(job["_id"], "arelle-v1")
    assert resumed["_id"] == job["_id"] and resumed["attempt"] == 2
    store.finish(job["_id"], "cancelled")
    with pytest.raises(Problem, match="current parser"):
        store.retry(job["_id"], "arelle-v2")


def test_cancel_queue_and_maintenance_guard(store, issuer):
    job = submit(store, issuer)
    with pytest.raises(Problem, match="Finish or cancel"):
        store.maintenance(True)
    assert store.cancel(job["_id"])["status"] == "cancelled"
    store.maintenance(True)
    with pytest.raises(Problem, match="paused"):
        submit(store, issuer, "refresh")
    store.maintenance(False)


def test_reconcile_admitted_pending_request_after_crash(store, issuer):
    job = submit(store, issuer)
    store.db.jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "pending"}})
    store.reconcile()
    assert store.get_job(job["_id"])["status"] == "queued"


def test_broad_writer_credentials_are_refused_before_bootstrap(store):
    from sec_ingestion.models import Problem
    store.permissions_verified=False
    before=store.db.schema.find_one({'_id':'ingestion'})
    store.db.command=lambda *args,**kwargs:{'authInfo':{'authenticatedUserRoles':[{'role':'readWriteAnyDatabase','db':'admin'}]}}
    with pytest.raises(Problem,match='broader credentials'):store.bootstrap()
    assert store.db.schema.find_one({'_id':'ingestion'})==before


def test_unique_active_cik_survives_expired_admission_and_orphaned_pending_job(store,issuer):
    from pymongo.errors import DuplicateKeyError
    first,_=store.submit(issuer,payload(),str(uuid.uuid4()),'v1')
    with pytest.raises(DuplicateKeyError):store.db.jobs.insert_one({'_id':'competing','activeCik':issuer['cik'],'status':'queued'})
    store.finish(first['_id'],'completed')
    refreshed,_=store.submit(issuer,payload(action='refresh'),str(uuid.uuid4()),'v1')
    # A crash between pending job creation and its request-pointer update is recoverable.
    store.update_job(refreshed['_id'],status='pending')
    store.db.requests.update_one({'_id':issuer['cik']},{'$set':{'activeJobId':None}})
    store.reconcile()
    assert store.get_job(refreshed['_id'])['status']=='queued'
    assert store.db.requests.find_one({'_id':issuer['cik']})['activeJobId']==refreshed['_id']


def test_queued_job_can_explicitly_recover_global_access_block(store,issuer):
    job,_=store.submit(issuer,payload(),str(uuid.uuid4()),'v1')
    store.db.control.update_one({'_id':'sec_budget'},{'$set':{'blocked':True}})
    resumed=store.retry(job['_id'],'v1')
    assert resumed['status']=='queued'
    assert not store.db.control.find_one({'_id':'sec_budget'})['blocked']


def test_custom_role_uses_effective_permissions_instead_of_role_name(store):
    actions=['find','insert','update','remove','createCollection','createIndex','listCollections','listIndexes']
    auth={'authenticatedUserRoles':[{'role':'custom-sec-writer','db':'admin'}],
          'authenticatedUserPrivileges':[{'resource':{'db':'SECIngestion','collection':''},'actions':actions}]}
    store.db.command=lambda *args,**kwargs:{'authInfo':auth}
    store.permissions_verified=False
    store.verify_permissions()
    assert store.permissions_verified
    for extra in [
        {'resource':{'db':'FinanceApp','collection':''},'actions':['find']},
        {'resource':{'cluster':True},'actions':['listDatabases']},
        {'resource':{'anyResource':True},'actions':['find']},
        {'resource':{'db':'SECIngestion','collection':''},'actions':['grantRole']},
    ]:
        auth['authenticatedUserPrivileges'].append(extra)
        store.permissions_verified=False
        with pytest.raises(Problem,match='broader credentials'):store.verify_permissions()
        auth['authenticatedUserPrivileges'].pop()
    auth['authenticatedUserPrivileges'][0]['actions']=['find']
    with pytest.raises(Problem,match='readWrite-equivalent'):store.verify_permissions()
