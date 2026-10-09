#!/usr/bin/env python3
"""Restore the original game ZIP from verified byte slices without overwriting."""
from pathlib import Path
import json,hashlib,os
root=Path(__file__).resolve().parents[1]
m=json.loads((root/'transfer-parts/game-source-parts.json').read_text())
def digest(b): return hashlib.sha256(b).hexdigest()
dest=root/m['destination']
if dest.exists():
    if dest.stat().st_size==m['bytes'] and digest(dest.read_bytes())==m['sha256']:
        print('PASS: original game source ZIP already present and verified')
        raise SystemExit(0)
    raise SystemExit('STOP: destination exists with different bytes; preserve and inspect it')
pieces=[]
for item in m['parts']:
    p=root/item['path']
    if not p.is_file(): raise SystemExit('MISSING: '+item['path']+'; extract all game transfer ZIPs first')
    b=p.read_bytes()
    if len(b)!=item['bytes'] or digest(b)!=item['sha256']: raise SystemExit('Slice checksum mismatch: '+item['path'])
    pieces.append(b)
result=b''.join(pieces)
if len(result)!=m['bytes'] or digest(result)!=m['sha256']: raise SystemExit('Combined source ZIP checksum mismatch')
dest.parent.mkdir(parents=True,exist_ok=True)
with dest.open('xb') as f: f.write(result)
print('PASS: restored original game source ZIP with matching SHA-256:',m['sha256'])
print('Next: python3 tools/verify-package.py; then python3 tools/unpack-sources.py')
