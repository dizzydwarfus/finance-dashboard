import json
from pathlib import Path
import subprocess
import sys
from sec_ingestion.bundle import build_bundle
from .conftest import FixtureClient, BASE


def parse(tmp_path, filename="filing.xml"):
    bundle = build_bundle(FixtureClient(), BASE + filename, tmp_path)
    input_path, output_path = tmp_path / "bundle.json", tmp_path / "output.json"
    input_path.write_text(json.dumps(bundle))
    result = subprocess.run([sys.executable, "-m", "sec_ingestion.parser", str(input_path), str(output_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(output_path.read_text())


def test_xml_exact_values_dimensions_labels_nils_and_dates(tmp_path):
    result = parse(tmp_path)
    facts = result["facts"]
    assert len(facts) == 6
    assert facts[0]["value"] == "123456789012345678.00"
    assert facts[1]["value"] != facts[0]["value"]
    assert facts[0]["label"] == "Revenue & sales"
    assert facts[0]["endDate"] == "2025-09-27"
    assert facts[0]["startDate"] == "2024-09-29"
    assert facts[2]["dimensions"][0]["member"].endswith("HardwareMember")
    assert facts[3]["nil"] and facts[3]["value"] is None
    assert facts[4]["instant"] == "2025-09-27"
    assert facts[5]["value"] == "-1.25"
    assert len(result["units"]) == 3
    assert facts[0]["sourceUrl"] == BASE + "filing.xml"


def test_inline_sign_scale_and_official_sec_transform(tmp_path):
    result = parse(tmp_path, "inline.htm")
    assert result["facts"][0]["value"] == "-1234500"
    assert result["facts"][1]["value"] == "100"
    assert result["facts"][0]["endDate"] == "2025-03-31"


def test_typed_dimensions_and_missing_label_fallback(tmp_path):
    result=parse(tmp_path,"typed.xml")
    dimension=result['facts'][2]['dimensions'][0]
    assert dimension['member'] is None
    assert dimension['axis'].endswith('RegionAxis')
    assert '>North<' in dimension['typedValue']
    assert result['facts'][5]['label']  # EPS has no label linkbase entry.


def test_custom_role_and_arcrole_references_are_bundled_for_offline_parsing(tmp_path):
    import httpx
    class RoleClient(FixtureClient):
        def get(self,url,**kwargs):
            response=super().get(url,**kwargs)
            content=response.content
            if url.endswith('taxonomy.xsd'):
                content=content.replace(b'</xs:appinfo>',b'<link:linkbaseRef xlink:type="simple" xlink:href="relationships.xml" xlink:role="http://www.xbrl.org/2003/role/presentationLinkbaseRef" xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/></xs:appinfo>')
            return httpx.Response(200,content=content,request=response.request)
    bundle=build_bundle(RoleClient(),BASE+'filing.xml',tmp_path)
    assert any(source['url'].endswith('reference-types.xsd') for source in bundle['sources'])
    manifest=tmp_path/'bundle.json';output=tmp_path/'result.json'
    manifest.write_text(json.dumps(bundle))
    child=subprocess.run([sys.executable,'-m','sec_ingestion.parser',str(manifest),str(output)],capture_output=True,text=True)
    assert child.returncode==0,child.stderr
    result=json.loads(output.read_text())
    assert len(result['facts'])==6
    assert any(row['arcrole'].endswith('parent-child') and row['role']=='https://ledger.invalid/role/statement' for row in result['relationships'])


def test_missing_offline_dependency_reports_safe_diagnostic_codes(tmp_path):
    bundle=build_bundle(FixtureClient(),BASE+'filing.xml',tmp_path)
    taxonomy=next(source for source in bundle['sources'] if source['url']==BASE+'taxonomy.xsd')
    Path(taxonomy['file']).unlink()
    manifest=tmp_path/'bundle.json';output=tmp_path/'result.json'
    manifest.write_text(json.dumps(bundle))
    child=subprocess.run([sys.executable,'-m','sec_ingestion.parser',str(manifest),str(output)],capture_output=True,text=True)
    assert child.returncode==1
    error=json.loads(output.read_text())['error']
    assert error['code']=='parse_dependency_missing'
    assert 'IOerror' in error['diagnostics']
    assert str(tmp_path) not in json.dumps(error)+child.stderr
