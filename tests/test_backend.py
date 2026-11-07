from copy import deepcopy
import pytest
from billing_agent.models import Chunk
from billing_agent.rules import reconcile
from billing_agent.parsers import parse_file, extract_ocr_text

def fee(**kw):
    d=dict(document_type='invoice', reference_no='INV1', charge_item='Freight', amount='100', currency='USD', payer='ACME', payee='Carrier', issuer='Carrier', recipient='ACME')
    d.update(kw)
    text=' | '.join(str(v) for v in d.values() if v is not None)
    d['evidence']={k:{'chunk_id':'c1','quote':str(v)} for k,v in d.items() if v is not None}
    d['explicit_updates']=[]
    return d, [Chunk(id='c1',name='invoice',text=text,locator='body',source_method='text')]

def test_create_and_idempotence():
    f,c=fee(); rows=reconcile([f],c,[],'ACME')
    assert rows[0]['operation']=='CREATE'
    assert rows[0]['financial_attributes']['posting_type']=='AP'
    assert reconcile([f],c,rows,'ACME')[0]['operation']=='NO_CHANGE'

def test_existing_immutable_and_change_requires_explicit_evidence():
    f,c=fee(); old=reconcile([f],c,[],'ACME'); old[0]['custom']={'protected':True}; before=deepcopy(old)
    g,d=fee(amount='120')
    result=reconcile([g],d,old,'ACME')[0]
    assert result['operation']=='PENDING_REVIEW'
    assert result['charge_details']['amount']==100
    assert result['custom']=={'protected':True}
    assert old==before

def test_invalid_and_missing_direction():
    for kw in ({'amount':'NaN'},{'currency':'ZZZ'},{'payer':None},{'reference_no':'O0'}):
        f,c=fee(**kw); assert reconcile([f],c,[],'ACME')[0]['operation']=='PENDING_REVIEW'

def test_evidence_and_ambiguity():
    f,c=fee(); f['evidence']['amount']['quote']='999'
    assert reconcile([f],c,[],'ACME')[0]['operation']=='PENDING_REVIEW'
    f,c=fee(); assert all(r['operation']=='PENDING_REVIEW' for r in reconcile([f,f],c,[],'ACME'))

def test_entity_required():
    with pytest.raises(ValueError): reconcile([],[],[],'')

def test_ocr_unknown_shape():
    assert extract_ocr_text({'data':{'text':'hello'}})=='hello'
    with pytest.raises(ValueError): extract_ocr_text({'data':{'words':[1,2]}})

def test_local_image_blocks_without_mapping(tmp_path):
    p=tmp_path/'invoice.png';p.write_bytes(b'fake')
    with pytest.raises(ValueError,match='URL|sidecar'):parse_file(p)

def test_explicit_update_preserves_protected_metadata():
    f,c=fee();old=reconcile([f],c,[],'ACME');old[0]['audit_trail']['approval_id']='protected'
    g,d=fee(amount='120');d[0].text+=' Update amount to 120'
    g['explicit_updates']=[{'field':'amount','chunk_id':'c1','quote':'Update amount to 120'}]
    result=reconcile([g],d,old,'ACME')[0]
    assert result['operation']=='UPDATE'
    assert result['charge_details']['amount']==120
    assert result['audit_trail']['approval_id']=='protected'

def test_partial_update_inherits_ledger_fields():
    f,c=fee();old=reconcile([f],c,[],'ACME')
    text='INV1 Freight Update amount to 120'
    g={'reference_no':'INV1','charge_item':'Freight','amount':'120','evidence':{k:{'chunk_id':'c1','quote':v} for k,v in {'reference_no':'INV1','charge_item':'Freight','amount':'120'}.items()},'explicit_updates':[{'field':'amount','chunk_id':'c1','quote':'Update amount to 120'}]}
    result=reconcile([g],[Chunk(id='c1',name='update',text=text,locator='body',source_method='text')],old,'ACME')[0]
    assert result['operation']=='UPDATE'
    assert result['charge_details']['currency']=='USD'
    assert result['charge_details']['amount']==120
    assert 'document_date' in result['document_info']
    assert 'payment_term' in result['charge_details']

def test_fee_alias_matching():
    f,c=fee(charge_item='Handling Fee');old=reconcile([f],c,[],'ACME')
    g,d=fee(charge_item='H/D Fee')
    assert old[0]['charge_details']['charge_item']=='Handling Charge'
    assert reconcile([g],d,old,'ACME')[0]['operation']=='NO_CHANGE'

def test_numeric_evidence_must_not_match_substring():
    f,c=fee(amount='10');c[0].text='Freight 100 USD INV1 invoice ACME Carrier'
    f['evidence']['amount']['quote']='100'
    assert reconcile([f],c,[],'ACME')[0]['operation']=='PENDING_REVIEW'

def test_numeric_output_never_silently_loses_decimal_precision():
    f,c=fee(amount='1234567890.123456789')
    result=reconcile([f],c,[],'ACME')[0]
    assert result['operation']=='PENDING_REVIEW'
    assert result['charge_details']['amount'] is None

def test_real_mode_empty_extraction_is_incomplete(tmp_path):
    from billing_agent.pipeline import run_pipeline
    path=tmp_path/'invoice.txt';path.write_text('invoice',encoding='utf-8')
    result=run_pipeline([path],'ACME',output_dir=tmp_path,extractor=lambda chunks:[])
    assert result['incomplete'] and result['errors'] and result['records']==[]

def test_multi_currency_totals_and_distinct_fees():
    a,c=fee(amount='60',total='100');b,d=fee(charge_item='Handling',amount='40',total='100')
    e,f=fee(charge_item='Local',currency='EUR',amount='20',total='20')
    c[0].text+=' '+d[0].text+' '+f[0].text
    assert [r['operation'] for r in reconcile([a,b,e],c,[],'ACME')]==['CREATE']*3

def test_eml_attachment_traversal_never_written(tmp_path):
    from email.message import EmailMessage
    msg=EmailMessage();msg['Subject']='Invoice';msg.set_content('Invoice body')
    msg.add_attachment(b'Freight USD 100',maintype='text',subtype='plain',filename='../../escape.txt')
    path=tmp_path/'mail.eml';path.write_bytes(msg.as_bytes())
    chunks=parse_file(path)
    assert any(c.name=='../../escape.txt' for c in chunks)
    assert not (tmp_path.parent/'escape.txt').exists()

def test_ocr_payload_and_failure(monkeypatch,tmp_path):
    from billing_agent import parsers
    seen=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'result':{'text':'Freight USD 100'}}
    def post(url,**kwargs):seen.append((url,kwargs));return Response()
    monkeypatch.setattr(parsers.requests,'post',post)
    path=tmp_path/'image.png';path.write_bytes(b'PNG')
    assert parse_file(path,{'image.png':'https://example.com/image.png'})[0].source_method=='remote_ocr'
    assert seen[0][1]['json']=={'file':'https://example.com/image.png','task':'orderChange','callBack':'','taskType':''}
    assert seen[0][1]['timeout']==(10,60)

def test_pipeline_isolates_failure_and_demo_roundtrip(tmp_path):
    from pathlib import Path
    from billing_agent.pipeline import run_pipeline
    path=Path(__file__).resolve().parents[1]/'examples'/'invoice.json'
    result=run_pipeline([path,tmp_path/'missing.pdf'],'ACME',mode='demo',output_dir=tmp_path)
    assert result['incomplete'] and len(result['errors'])==1
    assert result['records'][0]['operation']=='CREATE'
    result2=run_pipeline([path],'ACME',result['records'],mode='demo',output_dir=tmp_path)
    assert result2['records'][0]['operation']=='NO_CHANGE'

def test_codex_events_and_timeout(monkeypatch):
    import json,subprocess
    from billing_agent.codex import CodexExtractor
    seen=[]
    class Process:
        returncode=0
        def __init__(self,args,**kwargs):seen.append((args,kwargs));self.killed=False
        def communicate(self,*args,**kwargs):
            return '\n'.join(map(json.dumps,[{'type':'item.completed','item':{'type':'reasoning','text':'secret'}},{'type':'item.completed','item':{'type':'agent_message','text':'{"records": []}'}},{'type':'turn.completed','usage':{'input_tokens':15,'output_tokens':3}}])),''
        def kill(self):self.killed=True
    monkeypatch.setattr(subprocess,'Popen',Process)
    adapter=CodexExtractor('codex.exe');assert adapter([])==[]
    assert adapter.metadata['actual_model'] is None
    assert adapter.metadata['usage']['input_tokens']==15
    assert seen[0][1]['shell'] is False
    assert '--ephemeral' in seen[0][0] and 'shell_tool' in seen[0][0]
    class Timed(Process):
        def communicate(self,*args,**kwargs):
            if not self.killed:raise subprocess.TimeoutExpired('codex',1)
            return '',''
    monkeypatch.setattr(subprocess,'Popen',Timed)
    with pytest.raises(TimeoutError):CodexExtractor('codex.exe')([])

@pytest.mark.parametrize('quote',[
    'Do not update amount to 120',
    "Don't update amount to 120",
    'Never update amount to 120',
    'Update amount to 120 was not requested',
    'Change amount from 120 to 100',
    'Update amount from 120',
    '不要将金额调整为120',
    '不得将金额调整为120',
    '禁止将金额调整为120',
    '不应将金额调整为120',
    '无需将金额调整为120',
    '未要求将金额调整为120',
    '将金额从120调整为100',
])
def test_update_authorization_rejects_negation_and_old_value(quote):
    f,c=fee();ledger=reconcile([f],c,[],'ACME')
    g,d=fee(amount='120');d[0].text+=' '+quote
    g['explicit_updates']=[{'field':'amount','chunk_id':'c1','quote':quote}]
    result=reconcile([g],d,ledger,'ACME')[0]
    assert result['operation']=='PENDING_REVIEW'
    assert result['charge_details']['amount']==100

@pytest.mark.parametrize('quote',[
    'Update amount to 120',
    'Change amount from 100 to 120',
    'Update amount = 120',
    'Update amount: 120',
    '将金额从100调整为120',
    '将金额调整至120',
])
def test_update_authorization_binds_affirmative_destination(quote):
    f,c=fee();ledger=reconcile([f],c,[],'ACME')
    g,d=fee(amount='120');d[0].text+=' '+quote
    g['explicit_updates']=[{'field':'amount','chunk_id':'c1','quote':quote}]
    result=reconcile([g],d,ledger,'ACME')[0]
    assert result['operation']=='UPDATE'
    assert result['charge_details']['amount']==120
