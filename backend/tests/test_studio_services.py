import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import urljoin
from unittest.mock import patch
from pathlib import Path

from backend.coordinator import Coordinator
from backend.server import REPO_ROOT, make_server
from tools.studio_frontend import make_frontend_server
from tools.studio_services import component_command, process_identity


class IndependentFrontendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Coordinator(REPO_ROOT, state_root=Path(self.tmp.name)/'state', test_data=True)
        self.api = make_server(self.c, port=0)
        self.front = make_frontend_server(port=0, backend_port=self.api.server_port)
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.api, self.front)]
        for thread in self.threads:
            thread.start()
        self.base = f'http://127.0.0.1:{self.front.server_port}'

    def tearDown(self):
        for server in (self.front, self.api):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()
        self.c.close()
        self.tmp.cleanup()

    def test_static_and_same_origin_authenticated_command_use_independent_frontend(self):
        with urllib.request.urlopen(self.base+'/studio/') as response:
            self.assertIn(b'boot.js', response.read())
        with urllib.request.urlopen(self.base+'/api/v1/handshake') as response:
            handshake = json.load(response)
        message = {'schemaVersion': 'studio.message.v1', 'kind': 'command', 'type': 'project.create',
            'storeId': handshake['storeId'], 'commandId': 'independent-front', 'payload': {'name': 'Proxy fixture'}}
        request = urllib.request.Request(self.base+'/api/v1/commands', data=json.dumps(message).encode(),
            headers={'Origin': self.base, 'Content-Type': 'application/json', 'X-Workbench-Token': handshake['writeToken']})
        with urllib.request.urlopen(request) as response:
            receipt = json.load(response)
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(self.c._all('project')[0]['title'], 'Proxy fixture')

    def test_all_studio_entries_load_recursive_modules_styles_and_legacy(self):
        for entry in ('/', '/studio', '/studio/', '/studio/?project=fixture&target=player'):
            with self.subTest(entry=entry):
                page_url = self.base+entry
                with urllib.request.urlopen(page_url) as response:
                    html = response.read().decode()
                pending = [urljoin(page_url, path) for path in re.findall(
                    r'(?:src|href)="(\./[^\"]+\.(?:js|css))"', html)]
                visited = set()
                while pending:
                    resource = pending.pop()
                    if resource in visited:
                        continue
                    visited.add(resource)
                    with urllib.request.urlopen(resource) as response:
                        source = response.read().decode()
                        self.assertNotIn('text/html', response.headers['Content-Type'])
                    if resource.endswith('.js'):
                        imports = re.findall(r'(?:from\s*|import\s*\()\s*[\'\"](\./[^\'\"]+)[\'\"]', source)
                        pending.extend(urljoin(resource, path) for path in imports)
                self.assertTrue(any(url.endswith('/workbench-semantics.js') for url in visited))
                self.assertTrue(any(url.endswith('/workbench-semantics.css') for url in visited))
        for resource in ('/legacy', '/legacy/', '/legacy/app.js', '/legacy/workbench.js', '/legacy/style.css', '/legacy/assets/heroine.png'):
            with self.subTest(resource=resource), urllib.request.urlopen(self.base+resource) as response:
                self.assertEqual(response.status, 200)

    def test_static_paths_stay_within_public_files(self):
        for resource in ('/studio/package.json', '/studio/../package.json', '/legacy/../package.json', '/legacy/.git/config', '/AGENTS.md'):
            with self.subTest(resource=resource), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base+resource)
            self.assertEqual(error.exception.code, 404)

    def test_proxy_does_not_forward_foreign_origin_or_internal_runner_routes(self):
        request = urllib.request.Request(self.base+'/api/v1/handshake', headers={'Origin': 'https://untrusted.example'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base+'/internal/v1/handshake')
        self.assertEqual(error.exception.code, 404)
        self.assertEqual(self.c._all('project'), [])

    def test_component_commands_colocate_private_journals_for_backup(self):
        root = Path(self.tmp.name)/'state'
        for role in ('agent', 'project'):
            command = component_command(role, root)
            self.assertEqual(command[command.index('--state')+1], str(root/'runners'/role/'journal.sqlite3'))
        import os
        self.assertIsNotNone(process_identity(os.getpid()))

    def test_project_summary_uses_the_existing_workflow_projection(self):
        project = self.c.create_project(operator_id=self.c.operator_id, title='Stage fixture')
        pid = project['id']
        def state():
            return next(p['workflowState'] for p in self.c.workspace_summary()['projects'] if p['id'] == pid)
        self.assertEqual(state()['step'], 'concept')
        for status, expected in (('RUNNING', 'producing'), ('READY_FOR_REVIEW', 'candidate_review')):
            with self.subTest(status=status):
                with self.c.transaction():
                    self.c._put('job', {'id': 'stage-job', 'projectId': pid, 'status': status})
                self.assertEqual(state()['step'], expected)
        with self.c.transaction():
            self.c._put('job', {'id': 'stage-job', 'projectId': pid, 'status': 'REJECTED'})
        with patch.object(self.c, 'repair_context', return_value={'kind': 'REPAIR'}):
            self.assertEqual(state(), {'phase': 'iteration', 'step': 'repair', 'attention': 'user'})
        with self.c.transaction():
            project.update(snapshotId='accepted-snapshot', publicationRevision=1)
            self.c._put('project', project)
            self.c._put('job', {'id': 'stage-job', 'projectId': pid, 'status': 'PUBLISHED'})
        self.assertEqual(state()['step'], 'accepted')
