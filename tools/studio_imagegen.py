"""Operator CLI: generate exact bound PNGs, then attach through Studio commands.

Uses the immutable bundled ImageGen CLI; never gives credentials to producers.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from backend.imagegen_assets import ImageAssetError, git, load_bundle, requests_for, validate_png
from tools.imagegen_cli import generate_images, ImageGenerationError


def read_plan(state, proposal_id):
    with sqlite3.connect((state / 'state.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute("SELECT payload FROM entities WHERE kind='proposal' AND id=?", (proposal_id,)).fetchone()
    if not row:
        raise ImageAssetError('Proposal is unavailable.')
    plan = json.loads(row[0])
    if plan.get('status') not in {'READY', 'FROZEN'}:
        raise ImageAssetError('Generate assets only for a complete READY/FROZEN plan.')
    return {key: plan[key] for key in ('id', 'projectId', 'revision', 'publicationRevision', 'document', 'tasks', 'sourceRefs')}


def generate(state, plan, *, dry_run=False):
    jobs = requests_for(plan)
    if not jobs:
        raise ImageAssetError('This plan has no missing PNG bindings.')
    bundle_id = 'imagegen-' + uuid.uuid4().hex
    output = state / 'imagegen' / 'bundles' / bundle_id
    scratch = state / 'imagegen' / 'tmp' / bundle_id
    for path in (state / 'imagegen', output.parent, scratch.parent):
        if path.is_symlink():
            raise ImageAssetError('ImageGen output paths cannot be links.')
    scratch.mkdir(parents=True, mode=0o700)
    output.mkdir(parents=True, mode=0o700)
    try:
        generated = generate_images([{'prompt': j['prompt'], 'filename': f'image-{i}.png'}
                                     for i, j in enumerate(jobs)], output_dir=scratch / 'output', dry_run=dry_run)
        if dry_run:
            shutil.rmtree(output)
            return {**generated, 'requests': jobs}
        for job, image in zip(jobs, generated['images']):
            target = output / job['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image, target)
        for job in jobs:
            path = output / job['path']
            if path.is_symlink() or not path.is_file():
                raise ImageAssetError('ImageGen batch is incomplete; no bundle was attached.')
            validate_png(path.read_bytes())
        (output / 'manifest.json').write_text(json.dumps({
            'schemaVersion': 'studio.imagegen-bundle.v1', 'model': 'gpt-image-2',
            'plan': plan, 'requests': jobs}, ensure_ascii=False, indent=2) + '\n')
        git(output, 'init', '--quiet', '-b', 'main')
        git(output, 'config', 'user.name', 'Studio ImageGen Operator')
        git(output, 'config', 'user.email', 'studio@localhost')
        git(output, 'add', '--', 'manifest.json', *[j['path'] for j in jobs])
        git(output, 'commit', '--quiet', '-m', 'Capture plan-bound ImageGen PNG bundle')
        ref, _, _ = load_bundle(state, bundle_id)
        return {'status': 'GENERATED', 'assetBundle': ref, 'directory': str(output), 'log': generated['log']}
    except ImageGenerationError as exc:
        raise ImageAssetError(str(exc)) from None


def attach(url, plan, bundle_id):
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username:
        raise ImageAssetError('Studio URL must be an exact loopback HTTP origin.')
    url = url.rstrip('/')
    with urlopen(url + '/api/session', timeout=10) as response:
        session = json.load(response)
    with urlopen(url + '/api/v1/handshake', timeout=10) as response:
        handshake = json.load(response)
    command = {'schemaVersion': 'studio.message.v1', 'kind': 'command',
               'type': 'proposal.assets.attach', 'storeId': handshake['storeId'],
               'commandId': 'attach-' + bundle_id, 'projectId': plan['projectId'],
               'expected': {'proposalRevision': plan['revision'], 'publicationRevision': plan['publicationRevision']},
               'payload': {'proposalId': plan['id'], 'bundleId': bundle_id}}
    request = Request(url + '/api/v1/projects/' + plan['projectId'] + '/commands',
                      data=json.dumps(command).encode(), headers={'Origin': url,
                      'Content-Type': 'application/json', 'X-Workbench-Token': session['token']})
    with urlopen(request, timeout=30) as response:
        receipt = json.load(response)
    if receipt['status'] != 'accepted':
        raise ImageAssetError('Bundle attach rejected: ' + receipt['error']['message'])
    return {'status': 'ATTACHED', 'commandId': command['commandId'],
            'proposalId': plan['id'], 'revision': receipt['result']['proposal']['revision']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--proposal-id', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--attach', action='store_true')
    parser.add_argument('--bundle-id', help='Attach an already generated bundle, without API generation.')
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    if args.dry_run and (args.attach or args.bundle_id):
        parser.error('dry-run cannot attach or reuse a completed bundle')
    state = args.state_root.expanduser().resolve(strict=True)
    try:
        plan = read_plan(state, args.proposal_id)
        if args.bundle_id:
            ref, _, _ = load_bundle(state, args.bundle_id)
            result = {'status': 'GENERATED', 'assetBundle': ref}
        else:
            result = generate(state, plan, dry_run=args.dry_run)
        if args.attach:
            result['attachment'] = attach(args.url, plan, result['assetBundle']['bundleId'])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ImageAssetError as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
