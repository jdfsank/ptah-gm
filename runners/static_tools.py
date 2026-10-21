"""Typed file operations for managed roles; project text is never executable.

The trusted adapter supplies the root and scope. Model arguments cannot select
an executable, environment, network policy, authentication path, or sandbox.
Each operation runs in a new process with a separate filesystem boundary.
"""
from __future__ import annotations

import ctypes
import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from .common import RunnerError, strict_sandbox_rules

MAX_TEXT_BYTES = 256 * 1024
MAX_CALLS = 200
_READ_ROOTS = {"scripts", "scenes", "resources", "assets", "design", "studio"}
_READ_FILES = {"project.godot", "planning-input.json", "GDD.md", "PLAN.md",
               "STRUCTURE.md", "SCENES.md", "DESIGN.md", "ASSETS.md"}
_TEXT_SUFFIXES = {".gd", ".tscn", ".tres", ".json", ".md", ".godot"}
_WRITE_PATTERNS = {"scripts/**/*.gd": ("scripts", ".gd"),
                   "scenes/**/*.tscn": ("scenes", ".tscn"),
                   "resources/**/*.tres": ("resources", ".tres")}


def _parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RunnerError("file path must be bounded relative text")
    if "\\" in value or ":" in value or "\x00" in value:
        raise RunnerError("unsupported file path")
    parts = value.split("/")
    if any(not part or part.startswith(".") for part in parts):
        raise RunnerError("hidden and escaping file paths are forbidden")
    return tuple(parts)


def _read_allowed(value: str) -> bool:
    parts = _parts(value)
    return (value in _READ_FILES or
            (len(parts) > 1 and parts[0] in _READ_ROOTS
             and PurePosixPath(value).suffix in _TEXT_SUFFIXES))


def _write_allowed(value: str, scope: list[str]) -> bool:
    parts = _parts(value)
    if value == "project.godot":
        return value in scope
    for pattern in scope:
        policy = _WRITE_PATTERNS.get(pattern)
        if policy and len(parts) > 1 and parts[0] == policy[0] and PurePosixPath(value).suffix == policy[1]:
            return True
        if pattern == value and len(parts) > 1 and parts[0] in {"scripts", "scenes", "resources"}:
            return PurePosixPath(value).suffix == {"scripts": ".gd", "scenes": ".tscn", "resources": ".tres"}[parts[0]]
    return False


def _open_parent(root: Path, parts: tuple[str, ...], *, create=False) -> int:
    """Walk directory descriptors so concurrent symlink replacement cannot escape."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current = os.open(root, flags)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
            next_fd = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def file_operation(root: Path, role: str, scope: list[str], tool: str, arguments: dict) -> dict:
    if role not in {"plan", "produce"} or not isinstance(arguments, dict):
        raise RunnerError("invalid file operation")
    if tool == "studio_list_files":
        if arguments:
            raise RunnerError("list operation accepts no arguments")
        result = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            here = Path(directory)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                             and not (here / d).is_symlink()
                             and (here != root or d in _READ_ROOTS))
            for name in sorted(files):
                path = here / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or name.startswith(".") or not _read_allowed(relative):
                    continue
                result.append(relative)
                if len(result) > 5000:
                    raise RunnerError("static file inventory exceeds the role limit")
        return {"files": sorted(result)}
    if tool not in {"studio_read_file", "studio_write_file"}:
        raise RunnerError("unsupported static tool; project execution is unavailable")
    expected = {"path"} if tool == "studio_read_file" else {"path", "content"}
    if set(arguments) != expected:
        raise RunnerError("file operation arguments have an invalid shape")
    value = arguments["path"]
    parts = _parts(value)
    if tool == "studio_write_file":
        if role != "produce" or not _write_allowed(value, scope):
            raise RunnerError("file is outside the approved producer scope")
        content = arguments["content"]
        if not isinstance(content, str):
            raise RunnerError("source content must be UTF-8 text")
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise RunnerError("source content exceeds the static tool limit")
    elif not _read_allowed(value):
        raise RunnerError("file is outside the bounded static material")
    parent = _open_parent(root, parts, create=tool == "studio_write_file")
    fd = None
    try:
        flags = os.O_NOFOLLOW | (os.O_RDONLY if tool == "studio_read_file" else os.O_WRONLY | os.O_CREAT)
        fd = os.open(parts[-1], flags, mode=0o600, dir_fd=parent)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RunnerError("static file must be regular and cannot have hard links")
        if tool == "studio_read_file":
            if info.st_size > MAX_TEXT_BYTES:
                raise RunnerError("static file exceeds the read limit")
            chunks, remaining = [], MAX_TEXT_BYTES + 1
            while remaining:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > MAX_TEXT_BYTES:
                raise RunnerError("static file exceeds the read limit")
            return {"path": value, "content": data.decode("utf-8")}
        os.ftruncate(fd, 0)
        pending = memoryview(data)
        while pending:
            written = os.write(fd, pending)
            if not written:
                raise RunnerError("source write made no progress")
            pending = pending[written:]
        os.fsync(fd)
        return {"path": value, "bytesWritten": len(data)}
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def _apply_operation_boundary(request: dict) -> None:
    """Apply the complete policy after trusted bootstrap, before file access.

    macOS does not support reapplying a sandbox inside sandbox-exec. Bootstrap
    imports only pinned adapter code, then this first policy forbids all exec.
    """
    if sys.platform != "darwin":
        raise RunnerError("static process boundary requires macOS")
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    lib.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    lib.sandbox_init.restype = ctypes.c_int
    error = ctypes.c_char_p()
    workspace = Path(request["root"]).resolve(strict=True)
    private_tmp = Path(request["tmp"]).resolve(strict=True)
    host_root = Path(__file__).resolve().parents[1]
    write_roots = [private_tmp]
    if request["role"] == "produce":
        for name in ("scripts", "scenes", "resources"):
            if any(item.startswith(name + "/") for item in request["scope"]):
                write_roots.append(workspace / name)
        if "project.godot" in request["scope"]:
            write_roots.append(workspace / "project.godot")
    rules = strict_sandbox_rules(workspace,
        read_roots=[workspace, private_tmp], write_roots=write_roots,
        protected_paths=[Path(request["authRoot"]), host_root / "backend", workspace / ".runner-tmp/native",
                         workspace / ".runner-tmp/native-code-host"],
        deny_write_paths=[workspace / ".git", workspace / "design",
                          workspace / "studio", workspace / ".godotmaker"],
        allow_internet=False)
    rules += ["(deny process-exec)", "(deny process-fork)", "(deny network*)"]
    if lib.sandbox_init("".join(rules).encode(), 0, ctypes.byref(error)):
        raise RunnerError("cannot apply the static execution boundary")


class StaticToolBroker:
    def __init__(self, workspace: Path, role: str, scope: list[str], private_tmp: Path):
        self.workspace = workspace.resolve(strict=True)
        self.role = role
        if role not in {"plan", "produce"} or not isinstance(scope, list) or len(scope) > 128:
            raise RunnerError("invalid static tool role or scope")
        if any(not isinstance(item, str) for item in scope):
            raise RunnerError("static scope entries must be text")
        self.scope = list(scope)
        self.private_tmp = private_tmp.resolve(strict=True)
        self.calls = 0

    def specifications(self) -> list[dict]:
        def spec(name, description, properties, required):
            return {"type": "function", "deferLoading": False,
                    "name": name, "description": description, "inputSchema": {
                "type": "object", "properties": properties, "required": required,
                "additionalProperties": False}}
        result = [spec("studio_list_files", "List the authorized static source files.", {}, []),
                  spec("studio_read_file", "Read a bounded UTF-8 source file without executing it.",
                       {"path": {"type": "string"}}, ["path"])]
        if self.role == "produce":
            result.append(spec("studio_write_file", "Write UTF-8 source in the approved private project scope through a separate tool sandbox. The native runtime remains read-only; this function enforces the approved write scope.",
                               {"path": {"type": "string"}, "content": {"type": "string"}},
                               ["path", "content"]))
        return result

    def call(self, tool: str, arguments: dict) -> dict:
        self.calls += 1
        if self.calls > MAX_CALLS:
            raise RunnerError("static tool call limit exceeded")
        if tool not in {spec["name"] for spec in self.specifications()}:
            raise RunnerError("unsupported static tool; project execution is unavailable")
        host_root = Path(__file__).resolve().parents[1]
        if self.role == "produce":
            for name in ("scripts", "scenes", "resources"):
                if any(item.startswith(name + "/") for item in self.scope):
                    target = self.workspace / name
                    if target.is_symlink():
                        raise RunnerError("producer write root cannot be a symlink")
                    target.mkdir(mode=0o700, exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.private_tmp),
               "TMPDIR": str(self.private_tmp), "PYTHONPATH": str(host_root),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        request = {"root": str(self.workspace), "role": self.role, "scope": self.scope,
                   "tool": tool, "arguments": arguments, "tmp": str(self.private_tmp),
                   "authRoot": str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve())}
        proc = subprocess.run([str(Path(sys.executable).resolve()), "-m", "runners.static_tools"],
                              input=json.dumps(request, ensure_ascii=False, allow_nan=False),
                              capture_output=True, text=True, timeout=10, cwd=host_root, env=env)
        if proc.returncode:
            raise RunnerError("static tool process failed")
        try:
            result = json.loads(proc.stdout)
        except (ValueError, TypeError) as exc:
            raise RunnerError("static tool returned invalid JSON") from exc
        if not isinstance(result, dict) or set(result) != {"success", "contentItems"}:
            raise RunnerError("static tool returned an invalid response")
        return result


def main():
    request = json.loads(sys.stdin.read(MAX_TEXT_BYTES * 2 + 4096))
    if not isinstance(request, dict) or set(request) != {"root", "role", "scope", "tool", "arguments", "tmp", "authRoot"}:
        raise RunnerError("static operation envelope is invalid")
    _apply_operation_boundary(request)
    try:
        value = file_operation(Path(request["root"]), request["role"], request["scope"],
                               request["tool"], request["arguments"])
        success = True
    except (RunnerError, OSError, UnicodeError, ValueError):
        value, success = {"error": "Static operation rejected by its role boundary."}, False
    print(json.dumps({"success": success, "contentItems": [{"type": "inputText", "text": json.dumps(value, ensure_ascii=False)}]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
