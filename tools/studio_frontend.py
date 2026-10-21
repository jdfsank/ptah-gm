"""Independent loopback static frontend with an explicit same-origin API proxy."""
from __future__ import annotations

import argparse
import http.client
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parents[1]
STUDIO_FILES = {'index.html', 'boot.js', 'studio.js', 'studio.css', 'workbench.js',
    'workbench.css', 'workbench-semantics.js', 'workbench-semantics.css',
    'visual-feedback.js', 'visual-feedback.css', 'visual-planning.js', 'image-planning.js'}
LEGACY_FILES = {'index.html', 'style.css', 'workbench.css', 'app.js', 'workbench.js',
    'demo-data.js', 'semantic-model.js', 'semantic-data.js', 'semantic-data.json',
    'adapter-baseline.json', 'browser-demo.json'}


class FrontendHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO/'frontend'/'studio'), **kwargs)

    def log_message(self, *_args):
        pass

    def _authorized_origin(self, mutation=False):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        page_navigation = (not mutation and self.command == 'GET'
            and urlsplit(self.path).path in {'/', '/studio', '/studio/', '/legacy', '/legacy/'}
            and self.headers.get('Sec-Fetch-Mode') == 'navigate'
            and self.headers.get('Sec-Fetch-Dest') == 'document')
        return (self.headers.get('Host') == origin.removeprefix('http://')
            and self.headers.get('Origin') in ({origin} if mutation else {None, origin})
            and (page_navigation or self.headers.get('Sec-Fetch-Site') in {None, 'same-origin', 'none'}))

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        super().end_headers()

    def _proxy(self):
        if not self._authorized_origin(self.command == 'POST'):
            self.send_error(403, 'Invalid frontend origin')
            return
        if not self.path.startswith('/api/') or '#' in self.path:
            self.send_error(404)
            return
        raw_length = self.headers.get('Content-Length', '0')
        if not re.fullmatch(r'\d{1,9}', raw_length) or self.headers.get('Transfer-Encoding'):
            self.send_error(400)
            return
        length = int(raw_length)
        if length > 45_000_000:
            self.send_error(413)
            return
        self.connection.settimeout(20)
        data = self.rfile.read(length) if length else None
        if data is not None and len(data) != length:
            self.send_error(400)
            return
        headers = {key: self.headers[key] for key in ('Content-Type', 'X-Workbench-Token', 'Accept', 'Last-Event-ID') if key in self.headers}
        headers['Origin'] = self.server.backend_origin
        connection = http.client.HTTPConnection('127.0.0.1', self.server.backend_port, timeout=20)
        sent = False
        try:
            connection.request(self.command, self.path, data, headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for key in ('Content-Type', 'Content-Length'):
                value = response.getheader(key)
                if value:
                    self.send_header(key, value)
            self.send_header('Connection', 'close')
            self.end_headers()
            sent = True
            self.close_connection = True
            # read1 forwards SSE keepalives without buffering an entire stream.
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException):
            if not sent:
                self.send_error(503, 'Studio backend unavailable')
        finally:
            connection.close()

    def do_GET(self):
        if self.path.startswith('/api/'):
            return self._proxy()
        if not self._authorized_origin():
            self.send_error(403)
            return
        path = urlsplit(self.path).path
        self.directory = str(REPO/'frontend'/'studio')
        if path in {'/', '/studio', '/studio/'}:
            self.path = '/index.html'
        elif path == '/legacy':
            query = urlsplit(self.path).query
            self.send_response(308)
            self.send_header('Location', '/legacy/'+('?' + query if query else ''))
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        elif path.startswith('/legacy/'):
            root = REPO/'frontend'/'dist'
            relative = unquote(path.removeprefix('/legacy/')) or 'index.html'
            candidate = (root/relative).resolve()
            parts = Path(relative).parts
            public_asset = (len(parts) > 1 and parts[0] in {'assets', 'docs', 'evidence'}
                and candidate.suffix in {'.png', '.md', '.html', '.json'})
            if ('..' in parts or not candidate.is_relative_to(root.resolve())
                    or not candidate.is_file() or not (relative in LEGACY_FILES or public_asset)):
                self.send_error(404)
                return
            self.directory = str(root)
            self.path = '/'+relative
        else:
            relative = path.removeprefix('/studio/') if path.startswith('/studio/') else path.removeprefix('/')
            if relative not in STUDIO_FILES:
                self.send_error(404)
                return
            self.path = '/'+relative
        return super().do_GET()

    def do_POST(self):
        return self._proxy()


def make_frontend_server(port=8764, backend_port=8765):
    server = ThreadingHTTPServer(('127.0.0.1', port), FrontendHandler)
    server.daemon_threads = True
    server.backend_port = backend_port
    server.backend_origin = f'http://127.0.0.1:{backend_port}'
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8764)
    parser.add_argument('--backend-port', type=int, default=8765)
    args = parser.parse_args()
    server = make_frontend_server(args.port, args.backend_port)
    print(f'Studio frontend: http://127.0.0.1:{server.server_port}/studio/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
