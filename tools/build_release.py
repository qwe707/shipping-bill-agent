"""Build an allowlisted shareable archive, and check local secrets are absent."""
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parent.parent
FOLDERS=('billing_agent','tests','tools','docs','.streamlit','examples','verification')
FILES=('app.py','README.md','PRODUCT.md','requirements.txt','requirements.lock.txt','setup.ps1','start.ps1','start.cmd','.env.example','.gitignore')
paths=[ROOT/p for p in FILES]
for folder in FOLDERS:
    paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
secrets=[]
env=ROOT/'.env'
if env.exists():
    for line in env.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line:
            key,value=line.split('=',1)
            if ('KEY' in key or 'TOKEN' in key) and value.strip():secrets.append(value.strip().encode())
for p in paths:
    data=p.read_bytes()
    if any(secret in data for secret in secrets):raise RuntimeError('Credential found in release input; archive not created')
archive=ROOT.parent/'shipping-bill-agent-delivery.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(set(paths)):z.write(p,p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert '.env' not in z.namelist()
    assert not any(n.startswith(('runs/','uploads/','.venv/')) for n in z.namelist())
    assert z.testzip() is None
print(f'Release archive verified: {len(set(paths))} files, {archive.stat().st_size} bytes')
