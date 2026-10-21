"""Start, inspect and stop the four local Studio components independently."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPONENTS = ('backend', 'frontend', 'agent', 'project')


def process_identity(pid):
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart=', '-o', 'stat='],
                            capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    if not value or value.split()[-1].startswith('Z'):
        return None
    return ' '.join(value.split()[:-1])


@contextlib.contextmanager
def registry(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    lock = root/'services.lock'
    path = root/'services.json'
    if lock.is_symlink() or path.is_symlink():
        raise RuntimeError('Service registry cannot be a symlink.')
    with lock.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        records = json.loads(path.read_text()) if path.exists() else {}
        yield records
        temp = root/'services.json.tmp'
        if temp.is_symlink():
            raise RuntimeError('Service registry temporary path cannot be a symlink.')
        temp.write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n')
        temp.chmod(0o600)
        temp.replace(path)


def component_command(component, root, *, api_port=8765, frontend_port=8764, test_data=False, godot=None):
    python = str(REPO/'.venv'/'bin'/'python')
    if not Path(python).is_file():
        python = sys.executable
    if component == 'backend':
        return [python, '-m', 'backend.server', '--port', str(api_port), '--state-root', str(root), *(['--test-data'] if test_data else [])]
    if component == 'frontend':
        return [python, '-m', 'tools.studio_frontend', '--port', str(frontend_port), '--backend-port', str(api_port)]
    module = 'runners.agent' if component == 'agent' else 'runners.project'
    args = [python, '-m', module, '--url', f'http://127.0.0.1:{api_port}',
        '--runner-token-file', str(root/'runner-token'), '--state', str(root/'runners'/component/'journal.sqlite3'),
        '--artifact-root', str(root/'artifacts'), '--protected-root', str(root)]
    if component == 'agent':
        args += ['--workspace-root', str(root/'runners'/'agent'/'workspaces')]
    elif godot:
        args += ['--godot', godot]
    return args


def start(root, components, **options):
    with registry(root) as records:
        for component in components:
            old = records.get(component, {})
            if old.get('processIdentity') and process_identity(old.get('pid')) == old['processIdentity']:
                print(json.dumps({'component': component, 'status': 'already_running'}), flush=True)
                continue
            if component in {'agent', 'project'}:
                with urllib.request.urlopen(f"http://127.0.0.1:{options['api_port']}/api/v1/handshake", timeout=3) as response:
                    if json.load(response).get('protocolVersion') != 1:
                        raise RuntimeError('Backend protocol is incompatible.')
            log = root/'logs'/f'{component}.log'
            log.parent.mkdir(exist_ok=True, mode=0o700)
            if log.is_symlink():
                raise RuntimeError('Component log cannot be a symlink.')
            command = component_command(component, root, **options)
            with log.open('ab', buffering=0) as output:
                log.chmod(0o600)
                child = subprocess.Popen(command, cwd=REPO, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            time.sleep(.15)
            identity = process_identity(child.pid)
            if not identity:
                raise RuntimeError(f'{component} did not remain running; inspect {log}')
            records[component] = {'pid': child.pid, 'processIdentity': identity, 'argv': command, 'log': str(log)}
            # Save each successful start even if the next component fails.
            (root/'services.json').write_text(json.dumps(records, indent=2)+'\n')
            (root/'services.json').chmod(0o600)
            if component == 'backend':
                deadline = time.monotonic()+15
                while True:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{options['api_port']}/api/v1/handshake", timeout=1) as response:
                            json.load(response)
                        break
                    except OSError:
                        if time.monotonic() >= deadline or child.poll() is not None:
                            raise RuntimeError(f'Backend unavailable; inspect {log}')
                        time.sleep(.2)
            print(json.dumps({'component': component, 'status': 'running', 'pid': child.pid, 'log': str(log)}), flush=True)


def status(root, components):
    with registry(root) as records:
        for component in components:
            record = records.get(component, {})
            running = bool(record.get('processIdentity') and process_identity(record.get('pid')) == record['processIdentity'])
            print(json.dumps({'component': component, 'status': 'running' if running else 'stopped',
                'pid': record.get('pid'), 'log': record.get('log')}), flush=True)


def stop(root, components):
    with registry(root) as records:
        for component in components:
            record = records.get(component, {})
            expected = record.get('processIdentity')
            if not expected or process_identity(record.get('pid')) != expected:
                print(json.dumps({'component': component, 'status': 'stopped_or_identity_changed'}), flush=True)
                continue
            os.kill(record['pid'], signal.SIGINT)
            deadline = time.monotonic()+20
            while process_identity(record['pid']) == expected and time.monotonic() < deadline:
                time.sleep(.2)
            stopped = process_identity(record['pid']) != expected
            print(json.dumps({'component': component, 'status': 'stopped' if stopped else 'stop_unconfirmed'}), flush=True)
            if not stopped:
                raise RuntimeError('Stop remains unconfirmed; preserve journals and occupancy for reconciliation.')
            record['stopped'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status'))
    parser.add_argument('--component', choices=('all', *COMPONENTS), default='all')
    parser.add_argument('--state-root', type=Path, default=REPO/'.workbench')
    parser.add_argument('--api-port', type=int, default=8765)
    parser.add_argument('--frontend-port', type=int, default=8764)
    parser.add_argument('--test-data', action='store_true')
    parser.add_argument('--godot', default='/Applications/Godot.app/Contents/MacOS/Godot')
    args = parser.parse_args()
    root = args.state_root.resolve()
    components = list(COMPONENTS) if args.component == 'all' else [args.component]
    if args.action == 'start':
        start(root, components, api_port=args.api_port, frontend_port=args.frontend_port, test_data=args.test_data, godot=args.godot)
    elif args.action == 'stop':
        stop(root, [component for component in ('agent', 'project', 'frontend', 'backend') if component in components])
    else:
        status(root, components)


if __name__ == '__main__':
    main()
