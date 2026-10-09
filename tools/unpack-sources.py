#!/usr/bin/env python3
"""Extract original source archives into a new sources directory; never overwrite."""
from pathlib import Path,PurePosixPath
import hashlib,json,stat,zipfile
root=Path(__file__).resolve().parents[1]
out=root/'sources'
if out.exists(): raise SystemExit('STOP: sources already exists. Preserve it; inspect or choose a fresh unpacked handoff.')
archives=json.loads((root/'docs/VERSIONS.json').read_text())['archives']
seen=set()
for meta in archives:
    p=root/meta['path']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=meta['sha256']: raise SystemExit('Archive digest mismatch')
    with zipfile.ZipFile(p) as z:
        if z.testzip(): raise SystemExit('Archive CRC error')
        for info in z.infolist():
            n=PurePosixPath(info.filename)
            if n.is_absolute() or '..' in n.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr>>16):
                raise SystemExit('Unsafe archive member: '+info.filename)
            if info.filename in seen: raise SystemExit('Duplicate member')
            seen.add(info.filename)
out.mkdir()
for meta in archives:
    with zipfile.ZipFile(root/meta['path']) as z:
        z.extractall(out)
        for info in z.infolist():
            p=out/info.filename
            mode=(info.external_attr>>16)&0o777
            if mode: p.chmod(mode)
    for item in json.loads((root/meta['inventory']).read_text()):
        p=out/item['path']
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']: raise SystemExit('Extracted digest mismatch')
print('PASS: both original source trees extracted and all file digests verified in',out)
