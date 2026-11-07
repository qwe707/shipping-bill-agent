"""One actual sample; write only sanitized status, never signed URLs or tokens."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from billing_agent.mineru import MinerU

path=Path(sys.argv[1])
client=MinerU()
report={'provider':'mineru','file':path.name,'passed':False,'simulation':False}
start=time.monotonic()
try:
    text=client.parse(path.read_bytes(),path.name)
    target=ROOT/'runs'/'mineru-verification'
    target.mkdir(parents=True,exist_ok=True)
    (target/'recognized.md').write_text(text,encoding='utf-8')
    report.update(passed=True,characters=len(text))
except Exception as exc:
    report['error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
report.update(client.metadata)
report['duration_seconds']=round(time.monotonic()-start,3)
(ROOT/'verification'/'mineru-connectivity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if report['passed'] else 1)
