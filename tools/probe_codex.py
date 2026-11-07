"""Small synthetic connectivity check. Does not read credentials or actual invoices."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parent.parent
report_dir = root / 'verification'
report_dir.mkdir(exist_ok=True)
report = {'source': 'synthetic connectivity probe', 'passed': False, 'usage': None, 'actual_model': None}
schema = {'type': 'object', 'properties': {'reference_no': {'type': 'string'}, 'amount': {'type': 'number'}, 'currency': {'type': 'string'}}, 'required': ['reference_no', 'amount', 'currency'], 'additionalProperties': False}
start = time.monotonic()
with tempfile.TemporaryDirectory(prefix='bill-probe-') as folder:
    schema_path = Path(folder) / 'schema.json'
    schema_path.write_text(json.dumps(schema), encoding='utf-8')
    exe = shutil.which('codex')
    if not exe:
        raise RuntimeError('Codex executable not found')
    command = [exe, 'exec', '--ignore-user-config', '--disable', 'shell_tool', '--disable', 'apps', '--disable', 'plugins', '--disable', 'hooks', '--disable', 'browser_use', '--disable', 'computer_use', '--disable', 'multi_agent', '--ephemeral', '--sandbox', 'read-only', '--skip-git-repo-check', '--json', '--output-schema', str(schema_path), '-']
    prompt = 'Return JSON extracted from this SYNTHETIC test text only. Do not use any tools. Text: Invoice TEST-001. Handling Fee USD 40.00.'
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', cwd=folder)
    try:
        stdout, stderr = process.communicate(prompt, timeout=120)
        report['exit_code'] = process.returncode
        report['stderr_tail'] = stderr[-1500:]
        final = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'turn.completed':
                report['usage'] = event.get('usage')
            if isinstance(event.get('model'), str):
                report['actual_model'] = event['model']
            if event.get('type') in ('error', 'turn.failed'):
                report['error'] = event
            if event.get('type') == 'item.completed' and event.get('item', {}).get('type') == 'agent_message':
                final = event['item'].get('text')
        if final:
            report['result'] = json.loads(final)
            report['passed'] = process.returncode == 0 and report['result'] == {'reference_no': 'TEST-001', 'amount': 40, 'currency': 'USD'}
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        report['error'] = 'timeout'
report['duration_seconds'] = round(time.monotonic() - start, 3)
(report_dir / 'codex-connectivity.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['passed'] else 1)
