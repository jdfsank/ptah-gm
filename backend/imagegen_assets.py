"""Trusted ImageGen CLI bundles, kept outside managed agent capabilities."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
from pathlib import Path

from PIL import Image

MAX_IMAGE_BYTES = 32 * 1024 * 1024


class ImageAssetError(ValueError):
    pass


def git(root, *args, binary=False):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            timeout=30, check=False)
    if result.returncode:
        raise ImageAssetError('Image bundle Git operation failed.')
    return result.stdout if binary else result.stdout.decode().strip()


def image_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'assets/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.png', value):
        raise ImageAssetError('CLI image assets require bounded assets/**/*.png paths.')
    return value


def requests_for(plan):
    """Derive prompts from reviewed object intent, without inventing art scope."""
    grouped = {}
    for obj in plan['document']['objects']:
        for binding in obj.get('sourceBindings', []):
            if not binding.startswith('assets/') or binding in (plan.get('sourceRefs') or {}):
                continue
            path = image_path(binding)
            grouped.setdefault(path, []).append(obj)
    if len(grouped) > 20:
        raise ImageAssetError('Split image production into at most 20 bound PNGs.')
    requests = []
    for path, objects in sorted(grouped.items()):
        prompt = ('Use case: stylized-concept\nAsset type: Godot 2D game source art\n'
                  'Primary request: ' + str(plan['document'].get('summary', '')) + '\n'
                  'Requested source file: ' + path + '\n'
                  'Create only the image named by this file; when bindings list several boards, do not combine those boards.\n'
                  'Approved visual context: ' + json.dumps([{'id': o['id'], 'name': o['name'], 'description': o.get('description', '')} for o in plan['document']['objects']], ensure_ascii=False)[:12000] + '\n'
                  'Create the exact source image described by these approved objects:\n'
                  + json.dumps(objects, ensure_ascii=False, sort_keys=True) + '\n'
                  'Constraints: preserve the specified subjects, action counts, view directions and style. '
                  'For a sprite sheet, keep consistent cell sizes, alignment and complete unclipped figures. '
                  'Use a plain solid backdrop when isolation is needed. No watermark or invented text. '
                  'Do not claim transparent alpha or runtime animation correctness.')
        if len(prompt) > 24000:
            raise ImageAssetError('Image prompt is too large; split the object art scope.')
        requests.append({'path': path, 'prompt': prompt})
    return requests


def validate_png(data):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageAssetError('Image is missing or exceeds 32 MiB.')
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != 'PNG' or img.width * img.height > 16_777_216 or img.width < 16 or img.height < 16:
                raise ImageAssetError('Image must be a bounded, decodable PNG.')
            size = list(img.size)
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageAssetError('Image is not a valid PNG.') from exc
    return size


def load_bundle(state_root, bundle_id, expected=None):
    """Read exact committed bytes, reject dirty/linked or mismatched bundles."""
    if not isinstance(bundle_id, str) or not re.fullmatch(r'imagegen-[a-f0-9]{32}', bundle_id):
        raise ImageAssetError('Invalid image bundle ID.')
    root = Path(state_root) / 'imagegen' / 'bundles' / bundle_id
    for parent in [Path(state_root), root.parent.parent, root.parent, root]:
        if parent.is_symlink():
            raise ImageAssetError('Image bundle paths cannot be symlinks.')
    if not (root / '.git').is_dir() or (root / '.git').is_symlink():
        raise ImageAssetError('Image bundle repository is unavailable.')
    for entry in root.rglob('*'):
        if entry.is_symlink() or (entry.is_file() and entry.stat().st_nlink != 1):
            raise ImageAssetError('Image bundle cannot contain links.')
    if (root / '.git/objects/info/alternates').exists() or git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise ImageAssetError('Image bundle is dirty or shares Git objects.')
    commit = git(root, 'rev-parse', 'HEAD')
    try:
        manifest = json.loads(git(root, 'show', commit + ':manifest.json'))
        plan = manifest['plan']
        jobs = manifest['requests']
        if manifest['schemaVersion'] != 'studio.imagegen-bundle.v1' or manifest['model'] != 'gpt-image-2':
            raise ImageAssetError('Unsupported image bundle provenance.')
        if jobs != requests_for(plan) or not jobs:
            raise ImageAssetError('Image bundle prompts do not match the bound plan.')
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ImageAssetError('Image bundle manifest is invalid.') from exc
    paths = [job['path'] for job in jobs]
    names = git(root, 'ls-tree', '-r', '--name-only', commit).splitlines()
    if sorted(names) != sorted(['manifest.json', *paths]):
        raise ImageAssetError('Image bundle contains unexpected files.')
    images, inventory = {}, {}
    for path in paths:
        mode = git(root, 'ls-tree', commit, '--', path).split()[0]
        if mode != '100644':
            raise ImageAssetError('Image bundle files must be regular non-executable files.')
        data = git(root, 'show', commit + ':' + path, binary=True)
        validate_png(data)
        images[path] = data
        inventory[path] = 'git:blob:' + git(root, 'rev-parse', commit + ':' + path)
    ref = {'bundleId': bundle_id, 'sourceCommit': commit, 'model': 'gpt-image-2',
           'paths': paths, 'sourceRefs': inventory, 'requests': jobs}
    if expected is not None and ref != expected:
        raise ImageAssetError('Reviewed image bundle version changed.')
    return ref, plan, images


def import_bundle(state_root, packet, destination):
    ref = packet.get('assetBundle')
    if not ref:
        return []
    _, plan, images = load_bundle(state_root, ref['bundleId'], expected=ref)
    if plan['document'] != packet['document'] or plan['tasks'] != packet['tasks'] or plan['projectId'] != packet['projectId']:
        raise ImageAssetError('Image bundle intent differs from the approved packet.')
    for path, data in images.items():
        target = Path(destination) / image_path(path)
        if target.exists() or target.is_symlink() or any(p.is_symlink() for p in target.parents):
            raise ImageAssetError('Image import refuses existing or linked destinations.')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o644)
    return sorted(images)
