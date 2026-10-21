import tempfile
import unittest
import sqlite3
from pathlib import Path
from backend.coordinator import Coordinator
from backend.server import REPO_ROOT
from tools.studio_store import backup, restore
from runners.common import LocalJournal, RunnerLock


class StudioStoreTests(unittest.TestCase):
    def test_restore_preserves_projects_but_creates_new_receipt_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root/'original'
            c = Coordinator(REPO_ROOT, state_root=original, test_data=True)
            original_id = c.store_id
            operator = c.operator_id
            message = {'schemaVersion': 'studio.message.v1', 'kind': 'command', 'type': 'project.create',
                       'storeId': original_id, 'commandId': 'same-id', 'payload': {'name': 'Kept'}}
            receipt = c.submit_command(message, operator_id=operator)
            with self.assertRaisesRegex(RuntimeError, 'Stop the backend'):
                backup(original, root/'busy-backup')
            c.close()
            manifest = backup(original, root/'saved')
            self.assertEqual(manifest['storeId'], original_id)
            result = restore(root/'saved', root/'restored')
            self.assertNotEqual(result['storeId'], original_id)
            restored = Coordinator(REPO_ROOT, state_root=root/'restored', test_data=True)
            try:
                self.assertEqual(restored._all('project')[0]['id'], receipt['resource']['id'])
                self.assertFalse(restored.command_lookup(None, 'same-id', operator)['known'])
                self.assertEqual(restored.events_after(receipt['resource']['id'], 0), [])
            finally:
                restored.close()

    def test_restore_does_not_overwrite_existing_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.mkdir(exist_ok=True)
            with self.assertRaisesRegex(RuntimeError, 'existing stores'):
                restore(root/'missing', root)

    def test_backup_coordinates_runner_lock_and_preserves_unacked_wal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root/'original'
            c = Coordinator(REPO_ROOT, state_root=original, test_data=True)
            store_id = c.store_id
            c.close()
            journal_path = original/'runners'/'agent'/'journal.sqlite3'
            journal = LocalJournal(journal_path)
            journal.start_intent('attempt-original', {'storeId': store_id, 'taskKind': 'plan'})
            with RunnerLock(journal_path.parent/'service.lock'):
                with self.assertRaisesRegex(RuntimeError, 'both runners'):
                    backup(original, root/'busy')
            # Keep a WAL connection alive: copytree alone would miss this row.
            with sqlite3.connect(journal_path) as live:
                live.execute("INSERT INTO pending_claims VALUES(?,?)", (store_id, 'claim-original'))
                live.commit()
                backup(original, root/'saved')
            restore(root/'saved', root/'restored')
            saved = LocalJournal(root/'restored'/'runners'/'agent'/'journal.sqlite3')
            with saved._connect() as db:
                self.assertEqual(db.execute('SELECT command_id FROM pending_claims').fetchone()[0], 'claim-original')
                self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='quarantinedStoreId'").fetchone()[0], store_id)

    def test_repeated_restore_keeps_each_receipt_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            c = Coordinator(REPO_ROOT, state_root=root/'one', test_data=True)
            first_store = c.store_id
            c.close()
            backup(root/'one', root/'backup-one')
            restore(root/'backup-one', root/'two')
            c = Coordinator(REPO_ROOT, state_root=root/'two', test_data=True)
            second_store = c.store_id
            c.close()
            backup(root/'two', root/'backup-two')
            result = restore(root/'backup-two', root/'three')
            self.assertNotIn(result['storeId'], (first_store, second_store))
            with sqlite3.connect(root/'three'/'state.sqlite3') as db:
                names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn('restored_1_commands', names)
            self.assertIn('restored_2_commands', names)
