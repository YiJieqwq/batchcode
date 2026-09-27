#!/usr/bin/env python3
"""Allowlisted clean release; fail closed if public profiles contain keys."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
ROOT=Path(__file__).resolve().parents[1]
version=re.search(r"VERSION = '([^']+)'",(ROOT/'src/engine.py').read_text()).group(1)
for p in [ROOT/'model/deepseek-flash.txt',ROOT/'websearch/tavily.txt']:
    if json.loads(p.read_text())['api_key']!='':raise SystemExit('Refusing to package nonempty API key: '+p.name)
files=['LICENSE','README.md','AGENT.md','CHANGELOG.md','.gitignore','install.sh','uninstall.sh','batchcode','requirements.lock','config.default.json','model/deepseek-flash.txt','websearch/tavily.txt']
for folder in ['src','tests','docs','scripts']:
    files += [str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.md')]
out=ROOT/'dist';out.mkdir(exist_ok=True)
target=out/f'batchcode-v{version}.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for name in sorted(files):z.write(ROOT/name,'batchcode/'+name)
digest=hashlib.sha256(target.read_bytes()).hexdigest()
Path(str(target)+'.sha256').write_text(digest+'  '+target.name+'\n')
print(target)
print(digest)
