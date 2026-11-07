from copy import deepcopy
from email.message import EmailMessage
import json
from pathlib import Path

from billing_agent.models import Chunk
from billing_agent.parsers import parse_document
from billing_agent.pipeline import run_pipeline
from billing_agent.rules import reconcile
from test_backend import fee

def mail(tmp_path):
    msg=EmailMessage();msg['Subject']='Invoice INV1'
    msg.set_content('invoice INV1 Freight 120 USD ACME Carrier Update amount to 120')
    msg.add_alternative('<p>invoice INV1 Freight 120 USD ACME Carrier Update amount to 120</p>',subtype='html')
    for name in ('InsertPic_C25B.jpg','invoice.pdf','statement.pdf'):
        msg.add_attachment(b'not OCR text',maintype='application',subtype='octet-stream',filename=name)
    path=tmp_path/'mail.eml';path.write_bytes(msg.as_bytes());return path

def extracted(chunks):
    f,_=fee(amount='120');body=next(c for c in chunks if c.locator=='email body')
    for ev in f['evidence'].values():ev['chunk_id']=body.id
    f['explicit_updates']=[{'field':'amount','chunk_id':body.id,'quote':'Update amount to 120'}]
    return [f]

def test_parser_keeps_body_and_reports_every_attachment(tmp_path):
    result=parse_document(mail(tmp_path))
    assert result.incomplete
    assert {e['attachment'] for e in result.errors}=={'InsertPic_C25B.jpg','invoice.pdf','statement.pdf'}
    bodies=[c for c in result.chunks if c.locator=='email body']
    assert len(bodies)==1 and '<p>' not in bodies[0].text

def test_related_html_alternative_is_not_duplicate_body(tmp_path):
    msg=EmailMessage();msg.set_content('plain preferred')
    msg.add_alternative('<p>html duplicate</p>',subtype='html')
    msg.get_payload()[1].add_related(b'image',maintype='image',subtype='jpeg',filename='inline.jpg',cid='<inline>')
    path=tmp_path/'related.eml';path.write_bytes(msg.as_bytes())
    result=parse_document(path)
    assert [c.text.strip() for c in result.chunks if c.locator=='email body']==['plain preferred']
    assert result.errors[0]['attachment']=='inline.jpg'

def test_partial_pipeline_never_mutates_matched_ledger(tmp_path):
    f,c=fee();ledger=reconcile([f],c,[],'ACME');before=deepcopy(ledger)
    result=run_pipeline([mail(tmp_path)],'ACME',ledger,extractor=extracted,output_dir=tmp_path)
    assert result['incomplete'] and len(result['errors'])==3
    row=result['records'][0]
    assert row['operation']=='PENDING_REVIEW'
    assert row['charge_details']['amount']==100
    assert row['audit_trail']['changes']==[]
    assert 'invoice.pdf' in ' '.join(row['audit_trail']['issues'])
    assert ledger==before
    assert json.loads((Path(result['run_dir'])/'chunks.json').read_text(encoding='utf-8'))

def test_partial_create_is_pending(tmp_path):
    result=run_pipeline([mail(tmp_path)],'ACME',extractor=extracted,output_dir=tmp_path)
    assert result['records'][0]['operation']=='PENDING_REVIEW'

def test_entity_scope_cannot_be_rewritten():
    f,c=fee();ledger=reconcile([f],c,[],'ACME')
    result=reconcile([f],c,ledger,'Carrier')[0]
    assert result['operation']=='PENDING_REVIEW'
    assert result['financial_attributes']['accounting_entity']=='ACME'
    assert result['financial_attributes']['posting_type']=='AP'

def test_update_quote_must_name_the_field():
    f,c=fee();ledger=reconcile([f],c,[],'ACME')
    g,d=fee(amount='120');d[0].text+=' Update booking number to 120'
    g['explicit_updates']=[{'field':'amount','chunk_id':'c1','quote':'Update booking number to 120'}]
    result=reconcile([g],d,ledger,'ACME')[0]
    assert result['operation']=='PENDING_REVIEW'
    assert result['charge_details']['amount']==100

def test_effective_total_rejects_amount_only_update():
    f,c=fee(total='100');ledger=reconcile([f],c,[],'ACME')
    g,d=fee(amount='120');d[0].text+=' Update amount to 120'
    g['explicit_updates']=[{'field':'amount','chunk_id':'c1','quote':'Update amount to 120'}]
    result=reconcile([g],d,ledger,'ACME')[0]
    assert result['operation']=='PENDING_REVIEW'
    assert result['charge_details']['amount']==100

def test_effective_total_includes_other_ledger_lines():
    f,c=fee(amount='60',total='100');g,d=fee(charge_item='Handling',amount='40',total='100')
    c[0].text+=' '+d[0].text
    ledger=reconcile([f,g],c,[],'ACME')
    # A same-value partial document must not compare 60 against the group total 100.
    partial,p=fee(amount='60')
    assert reconcile([partial],p,ledger,'ACME')[0]['operation']=='NO_CHANGE'

def test_numeric_evidence_preserves_sign_and_full_token():
    for wrong in ('-10','1,010'):
        f,c=fee(amount='10');c[0].text=c[0].text.replace('10',wrong)
        f['evidence']['amount']['quote']=wrong
        assert reconcile([f],c,[],'ACME')[0]['operation']=='PENDING_REVIEW'
