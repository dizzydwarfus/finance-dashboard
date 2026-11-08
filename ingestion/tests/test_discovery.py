from datetime import date
import pytest
from sec_ingestion.discovery import Discovery
from sec_ingestion.models import JobRequest,Problem


def rows(forms,dates=None,periods=None):
    return {'form':forms,'accessionNumber':[f'0000000001-25-{i:06}' for i in range(len(forms))],
            'filingDate':dates or ['2025-11-01']*len(forms),'reportDate':periods or ['2025-09-27']*len(forms),'primaryDocument':['filing.htm']*len(forms),'isInlineXBRL':[1]*len(forms)}
class Client:
    def __init__(self,recent):self.recent=recent
    def json(self,url,**kwargs):
        assert url.endswith('CIK0000000001.json')
        return {'cik':1,'name':'Synthetic','filings':{'recent':self.recent,'files':[]}}


def test_latest_includes_only_associated_amendments(store,issuer):
    recent=rows(['10-K','10-Q','10-K/A','10-K/A','20-F'],['2025-11-01','2025-08-01','2025-11-03','2024-11-01','2025-12-01'],['2025-09-27','2025-06-30','2025-09-27','2024-09-27','2025-09-27'])
    result=Discovery(store,Client(recent)).filings(issuer,JobRequest(symbol='DEMO').model_dump(mode='json'),'job')
    assert [item['form'] for item in result]==['10-K/A','10-K','10-Q']


def test_range_limit_and_unsupported_issuer(store,issuer):
    request=JobRequest(symbol='DEMO',selection='range',fromDate='2025-01-01',toDate='2025-12-31').model_dump(mode='json')
    with pytest.raises(Problem,match='25 filings'):Discovery(store,Client(rows(['10-Q']*26))).filings(issuer,request,'job')
    with pytest.raises(Problem,match='No supported'):Discovery(store,Client(rows(['20-F']))).filings(issuer,request,'job')
    with pytest.raises(ValueError):JobRequest(symbol='DEMO',selection='range',fromDate='2010-01-01',toDate='2016-01-01')
