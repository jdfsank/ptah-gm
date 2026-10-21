from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.general_verification import GeneralVerificationError, audit_general_scope
from backend.object_protocol import validate_document
from backend.source_preparation import (
    load_uid_preparation_evidence,
    prepare_godot_uid_sidecars,
)


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "general_2d"


def _document() -> dict:
    return {
        "schemaVersion": "studio.objects.v1",
        "dimension": "2d",
        "title": "UID preparation fixture",
        "summary": "Trusted UID sidecar preparation test.",
        "objects": [
            {
                "id": "main-scene",
                "kind": "scene",
                "name": "Main scene",
                "sourceBindings": ["scenes/main.tscn", "scripts/main.gd"],
                "fields": [],
            },
            {
                "id": "player",
                "kind": "entity",
                "name": "Player",
                "parentId": "main-scene",
                "sourceBindings": ["scripts/main.gd"],
                "fields": [],
            },
        ],
        "requirements": [
            {
                "id": "load-main-scene",
                "text": "The main scene loads.",
                "objectIds": ["main-scene"],
                "verification": "automated",
            }
        ],
    }


class SourcePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        shutil.copytree(TEMPLATE, self.project)
        self.document = validate_document(_document())
        (self.project / "design/game.json").write_text(
            json.dumps(self.document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.project), "config", "user.email", "test@localhost"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.project), "add", "--all"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "trusted baseline"], check=True)
        self.base = subprocess.run(
            ["git", "-C", str(self.project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.godot = self.root / "godot-mock"

    def tearDown(self):
        self.temp.cleanup()

    def _fake_godot(self, body: str):
        self.godot.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            "if '--version' in sys.argv:\n print('4.6.3.stable.mock'); sys.exit(0)\n"
            + body,
            encoding="utf-8",
        )
        self.godot.chmod(0o755)

    @mock.patch(
        "runners.godot_runtime.sandboxed_godot_argv",
        side_effect=lambda executable, arguments, **_kwargs: [str(executable), *arguments],
    )
    def test_prepares_only_missing_sidecars_and_returns_auditable_evidence(self, sandboxed_command):
        self._fake_godot(
            "if '--editor' in sys.argv:\n"
            " assert '--recovery-mode' in sys.argv, 'UID import must not execute project tool scripts'\n"
            " pathlib.Path('scripts/main.gd.uid').write_bytes(b'uid://trustedmain\\n')\n"
            " pathlib.Path('studio/runtime.gd.uid').write_bytes(b'uid://trustedruntime\\n')\n"
            " sys.exit(0)\n"
            "sys.exit(4)\n"
        )

        prepared = prepare_godot_uid_sidecars(
            self.project,
            base_commit=self.base,
            document=self.document,
            godot_path=self.godot,
        )

        self.assertEqual(prepared.input_commit, self.base)
        self.assertEqual(prepared.engine_version, "4.6.3.stable.mock")
        self.assertEqual(
            dict(prepared.sidecars),
            {
                "scripts/main.gd.uid": b"uid://trustedmain\n",
                "studio/runtime.gd.uid": b"uid://trustedruntime\n",
            },
        )
        evidence = prepared.evidence("source-commit-after-preparation")
        self.assertEqual(evidence["method"], "quarantine-godot-editor-recovery-import")
        self.assertEqual(evidence["inputCommit"], self.base)
        self.assertEqual(evidence["sourceCommit"], "source-commit-after-preparation")
        self.assertEqual(evidence["engineVersion"], "4.6.3.stable.mock")
        self.assertEqual(
            evidence["writeBoundary"],
            "Godot child process tree; only listed missing .gd.uid paths writable",
        )
        self.assertEqual(
            evidence["sidecars"],
            [
                {"path": "scripts/main.gd.uid", "content": "uid://trustedmain\n"},
                {"path": "studio/runtime.gd.uid", "content": "uid://trustedruntime\n"},
            ],
        )
        artifact = self.root / "sealed-artifact"
        evidence_file = artifact / "evidence/uid-preparation.json"
        evidence_file.parent.mkdir(parents=True)
        evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
        loaded_sidecars, loaded_engine = load_uid_preparation_evidence(
            artifact,
            input_commit=self.base,
            source_commit="source-commit-after-preparation",
        )
        self.assertEqual(dict(loaded_sidecars), dict(prepared.sidecars))
        self.assertEqual(loaded_engine, prepared.engine_version)
        with self.assertRaises(TypeError):
            prepared.sidecars["scripts/main.gd.uid"] = b"uid://producer-replacement\n"
        self.assertEqual(
            audit_general_scope(
                self.project,
                self.base,
                self.document,
                prepared_uid_sidecars=prepared.sidecars,
            ),
            ["scripts/main.gd.uid", "studio/runtime.gd.uid"],
        )
        self.assertEqual(sandboxed_command.call_count, 2)
        version_call, import_call = sandboxed_command.call_args_list
        self.assertFalse(version_call.kwargs["uid_write_paths"])
        self.assertEqual(
            {Path(path).relative_to(Path(import_call.kwargs["project_root"]).resolve()).as_posix()
             for path in import_call.kwargs["uid_write_paths"]},
            {"scripts/main.gd.uid", "studio/runtime.gd.uid"},
        )

    @mock.patch("backend.source_preparation._run_scoped_godot")
    def test_rejects_producer_sidecar_before_launching_godot(self, run_godot):
        self._fake_godot("sys.exit(4)\n")
        sidecar = self.project / "scripts/main.gd.uid"
        sidecar.write_bytes(b"uid://producer-authored\n")

        with self.assertRaisesRegex(GeneralVerificationError, "unprepared UID sidecars"):
            prepare_godot_uid_sidecars(
                self.project,
                base_commit=self.base,
                document=self.document,
                godot_path=self.godot,
            )

        run_godot.assert_not_called()
        self.assertEqual(sidecar.read_bytes(), b"uid://producer-authored\n")

    @mock.patch(
        "runners.godot_runtime.sandboxed_godot_argv",
        side_effect=lambda executable, arguments, **_kwargs: [str(executable), *arguments],
    )
    def test_rejects_quarantine_changes_outside_the_uid_allowlist(self, _sandboxed_command):
        self._fake_godot(
            "if '--editor' in sys.argv:\n"
            " pathlib.Path('scripts/main.gd.uid').write_bytes(b'uid://trustedmain\\n')\n"
            " pathlib.Path('project.godot').write_text('producer mutation')\n"
            " sys.exit(0)\n"
            "sys.exit(4)\n"
        )

        with self.assertRaisesRegex(GeneralVerificationError, "outside the missing UID allowlist"):
            prepare_godot_uid_sidecars(
                self.project,
                base_commit=self.base,
                document=self.document,
                godot_path=self.godot,
            )

        self.assertFalse((self.project / "scripts/main.gd.uid").exists())
        self.assertNotEqual((self.project / "project.godot").read_text(encoding="utf-8"), "producer mutation")

    @mock.patch(
        "runners.godot_runtime.sandboxed_godot_argv",
        side_effect=lambda executable, arguments, **_kwargs: [str(executable), *arguments],
    )
    def test_rejects_successful_import_that_omits_a_missing_uid(self, _sandboxed_command):
        self._fake_godot(
            "if '--editor' in sys.argv:\n sys.exit(0)\n"
            "sys.exit(4)\n"
        )

        with self.assertRaisesRegex(GeneralVerificationError, "did not generate every missing UID"):
            prepare_godot_uid_sidecars(
                self.project,
                base_commit=self.base,
                document=self.document,
                godot_path=self.godot,
            )

        self.assertFalse((self.project / "scripts/main.gd.uid").exists())
        self.assertFalse((self.project / "studio/runtime.gd.uid").exists())

    def test_missing_evidence_is_legacy_empty_result(self):
        artifact = self.root / "legacy-artifact"
        artifact.mkdir()

        sidecars, engine_version = load_uid_preparation_evidence(
            artifact,
            input_commit=self.base,
            source_commit="legacy-source-commit",
        )

        self.assertEqual(dict(sidecars), {})
        self.assertIsNone(engine_version)

    def test_loader_rejects_bad_bindings_schema_duplicate_paths_and_uids(self):
        artifact = self.root / "bad-evidence-artifact"
        evidence_file = artifact / "evidence/uid-preparation.json"
        evidence_file.parent.mkdir(parents=True)
        valid = {
            "schemaVersion": "studio.uid-preparation.v1",
            "method": "quarantine-godot-editor-recovery-import",
            "inputCommit": self.base,
            "sourceCommit": "sealed-source-commit",
            "engineVersion": "4.6.3.stable.mock",
            "writeBoundary": "Godot child process tree; only listed missing .gd.uid paths writable",
            "sidecars": [
                {"path": "scripts/main.gd.uid", "content": "uid://evidencemain\n"},
                {"path": "studio/runtime.gd.uid", "content": "uid://evidenceruntime\n"},
            ],
        }
        invalid_cases = []
        wrong_input = dict(valid)
        wrong_input["inputCommit"] = "different-input-commit"
        invalid_cases.append((wrong_input, "different input or source commit"))
        wrong_source = dict(valid)
        wrong_source["sourceCommit"] = "different-source-commit"
        invalid_cases.append((wrong_source, "different input or source commit"))
        unknown_schema = {**valid, "producerClaim": True}
        invalid_cases.append((unknown_schema, "unsupported schema"))
        unsafe_import_method = {**valid, "method": "quarantine-godot-editor-import"}
        invalid_cases.append((unsafe_import_method, "method is unsupported"))
        duplicate_path = {**valid, "sidecars": [*valid["sidecars"], dict(valid["sidecars"][0])]}
        invalid_cases.append((duplicate_path, "duplicate path"))
        invalid_uid = {
            **valid,
            "sidecars": [{"path": "scripts/main.gd.uid", "content": "uid://invalid space\n"}],
        }
        invalid_cases.append((invalid_uid, "invalid UID"))
        duplicate_uid = {
            **valid,
            "sidecars": [
                {"path": "scripts/main.gd.uid", "content": "uid://sameuid\n"},
                {"path": "studio/runtime.gd.uid", "content": "uid://sameuid\n"},
            ],
        }
        invalid_cases.append((duplicate_uid, "duplicate UID"))

        for candidate, expected_message in invalid_cases:
            with self.subTest(expected_message=expected_message):
                evidence_file.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaisesRegex(GeneralVerificationError, expected_message):
                    load_uid_preparation_evidence(
                        artifact,
                        input_commit=self.base,
                        source_commit="sealed-source-commit",
                    )

    def test_loader_rejects_symlinked_and_hardlinked_evidence(self):
        artifact = self.root / "linked-evidence-artifact"
        evidence_file = artifact / "evidence/uid-preparation.json"
        evidence_file.parent.mkdir(parents=True)
        outside = self.root / "outside-evidence.json"
        outside.write_text("{}", encoding="utf-8")
        evidence_file.symlink_to(outside)
        with self.assertRaisesRegex(GeneralVerificationError, "unsafe"):
            load_uid_preparation_evidence(
                artifact,
                input_commit=self.base,
                source_commit="sealed-source-commit",
            )

        evidence_file.unlink()
        evidence_file.write_text("{}", encoding="utf-8")
        os.link(evidence_file, artifact / "evidence-copy.json")
        with self.assertRaisesRegex(GeneralVerificationError, "hard-linked"):
            load_uid_preparation_evidence(
                artifact,
                input_commit=self.base,
                source_commit="sealed-source-commit",
            )


if __name__ == "__main__":
    unittest.main()
