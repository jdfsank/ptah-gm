"""Independent prompt-to-image tool using the bundled ImageGen CLI.

No Studio, project, approval, asset import or game concepts belong here.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CLI = Path.home() / '.codex/skills/.system/imagegen/scripts/image_gen.py'


class ImageGenerationError(RuntimeError):
    pass


def generate_images(requests, *, output_dir, size='1536x1024', quality='medium',
                    dry_run=False, timeout=1200, cancel_event=None):
    """Accept [{prompt, filename}], return output paths; never import outputs."""
    if not isinstance(requests, list) or not 1 <= len(requests) <= 100:
        raise ImageGenerationError('Provide between 1 and 100 image prompts.')
    if not CLI.is_file() or CLI.resolve() != CLI:
        raise ImageGenerationError('Bundled ImageGen CLI is unavailable.')
    if not dry_run and not os.environ.get('OPENAI_API_KEY'):
        raise ImageGenerationError('Set OPENAI_API_KEY locally before live generation.')
    output = Path(output_dir).expanduser().absolute()
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ImageGenerationError('Use a new, unlinked output directory.')
    names = []
    jobs = []
    for job in requests:
        if not isinstance(job, dict) or set(job) != {'prompt', 'filename'}:
            raise ImageGenerationError('Each request needs only prompt and filename.')
        prompt, filename = job['prompt'], job['filename']
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
            raise ImageGenerationError('Image prompt must be nonempty and bounded.')
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.png') or filename.startswith('.') or filename in names:
            raise ImageGenerationError('Use distinct plain PNG filenames.')
        names.append(filename)
        jobs.append({'prompt': prompt, 'out': str(output / filename)})
    output.mkdir(parents=True, mode=0o700)
    log = output / 'imagegen-cli.log'
    try:
        with tempfile.TemporaryDirectory(prefix='imagegen-cli-') as scratch:
            batch = Path(scratch) / 'requests.jsonl'
            batch.write_text(''.join(json.dumps(job, ensure_ascii=False) + '\n' for job in jobs))
            command = [sys.executable, str(CLI), 'generate-batch', '--input', str(batch),
                       '--out-dir', str(output), '--model', 'gpt-image-2', '--size', size,
                       '--quality', quality, '--output-format', 'png', '--concurrency', '1',
                       '--max-attempts', '1', '--no-augment']
            if dry_run:
                command.append('--dry-run')
            with log.open('wb') as stream:
                os.chmod(log, 0o600)
                process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + timeout
                try:
                    while process.poll() is None:
                        if time.monotonic() >= deadline or (cancel_event is not None and cancel_event.is_set()):
                            raise ImageGenerationError('ImageGen CLI stopped; reconcile the original request. Private log: ' + str(log))
                        time.sleep(0.1)
                finally:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            process.wait(3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
        if process.returncode:
            raise ImageGenerationError('ImageGen CLI failed; private log: ' + str(log))
        files = [output / name for name in names]
        if not dry_run and any(p.is_symlink() or not p.is_file() or p.stat().st_size == 0 for p in files):
            raise ImageGenerationError('ImageGen did not return every requested image.')
        (output / 'prompts.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2) + '\n')
        return {'status': 'DRY_RUN' if dry_run else 'GENERATED',
                'model': 'gpt-image-2', 'images': [] if dry_run else [str(p) for p in files],
                'prompts': str(output / 'prompts.json'), 'log': str(log)}
    except subprocess.TimeoutExpired:
        raise ImageGenerationError('ImageGen CLI exceeded its time limit; private log: ' + str(log)) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--prompt')
    inputs.add_argument('--prompt-file', type=Path)
    inputs.add_argument('--input', type=Path, help='JSON array of {prompt,filename}')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--filename', default='image.png')
    parser.add_argument('--size', default='1536x1024')
    parser.add_argument('--quality', choices=('low', 'medium', 'high', 'auto'), default='medium')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        requests = json.loads(args.input.read_text()) if args.input else [{'prompt': args.prompt if args.prompt is not None else args.prompt_file.read_text(), 'filename': args.filename}]
        print(json.dumps(generate_images(requests, output_dir=args.output_dir,
                         size=args.size, quality=args.quality, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    except (ImageGenerationError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
