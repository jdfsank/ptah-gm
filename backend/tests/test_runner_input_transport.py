from __future__ import annotations

import base64
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
from unittest import mock

from runners.common import RunnerError, RunnerHTTP, strict_json


INPUT_ROUTE = "/internal/v1/attempts/attempt-large/input"


class RunnerInputTransportTests(unittest.TestCase):
    def make_api(self, root: Path, base_url: str = "http://127.0.0.1") -> RunnerHTTP:
        token_path = root / "runner-token"
        token_path.write_text("test-token", encoding="utf-8")
        token_path.chmod(0o600)
        return RunnerHTTP(base_url, token_path, "runner-test")

    def test_large_input_json_is_read_completely_from_local_http_server(self):
        png_like = b"\x89PNG\r\n\x1a\n" + b"P" * (3_000_000 - 8)
        encoded_asset = base64.b64encode(png_like).decode("ascii")
        response_body = json.dumps({"assets": [{"data": encoded_asset}]},
                                   separators=(",", ":")).encode("utf-8")
        self.assertGreater(len(response_body), 2_000_001)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, _format, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                api = self.make_api(Path(directory), f"http://127.0.0.1:{server.server_port}")
                result = api.request("GET", INPUT_ROUTE)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(base64.b64decode(result["assets"][0]["data"], validate=True), png_like)

    def test_control_routes_keep_the_two_megabyte_response_limit(self):
        response_body = b'{"payload":"' + b"x" * 2_000_001 + b'"}'
        requests = (
            ("GET", "/internal/v1/attempts/attempt-large/status"),
            ("POST", INPUT_ROUTE),
            ("GET", INPUT_ROUTE + "?format=json"),
        )
        with tempfile.TemporaryDirectory() as directory:
            api = self.make_api(Path(directory))
            for method, route in requests:
                with self.subTest(method=method, route=route):
                    with mock.patch(
                        "runners.common.urllib.request.urlopen",
                        side_effect=lambda *_args, **_kwargs: io.BytesIO(response_body),
                    ), mock.patch("runners.common.strict_json") as parse_response:
                        with self.assertRaisesRegex(RunnerError, "response exceeds"):
                            api.request(method, route)
                    parse_response.assert_not_called()

    def test_input_response_over_its_configured_limit_is_rejected_before_json_parse(self):
        response_body = b'{"payload":"' + b"x" * 128 + b'"}'
        with tempfile.TemporaryDirectory() as directory:
            api = self.make_api(Path(directory))
            with mock.patch("runners.common.INPUT_RESPONSE_BYTES", 32), \
                 mock.patch(
                     "runners.common.urllib.request.urlopen",
                     side_effect=lambda *_args, **_kwargs: io.BytesIO(response_body),
                 ), mock.patch("runners.common.strict_json") as parse_response:
                with self.assertRaisesRegex(RunnerError, "response exceeds"):
                    api.request("GET", INPUT_ROUTE)
            parse_response.assert_not_called()

    def test_large_input_response_still_rejects_duplicate_json_keys(self):
        response_body = (b'{"duplicate":1,"duplicate":2,"padding":"'
                         + b"x" * 2_000_001 + b'"}')
        with tempfile.TemporaryDirectory() as directory:
            api = self.make_api(Path(directory))
            with mock.patch(
                "runners.common.urllib.request.urlopen",
                side_effect=lambda *_args, **_kwargs: io.BytesIO(response_body),
            ):
                with self.assertRaisesRegex(RunnerError, "duplicate JSON key"):
                    api.request("GET", INPUT_ROUTE)

        with self.assertRaisesRegex(RunnerError, "duplicate JSON key"):
            strict_json(response_body)


if __name__ == "__main__":
    unittest.main()
