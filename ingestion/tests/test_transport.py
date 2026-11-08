from datetime import datetime, timedelta, timezone
import httpx
import pytest
from sec_ingestion.models import Problem
from sec_ingestion.transport import SECClient, RatePause
from sec_ingestion.store import now


class Clock:
    def __init__(self): self.value = now()
    def now(self): return self.value
    def sleep(self, seconds): self.value += timedelta(seconds=seconds)


def setup(store, settings, handler):
    clock = Clock()
    client = SECClient(store, settings, http=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False), clock=clock.now, sleep=clock.sleep)
    return client, clock


def test_global_spacing_retries_redirects_and_credentials_never_forwarded(store, settings, monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://should-not-be-used.invalid')
    requests, attempts = [], {'value': 0}
    def handler(request):
        requests.append((request, clock.now()))
        assert request.headers['User-Agent'] == settings.user_agent
        for key in ('authorization', 'cookie', 'cf-access-client-secret', 'cf-access-jwt-assertion'):
            assert key not in request.headers
        if request.url.path.endswith('first.json'):
            return httpx.Response(302, headers={'location':'https://data.sec.gov/submissions/final.json'})
        attempts['value'] += 1
        return httpx.Response(503 if attempts['value'] == 1 else 200, json={'ok':True})
    client, clock = setup(store, settings, handler)
    assert client.json('https://data.sec.gov/submissions/first.json') == {'ok':True}
    for (_, previous), (_, current) in zip(requests, requests[1:]):
        assert (current-previous).total_seconds() >= .5
    # Another client instance uses the same durable budget, not a private decorator.
    second = SECClient(store, settings, http=client.http, clock=clock.now, sleep=clock.sleep)
    second.get('https://data.sec.gov/submissions/final.json')
    assert (requests[-1][1]-requests[-2][1]).total_seconds() >= .5


def test_429_cooldown_survives_client_restart_and_403_is_not_retried(store, settings):
    calls=[]
    client, clock = setup(store, settings, lambda request: (calls.append(request), httpx.Response(429, headers={'Retry-After':'900'}))[1])
    with pytest.raises(RatePause): client.get('https://data.sec.gov/submissions/test.json')
    assert len(calls) == 1
    next_client = SECClient(store, settings, http=client.http, clock=clock.now, sleep=clock.sleep)
    with pytest.raises(RatePause): next_client.get('https://data.sec.gov/submissions/test.json')
    assert len(calls) == 1
    assert store.db.control.find_one({'_id':'sec_budget'})['blockedUntil'] >= clock.now()+timedelta(seconds=899)
    clock.sleep(901)
    denied = SECClient(store, settings, http=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))), clock=clock.now, sleep=clock.sleep)
    with pytest.raises(Problem, match='denied'): denied.get('https://data.sec.gov/submissions/test.json')
    with pytest.raises(Problem, match='blocked'): next_client.get('https://data.sec.gov/submissions/test.json')


def test_specific_robots_exclusion_overrides_archive_allow_and_cache_is_reused(store, settings):
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /Archives/edgar/data\nDisallow: /Archives/edgar/data/1/private.xml\n')
        return httpx.Response(200, text='OK')
    client, _ = setup(store, settings, handler)
    with pytest.raises(Problem, match='robots'): client.get('https://www.sec.gov/Archives/edgar/data/1/private.xml')
    client.get('https://www.sec.gov/Archives/edgar/data/1/public.xml')
    assert len([url for url in calls if url.endswith('/robots.txt')]) == 1
    assert not any(url.endswith('/private.xml') for url in calls)


def test_source_allowlist_and_identity_are_required(store, settings):
    client, _ = setup(store, settings, lambda _: pytest.fail('No request should be issued'))
    for url in ['https://localhost/secret','https://www.sec.gov/cgi-bin/x','https://data.sec.gov/not-an-api','https://www.sec.gov:9000/files/company_tickers.json','https://www.sec.gov:bad/files/company_tickers.json','https://www.sec.gov/Archives/edgar/data/../../cgi-bin/x','https://www.sec.gov/Archives/edgar/data/%252e%252e/cgi-bin/x']:
        with pytest.raises(Problem): client.get(url)
    from dataclasses import replace
    no_identity = SECClient(store, replace(settings,user_agent=''),http=client.http)
    with pytest.raises(ValueError): no_identity.get('https://data.sec.gov/submissions/test.json')


def test_exact_json_decimals_and_one_automatic_rate_limit_retry(store,settings,issuer):
    from decimal import Decimal
    import uuid
    from sec_ingestion.models import JobRequest
    exact,_=setup(store,settings,lambda _:httpx.Response(200,content=b'{"amount":123456789012345678.12}'))
    assert exact.json('https://data.sec.gov/submissions/test.json')['amount']==Decimal('123456789012345678.12')
    job,_=store.submit(issuer,JobRequest(symbol='DEMO').model_dump(mode='json'),str(uuid.uuid4()),settings.parser_version)
    limited,clock=setup(store,settings,lambda _:httpx.Response(429))
    with pytest.raises(RatePause): limited.get('https://data.sec.gov/submissions/test.json',job_id=job['_id'])
    clock.sleep(601)
    with pytest.raises(Problem,match='throttled this job again'): limited.get('https://data.sec.gov/submissions/test.json',job_id=job['_id'])
    assert store.db.control.find_one({'_id':'sec_budget'})['blocked']


@pytest.mark.parametrize('encoding', ['gzip', 'deflate'])
def test_compressed_stream_is_decoded_once_and_buffer_headers_are_correct(store, settings, encoding):
    import gzip
    import zlib
    payload=b'{"amount":123456789012345678.12}'
    compressed=(gzip.compress if encoding=='gzip' else zlib.compress)(payload)
    client,_=setup(store,settings,lambda _:httpx.Response(200,headers={'Content-Encoding':encoding,'Content-Length':str(len(compressed)),'ETag':'"fixture"'},stream=httpx.ByteStream(compressed)))
    response=client.get('https://data.sec.gov/submissions/test.json')
    assert response.content==payload
    assert 'content-encoding' not in response.headers
    assert int(response.headers['content-length'])==len(payload)
    assert response.headers['etag']=='"fixture"'
    assert response.json()['amount']  # Reading the buffered response must not decode it again.


@pytest.mark.parametrize('status', [403,429])
def test_access_controls_are_honored_even_when_error_body_has_broken_compression(store,settings,status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,headers={'Content-Encoding':'gzip'},stream=httpx.ByteStream(b'not gzip'))
    client,_=setup(store,settings,handler)
    with pytest.raises(Problem) as failure:client.get('https://data.sec.gov/submissions/test.json')
    assert failure.value.code==('sec_blocked' if status==403 else 'sec_rate_limited')
    assert len(calls)==1


def test_corrupt_successful_compression_returns_retryable_problem(store,settings):
    client,_=setup(store,settings,lambda _:httpx.Response(200,headers={'Content-Encoding':'gzip'},stream=httpx.ByteStream(b'not gzip')))
    client.attempts=1
    with pytest.raises(Problem) as failure:client.get('https://data.sec.gov/submissions/test.json')
    assert failure.value.status==503
    assert failure.value.code=='sec_unavailable'
