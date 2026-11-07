import io
import zipfile
from unittest.mock import Mock
import pytest
from billing_agent.mineru import MinerU


def reply(data=None, content=b'', status=200):
    r=Mock(status_code=status, content=content)
    r.json.return_value=data
    r.iter_content.return_value=iter([content])
    return r


def test_upload_poll_result_without_forwarding_token():
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr('doc/full.md','# Invoice\nUSD 40')
    session=Mock()
    session.request.side_effect=[
        reply({'code':0,'data':{'batch_id':'b1','file_urls':['https://upload.example/file?secret=1']}}),
        reply(status=200),
        reply({'code':0,'data':{'extract_result':[{'state':'done','full_zip_url':'https://result.example/a.zip'}]}}),
        reply(content=buf.getvalue()),
    ]
    client=MinerU(token='private-token',session=session)
    assert 'USD 40' in client.parse(b'%PDF','bill.pdf')
    calls=session.request.call_args_list
    assert calls[0].kwargs['headers']['Authorization']=='Bearer private-token'
    assert 'headers' not in calls[1].kwargs
    assert 'headers' not in calls[3].kwargs
    assert client.metadata['state']=='done'


@pytest.mark.parametrize('response',[reply({'code':'A0202','msg':'private-token'}),reply(status=401)])
def test_auth_failure_sanitized(response):
    session=Mock(); session.request.return_value=response
    with pytest.raises(ValueError) as error:MinerU(token='private-token',session=session).parse(b'x','a.pdf')
    assert 'private-token' not in str(error.value)


def test_empty_zip_rejected():
    with pytest.raises(ValueError):MinerU.read_markdown(b'not zip')


def test_parser_marks_real_provider(tmp_path, monkeypatch):
    from billing_agent.parsers import parse_document
    p=tmp_path/'test.pdf';p.write_bytes(b'%PDF')
    monkeypatch.setenv('BILLING_OCR_PROVIDER','mineru')
    monkeypatch.setattr(MinerU,'parse',lambda self,data,name:'# Actual OCR text')
    monkeypatch.setenv('MINERU_API_TOKEN','test-only')
    result=parse_document(p)
    assert not result.errors
    assert result.chunks[0].source_method=='mineru'
