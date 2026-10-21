"""Private native model runtime, separate from project file tools.

Only the trusted adapter loads real provider authentication. A dedicated
forwarding endpoint injects it into upstream HTTPS; native receives only an
ephemeral bridge nonce, never the real credentials. Providers
requiring a native credential file are unsupported here and fail closed.
"""
from __future__ import annotations

import json
import ipaddress
import os
import shutil
import socket
import hmac
import secrets as secure_random
import threading
from datetime import datetime, timezone
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .common import RunnerError, _seatbelt_quote, strict_sandbox_rules

_PUBLIC_PROVIDER_KEYS = {"name", "base_url", "wire_api", "requires_openai_auth",
                         "request_max_retries", "stream_max_retries", "stream_idle_timeout_ms",
                         "supports_websockets"}
_AUTH_PROVIDER_KEYS = {"experimental_bearer_token", "env_key", "http_headers", "env_http_headers"}
_NATIVE_INSTALLATIONS = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _UnsupportedContentType(ValueError):
    pass


def _provider_authentication_values(provider: dict) -> tuple[str, ...]:
    """Include the transmitted token as well as its Authorization header."""
    values = []
    bearer = provider.get("experimental_bearer_token")
    if isinstance(bearer, str) and bearer:
        values.append(bearer)
    for name, value in (provider.get("http_headers") or {}).items():
        if not isinstance(value, str) or not value:
            continue
        values.append(value)
        if name.lower() in {"authorization", "proxy-authorization"}:
            parts = value.split()
            if len(parts) == 2 and parts[0].lower() in {"bearer", "basic"}:
                values.append(parts[1])
    return tuple(dict.fromkeys(values))


def _redacted_provider_chunks(upstream, credentials):
    """Reject known credential reflections before bytes enter native's domain.

    Keep a bounded suffix so a credential split across network reads is still
    matched. JSON escaped forms are covered as well as plain header values.
    """
    patterns = set()
    for credential in credentials:
        if isinstance(credential, str) and credential:
            patterns.add(credential.encode("utf-8"))
            for ascii_only in (False, True):
                patterns.add(json.dumps(credential, ensure_ascii=ascii_only)[1:-1].encode("utf-8"))
    patterns = sorted(patterns, key=len, reverse=True)
    if not patterns:
        while chunk := upstream.read1(65536):
            yield chunk
        return
    retain = max(map(len, patterns)) - 1
    pending = b""
    while True:
        chunk = upstream.read1(65536)
        pending += chunk
        cutoff = len(pending) if not chunk else max(0, len(pending) - retain)
        position = 0
        while position < cutoff:
            matches = [(pending.find(pattern, position), pattern) for pattern in patterns]
            matches = [(index, pattern) for index, pattern in matches if 0 <= index < cutoff]
            if not matches:
                yield pending[position:cutoff]
                position = cutoff
                break
            raise ValueError("upstream reflected protected provider authentication")
        pending = pending[position:]
        if not chunk:
            break


class ProviderBridge:
    """Trusted, single-provider forwarding endpoint; credentials never reach native."""

    def __init__(self, provider: dict, model: str | None):
        self.provider, self.model = provider, model
        self.nonce = secure_random.token_urlsafe(32)
        self.streams = set()
        self.lock = threading.Lock()
        self.diagnostic_lock = threading.Lock()
        idle_ms = provider.get("stream_idle_timeout_ms")
        if not isinstance(idle_ms, int) or isinstance(idle_ms, bool) or idle_ms <= 0:
            idle_ms = 300_000
        self.timeout_seconds = idle_ms / 1000.0
        self._request_count = 0
        self._failure_count = 0
        self._failures = []
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def reject(self, status):
                body = b'{"error":{"message":"Managed provider bridge rejected request"}}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def do_POST(self):
                response_started = False
                with bridge.diagnostic_lock:
                    bridge._request_count += 1
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge.nonce):
                    return self.reject(403)
                if self.path not in {"/v1/responses", "/v1/chat/completions"}:
                    return self.reject(404)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8 * 1024 * 1024:
                        return self.reject(413)
                    body = self.rfile.read(length)
                    request = json.loads(body)
                    if not bridge.model or request.get("model") != bridge.model:
                        return self.reject(403)
                    endpoint = urlsplit(bridge.provider["base_url"])
                    addresses = {row[4][0] for row in socket.getaddrinfo(endpoint.hostname,
                                 endpoint.port or 443, type=socket.SOCK_STREAM)}
                    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                        return self.reject(502)
                    headers = {"Content-Type": "application/json", "Accept": self.headers.get("Accept", "application/json")}
                    bearer = bridge.provider.get("experimental_bearer_token")
                    if bearer:
                        headers["Authorization"] = "Bearer " + bearer
                    headers.update(bridge.provider.get("http_headers") or {})
                    for name in ("OpenAI-Beta", "x-codex-beta-features", "x-codex-turn-metadata"):
                        if self.headers.get(name):
                            headers[name] = self.headers[name]
                    target = bridge.provider["base_url"].rstrip("/") + self.path.removeprefix("/v1")
                    upstream = urllib.request.build_opener(_NoRedirect()).open(
                        urllib.request.Request(target, data=body, headers=headers, method="POST"),
                        timeout=bridge.timeout_seconds)
                    content_type = upstream.headers.get("Content-Type", "application/json").split(";", 1)[0].strip().lower()
                    if content_type not in {"application/json", "text/event-stream"}:
                        upstream.close()
                        raise _UnsupportedContentType()
                    with bridge.lock:
                        bridge.streams.add(upstream)
                    try:
                        self.send_response(upstream.status)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Connection", "close")
                        self.end_headers()
                        response_started = True
                        credentials = _provider_authentication_values(bridge.provider)
                        for chunk in _redacted_provider_chunks(upstream, credentials):
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    finally:
                        self.close_connection = True
                        with bridge.lock:
                            bridge.streams.discard(upstream)
                        upstream.close()
                except urllib.error.HTTPError as exc:
                    try:
                        exc.close()
                    except OSError:
                        pass
                    bridge._record_failure("http_error", exc.code, response_started)
                    self._bridge_failure(response_started)
                except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
                    # Do not reflect upstream authentication headers or error
                    # bodies into native diagnostics or project tool output.
                    if isinstance(exc, (TimeoutError, socket.timeout)) or (
                            isinstance(exc, urllib.error.URLError) and
                            isinstance(exc.reason, (TimeoutError, socket.timeout))):
                        kind = "timeout"
                    elif isinstance(exc, _UnsupportedContentType):
                        kind = "unsupported_content_type"
                    elif isinstance(exc, ValueError) and "reflected protected" in str(exc):
                        kind = "credential_reflection"
                    else:
                        kind = "network_error"
                    bridge._record_failure(kind, None, response_started)
                    self._bridge_failure(response_started)

            def _bridge_failure(self, response_started):
                self.close_connection = True
                if response_started:
                    return
                try:
                    self.reject(502)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_port

    def _record_failure(self, kind: str, http_status: int | None, response_started: bool):
        entry = {"kind": kind, "httpStatus": http_status,
                 "responseStarted": bool(response_started),
                 "observedAt": datetime.now(timezone.utc).isoformat(),
                 "timeoutSeconds": self.timeout_seconds}
        with self.diagnostic_lock:
            self._failure_count += 1
            self._failures.append(entry)
            del self._failures[:-20]

    def diagnostic_summary(self) -> dict:
        """Return bounded, credential-free aggregate and recent failure metadata."""
        with self.diagnostic_lock:
            failures = [dict(item) for item in self._failures]
            return {"requestCount": self._request_count,
                    "failureCount": self._failure_count,
                    "timeoutSeconds": self.timeout_seconds,
                    "failures": failures}

    def close(self):
        self.server.shutdown()
        with self.lock:
            streams = list(self.streams)
        for stream in streams:
            stream.close()
        self.server.server_close()
        self.thread.join(timeout=1)


@dataclass
class ManagedNativeContext:
    root: Path
    provider: str
    config_overrides: dict
    secrets: tuple[str, ...]
    real_auth_root: Path
    bridge: ProviderBridge
    tool_host: object = None

    @staticmethod
    def authentication_environment(provider: str, source_environment: dict | None = None) -> dict:
        """Forward only configured authentication variables to the trusted adapter."""
        source = dict(os.environ) if source_environment is None else source_environment
        auth_root = Path(source.get("CODEX_HOME", Path.home() / ".codex")).resolve(strict=True)
        try:
            raw = (tomllib.loads((auth_root / "config.toml").read_text(encoding="utf-8"))
                   .get("model_providers", {}).get(provider, {}))
            names = [raw.get("env_key"), *(raw.get("env_http_headers") or {}).values()]
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise RunnerError("cannot load trusted provider authentication environment") from exc
        result = {"CODEX_HOME": str(auth_root)}
        for name in names:
            if isinstance(name, str) and name in source:
                result[name] = source[name]
        return result

    @classmethod
    def create(cls, root: Path, provider: str, *, auth_root: Path | None = None,
               source_environment: dict | None = None, model: str | None = None):
        source_environment = dict(os.environ) if source_environment is None else source_environment
        auth_root = auth_root or Path(source_environment.get("CODEX_HOME", Path.home() / ".codex"))
        auth_root = auth_root.resolve(strict=True)
        if not isinstance(provider, str) or not provider or len(provider) > 120:
            raise RunnerError("managed native provider key is invalid")
        try:
            config = tomllib.loads((auth_root / "config.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RunnerError("cannot load trusted provider configuration") from exc
        raw_provider = (config.get("model_providers") or {}).get(provider)
        if not isinstance(raw_provider, dict) or raw_provider.get("requires_openai_auth") is not False:
            raise RunnerError("managed native boundary currently requires a custom stateless provider")
        unknown = set(raw_provider) - _PUBLIC_PROVIDER_KEYS - _AUTH_PROVIDER_KEYS
        if unknown:
            raise RunnerError("provider has unsupported configuration fields")
        public = {key: value for key, value in raw_provider.items() if key in _PUBLIC_PROVIDER_KEYS}
        url = urlsplit(public.get("base_url", ""))
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise RunnerError("managed provider requires a bounded HTTPS endpoint without URL credentials")
        if url.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise RunnerError("managed model provider cannot use the local approval network")
        if any(not isinstance(value, (str, bool, int)) or isinstance(value, float) for value in public.values()):
            raise RunnerError("provider configuration has an unsupported value")
        private = dict(public)
        bearer = raw_provider.get("experimental_bearer_token")
        env_key = raw_provider.get("env_key")
        if env_key:
            if not isinstance(env_key, str) or not source_environment.get(env_key):
                raise RunnerError("provider authentication environment is unavailable")
            if bearer:
                raise RunnerError("provider has ambiguous authentication sources")
            bearer = source_environment[env_key]
        if bearer is not None:
            if not isinstance(bearer, str) or not bearer:
                raise RunnerError("provider bearer authentication is invalid")
            private["experimental_bearer_token"] = bearer
        headers = dict(raw_provider.get("http_headers") or {})
        for name, variable in (raw_provider.get("env_http_headers") or {}).items():
            if not isinstance(variable, str) or not source_environment.get(variable):
                raise RunnerError("provider header authentication is unavailable")
            if name in headers:
                raise RunnerError("provider has ambiguous authentication headers")
            headers[name] = source_environment[variable]
        if headers:
            if any(not isinstance(name, str) or not isinstance(value, str) or not value for name, value in headers.items()):
                raise RunnerError("provider headers are invalid")
            private["http_headers"] = headers
        raw_root = Path(root)
        if raw_root.exists() or raw_root.is_symlink():
            raise RunnerError("private native runtime already exists")
        raw_root.mkdir(mode=0o700, parents=True)
        root = raw_root.resolve(strict=True)
        native_home = root / "home"
        codex_home = root / "codex"
        native_tmp = root / "tmp"
        for path in (native_home, codex_home, native_tmp):
            path.mkdir(mode=0o700)
        bridge = ProviderBridge(private, model)
        native_provider = {**public, "base_url": f"http://127.0.0.1:{bridge.port}/v1",
                           "experimental_bearer_token": bridge.nonce, "supports_websockets": False}
        # No real credential or user plugin/MCP settings are copied to this file.
        public["base_url"] = native_provider["base_url"]
        public["supports_websockets"] = False
        lines = ["model_provider = " + json.dumps(provider),
                 'cli_auth_credentials_store = "ephemeral"', 'web_search = "disabled"',
                 "[features]", "shell_tool = false", "view_image = false",
                 "multi_agent = false", "apps = false", "code_mode = false", "code_mode_only = false",
                 "[model_providers." + json.dumps(provider) + "]"]
        for key, value in sorted(public.items()):
            lines.append(key + " = " + json.dumps(value, ensure_ascii=False))
        (codex_home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (codex_home / "config.toml").chmod(0o600)
        return cls(root, provider, {"model_providers": {provider: native_provider}},
                   _provider_authentication_values(private) + (bridge.nonce,), auth_root, bridge)

    def environment(self):
        return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.root / "home"),
                "CODEX_HOME": str(self.root / "codex"), "TMPDIR": str(self.root / "tmp"),
                "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}

    def executable(self) -> str:
        # Managed execution never selects a binary from the project's PATH.
        for candidate in _NATIVE_INSTALLATIONS:
            if candidate.is_file() and not candidate.is_symlink() and candidate.resolve() == candidate:
                if candidate.stat().st_mode & 0o022:
                    continue
                return str(candidate)
        raise RunnerError("trusted installed native executable is unavailable")

    def command(self, executable: str) -> list[str]:
        native = Path(executable).resolve(strict=True)
        if str(native) != self.executable():
            raise RunnerError("managed native executable must be the pinned desktop installation")
        host_root = Path(__file__).resolve().parents[1]
        rules = strict_sandbox_rules(self.root, read_roots=[self.root], write_roots=[self.root],
            protected_paths=[self.real_auth_root, host_root / "backend"], allow_internet=False)
        # Native configuration discovery stats absent optional files outside
        # its runtime. This grants no file contents or directory enumeration;
        # explicit authentication/backend denials still override metadata.
        rules.append("(allow file-read-metadata)")
        # Seatbelt can restrict a localhost port but cannot express arbitrary
        # remote host addresses. Only the trusted bridge performs real HTTPS.
        rules.append(f'(allow network-outbound (remote tcp "localhost:{self.bridge.port}"))')
        if self.tool_host is None:
            from .code_mode_runtime import IsolatedCodeModeHost
            self.tool_host = IsolatedCodeModeHost(self.root.parent / (self.root.name + "-code-host"), str(native),
                [self.real_auth_root, host_root / "backend", self.root])
        rules.append(f'(allow network-outbound (remote tcp "localhost:{self.tool_host.port}"))')
        # Only the native runtime can bootstrap. Shells, interpreters, engines,
        # external MCPs and project programs cannot be launched in this domain.
        rules.append(f"(deny process-exec (require-not (literal {_seatbelt_quote(native)})))")
        return ["/usr/bin/sandbox-exec", "-p", "".join(rules), str(native), "app-server", "--stdio",
                "--disable", "shell_tool", "--disable", "view_image", "--disable", "multi_agent",
                "--disable", "apps", "--disable", "code_mode", "--disable", "code_mode_only",
                "--code-mode-host", self.tool_host.client_url,
                "-c", 'cli_auth_credentials_store="ephemeral"']

    def stage_images(self, images: list[str]) -> list[str]:
        if not images:
            return []
        folder = self.root / "references"
        folder.mkdir(mode=0o700)
        result = []
        for index, value in enumerate(images):
            source = Path(value)
            if source.is_symlink() or not source.is_file():
                raise RunnerError("reference image cannot be a symlink")
            target = folder / (str(index) + source.suffix)
            shutil.copyfile(source, target)
            target.chmod(0o600)
            result.append(str(target))
        return result

    def secrets_on_disk(self) -> bool:
        try:
            for path in self.root.rglob("*"):
                if path.is_symlink():
                    # Native bootstraps these fixed aliases for its own CLI.
                    # Never follow project-selected or other runtime links.
                    relative = path.relative_to(self.root).parts
                    if (len(relative) == 5 and relative[:3] == ("codex", "tmp", "arg0")
                            and relative[3].startswith("codex-arg0")
                            and relative[4] in {"applypatch", "apply_patch", "codex-execve-wrapper"}
                            and str(path.resolve()) == self.executable()):
                        continue
                    return True
                if path.is_file():
                    data = path.read_bytes()
                    if any(secret.encode() in data for secret in self.secrets):
                        return True
        except OSError:
            return True
        return False

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[provider credential redacted]")
            return value
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        return value

    def close(self):
        try:
            if self.tool_host is not None:
                self.tool_host.close()
        finally:
            self.bridge.close()
