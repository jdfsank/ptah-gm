from __future__ import annotations

import json
import http.client
import io
import os
import platform
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import urllib.error

from runners.common import RunnerError
from runners.static_tools import StaticToolBroker, file_operation
from runners.native_adapter import ManagedNativeContext, ProviderBridge, _NoRedirect
from runners.code_mode_runtime import IsolatedCodeModeHost


class StaticToolTests(unittest.TestCase):
    def routing_executable(self):
        bundle = self.root / 'bundle'
        executable = bundle / 'bin/codex-code-mode-host'
        executable.parent.mkdir(parents=True)
        executable.write_text('synthetic test host')
        executable.chmod(0o700)
        return str(bundle / 'nested/Contents/MacOS/codex')

    def test_tool_host_retries_once_only_after_previous_process_is_reaped(self):
        first = Mock()
        first.poll.return_value = None
        second = Mock()
        second.poll.return_value = 0
        launches = []

        def start(host, *_args):
            if launches:
                first.terminate.assert_called_once()
                self.assertGreaterEqual(first.wait.call_count, 1)
                host.process = second
                launches.append('ready')
            else:
                host.process = first
                launches.append('failed')
                raise RunnerError('synthetic bind denial')

        with patch.object(IsolatedCodeModeHost, '_start', start), patch('runners.code_mode_runtime.time.sleep') as pause:
            host = IsolatedCodeModeHost(self.root / 'routing', self.routing_executable(), [])
        self.assertEqual(launches, ['failed', 'ready'])
        pause.assert_called_once()
        host.close()

    def test_tool_host_permanent_failure_is_bounded_to_two_launches(self):
        with patch.object(IsolatedCodeModeHost, '_start', side_effect=RunnerError('permanent')) as start, \
                patch('runners.code_mode_runtime.time.sleep') as pause:
            with self.assertRaises(RunnerError):
                IsolatedCodeModeHost(self.root / 'routing', self.routing_executable(), [])
        self.assertEqual(start.call_count, 2)
        pause.assert_called_once()

    def test_tool_host_uncertain_cleanup_prevents_second_launch(self):
        with patch.object(IsolatedCodeModeHost, '_start', side_effect=RunnerError('bind denial')) as start, \
                patch.object(IsolatedCodeModeHost, 'close', side_effect=OSError('stop unknown')), \
                patch('runners.code_mode_runtime.time.sleep') as pause:
            with self.assertRaises(OSError):
                IsolatedCodeModeHost(self.root / 'routing', self.routing_executable(), [])
        start.assert_called_once()
        pause.assert_not_called()

    def test_native_cleanup_closes_provider_bridge_even_when_tool_host_close_fails(self):
        from unittest import mock
        context = object.__new__(ManagedNativeContext)
        context.tool_host = mock.Mock()
        context.tool_host.close.side_effect = OSError('tool host cleanup error')
        context.bridge = mock.Mock()
        with self.assertRaises(OSError):
            context.close()
        context.bridge.close.assert_called_once()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.auth = self.root / "auth"
        self.auth.mkdir()
        (self.workspace / "GDD.md").write_text("bounded static source", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_planner_rejects_execution_writes_hidden_and_escaping_reads(self):
        for name, args in [("studio_exec", {"command": "python scripts/main.gd"}),
                           ("studio_write_file", {"path": "scripts/main.gd", "content": "x"}),
                           ("studio_read_file", {"path": "../auth/token"}),
                           ("studio_read_file", {"path": ".git/config"}),
                           ("studio_read_file", {"path": "/etc/passwd"})]:
            with self.subTest(tool=name, args=args), self.assertRaises(RunnerError):
                file_operation(self.workspace, "plan", [], name, args)
        result = file_operation(self.workspace, "plan", [], "studio_read_file", {"path": "GDD.md"})
        self.assertEqual(result["content"], "bounded static source")

    def test_producer_can_write_only_scoped_source_and_never_uid_or_frozen_source(self):
        scope = ["scripts/**/*.gd"]
        args = {"path": "scripts/nested/new.gd", "content": "extends Node\n"}
        file_operation(self.workspace, "produce", scope, "studio_write_file", args)
        self.assertEqual((self.workspace / args["path"]).read_text(), args["content"])
        for path in ("scripts/new.gd.uid", "studio/runtime.gd", "design/game.json",
                     "project.godot", "scenes/main.tscn", "scripts/.hidden.gd"):
            with self.subTest(path=path), self.assertRaises(RunnerError):
                file_operation(self.workspace, "produce", scope, "studio_write_file", {"path": path, "content": "x"})

    def test_static_tools_reject_symlinks_and_hardlinks_before_mutation(self):
        (self.workspace / "scripts").mkdir()
        external = self.root / "external.gd"
        external.write_text("outside")
        (self.workspace / "scripts/link.gd").symlink_to(external)
        os.link(external, self.workspace / "scripts/hard.gd")
        for name in ("link.gd", "hard.gd"):
            with self.subTest(name=name), self.assertRaises((RunnerError, OSError)):
                file_operation(self.workspace, "produce", ["scripts/**/*.gd"], "studio_write_file", {
                    "path": "scripts/" + name, "content": "changed"})
        self.assertEqual(external.read_text(), "outside")

    @unittest.skipUnless(platform.system() == "Darwin", "macOS static tool sandbox")
    def test_actual_broker_read_and_write_run_in_separate_processes(self):
        project_package = self.workspace / "runners"
        project_package.mkdir()
        import_marker = self.root / "synthetic-project-runners-imported"
        project_package.joinpath("__init__.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(import_marker)!r}).write_text('SYNTHETIC_PROJECT_RUNNERS_IMPORTED')\n"
            "print('SYNTHETIC_PROJECT_RUNNERS_IMPORTED')\n", encoding="utf-8")
        plan = StaticToolBroker(self.workspace, "plan", [], self.tmp)
        read_result = plan.call("studio_read_file", {"path": "GDD.md"})
        self.assertTrue(read_result["success"])
        self.assertEqual(json.loads(read_result["contentItems"][0]["text"]),
                         {"path": "GDD.md", "content": "bounded static source"})
        self.assertNotIn("SYNTHETIC_PROJECT_RUNNERS_IMPORTED", json.dumps(read_result))
        self.assertFalse(import_marker.exists(), "workspace package initializer must not execute")
        self.assertFalse(plan.call("studio_read_file", {"path": "../auth/token"})["success"])
        producer = StaticToolBroker(self.workspace, "produce", ["scripts/**/*.gd"], self.tmp)
        self.assertTrue(producer.call("studio_write_file", {"path": "scripts/main.gd", "content": "extends Node\n"})["success"])
        self.assertFalse(producer.call("studio_write_file", {"path": "studio/runtime.gd", "content": "x"})["success"])

    @unittest.skipUnless(platform.system() == "Darwin", "macOS static tool sandbox")
    def test_actual_operation_policy_denies_auth_backend_other_exec_and_network(self):
        auth_canary = self.auth / "canary"
        auth_canary.write_text("synthetic authentication")
        code_host_canary = self.workspace / ".runner-tmp" / "native-code-host" / "host-canary"
        code_host_canary.parent.mkdir(parents=True)
        code_host_canary.write_text("synthetic code host data")
        native_runtime_canary = self.workspace / ".runner-tmp" / "native" / "runtime-canary"
        native_runtime_canary.parent.mkdir(parents=True)
        native_runtime_canary.write_text("synthetic native runtime data")
        other = self.root / "other"
        other.write_text("synthetic other project")
        script = self.workspace / "project-script.py"
        script.write_text("print('PROJECT_EXECUTED')")
        request = {"root": str(self.workspace), "tmp": str(self.tmp), "authRoot": str(self.auth),
                   "role": "plan", "scope": []}
        listeners = []
        try:
            for name, family, address in (("bridge", socket.AF_INET, "127.0.0.1"),
                                           ("approval", socket.AF_INET, "127.0.0.1"),
                                           ("approval_ipv6", socket.AF_INET6, "::1")):
                server = socket.socket(family)
                server.bind((address, 0)); server.listen(1)
                listeners.append((server, name, address, server.getsockname()[1]))
            program = """import json,sys,subprocess,socket,os
from pathlib import Path
from runners.static_tools import _apply_operation_boundary,file_operation
r=json.loads(sys.argv[1]); paths=json.loads(sys.argv[2]); ports=json.loads(sys.argv[3])
_apply_operation_boundary(r)
result={}
for key,path in paths.items():
 try: Path(path).read_bytes(); result[key]='ALLOWED'
 except OSError: result[key]='DENIED'
for key in ('auth','other','backend'):
 descriptor=None
 try:
  descriptor=os.open(paths[key],os.O_WRONLY|getattr(os,'O_NOFOLLOW',0)); result[key+'_write']='ALLOWED'
 except OSError: result[key+'_write']='DENIED'
 finally:
  if descriptor is not None: os.close(descriptor)
try: subprocess.run([sys.executable,sys.argv[4]],check=True); result['exec']='ALLOWED'
except OSError: result['exec']='DENIED'
try:
 value=file_operation(Path(r['root']),r['role'],r['scope'],'studio_read_file',{'path':'GDD.md'})
 result['static_operation']='ALLOWED' if value.get('content')=='bounded static source' else 'DENIED'
except Exception: result['static_operation']='DENIED'
for name,address,port in ports:
 try: socket.create_connection((address,port),timeout=.3); result[name]='ALLOWED'
 except OSError: result[name]='DENIED'
print(json.dumps(result))
"""
            host = Path(__file__).resolve().parents[2]
            proc = subprocess.run([sys.executable, "-c", program, json.dumps(request),
                json.dumps({"auth": str(auth_canary), "other": str(other),
                            "backend": str(host / "backend/codex_driver.py"),
                            "code_host": str(code_host_canary),
                            "native_runtime": str(native_runtime_canary)}),
                json.dumps([(name, address, port) for _, name, address, port in listeners]), str(script)],
                capture_output=True, text=True, timeout=10, cwd=host)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {key: "DENIED" for key in
                ("auth", "other", "backend", "code_host", "native_runtime", "exec", "bridge", "approval", "approval_ipv6",
                 "auth_write", "other_write", "backend_write")}
                | {"static_operation": "ALLOWED"})
        finally:
            for server, _, _, _ in listeners:
                server.close()

    @unittest.skipUnless(platform.system() == "Darwin" and Path(
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex").is_file(),
        "installed macOS native host required")
    def test_actual_code_mode_host_policy_denies_synthetic_files_and_outbound_ports(self):
        from runners.code_mode_runtime import IsolatedCodeModeHost

        backend = self.root / 'synthetic-backend'
        project = self.root / 'synthetic-project'
        backend.mkdir()
        project.mkdir()
        canaries = {
            'auth': self.auth / 'canary',
            'backend': backend / 'canary',
            'project': project / 'canary',
        }
        for path in canaries.values():
            path.write_text('SYNTHETIC_BOUNDARY_CANARY')
        listeners = []
        host = None
        try:
            for name in ('bridge', 'approval'):
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.bind(('127.0.0.1', 0))
                server.listen(1)
                listeners.append((name, server, server.getsockname()[1]))
            native = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
            host = IsolatedCodeModeHost(self.root / 'synthetic-code-host', str(native),
                [self.auth, backend, project])

            program = """import ctypes,json,socket,sys
from pathlib import Path
lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
lib.sandbox_init.argtypes=[ctypes.c_char_p,ctypes.c_uint64,ctypes.POINTER(ctypes.c_char_p)]
lib.sandbox_init.restype=ctypes.c_int
error=ctypes.c_char_p()
if lib.sandbox_init(sys.argv[1].encode(),0,ctypes.byref(error)):
 raise SystemExit('sandbox_init failed')
paths=json.loads(sys.argv[2]); ports=json.loads(sys.argv[3]); result={}
for name,path in paths.items():
 try: Path(path).read_bytes(); result[name]='ALLOWED'
 except OSError: result[name]='DENIED'
for name,address,port in ports:
 try: socket.create_connection((address,port),timeout=.3); result[name]='ALLOWED'
 except OSError: result[name]='DENIED'
print(json.dumps(result))
"""
            targets = [(name, '127.0.0.1', port) for name, _, port in listeners]
            process = subprocess.run([sys.executable, '-c', program, host.policy,
                json.dumps({name: str(path) for name, path in canaries.items()}), json.dumps(targets)],
                capture_output=True, text=True, timeout=10, cwd=self.root)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), {
                'auth': 'DENIED', 'backend': 'DENIED', 'project': 'DENIED',
                'bridge': 'DENIED', 'approval': 'DENIED'})
        finally:
            if host is not None:
                host.close()
            for _, server, _ in listeners:
                server.close()

    def _write_provider(self, provider):
        # Simple fixture TOML deliberately includes a synthetic token only.
        def toml_value(value):
            if isinstance(value, dict):
                return '{ ' + ', '.join(json.dumps(key) + ' = ' + json.dumps(item)
                                       for key, item in value.items()) + ' }'
            return json.dumps(value)
        text = '[model_providers.fixture]\n' + '\n'.join(key + ' = ' + toml_value(value)
                                                            for key, value in provider.items())
        (self.auth / 'config.toml').write_text(text)

    def _provider(self, **extra):
        self._write_provider({'name': 'Fixture', 'base_url': 'https://example.invalid/v1',
            'wire_api': 'responses', 'requires_openai_auth': False,
            'experimental_bearer_token': 'SYNTHETIC_PROVIDER_CANARY_BEARER_42', **extra})

    def _bridge_post(self, bridge, path, *, model='fixture-model-2026', nonce=None, authorization=True):
        connection = http.client.HTTPConnection('127.0.0.1', bridge.port, timeout=2)
        headers = {'Content-Type': 'application/json'}
        if authorization:
            headers['Authorization'] = 'Bearer ' + (nonce if nonce is not None else bridge.nonce)
        connection.request('POST', path, json.dumps({'model': model, 'input': 'synthetic fixture'}), headers)
        response = connection.getresponse()
        body = response.read()
        status = response.status
        connection.close()
        return status, body

    def _native_argv(self, context, name):
        executable = self.root / name
        executable.write_text('synthetic executable')
        executable.chmod(0o755)

        class FakeToolHost:
            def __init__(self, root, *_args):
                self.root = Path(root)
                self.port = 43210
                self.client_url = 'http://127.0.0.1:43210'

            def close(self):
                pass

        with patch('runners.native_adapter._NATIVE_INSTALLATIONS', (executable,)), \
             patch('runners.code_mode_runtime.IsolatedCodeModeHost', FakeToolHost):
            command = context.command(str(executable))
        self.assertEqual(context.tool_host.root,
                         context.root.parent / (context.root.name + '-code-host'))
        return command

    def test_provider_bridge_pins_model_and_routes_and_requires_nonce(self):
        bridge = ProviderBridge({'base_url': 'https://provider.example/v1'}, 'fixture-model-2026')
        self.addCleanup(bridge.close)
        self.assertEqual(bridge.model, 'fixture-model-2026')
        for path, model, nonce, authorization, expected in (
            ('/v1/responses', 'fixture-model-2026', None, False, 403),
            ('/v1/responses', 'fixture-model-2026', 'wrong-synthetic-nonce', True, 403),
            ('/v1/responses', 'other-model', None, True, 403),
            ('/v1/unknown', 'fixture-model-2026', None, True, 404),
        ):
            with self.subTest(path=path, model=model, expected=expected):
                status, body = self._bridge_post(bridge, path, model=model, nonce=nonce,
                                                 authorization=authorization)
                self.assertEqual(status, expected)
                self.assertNotIn(b'SYNTHETIC_PROVIDER_CANARY', body)

    def test_provider_bridge_forwards_only_mocked_https_and_rejects_redirects_and_private_dns(self):
        token = 'SYNTHETIC_PROVIDER_CANARY_BEARER_42'
        model = 'fixture-model-2026'
        bridge = ProviderBridge({'base_url': 'https://provider.example/v1',
                                 'experimental_bearer_token': token}, model)
        self.addCleanup(bridge.close)

        class FakeUpstream:
            status = 200
            headers = {'Content-Type': 'application/json'}

            def __init__(self):
                self.chunks = [b'{"output_text":"synthetic response"}', b'']

            def read1(self, _size):
                return self.chunks.pop(0)

            def close(self):
                pass

        upstream = FakeUpstream()
        opener = unittest.mock.Mock()
        opener.open.return_value = upstream
        dns_public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        real_getaddrinfo = socket.getaddrinfo
        def public_provider_only(host, port, *args, **kwargs):
            if host == 'provider.example':
                return dns_public
            return real_getaddrinfo(host, port, *args, **kwargs)
        with patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
             patch('runners.native_adapter.urllib.request.build_opener', return_value=opener) as build_opener:
            status, body = self._bridge_post(bridge, '/v1/responses')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"output_text":"synthetic response"}')
        build_opener.assert_called_once()
        self.assertIsInstance(build_opener.call_args.args[0], _NoRedirect)
        forwarded, = opener.open.call_args.args
        self.assertEqual(forwarded.full_url, 'https://provider.example/v1/responses')
        self.assertEqual(forwarded.get_header('Authorization'), 'Bearer ' + token)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 300)

        chat_upstream = FakeUpstream()
        chat_opener = unittest.mock.Mock()
        chat_opener.open.return_value = chat_upstream
        with patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
             patch('runners.native_adapter.urllib.request.build_opener', return_value=chat_opener):
            status, body = self._bridge_post(bridge, '/v1/chat/completions')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"output_text":"synthetic response"}')
        forwarded_chat, = chat_opener.open.call_args.args
        self.assertEqual(forwarded_chat.full_url, 'https://provider.example/v1/chat/completions')

        redirect = urllib.error.HTTPError('https://provider.example/v1/responses', 302, 'Found',
            {'Location': 'https://private.example/steal'}, io.BytesIO(b'SYNTHETIC_REDIRECT_BODY'))
        redirect_opener = unittest.mock.Mock()
        redirect_opener.open.side_effect = redirect
        with patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
             patch('runners.native_adapter.urllib.request.build_opener', return_value=redirect_opener) as build_redirect_opener:
            status, body = self._bridge_post(bridge, '/v1/responses')
        self.assertEqual(status, 502)
        self.assertNotIn(b'private.example', body)
        self.assertNotIn(b'SYNTHETIC_REDIRECT_BODY', body)
        self.assertIsInstance(build_redirect_opener.call_args.args[0], _NoRedirect)

        private_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.20.30.40', 443))]
        def private_provider_only(host, port, *args, **kwargs):
            if host == 'provider.example':
                return private_dns
            return real_getaddrinfo(host, port, *args, **kwargs)
        with patch('runners.native_adapter.socket.getaddrinfo', side_effect=private_provider_only), \
             patch('runners.native_adapter.urllib.request.build_opener') as private_opener:
            status, body = self._bridge_post(bridge, '/v1/responses')
        self.assertEqual(status, 502)
        self.assertEqual(body, b'{"error":{"message":"Managed provider bridge rejected request"}}')
        private_opener.assert_not_called()

    def test_provider_bridge_records_bounded_redacted_http_and_timeout_diagnostics(self):
        secret = 'SYNTHETIC_DIAGNOSTIC_SECRET_481'
        model = 'fixture-model-2026'
        bridge = ProviderBridge({'base_url': 'https://provider.example/v1',
            'experimental_bearer_token': secret, 'stream_idle_timeout_ms': 37}, model)
        self.addCleanup(bridge.close)
        dns_public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        real_getaddrinfo = socket.getaddrinfo

        def public_provider_only(host, port, *args, **kwargs):
            if host == 'provider.example':
                return dns_public
            return real_getaddrinfo(host, port, *args, **kwargs)

        cases = (
            ('startup timeout', socket.timeout('SYNTHETIC_RAW_STARTUP_ERROR'), 'timeout', False),
            ('HTTPError', urllib.error.HTTPError('https://provider.example/private-url', 429,
                'SYNTHETIC_RAW_HTTP_REASON', {'X-Synthetic-Secret': secret},
                io.BytesIO(('SYNTHETIC_RAW_BODY_' + secret).encode())), 'http_error', False),
        )
        for label, failure, kind, started in cases:
            opener = unittest.mock.Mock()
            opener.open.side_effect = failure
            with self.subTest(label=label), \
                 patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
                 patch('runners.native_adapter.urllib.request.build_opener', return_value=opener):
                status, body = self._bridge_post(bridge, '/v1/responses')
            self.assertEqual(status, 502)
            self.assertNotIn(secret.encode(), body)
            self.assertNotIn(b'SYNTHETIC_RAW', body)
            if label == 'startup timeout':
                self.assertEqual(opener.open.call_args.kwargs['timeout'], .037)

        class FakeUpstream:
            status = 200
            headers = {'Content-Type': 'text/event-stream'}

            def read1(self, _size):
                raise socket.timeout('SYNTHETIC_RAW_STREAM_TIMEOUT')

            def close(self):
                pass

        opener = unittest.mock.Mock()
        opener.open.return_value = FakeUpstream()
        with patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
             patch('runners.native_adapter.urllib.request.build_opener', return_value=opener):
            status, body = self._bridge_post(bridge, '/v1/responses')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')

        class ReflectedUpstream:
            status = 200
            headers = {'Content-Type': 'application/json'}

            def __init__(self):
                self.chunks = [b'{"data":"' + secret.encode() + b'"}', b'']

            def read1(self, _size):
                return self.chunks.pop(0)

            def close(self):
                pass

        opener = unittest.mock.Mock()
        opener.open.return_value = ReflectedUpstream()
        with patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
             patch('runners.native_adapter.urllib.request.build_opener', return_value=opener):
            status, body = self._bridge_post(bridge, '/v1/responses')
        self.assertEqual(status, 200)
        self.assertNotIn(secret.encode(), body)
        summary = bridge.diagnostic_summary()
        self.assertEqual(summary['requestCount'], 4)
        self.assertEqual(summary['failureCount'], 4)
        self.assertEqual(summary['timeoutSeconds'], .037)
        self.assertEqual([item['kind'] for item in summary['failures']],
                         ['timeout', 'http_error', 'timeout', 'credential_reflection'])
        self.assertEqual([item['httpStatus'] for item in summary['failures']],
                         [None, 429, None, None])
        self.assertEqual([item['responseStarted'] for item in summary['failures']],
                         [False, False, True, True])
        self.assertTrue(all(item['timeoutSeconds'] == .037 and item['observedAt']
                            for item in summary['failures']))
        serialized = json.dumps(summary)
        for forbidden in (secret, 'SYNTHETIC_RAW', 'provider.example', 'private-url',
                          'Authorization', 'X-Synthetic-Secret', 'synthetic fixture'):
            self.assertNotIn(forbidden, serialized)

        unauthenticated_status, unauthenticated_body = self._bridge_post(
            bridge, '/v1/responses', authorization=False)
        self.assertEqual(unauthenticated_status, 403)
        self.assertNotIn(secret.encode(), unauthenticated_body)

    def test_provider_bridge_uses_default_timeout_for_invalid_timeout_values(self):
        for value in (None, 0, -1, True, 1.5, '37'):
            provider = {'base_url': 'https://provider.example/v1'}
            if value is not None:
                provider['stream_idle_timeout_ms'] = value
            bridge = ProviderBridge(provider, 'fixture-model-2026')
            try:
                self.assertEqual(bridge.timeout_seconds, 300)
                self.assertEqual(bridge.diagnostic_summary()['timeoutSeconds'], 300)
            finally:
                bridge.close()

    def test_provider_bridge_redacts_plain_and_json_escaped_credential_reflections_across_chunks(self):
        bearer = 'SYNTHETIC_BEARER_秘密_CANARY_42'
        header = 'SYNTHETIC_HEADER_CANARY_"\\_73'
        scheme_token = 'SYNTHETIC_AUTH_SCHEME_秘密_CANARY_91'
        model = 'fixture-model-2026'
        bridge = ProviderBridge({'base_url': 'https://provider.example/v1',
            'experimental_bearer_token': bearer, 'http_headers': {
                'X-Fixture-Key': header, 'aUtHoRiZaTiOn': 'bEaReR\t' + scheme_token}}, model)
        self.addCleanup(bridge.close)
        safe_prefix = b'{"prefix":"SAFE_PREFIX_BYTES_UNCHANGED","credential":"'
        safe_before_reflection = safe_prefix + b'P' * 256
        safe_tail = b'.' * 256
        credentials = (bearer, header, scheme_token,
            json.dumps(bearer, ensure_ascii=True)[1:-1],
            json.dumps(header, ensure_ascii=True)[1:-1],
            json.dumps(scheme_token, ensure_ascii=True)[1:-1])
        reflections = (
            ('bearer-plain', bearer.encode('utf-8')),
            ('header-plain', header.encode('utf-8')),
            ('bearer-json-escaped', json.dumps(bearer, ensure_ascii=True)[1:-1].encode('utf-8')),
            ('header-json-escaped', json.dumps(header, ensure_ascii=True)[1:-1].encode('utf-8')),
            ('authorization-token-without-scheme', scheme_token.encode('utf-8')),
            ('authorization-token-json-escaped', json.dumps(scheme_token, ensure_ascii=True)[1:-1].encode('utf-8')),
        )
        dns_public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        real_getaddrinfo = socket.getaddrinfo

        def public_provider_only(host, port, *args, **kwargs):
            if host == 'provider.example':
                return dns_public
            return real_getaddrinfo(host, port, *args, **kwargs)

        class FakeUpstream:
            status = 200

            def __init__(self, chunks, content_type='application/json'):
                self.headers = {'Content-Type': content_type}
                self.chunks = list(chunks)
                self.read_calls = 0

            def read1(self, _size):
                self.read_calls += 1
                return self.chunks.pop(0)

            def close(self):
                pass

        def bridge_post(upstream):
            opener = unittest.mock.Mock()
            opener.open.return_value = upstream
            connection = http.client.HTTPConnection('127.0.0.1', bridge.port, timeout=2)
            with patch('runners.native_adapter.socket.getaddrinfo', side_effect=public_provider_only), \
                 patch('runners.native_adapter.urllib.request.build_opener', return_value=opener):
                connection.request('POST', '/v1/responses',
                    json.dumps({'model': model, 'input': 'synthetic fixture'}),
                    {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + bridge.nonce})
                response = connection.getresponse()
                content_type = response.getheader('Content-Type')
                body = response.read()
            status = response.status
            connection.close()
            return status, content_type, body

        for name, reflection in reflections:
            with self.subTest(reflection=name):
                split_at = max(1, len(reflection) // 2)
                upstream = FakeUpstream((safe_before_reflection, reflection[:split_at],
                                         reflection[split_at:] + safe_tail, b''))
                status, content_type, body = bridge_post(upstream)
                self.assertEqual(status, 200)
                self.assertTrue(body.startswith(safe_prefix))
                self.assertEqual(body, safe_before_reflection[:len(body)],
                    'safe response bytes before the reflection must pass unchanged')
                self.assertGreaterEqual(upstream.read_calls, 3, 'credential reflection must cross read1 chunks')
                self.assertEqual(content_type, 'application/json')
                for credential in credentials:
                    self.assertNotIn(credential.encode('utf-8'), body)
                    self.assertNotIn(credential, content_type)

        reflected_content_type = 'application/' + bearer
        upstream = FakeUpstream((b'ignored', b''), content_type=reflected_content_type)
        status, content_type, body = bridge_post(upstream)
        self.assertEqual(status, 502)
        self.assertNotIn(bearer.encode('utf-8'), body)
        self.assertEqual(content_type, 'application/json')
        for credential in credentials:
            self.assertNotIn(credential, content_type)

    def test_native_adapter_protects_authorization_token_without_scheme(self):
        token = 'SYNTHETIC_AUTHORIZATION_TOKEN_51'
        self._write_provider({'name': 'Fixture', 'base_url': 'https://example.invalid/v1',
            'wire_api': 'responses', 'requires_openai_auth': False,
            'http_headers': {'aUtHoRiZaTiOn': 'bEaReR\t' + token}})
        context = ManagedNativeContext.create(self.tmp / 'native', 'fixture', auth_root=self.auth,
                                              source_environment={}, model='fixture-model-2026')
        self.addCleanup(context.close)
        self.assertIn(token, context.secrets)
        self.assertEqual(context.redact({'reflection': token}),
                         {'reflection': '[provider credential redacted]'})
        (context.root / 'unexpected').write_text(token)
        self.assertTrue(context.secrets_on_disk())

    def test_native_adapter_separates_credentials_from_disk_environment_and_argv(self):
        self._provider()
        token = 'SYNTHETIC_PROVIDER_CANARY_BEARER_42'
        context = ManagedNativeContext.create(self.tmp / 'native', 'fixture', auth_root=self.auth,
                                              source_environment={}, model='fixture-model-2026')
        self.addCleanup(context.close)
        native_provider = context.config_overrides['model_providers']['fixture']
        self.assertEqual(context.bridge.model, 'fixture-model-2026')
        self.assertEqual(native_provider['experimental_bearer_token'], context.bridge.nonce)
        self.assertNotEqual(native_provider['experimental_bearer_token'], token)
        self.assertEqual(context.bridge.provider['experimental_bearer_token'], token)
        self.assertNotIn(token, json.dumps(native_provider))
        self.assertNotIn(token, json.dumps(context.environment()))
        self.assertNotIn(context.bridge.nonce, json.dumps(context.environment()))
        self.assertNotIn(token, (context.root / 'codex/config.toml').read_text())
        self.assertNotIn(context.bridge.nonce, (context.root / 'codex/config.toml').read_text())
        argv = self._native_argv(context, 'synthetic-codex')
        self.assertNotIn(token, json.dumps(argv))
        self.assertNotIn(context.bridge.nonce, json.dumps(argv))
        self.assertFalse(context.secrets_on_disk())
        self.assertEqual(context.redact({'token': token}), {'token': '[provider credential redacted]'})
        (context.root / 'unexpected').write_text(token)
        self.assertTrue(context.secrets_on_disk())

    def test_native_adapter_keeps_environment_credentials_inside_the_bridge(self):
        bearer = 'SYNTHETIC_ENV_BEARER_CANARY_51'
        header = 'SYNTHETIC_ENV_HEADER_CANARY_92'
        runner_token = 'SYNTHETIC_RUNNER_TOKEN_CANARY_73'
        unrelated_secret = 'SYNTHETIC_UNRELATED_ENV_CANARY_84'
        parent_path = 'SYNTHETIC_PARENT_PATH_CANARY'
        self._write_provider({'name': 'Fixture', 'base_url': 'https://example.invalid/v1',
            'wire_api': 'responses', 'requires_openai_auth': False,
            'env_key': 'FIXTURE_PROVIDER_BEARER',
            'env_http_headers': {'X-Fixture-Key': 'FIXTURE_PROVIDER_HEADER'}})
        source_environment = {'CODEX_HOME': str(self.auth),
            'FIXTURE_PROVIDER_BEARER': bearer, 'FIXTURE_PROVIDER_HEADER': header,
            'STUDIO_RUNNER_TOKEN': runner_token, 'UNRELATED_SECRET': unrelated_secret,
            'PATH': parent_path}
        authentication_environment = ManagedNativeContext.authentication_environment(
            'fixture', source_environment)
        self.assertEqual(authentication_environment, {
            'CODEX_HOME': str(self.auth.resolve()),
            'FIXTURE_PROVIDER_BEARER': bearer,
            'FIXTURE_PROVIDER_HEADER': header,
        })
        context = ManagedNativeContext.create(self.tmp / 'native-env', 'fixture', auth_root=self.auth,
            source_environment=source_environment,
            model='fixture-model-2026')
        self.addCleanup(context.close)
        self.assertEqual(context.bridge.provider['experimental_bearer_token'], bearer)
        self.assertEqual(context.bridge.provider['http_headers'], {'X-Fixture-Key': header})
        surfaces = [json.dumps(context.environment()), json.dumps(context.config_overrides),
                    (context.root / 'codex/config.toml').read_text()]
        surfaces.append(json.dumps(self._native_argv(context, 'synthetic-codex-env')))
        for canary in (bearer, header, runner_token, unrelated_secret, parent_path):
            with self.subTest(canary=canary):
                self.assertTrue(all(canary not in surface for surface in surfaces))
        self.assertFalse(context.secrets_on_disk())

        captured = {}
        def fake_run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0,
                stdout=json.dumps({'success': True, 'contentItems': []}), stderr='')
        broker = StaticToolBroker(self.workspace, 'plan', [], self.tmp)
        with patch.dict(os.environ, source_environment), \
             patch('runners.static_tools.subprocess.run', side_effect=fake_run):
            result = broker.call('studio_read_file', {'path': 'GDD.md'})
        self.assertTrue(result['success'])
        self.assertEqual(captured['env']['PYTHONNOUSERSITE'], '1')
        self.assertNotIn('CODEX_HOME', captured['env'])
        self.assertNotIn(bearer, json.dumps(captured['env']))
        self.assertNotIn(header, json.dumps(captured['env']))
        self.assertNotIn(runner_token, json.dumps(captured['env']))
        self.assertNotIn(unrelated_secret, json.dumps(captured['env']))
        for canary in (bearer, header, runner_token, unrelated_secret, parent_path):
            self.assertNotIn(canary, captured['input'])

    def test_native_adapter_fails_closed_for_file_auth_and_local_provider(self):
        self._provider(requires_openai_auth=True)
        with self.assertRaises(RunnerError):
            ManagedNativeContext.create(self.tmp / 'native', 'fixture', auth_root=self.auth)
        self._provider(base_url='http://127.0.0.1:8765')
        with self.assertRaises(RunnerError):
            ManagedNativeContext.create(self.tmp / 'native2', 'fixture', auth_root=self.auth)


if __name__ == '__main__':
    unittest.main()
