import json
from datetime import datetime,timezone
from pathlib import Path
import time
import uuid
from langchain_core.runnables import RunnableLambda
from .codex import CodexExtractor
from .api import ResponsesExtractor
from .models import Extraction
from .parsers import parse_document
from .rules import reconcile

class DemoExtractor:
    metadata={'actual_model':None,'usage':None,'simulation':True}
    def __call__(self,chunks):
        # Only deliberately synthetic fixtures can enter this path.
        if len(chunks)!=1:raise ValueError('Demo requires a single synthetic JSON fixture')
        data=json.loads(chunks[0].text)
        if data.get('simulation') is not True:raise ValueError('Demo fixture must explicitly declare simulation: true')
        rows=data['records']
        for row in rows:
            for ev in row.get('evidence',{}).values():ev['chunk_id']=chunks[0].id
            for ev in row.get('explicit_updates',[]):ev['chunk_id']=chunks[0].id
        return Extraction.model_validate({'records':rows}).model_dump()['records']

def run_pipeline(paths,accounting_entity,existing=None,*,mode='api',ocr_map=None,output_dir=None,on_event=None,extractor=None):
    if not accounting_entity or not accounting_entity.strip():raise ValueError('Current accounting entity is required')
    if mode not in ('demo','codex','api'):raise ValueError('mode must be demo, api or codex')
    if not paths:raise ValueError('At least one document is required')
    if existing is not None and (not isinstance(existing,list) or not all(isinstance(r,dict) for r in existing)):raise ValueError('Existing ledger must be an array of objects')
    run_dir=Path(output_dir or 'runs')/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run_dir.mkdir(parents=True)
    events=[]; errors=[];chunks=[];fees=[];source_issues=[]
    adapter=extractor or (DemoExtractor() if mode=='demo' else ResponsesExtractor() if mode=='api' else CodexExtractor())
    def event(stage,status,document=None,duration=None):
        item={'stage':stage,'status':status,'document':document,'time':datetime.now(timezone.utc).isoformat(),'duration_seconds':duration,**getattr(adapter,'metadata',{'actual_model':None,'usage':None})}
        events.append(item)
        with (run_dir/'events.jsonl').open('a',encoding='utf-8') as fh:fh.write(json.dumps(item,ensure_ascii=False)+'\n')
        if on_event:on_event(item)
    def stage(name,fn,document=None):
        event(name,'start',document);start=time.monotonic()
        try:result=fn()
        except Exception:
            event(name,'error',document,round(time.monotonic()-start,3));raise
        event(name,'end',document,round(time.monotonic()-start,3));return result
    extraction_chain=RunnableLambda(adapter)
    def process(path):
        if hasattr(adapter,'metadata'):adapter.metadata={'actual_model':None,'usage':None,'simulation':mode=='demo'}
        document=stage('parse',lambda:parse_document(path,ocr_map),Path(path).name)
        parsed=document.chunks
        errors.extend(document.errors)
        if document.incomplete:event('parse','incomplete',Path(path).name)
        chunks.extend(parsed)
        if not parsed:return [],[]
        def extract_validated():
            extracted=Extraction.model_validate({'records':extraction_chain.invoke(parsed)}).model_dump()['records']
            if not extracted:raise ValueError('No fee records extracted; input requires manual review')
            return extracted
        extracted=stage('extract',extract_validated,Path(path).name)
        issues=[f'Incomplete source attachment {e["attachment"]}: {e["message"]}' for e in document.errors]
        source_issues.extend([issues.copy() for _ in extracted])
        return parsed,extracted
    orchestration=RunnableLambda(process)
    for path in paths:
        try:
            parsed,extracted=orchestration.invoke(path);fees.extend(extracted)
        except Exception as exc:
            # Known user-actionable errors only; never persist raw server/CLI response bodies.
            message=str(exc) if isinstance(exc,(ValueError,RuntimeError,TimeoutError)) and not type(exc).__module__.startswith('pydantic') else 'Document processing failed; check file format and configuration'
            errors.append({'document':Path(path).name,'error_type':type(exc).__name__,'message':message[:1000]})
    (run_dir/'extracted.json').write_text(json.dumps(fees,ensure_ascii=False,indent=2),encoding='utf-8')
    records=stage('reconcile',lambda:reconcile(fees,chunks,existing or [],accounting_entity,source_issues=source_issues))
    if mode=='demo':
        for r in records:r['audit_trail']['simulation']=True
    result={'records':records,'errors':errors,'events':events,'incomplete':bool(errors),'mode':mode,'run_dir':str(run_dir.resolve())}
    (run_dir/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    (run_dir/'chunks.json').write_text(json.dumps([c.model_dump() for c in chunks],ensure_ascii=False,indent=2),encoding='utf-8')
    (run_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
