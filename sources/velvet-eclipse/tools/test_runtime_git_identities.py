from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / ".godotmaker" / "hooks"))

import append_stage_event
import git_baseline
import seal_tag
from metrics import diagnostics


class RuntimeGitIdentityTests(unittest.TestCase):
    def test_new_stage_digest_fields_accept_git_sha1_and_sha256_object_ids_only(self):
        for oid in ("a" * 40, "b" * 64):
            append_stage_event.validate_fields("verify", {"source_digest": f"git:blob:{oid}"})
        for old_sha in ("a" * 64, "sha256:" + "a" * 64):
            with self.assertRaisesRegex(ValueError, "Git blob identity"):
                append_stage_event.validate_fields("verify", {"source_digest": old_sha})

    def test_stage_log_history_is_read_as_is(self):
        legacy = {"role": "verify", "source_digest": "a" * 64}
        self.assertEqual(json.loads(json.dumps(legacy)), legacy)

    def test_seal_manifest_and_review_references_use_git_blob_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / ".godotmaker").mkdir()
            source = project / ".godotmaker" / "verify_report.json"
            source.write_bytes(b'{"result":"PASS"}\n')
            archive = project / "archive"
            archive.mkdir()

            gate = {"run_id": "run-1", "result": "PASS"}
            seal_tag._archive_review(project, archive, gate)
            entries = json.loads((archive / seal_tag.REVIEW_DIR / "references.json").read_text())
            self.assertEqual(entries[0]["git_identity"], git_baseline.identity_file(
                archive / entries[0]["archive"]))
            self.assertNotIn("sha256", entries[0])

            seal_tag._check_archived_review(project, archive, gate)
            manifest_entries = seal_tag._scan_archive_files(archive)
            self.assertTrue(manifest_entries)
            self.assertTrue(all(item["git_identity"].startswith("git:blob:") for item in manifest_entries))
            self.assertTrue(all("sha256" not in item for item in manifest_entries))

            source.write_bytes(b'{"result":"FAIL"}\n')
            with self.assertRaisesRegex(ValueError, "review evidence changed"):
                seal_tag._check_archived_review(project, archive, gate)

    def test_metrics_diagnostics_use_git_identity_for_digests_and_fingerprints(self):
        result = diagnostics.extract_large_output_reference(
            "## Tests\n" + "failure details " * 400)
        self.assertRegex(result["output_digest"], r"^git:blob:(?:[0-9a-f]{40}|[0-9a-f]{64})$")
        fingerprint = diagnostics._fingerprint("T1", "build", "task_failed", "failure", 1)
        self.assertRegex(fingerprint, r"^git:blob:(?:[0-9a-f]{40}|[0-9a-f]{64})$")


if __name__ == "__main__":
    unittest.main()
