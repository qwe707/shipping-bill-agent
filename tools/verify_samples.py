"""Actual sample acceptance run. Uses test entity; makes no ledger writes."""
import json
from pathlib import Path
import sys
from collections import Counter
ROOT=Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0,str(ROOT))
from billing_agent.pipeline import run_pipeline

folder=Path(sys.argv[1])
reports=[]
for path in sorted(folder.iterdir()):
    if path.suffix.lower() not in ('.pdf','.png','.eml'):continue
    if path.name=='PDF示例账单1.pdf':continue  # already verified independently
    print(json.dumps({'document':path.name,'status':'start'},ensure_ascii=False),flush=True)
    def progress(event):
        print(json.dumps({k:event.get(k) for k in ('stage','status','document','duration_seconds','actual_model','usage')},ensure_ascii=False),flush=True)
    result=run_pipeline([path],'TEST_ENTITY_UNCONFIRMED',mode='api',output_dir=ROOT/'runs',on_event=progress)
    chunks=json.loads((Path(result['run_dir'])/'chunks.json').read_text(encoding='utf-8'))
    report={'document':path.name,'run_dir':result['run_dir'],'entity_is_test_assumption':True,
            'incomplete':result['incomplete'],'errors':result['errors'],
            'counts':dict(Counter(r['operation'] for r in result['records'])),
            'sources':[{'name':c['name'],'method':c['source_method'],'characters':len(c['text'])} for c in chunks],
            'fees':[{'charge':r['charge_details'],'operation':r['operation'],'issues':r['audit_trail']['issues']} for r in result['records']]}
    reports.append(report)
    (ROOT/'verification'/'remaining-samples.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
print('All requested sample runs finished.',flush=True)
