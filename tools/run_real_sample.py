"""Run the actual PDF through OCR, model, and rules; no ledger write."""
from pathlib import Path
import json
import sys
from collections import Counter

ROOT=Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,str(ROOT))
from billing_agent.pipeline import run_pipeline

path=Path(sys.argv[1])
entity=sys.argv[2]
def progress(event):
    print(json.dumps({k:event.get(k) for k in ('stage','status','duration_seconds','actual_model','usage')},ensure_ascii=False),flush=True)

result=run_pipeline([path],entity,mode='api',output_dir=ROOT/'runs',on_event=progress)
summary={
    'source':'actual sample PDF; live MinerU and model API',
    'accounting_entity':entity,'entity_is_test_assumption':True,
    'run_dir':result['run_dir'],'incomplete':result['incomplete'],
    'errors':result['errors'],
    'counts':dict(Counter(r['operation'] for r in result['records'])),
    'fees':[{'operation':r['operation'],'charge':r['charge_details'],
             'financial':r['financial_attributes'],'issues':r['audit_trail']['issues']}
            for r in result['records']],
}
(ROOT/'verification'/(Path(sys.argv[3]).name if len(sys.argv)>3 else 'real-pdf-pipeline.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False),flush=True)
raise SystemExit(2 if result['incomplete'] else 0)
