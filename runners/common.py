"""Strict HTTP client, durable report outbox, and local process supervision.

This module deliberately has no dependency on the Studio database or user
session. Runner credentials are loaded only by the runner process.
"""
from __future__ import annotations

import json
import math
import os
import random
import fcntl
import errno
import sqlite3
import stat
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CONTROL_RESPONSE_BYTES = 2_000_000
MAX_REFERENCE_ASSETS = 16
MAX_REFERENCE_ASSET_BYTES = 5 * 1024 * 1024
# Input packets can contain every supported image, encoded as base64, plus
# bounded planning/source metadata. Control messages keep their smaller limit.
INPUT_RESPONSE_BYTES = (CONTROL_RESPONSE_BYTES
                        + MAX_REFERENCE_ASSETS * 4 * ((MAX_REFERENCE_ASSET_BYTES + 2) // 3))


class RunnerError(RuntimeError):
    pass


class TransportError(RunnerError):
    """Temporary backend transport failure; durable runner state is retained."""


def _retry_delay(delay: float, failures: int, maximum: float = 60.0) -> float:
    return min(maximum, delay * 2 ** min(failures - 1, 10) * random.uniform(0.8, 1.2))


def retry_transport(operation, stop_event, *, delay: float = 2.0, sleep_fn=time.sleep):
    """Retry only transient transport failures until success or shutdown."""
    failures = 0
    while not stop_event.is_set():
        try:
            return operation()
        except TransportError:
            failures += 1
            pause = _retry_delay(delay, failures)
            stop_event.wait(pause) if hasattr(stop_event, "wait") else sleep_fn(pause)
    return None


def service_loop(iteration, stop_event, *, once: bool = False, delay: float = 5.0,
                 sleep_fn=time.sleep):
    """Run service iterations through transient outages without losing intent."""
    failures = 0
    while not stop_event.is_set():
        try:
            iteration()
            failures = 0
            if once:
                return
            stop_event.wait(delay) if hasattr(stop_event, "wait") else sleep_fn(delay)
        except TransportError:
            if once:
                return
            failures += 1
            pause = _retry_delay(delay, failures)
            stop_event.wait(pause) if hasattr(stop_event, "wait") else sleep_fn(pause)


def stop_process_group(pgid: int, *, process=None, grace_seconds: float = 5.0) -> bool:
    """Request group shutdown, escalate if needed, and confirm the group is gone."""
    import signal

    def exists():
        try:
            os.killpg(pgid, 0)
            return True
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            # Inspection may transiently fail while a leader exits. Only
            # ESRCH proves the group is gone; retain bounded supervision for
            # permission failures rather than aborting cleanup.
            return True

    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return True
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process is not None:
            process.poll()  # Reap the leader so an exited group can disappear.
        if not exists():
            return True
        time.sleep(0.05)
    if exists():
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return True
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process is not None:
            process.poll()
        if not exists():
            return True
        time.sleep(0.05)
    return not exists()


def process_output_lines(process, *, timeout: float = 1.0,
                         max_output_bytes: int = 12_000_000):
    """Yield decoded lines, or None while waiting, without blocking supervision.

    EOF is permanently readable to select(); track it explicitly rather than
    spinning after the worker exits. Read bytes directly so a partial line
    cannot hold up cancellation, heartbeats or local time limits.
    """
    import select

    if process.stdout is None:
        raise RunnerError("worker has no output pipe")
    pending = b""
    total = 0
    eof = False
    while not eof or process.poll() is None:
        if eof:
            time.sleep(timeout)
            yield None
            continue
        ready, _, _ = select.select([process.stdout], [], [], timeout)
        if not ready:
            yield None
            continue
        chunk = os.read(process.stdout.fileno(), 65536)
        if not chunk:
            eof = True
            if pending:
                yield pending.decode("utf-8", errors="replace")
                pending = b""
            continue
        total += len(chunk)
        if total > max_output_bytes:
            raise RunnerError("worker output exceeded the configured limit")
        lines = (pending + chunk).split(b"\n")
        pending = lines.pop()
        for line in lines:
            yield line.decode("utf-8", errors="replace") + "\n"
        # A chunk with no complete line must also permit supervision.
        if not lines:
            yield None


def _seatbelt_quote(path: str | Path) -> str:
    value = str(Path(path).resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def sandboxed_run(argv: list[str], *, cwd: Path, deny_paths: list[Path],
                  studio_host: str = "localhost", studio_port: int | None = None,
                  timeout: float | None = None, input_text: str | None = None):
    """Run a complete child process tree under a verified macOS seatbelt.

    The runner itself retains API credentials; the worker receives neither the
    token nor access to the local Studio HTTP port. External model networking
    remains available to the native client.
    """
    import platform
    import subprocess

    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RunnerError("macOS process sandbox is unavailable; execution is disabled")
    protected = sorted({Path(path).resolve() for path in deny_paths if Path(path).exists()}, key=str)
    active = Path(cwd).resolve(strict=True)
    if not protected:
        raise RunnerError("no protected sibling project paths were supplied")
    executable = Path(argv[0])
    if executable.is_file():
        argv = [str(executable.resolve()), *argv[1:]]
    rules = strict_sandbox_rules(active, read_roots=[active], write_roots=[active],
                                 protected_paths=protected, allow_internet=True)
    profile = "".join(rules)
    return subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, *argv], cwd=str(active),
                          capture_output=True, text=True, timeout=timeout, input=input_text,
                          check=False)


def strict_sandbox_rules(active_root: Path, *, read_roots: list[Path],
                         write_roots: list[Path], protected_paths: list[Path],
                         deny_write_paths: list[Path] | None = None,
                         extra_read_paths: list[Path] | None = None,
                         list_roots: list[Path] | None = None,
                         allow_graphics: bool = False,
                         allow_internet: bool = False) -> list[str]:
    """Build deny-default rules with explicit runtime, workspace and write roots."""
    import sys
    import shutil

    rules = ["(version 1)", "(deny default)", "(allow process*)", "(allow sysctl-read)",
             "(allow mach-lookup)", "(allow ipc-posix-shm)", "(allow file-read* (literal \"/dev/null\"))",
             "(allow file-write* (literal \"/dev/null\"))",
             # Seatbelt needs permission to stat the root inode during exec
             # path traversal; child file access remains governed by the
             # narrower runtime/workspace rules and explicit denies below.
             "(allow file-read* (literal \"/\"))"]
    for device in ("/dev/urandom", "/dev/random"):
        rules.append(f'(allow file-read* (literal "{device}"))')
    if allow_graphics:
        rules.append('(allow iokit-open (iokit-user-client-class "IOSurfaceRootUserClient") '
                     '(iokit-user-client-class "IOHIDParamUserClient") '
                     '(iokit-user-client-class "IOGPUGLDrawableUserClient") '
                     '(iokit-user-client-class "AGXDeviceUserClient"))')
        rules.append('(allow file-read* (literal "/Library/Preferences/com.apple.ViewBridge.plist"))')
    runtime_roots = {Path("/System"), Path("/usr"), Path("/bin"), Path("/sbin"),
                     Path("/Library/Apple"), Path("/Library/Developer/CommandLineTools"), Path("/etc")}
    for item in (Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).parent):
        runtime_roots.add(item.resolve())
    executable = shutil.which("codex")
    if executable:
        executable_path = Path(executable).resolve()
        rules.append(f"(allow file-read* (literal {_seatbelt_quote(executable_path)}))")
        # Bundled CLI resources share its app bundle; executable parent alone
        # is insufficient for the native app-server runtime.
        for parent in executable_path.parents:
            if parent.name.endswith(".app"):
                runtime_roots.add(parent)
                break
    for path in sorted(runtime_roots, key=str):
        if path.exists():
            rules.append(f"(allow file-read* (subpath {_seatbelt_quote(path)}))")
    for path in sorted({Path(p).resolve() for p in [*read_roots, *(extra_read_paths or [])]
                        if Path(p).exists()}, key=str):
        rules.append(f"(allow file-read* (subpath {_seatbelt_quote(path)}))")
        # Python import machinery stats each sys.path directory before looking
        # inside a granted package. Permit inode metadata, never parent data.
        for parent in path.parents:
            rules.append(f"(allow file-read-metadata (literal {_seatbelt_quote(parent)}))")
    for path in sorted({Path(p).resolve() for p in write_roots if Path(p).exists()}, key=str):
        rules.append(f"(allow file-write* (subpath {_seatbelt_quote(path)}))")
    for path in sorted({Path(p).resolve() for p in (list_roots or [])}, key=str):
        # Package discovery needs directory entries at PYTHONPATH itself, but
        # that grants no read access to files or sibling packages underneath.
        rules.append(f"(allow file-read* (literal {_seatbelt_quote(path)}))")
    # Deny rules take precedence over any broader active-workspace grant.
    for path in sorted({Path(p).resolve() for p in protected_paths}, key=str):
        quoted = _seatbelt_quote(path)
        rules.append(f"(deny file-read* (subpath {quoted}))")
        rules.append(f"(deny file-write* (subpath {quoted}))")
    for path in sorted({Path(p).resolve() for p in (deny_write_paths or [])}, key=str):
        rules.append(f"(deny file-write* (subpath {_seatbelt_quote(path)}))")
    if allow_internet:
        rules.append("(allow network-outbound)")
        # Seatbelt resolves localhost to both IPv4 and IPv6 loopback. Wildcard
        # ports cover dynamic service and local API ports.
        rules.append('(deny network-outbound (remote tcp "localhost:*"))')
    return rules


def protected_siblings(root: Path, active: Path | None = None) -> list[Path]:
    """Return project directories below root except the one active workspace."""
    root = Path(root).resolve()
    active_path = Path(active).resolve() if active else None
    denied: list[Path] = []

    def walk(parent: Path):
        try:
            children = sorted(parent.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            resolved = child.resolve()
            if active_path == resolved:
                continue
            if active_path and active_path.is_relative_to(resolved):
                walk(child)
            else:
                denied.append(resolved)

    if root.is_dir():
        walk(root)
    return denied


def materialize_service_records(root: Path, records: dict | None) -> None:
    """Write only backend-pinned ignored GM records into a private copy."""
    if records is None:
        return
    allowed = {".godotmaker/frontend-approval.json", ".godotmaker/stage.jsonl"}
    if not isinstance(records, dict) or set(records) - allowed:
        raise RunnerError("prepared service record set is invalid")
    root = Path(root).resolve(strict=True)
    folder = root / ".godotmaker"
    if folder.is_symlink():
        raise RunnerError("GM service record directory cannot be a symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    for relative, content in records.items():
        if not isinstance(content, str) or len(content.encode("utf-8")) > 2_000_000:
            raise RunnerError("prepared GM service record content is invalid")
        target = root / relative
        if target.is_symlink():
            raise RunnerError("prepared GM service record cannot overwrite a symlink")
        temporary = folder / (".runner-record-" + str(uuid.uuid4()))
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)


def strict_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RunnerError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise RunnerError(f"invalid JSON constant: {value}")

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise RunnerError("non-finite JSON number")
        return parsed

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=constant, parse_float=finite_float)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError(f"invalid JSON response: {exc}") from exc


class RunnerHTTP:
    def __init__(self, base_url: str, token_file: str | Path, runner_id: str, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        path = Path(token_file)
        if path.is_symlink() or not path.is_file():
            raise RunnerError("runner token file must be a regular file")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise RunnerError("runner token file must be private (0600)")
        self.token = path.read_text(encoding="utf-8").strip()
        if not self.token:
            raise RunnerError("runner token is empty")
        self.timeout = timeout
        self.runner_id = runner_id
        self.token_path = path.resolve()

    def request(self, method: str, route: str, body: dict | None = None) -> dict:
        if not route.startswith("/") or ".." in route.split("/"):
            raise RunnerError("invalid internal API route")
        encoded = None if body is None else json.dumps(
            body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + route, data=encoded, method=method,
            headers={"X-Runner-Token": self.token, "X-Runner-Id": self.runner_id,
                     "Accept": "application/json",
                     **({"Content-Type": "application/json"} if encoded is not None else {})},
        )
        parts = route.split("/")
        is_input = (method == "GET" and len(parts) == 6
                    and parts[:4] == ["", "internal", "v1", "attempts"]
                    and parts[4] and all(c.isalnum() or c in "._:-" for c in parts[4])
                    and parts[5] == "input")
        response_limit = INPUT_RESPONSE_BYTES if is_input else CONTROL_RESPONSE_BYTES
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(response_limit + 1)
                if len(raw) > response_limit:
                    raise RunnerError("Studio API response exceeds the configured byte limit")
                result = strict_json(raw)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(1000).decode("utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            finally:
                exc.close()
            if exc.code == 429 or 500 <= exc.code <= 599:
                raise TransportError(f"Studio API temporarily unavailable (HTTP {exc.code})") from exc
            raise RunnerError(f"Studio API rejected request (HTTP {exc.code})"
                              + (f": {detail}" if detail else "")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"Studio API unavailable: {exc}") from exc
        if not isinstance(result, dict):
            raise RunnerError("Studio API response must be an object")
        return result


class RunnerLock:
    """Exclusive lifetime lock colocated with one runner's private journal."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise RunnerError("runner service lock cannot be a symlink")
        self._stream = self.path.open("a+", encoding="utf-8")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._stream.close()
            self._stream = None
            raise RunnerError("another runner already holds this service lock") from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._stream is not None:
            try:
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            finally:
                self._stream.close()
                self._stream = None


class LocalJournal:
    """Durable intent and report spool; report IDs survive process restarts."""
    MAX_PENDING_REPORTS = 1000
    MAX_PENDING_BYTES = 32 * 1024 * 1024
    MAX_PENDING_ACTIVITY = 500
    MAX_ACKED_ACTIVITY = 500
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise RunnerError("journal path cannot be a symlink")
        self.path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.path, 0o600)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(
                    attempt_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                    native_identity TEXT, state TEXT NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS reports(
                    report_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
                    body_json TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS pending_claims(
                    store_id TEXT PRIMARY KEY, command_id TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO metadata VALUES('runnerId',?)", ("runner-" + uuid.uuid4().hex,))
        self.bound_store_id = None

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @property
    def runner_id(self):
        with self._connect() as db:
            return db.execute("SELECT value FROM metadata WHERE key='runnerId'").fetchone()[0]

    def bind_store(self, store_id: str) -> None:
        """Pin this journal to one store and quarantine restored/mixed namespaces."""
        if not isinstance(store_id, str) or not store_id:
            raise RunnerError("Studio handshake storeId is invalid")
        quarantine_error = None
        with self._connect() as db:
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            quarantine = metadata.get("quarantinedStoreId")
            if quarantine:
                raise RunnerError(f"journal is quarantined for original store {quarantine}; reconcile before use")
            old_store = metadata.get("storedStoreId")
            observed = set()
            for (request_json,) in db.execute("SELECT request_json FROM attempts"):
                try:
                    request = json.loads(request_json)
                except (ValueError, TypeError):
                    raise RunnerError("journal attempt namespace is malformed")
                value = request.get("storeId") if isinstance(request, dict) else None
                if isinstance(value, str): observed.add(value)
            for (body_json,) in db.execute("SELECT body_json FROM reports WHERE acknowledged=0"):
                try:
                    body = json.loads(body_json)
                except (ValueError, TypeError):
                    raise RunnerError("journal report namespace is malformed")
                value = body.get("storeId") if isinstance(body, dict) else None
                if isinstance(value, str): observed.add(value)
            if old_store:
                observed.add(old_store)
            mismatched = {value for value in observed if value != store_id}
            if mismatched:
                if len(mismatched) != 1:
                    raise RunnerError("journal contains multiple old store namespaces; manual reconcile is required")
                quarantined = next(iter(mismatched))
                db.execute("INSERT OR REPLACE INTO metadata VALUES('quarantinedStoreId',?)", (quarantined,))
                self.bound_store_id = None
                quarantine_error = f"journal is quarantined for original store {quarantined}; reconcile before use"
            else:
                db.execute("INSERT OR REPLACE INTO metadata VALUES('storedStoreId',?)", (store_id,))
                self.bound_store_id = store_id
        if quarantine_error:
            raise RunnerError(quarantine_error)

    def _require_store(self, store_id: str) -> None:
        if not isinstance(store_id, str) or not store_id:
            raise RunnerError("journal operation has no store namespace")
        if self.bound_store_id is not None and self.bound_store_id != store_id:
            raise RunnerError("journal operation crosses its pinned store namespace")
        namespace_error = None
        with self._connect() as db:
            metadata = dict(db.execute("SELECT key,value FROM metadata WHERE key IN ('storedStoreId','quarantinedStoreId')"))
            quarantine = metadata.get("quarantinedStoreId")
            if quarantine:
                namespace_error = f"journal is quarantined for original store {quarantine}; reconcile before use"
            elif metadata.get("storedStoreId") and metadata["storedStoreId"] != store_id:
                old_store = metadata["storedStoreId"]
                db.execute("INSERT OR REPLACE INTO metadata VALUES('quarantinedStoreId',?)", (old_store,))
                namespace_error = f"journal is quarantined for original store {old_store}; reconcile before use"
        if namespace_error:
            raise RunnerError(namespace_error)

    def record_claim(self, request: dict) -> None:
        """Durably save a backend claim before acknowledging its local command."""
        if not isinstance(request, dict):
            raise RunnerError("claimed execution request is invalid")
        attempt_id, store_id = request.get("attemptId"), request.get("storeId")
        if not isinstance(attempt_id, str) or not attempt_id or not isinstance(store_id, str):
            raise RunnerError("claimed execution is missing its attempt/store identity")
        self._require_store(store_id)
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as db:
            row = db.execute("SELECT request_json FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row and row[0] != encoded:
                raise RunnerError("attempt ID was reused with a different execution request")
            db.execute("INSERT OR IGNORE INTO attempts VALUES(?,?,NULL,'claimed',?)", (attempt_id, encoded, time.time()))

    def start_intent(self, attempt_id: str, request: dict) -> None:
        """Atomically consume a claimed attempt before the first worker launch."""
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as db:
            row = db.execute("SELECT request_json,state FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row and row[0] != encoded:
                raise RunnerError("attempt ID was reused with a different execution request")
            if row and row[1] != "claimed":
                raise RunnerError("attempt already crossed the launch-intent boundary; reconcile it instead of starting again")
            if row:
                db.execute("UPDATE attempts SET state='launch_intent',updated_at=? WHERE attempt_id=?",
                           (time.time(), attempt_id))
            else:
                # Compatibility for explicit diagnostic tooling; production
                # claim paths persist `claimed` first and use the guarded
                # transition above.
                db.execute("INSERT INTO attempts VALUES(?,?,NULL,'launch_intent',?)",
                           (attempt_id, encoded, time.time()))

    def set_identity(self, attempt_id: str, native_identity: str, state: str = "running") -> None:
        with self._connect() as db:
            row = db.execute("SELECT native_identity FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not row:
                raise RunnerError("native identity has no persisted start intent")
            if row[0]:
                try:
                    old, new = json.loads(row[0]), json.loads(native_identity)
                except (TypeError, ValueError) as exc:
                    raise RunnerError("persisted native identity is malformed") from exc
                keys = {"threadId", "turnId", "processId", "processGroupId", "processStartTime"}
                if not isinstance(old, dict) or not isinstance(new, dict) or set(old) != keys or set(new) != keys:
                    raise RunnerError("native identity has an invalid shape")
                for key, value in old.items():
                    if value is not None and new.get(key) != value:
                        raise RunnerError("native process identity changed during an attempt")
                for key, value in new.items():
                    if value is not None and old.get(key) not in (None, value):
                        raise RunnerError("native thread identity changed during an attempt")
            db.execute("UPDATE attempts SET native_identity=?,state=?,updated_at=? WHERE attempt_id=?",
                       (native_identity, state, time.time(), attempt_id))

    def add_report(self, attempt_id: str, kind: str, store_id: str, project_id: str,
                   runner_id: str, payload: dict) -> str | None:
        self._require_store(store_id)
        report_id = "report-" + uuid.uuid4().hex
        with self._connect() as db:
            request_row = db.execute("SELECT request_json FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if not request_row:
            raise RunnerError("cannot report an attempt without its persisted execution request")
        task_kind = json.loads(request_row[0]).get("taskKind")
        body = {"schemaVersion": "studio.message.v1", "kind": "execution_report",
                "storeId": store_id, "runnerId": runner_id, "projectId": project_id,
                "attemptId": attempt_id, "taskKind": task_kind,
                "reportId": report_id, "type": kind, "payload": payload}
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as db:
            if kind == "activity":
                count = 0
                for (pending_json,) in db.execute(
                        "SELECT body_json FROM reports WHERE acknowledged=0"):
                    try:
                        if json.loads(pending_json).get("type") == "activity":
                            count += 1
                    except (ValueError, AttributeError):
                        count += 1
                if count >= self.MAX_PENDING_ACTIVITY:
                    return None
            db.execute("INSERT INTO reports(report_id,attempt_id,body_json,created_at) VALUES(?,?,?,?)",
                       (report_id, attempt_id, encoded, time.time()))
        return report_id

    def prune_acknowledged_activity(self) -> int:
        """Bound low-value acknowledged activity history; retain terminal evidence."""
        with self._connect() as db:
            rows = db.execute("SELECT report_id,body_json FROM reports WHERE acknowledged=1 ORDER BY created_at DESC").fetchall()
            activity_ids = []
            for report_id, body_json in rows:
                try:
                    if json.loads(body_json).get("type") == "activity":
                        activity_ids.append(report_id)
                except (ValueError, AttributeError):
                    continue
            stale = activity_ids[self.MAX_ACKED_ACTIVITY:]
            if stale:
                db.executemany("DELETE FROM reports WHERE report_id=? AND acknowledged=1",
                               ((item,) for item in stale))
            return len(stale)

    def can_claim(self, *, max_reports: int | None = None, max_bytes: int | None = None) -> bool:
        """Pause new claims when durable unacknowledged reports approach capacity."""
        self.prune_acknowledged_activity()
        report_limit = self.MAX_PENDING_REPORTS if max_reports is None else max_reports
        byte_limit = self.MAX_PENDING_BYTES if max_bytes is None else max_bytes
        with self._connect() as db:
            count, size = db.execute(
                "SELECT count(*),coalesce(sum(length(CAST(body_json AS BLOB))),0) "
                "FROM reports WHERE acknowledged=0"
            ).fetchone()
        return count < report_limit and size < byte_limit

    def flush(self, api: RunnerHTTP) -> int:
        sent = 0
        with self._connect() as db:
            rows = db.execute("SELECT report_id,body_json FROM reports WHERE acknowledged=0 ORDER BY created_at").fetchall()
        for report_id, encoded in rows:
            body = json.loads(encoded)
            self._require_store(body.get("storeId"))
            ack = api.request("POST", "/internal/v1/reports", body)
            expected_identity = {key: body.get(key) for key in
                                 ("storeId", "projectId", "attemptId", "runnerId", "reportId")}
            if (ack.get("schemaVersion") != "studio.message.v1" or ack.get("kind") != "report_ack"
                    or any(ack.get(key) != value for key, value in expected_identity.items())):
                raise RunnerError("report acknowledgement identity mismatch")
            if ack.get("disposition") not in {"recorded", "evidence_only", "rejected"}:
                raise RunnerError("report acknowledgement disposition is invalid")
            if (ack["disposition"] == "evidence_only" and body.get("type") in {"completed", "stopped", "failed"}
                    and (body.get("payload") or {}).get("stopped") is True):
                self._reconcile_stopped(api, body)
            with self._connect() as db:
                db.execute("UPDATE reports SET acknowledged=1 WHERE report_id=?", (report_id,))
            sent += 1
        self.prune_acknowledged_activity()
        return sent

    def _reconcile_stopped(self, api: RunnerHTTP, report: dict) -> None:
        """After a lost lease, confirm the original stopped process; never resume it."""
        with self._connect() as db:
            row = db.execute("SELECT native_identity FROM attempts WHERE attempt_id=?",
                             (report["attemptId"],)).fetchone()
        if not row or not row[0]:
            return
        identity = json.loads(row[0])
        pid, group = identity.get("processId"), identity.get("processGroupId")
        if type(pid) is not int or type(group) is not int or pid <= 1 or group <= 1:
            return
        for inspect in (lambda: os.kill(pid, 0), lambda: os.killpg(group, 0)):
            try:
                inspect()
                return
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    return
        response = api.request("POST", "/internal/v1/reconcile", {
            "runnerId": report["runnerId"], "storeId": report["storeId"],
            "attemptId": report["attemptId"], "nativeIdentity": identity, "stopped": True})
        if (response.get("storeId") != report["storeId"] or response.get("attemptId") != report["attemptId"]
                or response.get("status") not in {"STOPPED", "COMPLETED", "FAILED"}):
            raise RunnerError("stopped reconciliation acknowledgement is invalid")

    def pending(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT count(*) FROM reports WHERE acknowledged=0").fetchone()[0]

    def claim_command(self, store_id: str) -> str:
        self._require_store(store_id)
        with self._connect() as db:
            row = db.execute("SELECT command_id FROM pending_claims WHERE store_id=?", (store_id,)).fetchone()
            if row:
                return row[0]
            command_id = "claim-" + uuid.uuid4().hex
            db.execute("INSERT INTO pending_claims VALUES(?,?)", (store_id, command_id))
            return command_id

    def claim_recorded(self, store_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM pending_claims WHERE store_id=?", (store_id,))


def sandbox_probe() -> dict:
    """Probe an actual file-read denial on macOS; unknown platforms fail closed."""
    import platform
    import subprocess
    import tempfile

    result = {"scheme": "macos-sandbox-exec-boundary-probe-v1", "status": "NOT_READY",
              "policy": "allow-default",
              "available": False, "passed": False, "crossProjectDenied": False,
              "approvalNetworkDenied": False, "verifiedCapabilities": [],
              "roleAssessment": {"planning-readonly-v1": "NOT_VERIFIED",
                                 "production-private-v1": "NOT_VERIFIED",
                                 "verification-isolated-v1": "NOT_VERIFIED",
                                 "preview-isolated-v1": "NOT_VERIFIED"},
              "observedAt": time.time(),
              "detail": "unsupported platform"}
    if platform.system() != "Darwin":
        return result
    executable = Path("/usr/bin/sandbox-exec")
    if not executable.is_file():
        result["detail"] = "sandbox-exec unavailable"
        return result
    with tempfile.TemporaryDirectory(prefix="studio-sandbox-probe-") as directory:
        target = Path(directory) / "secret"
        target.write_text("private", encoding="utf-8")
        resolved_directory = Path(directory).resolve()
        policy = (f'(version 1)(allow default)(deny file-read* (subpath {_seatbelt_quote(resolved_directory)}))'
                  f'(deny file-write* (subpath {_seatbelt_quote(resolved_directory)}))'
                  '(deny network-outbound)')
        listeners = []
        try:
            import socket
            for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
                listener = socket.socket(family)
                listeners.append(listener)
                listener.bind((host, 0))
                listener.listen(2)
            script = ("import socket,sys; "
                      "\ntry:\n open(sys.argv[1], encoding='utf-8').read(); print('FILE_ALLOWED')"
                      "\nexcept Exception: print('FILE_DENIED')"
                      "\ntry:\n open(sys.argv[1], 'w', encoding='utf-8').write('changed'); print('WRITE_ALLOWED')"
                      "\nexcept Exception: print('WRITE_DENIED')"
                      "\nfor host,port in ((\"127.0.0.1\",int(sys.argv[2])),(\"::1\",int(sys.argv[3]))):\n"
                      " try:\n  socket.create_connection((host,port),timeout=.5); print('NETWORK_ALLOWED:'+host)"
                      "\n except Exception: print('NETWORK_DENIED:'+host)")
            proc = subprocess.run([str(executable), "-p", policy, "/usr/bin/python3", "-c", script,
                                   str(target), str(listeners[0].getsockname()[1]),
                                   str(listeners[1].getsockname()[1])],
                                  capture_output=True, timeout=5, check=False, text=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["detail"] = f"probe failed to run: {exc}"
            return result
        finally:
            for listener in listeners:
                listener.close()
        file_denied = ("FILE_DENIED" in proc.stdout and "FILE_ALLOWED" not in proc.stdout
                       and "WRITE_DENIED" in proc.stdout and "WRITE_ALLOWED" not in proc.stdout)
        network_denied = ("NETWORK_DENIED:127.0.0.1" in proc.stdout
                          and "NETWORK_DENIED:::1" in proc.stdout
                          and "NETWORK_ALLOWED" not in proc.stdout)
        passed = proc.returncode == 0 and file_denied and network_denied
        result.update(available=True, passed=passed, status="PASS" if passed else "NOT_READY",
                      crossProjectDenied=file_denied, approvalNetworkDenied=network_denied,
                      detail="file and network denial observed" if passed else
                      f"sandbox boundary probe failed (exit {proc.returncode}): "
                      + (proc.stdout.strip() + " " + proc.stderr.strip())[:1000])
    return result
