"""Live model probe using synthetic data only; secret is loaded from local settings."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from billing_agent.api import ResponsesExtractor
from billing_agent.models import Chunk
from billing_agent.rules import reconcile

chunk=Chunk(id='probe1',name='synthetic.txt',locator='body',source_method='synthetic',text='SYNTHETIC TEST ONLY. Invoice reference INV-TEST-001. Issuer Carrier. Recipient ACME. Payer ACME. Payee Carrier. Charge Handling Fee. Amount 40. Currency USD. Payment term PP.')
adapter=ResponsesExtractor(timeout=90)
start=time.monotonic()
report={'source':'synthetic input, live model API','passed':False}
try:
    fees=adapter([chunk])
    rows=reconcile(fees,[chunk],[],'ACME')
    report['records']=rows
    report['passed']=len(rows)==1 and rows[0]['operation']=='CREATE' and rows[0]['charge_details']['amount']==40 and rows[0]['financial_attributes']['posting_type']=='AP'
except Exception as exc:
    report['error']=str(exc)
report.update(adapter.metadata)
report['duration_seconds']=round(time.monotonic()-start,3)
(ROOT/'verification').mkdir(exist_ok=True)
(ROOT/'verification'/'api-connectivity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
