#!/usr/bin/env python3
"""Verify this handoff without installing dependencies or invoking a model."""
from pathlib import Path
import hashlib
root=Path(__file__).resolve().parents[1]
expected=set()
for line in (root/'SHA256SUMS').read_text().splitlines():
    digest,name=line.split('  ',1)
    p=(root/name).resolve()
    if not p.is_relative_to(root): raise SystemExit('Unsafe manifest path')
    expected.add(name)
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
        raise SystemExit('MISMATCH: '+name)
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS' and 'sources' not in p.relative_to(root).parts}
extra=actual-expected
if extra: print('Unmanifested local files (possibly your later work):',sorted(extra))
print('PASS:',len(expected),'packaged files verified; extracted sources checked separately by unpack-sources.py')
