from datetime import timedelta
from copy import deepcopy
import uuid
import pytest
from sec_ingestion.store import now
from sec_ingestion.models import JobRequest, Problem
from sec_ingestion.runner import Runner
from .conftest import BASE, FixtureClient


class FilingClient(FixtureClient):
    def json(self, url, **kwargs):
        if url.endswith('index.json'):
            return {'directory':{'item':[{'name':'filing.xml'}]}}
        raise AssertionError('No unexpected SEC requests')


def ready_job(store, settings, issuer):
    job, _ = store.submit(issuer,JobRequest(symbol='DEMO').model_dump(mode='json'),str(uuid.uuid4()),settings.parser_version)
    filing={'cik':issuer['cik'],'accession':'0000000001-25-000001','form':'10-K','filingDate':'2025-11-01','reportDate':'2025-09-27','folderUrl':BASE,'sourceUrl':BASE+'filing.xml'}
    store.update_job(job['_id'],filingPlan=[filing],total=1)
    runner=Runner(store,settings,FilingClient)
    store.db.control.update_one({'_id':'runner'},{'$set':{'leaseOwner':runner.owner,'leaseUntil':now()+timedelta(minutes=3)}})
    return runner,store.get_job(job['_id']),filing


def test_real_parser_publish_resume_and_refresh_are_idempotent(store,settings,issuer):
    runner,job,filing=ready_job(store,settings,issuer)
    runner.process(job)
    result=store.get_job(job['_id'])
    assert result['status']=='completed',result
    assert store.db.facts.count_documents({}) == 6
    assert store.db.issuers.find_one({'_id':issuer['cik']})['lastSuccessfullyScrapedAt']
    count=store.db.facts.count_documents({})
    runner.process(store.get_job(job['_id']))
    assert store.db.facts.count_documents({}) == count
    assert store.db.job_filings.count_documents({'status':'completed'}) == 1


def test_failed_generation_does_not_replace_successful_filing(store,settings,issuer,monkeypatch):
    runner,job,filing=ready_job(store,settings,issuer)
    runner.process(job)
    old=store.db.filings.find_one({'_id':filing['accession']})['generation']
    from sec_ingestion.models import Problem
    records={'facts':[{'concept':'changed','value':'9'}],'contexts':[],'units':[],'labels':[],'relationships':[]}
    def interrupted(*args,**kwargs): raise Problem(409,'cancelled','Cancelled')
    monkeypatch.setattr(runner,'cancelled',lambda _: False)
    monkeypatch.setattr(store.db.facts,'insert_many',interrupted)
    with pytest.raises(Problem):runner.publish(job,issuer,filing,records,[],'incomplete')
    assert store.db.filings.find_one({'_id':filing['accession']})['generation'] == old


def test_lost_lease_prevents_publication(store,settings,issuer):
    runner,job,filing=ready_job(store,settings,issuer)
    store.db.control.update_one({'_id':'runner'},{'$set':{'leaseOwner':'another-process'}})
    with pytest.raises(Problem,match='reassigned'):runner.publish(job,issuer,filing,{},[],'bad')
    assert store.db.filings.count_documents({}) == 0


def test_explicit_refresh_reuses_unchanged_generation_and_publishes_corrections(store,settings,issuer):
    runner,job,filing=ready_job(store,settings,issuer)
    runner.process(job)
    original=store.db.filings.find_one({'_id':filing['accession']})['generation']
    def refresh():
        request=JobRequest(symbol='DEMO',action='refresh').model_dump(mode='json')
        row,_=store.submit(issuer,request,str(uuid.uuid4()),settings.parser_version)
        store.update_job(row['_id'],filingPlan=[filing],total=1)
        runner.process(store.get_job(row['_id']))
        assert store.get_job(row['_id'])['status']=='completed'
    refresh()
    assert store.db.facts.count_documents({})==6
    assert store.db.filings.find_one({'_id':filing['accession']})['generation']==original
    class Corrected(FilingClient):
        def get(self,url,**kwargs):
            import httpx
            response=super().get(url,**kwargs)
            return httpx.Response(200,content=response.content.replace(b'123456789012345678.00',b'123456789012345679.00'),request=response.request)
    runner.client_factory=Corrected
    refresh()
    published=store.db.filings.find_one({'_id':filing['accession']})
    assert published['generation']!=original
    assert store.db.facts.count_documents({})==12
    assert store.db.facts.find_one({'generation':published['generation'],'ordinal':0})['value']=='123456789012345679.00'
    assert all(source['retrievedAt'] and source['checksum'] for source in published['sources'])


def test_shutdown_keeps_accepted_job_recoverable_instead_of_cancelling_it(store,settings,issuer,monkeypatch):
    runner,job,filing=ready_job(store,settings,issuer)
    def interrupted(*args):
        runner.stop_event.set()
        raise Problem(409,'cancelled','Process is stopping')
    monkeypatch.setattr(runner,'parse',interrupted)
    runner.process(job)
    assert store.get_job(job['_id'])['status']=='running'
    assert store.db.requests.find_one({'_id':issuer['cik']})['activeJobId']==job['_id']
    replacement=Runner(store,settings,FilingClient)
    store.db.control.update_one({'_id':'runner'},{'$set':{'leaseOwner':replacement.owner,'leaseUntil':now()+timedelta(minutes=3)}})
    replacement.process(store.get_job(job['_id']))
    assert store.get_job(job['_id'])['status']=='completed'


def test_parser_dependency_failure_is_returned_without_raw_details(store,settings,issuer,tmp_path):
    from sec_ingestion.bundle import build_bundle
    from pathlib import Path
    runner,job,filing=ready_job(store,settings,issuer)
    bundle=build_bundle(FixtureClient(),BASE+'filing.xml',tmp_path)
    Path(next(row['file'] for row in bundle['sources'] if row['url']==BASE+'taxonomy.xsd')).unlink()
    with pytest.raises(Problem) as failure:runner.parse(tmp_path,bundle,job['_id'])
    assert failure.value.code=='parse_dependency_missing'
    assert 'IOerror' in failure.value.details['diagnostics']
    assert str(tmp_path) not in failure.value.message
    assert store.db.facts.count_documents({})==0
