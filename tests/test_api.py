import json
import pytest
from billing_agent.models import Chunk


def test_api_extracts_structured_response_and_usage(monkeypatch):
    from billing_agent.api import ResponsesExtractor
    sent = {}
    class Response:
        status_code = 200
        def json(self):
            return {'status':'completed','model':'returned-model','usage':{'input_tokens':12,'output_tokens':7},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'records':[]})}]}]}
    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr('billing_agent.api.requests.post',post)
    adapter=ResponsesExtractor(base_url='https://example.test/v1',model='test-model',api_key='secret-test')
    assert adapter([Chunk(id='c1',name='test',text='no bill',locator='body',source_method='text')])==[]
    assert sent['url']=='https://example.test/v1/responses'
    assert sent['json']['store'] is False
    assert sent['allow_redirects'] is False
    assert adapter.metadata['actual_model']=='returned-model'
    assert adapter.metadata['usage']['input_tokens']==12


@pytest.mark.parametrize('status',[401,403,429,500,302])
def test_http_error_does_not_expose_body_or_key(monkeypatch,status):
    from billing_agent.api import ResponsesExtractor
    class Response:
        status_code=status
        text='private-secret-test'
    monkeypatch.setattr('billing_agent.api.requests.post',lambda *a,**k:Response())
    with pytest.raises(RuntimeError) as error:
        ResponsesExtractor(base_url='https://example.test/v1',model='m',api_key='private-secret-test')([])
    assert 'private-secret-test' not in str(error.value)


def test_incomplete_response_is_not_accepted(monkeypatch):
    from billing_agent.api import ResponsesExtractor
    class Response:
        status_code=200
        def json(self):return {'status':'incomplete','output':[]}
    monkeypatch.setattr('billing_agent.api.requests.post',lambda *a,**k:Response())
    with pytest.raises(RuntimeError,match='incomplete'):
        ResponsesExtractor(base_url='https://example.test/v1',model='m',api_key='secret')([])
