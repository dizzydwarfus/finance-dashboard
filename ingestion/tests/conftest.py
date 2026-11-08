from datetime import datetime, timezone
from pathlib import Path
import sys
import mongomock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec_ingestion.store import Store
from sec_ingestion.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/"


@pytest.fixture
def store():
    client = mongomock.MongoClient(tz_aware=True)
    database = client.SECIngestion
    database.command = lambda *a, **kw: {"ok": 1, "authInfo": {"authenticatedUserRoles": [{"role": "readWrite", "db": "SECIngestion"}]}}
    result = Store(database)
    result.bootstrap()
    return result


@pytest.fixture
def settings():
    return Settings(user_agent="Ledger Tests sec-tests@ledger.invalid")


@pytest.fixture
def issuer():
    return {"symbol": "DEMO", "symbols": ["DEMO", "DEMO.A"], "name": "Synthetic issuer", "cik": "0000000001"}


class FixtureClient:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, url, **kwargs):
        import httpx
        name = url.rsplit("/", 1)[-1]
        path = FIXTURES / name
        if not path.is_file():
            raise AssertionError(f"Unexpected fixture request: {url}")
        return httpx.Response(200, content=path.read_bytes(), request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    import httpx
    def forbidden(*args,**kwargs):
        raise AssertionError("Live HTTP is forbidden in ingestion tests; use an offline fixture or MockTransport")
    monkeypatch.setattr(httpx.HTTPTransport,"handle_request",forbidden)
