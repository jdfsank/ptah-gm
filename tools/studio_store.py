#!/usr/bin/env python3
"""Offline coordinated Studio backup/restore, using Git identities and refs.

Restore deliberately creates a new namespace. Old runner intents cannot be
replayed against a store whose command/event history may have gone backwards.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import shutil
import sqlite3
import uuid
import subprocess
from pathlib import Path


@contextlib.contextmanager
def locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    paths = [root / 'service.lock']
    runners = root / 'runners'
    if runners.is_dir():
        paths.extend(sorted(runners.rglob('service.lock')))
    with contextlib.ExitStack() as stack:
        for path in paths:
            if path.is_symlink():
                raise RuntimeError('Service lock cannot be a symlink.')
            stream = stack.enter_context(path.open('a+'))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Stop the backend and both runners before backup or restore.') from None
        yield


def _git(root: Path, *args: str):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            text=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError('Retained Git object is unavailable.')
    return result.stdout.strip()


def inventory(root: Path):
    database = root / 'state.sqlite3'
    if database.is_symlink() or not database.is_file():
        raise RuntimeError('Source must contain a regular Studio state database.')
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        refs = []
        for kind, encoded in db.execute("SELECT kind,payload FROM entities WHERE kind IN ('artifact','snapshot','job','attempt')"):
            item = json.loads(encoded)
            refs_for_item = [item.get('artifactRef'), item.get('ref'),
                            (item.get('inputRefs') or {}).get('inputArtifactRef'),
                            (item.get('inputRefs') or {}).get('artifactRef')]
            for ref in refs_for_item:
                if not ref:
                    continue
                if not isinstance(ref, dict) or not isinstance(ref.get('artifactId'), str) or not ref['artifactId'].replace('-', '').replace('_', '').isalnum():
                    raise RuntimeError('Retained artifact reference has an invalid identity.')
                artifact = root / 'artifacts' / ref['artifactId'] / 'repository'
                if artifact.is_symlink() or artifact.parent.is_symlink() or not (artifact / '.git').is_dir():
                    raise RuntimeError('A retained artifact is missing: ' + ref['artifactId'])
                if _git(artifact, 'rev-parse', 'HEAD') != ref.get('sourceCommit') or _git(artifact, 'status', '--porcelain'):
                    raise RuntimeError('A retained artifact has drifted: ' + ref['artifactId'])
                _git(artifact, 'cat-file', '-e', ref['sourceCommit'] + '^{commit}')
                refs.append({'kind': kind, 'id': item['id'], 'artifactRef': ref})
        store = db.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]
        return {'schemaVersion': 'studio.backup.v1', 'storeId': store, 'references': refs}
    finally:
        db.close()


def backup(root: Path, destination: Path):
    root, destination = root.resolve(), destination.resolve()
    if not root.is_dir() or not (root / 'state.sqlite3').is_file():
        raise RuntimeError('Source must be an existing Studio state directory.')
    if destination.exists() or destination.is_relative_to(root):
        raise RuntimeError('Backup destination must be a new directory outside the active store.')
    with locked(root):
        manifest = inventory(root)
        # All runner services must also be stopped; journals and unacked reports
        # are kept with the same store alongside the artifact vault.
        shutil.copytree(root, destination, ignore=shutil.ignore_patterns('service.lock', '*.sqlite3-wal', '*.sqlite3-shm'))
        for database in [root / 'state.sqlite3', *sorted((root / 'runners').rglob('*.sqlite3'))]:
            if database.is_symlink():
                raise RuntimeError('Runner database cannot be a symlink.')
            source = sqlite3.connect(database)
            target = sqlite3.connect(destination / database.relative_to(root))
            try:
                source.backup(target)
            finally:
                source.close()
                target.close()
        (destination / 'backup.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        destination.chmod(0o700)
    return manifest


def restore(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise RuntimeError('Restore requires a new destination; existing stores are preserved.')
    if not source.is_dir() or not (source / 'state.sqlite3').is_file():
        raise RuntimeError('Source must be an existing Studio backup directory.')
    with locked(source):
        inventory(source)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('service.lock', '*.sqlite3-wal', '*.sqlite3-shm', 'runner-token', 'services.json', 'services.lock'))
    db = sqlite3.connect(destination / 'state.sqlite3')
    new_store = 'store-' + uuid.uuid4().hex
    try:
        old_store = db.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]
        with db:
            db.execute("UPDATE meta SET value=? WHERE key='store_id'", (new_store,))
            db.execute("INSERT OR REPLACE INTO meta VALUES('restored_from_store',?)", (old_store,))
            # Preserve old evidence, never return an old receipt in the new scope.
            for table in ('commands', 'reports', 'claims', 'project_events'):
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if exists:
                    # A restored store can itself be backed up and restored.
                    # Preserve every generation without colliding table names.
                    generation = 1
                    while db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (f'restored_{generation}_{table}',)).fetchone():
                        generation += 1
                    db.execute(f'ALTER TABLE {table} RENAME TO restored_{generation}_{table}')
            for kind, ident, encoded in db.execute("SELECT kind,id,payload FROM entities WHERE kind IN ('attempt','runner')").fetchall():
                item = json.loads(encoded)
                if kind == 'runner':
                    item.update(lastHeartbeat=0, catalog=None, capabilities=[],
                        previousSandboxEvidence=item.get('sandboxEvidence'),
                        sandboxEvidence={'status': 'NOT_READY', 'restoreReviewRequired': True})
                elif item.get('status') not in {'COMPLETED', 'STOPPED', 'FAILED'}:
                    item.update(status='UNKNOWN', restoreReviewRequired=True)
                db.execute('UPDATE entities SET payload=? WHERE kind=? AND id=?', (json.dumps(item, separators=(',', ':')), kind, ident))
    finally:
        db.close()
    for journal in sorted((destination / 'runners').rglob('*.sqlite3')):
        connection = sqlite3.connect(journal)
        try:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone():
                with connection:
                    connection.execute("INSERT OR REPLACE INTO metadata VALUES('quarantinedStoreId',?)", (old_store,))
        finally:
            connection.close()
    destination.chmod(0o700)
    return {'oldStoreId': old_store, 'storeId': new_store, 'reconciliationRequired': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('backup', 'restore'):
        command = sub.add_parser(action)
        command.add_argument('source', type=Path)
        command.add_argument('destination', type=Path)
    args = parser.parse_args()
    result = backup(args.source, args.destination) if args.action == 'backup' else restore(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
