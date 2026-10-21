"""Isolated native tool-routing host, without project or authentication access."""
from __future__ import annotations

import os
import random
import socket
import subprocess
import time
from pathlib import Path

from .common import RunnerError, _seatbelt_quote, strict_sandbox_rules


class IsolatedCodeModeHost:
    def __init__(self, root: Path, native_executable: str, protected: list[Path]):
        bundle = Path(native_executable).parents[3]
        executable = bundle / "bin/codex-code-mode-host"
        if (not executable.is_file() or executable.is_symlink()
                or executable.resolve() != executable or executable.stat().st_mode & 0o022):
            raise RunnerError("trusted installed tool-routing host is unavailable")
        root.mkdir(mode=0o700)
        self.root = root.resolve(strict=True)
        self.process = None
        self.log = None
        for attempt in range(2):
            try:
                self._start(executable, bundle, protected)
                return
            except (OSError, RunnerError):
                # No native thread exists at this stage. Close/reap the first
                # host before the single bounded retry; uncertain cleanup raises.
                self.close()
                if attempt == 1:
                    raise
                time.sleep(random.uniform(.1, .3))

    def _start(self, executable, bundle, protected):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.url = f"grpc://127.0.0.1:{self.port}"
        self.client_url = f"http://127.0.0.1:{self.port}"
        rules = strict_sandbox_rules(self.root, read_roots=[self.root, bundle], write_roots=[self.root],
            protected_paths=protected, allow_internet=False)
        rules += ["(allow file-read-metadata)", "(deny process-fork)",
                  f"(deny process-exec (require-not (literal {_seatbelt_quote(executable)})))",
                  f'(allow network-bind (local tcp "localhost:{self.port}"))',
                  f'(allow network-inbound (local tcp "localhost:{self.port}"))']
        self.policy = "".join(rules)
        self.log = (self.root / "host.log").open("ab")
        self.process = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", self.policy,
            str(executable), "--listen", self.url], cwd=self.root,
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.root), "TMPDIR": str(self.root)},
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RunnerError("isolated tool-routing host exited before readiness")
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=.1):
                        return
                except OSError:
                    time.sleep(.05)
            raise RunnerError("isolated tool-routing host did not become ready")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.process is not None:
            self.process.wait(timeout=2)
        if self.log is not None:
            self.log.close()

