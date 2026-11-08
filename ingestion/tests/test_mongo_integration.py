"""Only a disposable MongoDB server: this creates users and drops SECIngestion."""
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import quote, urlsplit, urlunsplit
import uuid
import pytest
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from sec_ingestion.store import Store
from sec_ingestion.config import Settings
from sec_ingestion.models import JobRequest

URI = os.getenv('SEC_TEST_MONGODB_URI')
pytestmark = pytest.mark.skipif(not URI, reason='Disposable authenticated MongoDB not configured')


def test_unique_requests_recovery_generation_publication_and_database_isolation(issuer):
    admin = MongoClient(URI, tz_aware=True, serverSelectionTimeoutMS=5000)
    admin.admin.command('ping')
    username = 'sec_test_' + uuid.uuid4().hex[:10]
    password = uuid.uuid4().hex
    admin.drop_database('SECIngestion')
    admin.SECIngestion.command('createUser',username,pwd=password,roles=[{'role':'readWrite','db':'SECIngestion'}])
    parsed = urlsplit(URI)
    host = parsed.netloc.rsplit('@',1)[-1]
    writer_uri = urlunsplit((parsed.scheme,f'{username}:{password}@{host}','/SECIngestion','authSource=SECIngestion',''))
    client = MongoClient(writer_uri,tz_aware=True,serverSelectionTimeoutMS=5000)
    try:
        store = Store(client.SECIngestion)
        store.bootstrap(); store.ready()
        payload = JobRequest(symbol='DEMO').model_dump(mode='json')
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = list(pool.map(lambda _: store.submit(issuer,payload,str(uuid.uuid4()),'fixture-parser')[0],range(6)))
        assert len({job['_id'] for job in jobs}) == 1
        assert store.db.requests.count_documents({}) == 1
        assert store.db.jobs.count_documents({}) == 1
        store.finish(jobs[0]['_id'],'completed')
        assert store.submit(issuer,payload,str(uuid.uuid4()),'new-parser')[0]['_id'] == jobs[0]['_id']
        # A real parser subprocess and immutable batched writes, with only this database's writer.
        from .test_runner import ready_job
        runner, job, filing = ready_job(store,Settings(parser_version='fixture-parser'),issuer)
        runner.process(job)
        assert store.get_job(job['_id'])['status']=='completed'
        assert store.db.facts.count_documents({})==6
        runner.process(store.get_job(job['_id']))
        assert store.db.facts.count_documents({})==6
        for database in ('FinanceApp','SECRawData'):
            with pytest.raises(OperationFailure) as denied:
                client[database].forbidden.insert_one({'not':'allowed'})
            assert denied.value.code == 13
            with pytest.raises(OperationFailure): list(client[database].forbidden.find({}))
        with pytest.raises(ValueError): Store(client.FinanceApp)
    finally:
        client.close()
        admin.SECIngestion.command('dropUser',username)
        admin.drop_database('SECIngestion')
        admin.close()
