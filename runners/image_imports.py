"""Exact disposable image-import metadata; never part of sealed source."""
from __future__ import annotations

import json
import re
import stat
from pathlib import Path, PurePosixPath

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def validate_import_path(project: Path, value) -> Path:
    project = project.resolve(strict=True)
    raw = Path(value)
    if not raw.is_absolute():
        raw = project / raw
    try:
        relative = raw.relative_to(project)
    except ValueError as exc:
        raise ValueError('image import metadata must stay inside the project') from exc
    parts = relative.parts
    if len(parts) < 2 or parts[0] != 'assets' or any(p in {'.', '..'} for p in parts) or not str(raw).endswith('.import'):
        raise ValueError('image import metadata must accompany an assets/ image')
    source = Path(str(raw)[:-7])
    if source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError('unsupported image import source')
    cursor = project
    for part in parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError('image import metadata cannot contain symlinks')
    if source.is_symlink() or not source.is_file() or source.stat().st_nlink != 1:
        raise ValueError('image import source must be a regular unlinked image')
    return raw


def missing_image_imports(project: Path, source_paths) -> tuple[str, ...]:
    paths = []
    for name in sorted(source_paths):
        source = PurePosixPath(name)
        if len(source.parts) < 2 or source.parts[0] != 'assets' or source.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        path = validate_import_path(project, name + '.import')
        if not path.exists():
            paths.append(name + '.import')
    return tuple(paths)


def read_generated_imports(project: Path, paths) -> dict[str, bytes]:
    """Accept only bounded texture metadata bound to the exact source/cache."""
    results = {}
    for name in paths:
        path = validate_import_path(project, name)
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_mode & 0o111 or not 0 < metadata.st_size <= 128 * 1024:
            raise ValueError('invalid disposable image import metadata file')
        data = path.read_bytes()
        text = data.decode('utf-8')
        def field(key):
            values = re.findall(r'^' + re.escape(key) + r'=(.+)$', text, re.MULTILINE)
            if len(values) != 1:
                raise ValueError('invalid image import metadata field: ' + key)
            return json.loads(values[0])
        if field('importer') != 'texture' or field('type') != 'CompressedTexture2D' or field('source_file') != 'res://' + name[:-7]:
            raise ValueError('image import metadata differs from its exact source')
        destination = field('path')
        dest_files = field('dest_files')
        if not isinstance(destination, str) or not re.fullmatch(r'res://\.godot/imported/[^/\\]+\.ctex', destination) or dest_files != [destination]:
            raise ValueError('image import metadata must reference only disposable texture cache')
        results[name] = data
    return results
