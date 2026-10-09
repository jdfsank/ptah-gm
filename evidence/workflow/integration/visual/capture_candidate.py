#!/usr/bin/env python3
"""Capture a native game viewport from an immutable source commit.

GodotE2E's trusted addon and its Python package are added only to a disposable
preview. The source commit and project files are never modified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from godot_e2e import GodotE2E
from importlib.metadata import version as package_version


GODOT = "/Applications/Godot.app/Contents/MacOS/Godot"
ADDON = "sources/velvet-eclipse/addons/godot_e2e"


def git_revision(repo: Path, revision: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", revision],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def git_archive(repo: Path, revision: str, *paths: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", revision, *paths],
        check=True, capture_output=True,
    ).stdout


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "x") and hasattr(value, "y"):
        return {"x": float(value.x), "y": float(value.y)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-repo", type=Path, required=True)
    parser.add_argument("--addon-repo", type=Path, default=Path.cwd())
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--addon-commit", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--sessions", required=True, help="Comma-separated session IDs in stage order")
    args = parser.parse_args()

    project_repo = args.project_repo.resolve()
    addon_repo = args.addon_repo.resolve()
    source_commit = git_revision(project_repo, args.source_commit)
    addon_commit = git_revision(addon_repo, args.addon_commit)
    output = args.output.resolve()
    record_path = args.record.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    record_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ptah-collect-loop-visual-") as scratch:
        project = Path(scratch) / "preview-project"
        project.mkdir()
        with tarfile.open(fileobj=io.BytesIO(git_archive(project_repo, source_commit)), mode="r:") as archive:
            archive.extractall(project, filter="data")
        addon_stage = Path(scratch) / "addon-archive"
        addon_stage.mkdir()
        with tarfile.open(fileobj=io.BytesIO(git_archive(addon_repo, addon_commit, ADDON)), mode="r:") as archive:
            archive.extractall(addon_stage, filter="data")
        addon_root = addon_stage / ADDON
        if not (project / "project.godot").is_file() or not (addon_root / "plugin.cfg").is_file():
            raise RuntimeError("source commit archive is missing the project template or trusted E2E addon")
        shutil.rmtree(project / ".godot", ignore_errors=True)
        shutil.rmtree(project / "addons" / "godot_e2e", ignore_errors=True)
        shutil.copytree(addon_root, project / "addons" / "godot_e2e")

        rules_path = project / "config" / "rules.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        expected = {"initialized": True, "target_count": 5, "time_limit": 40.0, "player_speed": 300.0}
        if rules != expected:
            raise RuntimeError(f"candidate rules differ from the reported production probe: {rules!r}")

        project_file = project / "project.godot"
        with project_file.open("a", encoding="utf-8") as handle:
            handle.write('\n[autoload]\nAutomationServer="*res://addons/godot_e2e/automation_server.gd"\n')

        # This config is only for the visual-QA skill's runtime-native mode and
        # exists solely inside the disposable preview directory.
        vqa_config = project / ".godotmaker" / "config.yaml"
        vqa_config.parent.mkdir(parents=True, exist_ok=True)
        vqa_config.write_text("vqa_model: native\nvqa_fallback_model: none\n", encoding="utf-8")

        import_check = subprocess.run(
            [GODOT, "--headless", "--path", str(project), "--editor", "--import", "--quit"],
            capture_output=True, text=True, timeout=45.0, check=False,
        )
        if import_check.returncode != 0:
            raise RuntimeError(
                "Godot preview import failed; stdout=" + import_check.stdout[-3000:]
                + " stderr=" + import_check.stderr[-3000:]
            )

        logs = []
        captured_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with GodotE2E.launch(
            str(project), godot_path=GODOT, timeout=30.0, log_verbosity="warning",
        ) as game:
            game.wait_for_node("/root/CollectLoop", timeout=15.0)
            game.wait_seconds(1.0)
            runtime_snapshot = {
                "gameState": game.get_property("/root/CollectLoop", "game_state"),
                "collectedCount": game.get_property("/root/CollectLoop", "collected_count"),
                "remainingTime": game.get_property("/root/CollectLoop", "remaining_time"),
                "pickupPositions": game.get_property("/root/CollectLoop", "pickup_positions"),
                "collected": game.get_property("/root/CollectLoop", "collected"),
                "playerPosition": game.get_property("/root/CollectLoop/Player", "position"),
            }
            runtime_snapshot = json_safe(runtime_snapshot)
            if (runtime_snapshot["gameState"] != "playing"
                    or runtime_snapshot["collectedCount"] != 0
                    or len(runtime_snapshot["pickupPositions"]) != 5
                    or runtime_snapshot["collected"] != [False] * 5):
                raise RuntimeError(f"unexpected candidate runtime state: {runtime_snapshot!r}")
            screenshot = game.screenshot(save_path=str(output))
            logs = [
                {"level": entry.level, "message": entry.message, "file": entry.file, "line": entry.line}
                for entry in game.collected_logs
            ]

        record = {
            "schemaVersion": 1,
            "testData": True,
            "productionAuthorized": False,
            "humanAcceptance": "NOT PERFORMED",
            "sourceCommit": source_commit,
            "sourceProjectRepo": str(project_repo),
            "screenshotAddonSourceCommit": addon_commit,
            "screenshotAddonSourceRepo": str(addon_repo),
            "jobId": args.job_id,
            "projectId": args.project_id,
            "sessionIds": [value for value in args.sessions.split(",") if value],
            "capturedAt": captured_at,
            "screenshot": str(Path(screenshot).resolve()),
            "gameRules": rules,
            "runtimeSnapshot": runtime_snapshot,
            "godotExecutable": GODOT,
            "importCheck": {
                "returnCode": import_check.returncode,
                "stdout": import_check.stdout,
                "stderr": import_check.stderr,
            },
            "godotE2ePythonPackage": package_version("godot-e2e"),
            "previewOnlyChanges": [
                "copied trusted sources/velvet-eclipse/addons/godot_e2e from the recorded support commit into disposable project",
                "added the godot-e2e AutomationServer autoload to disposable project.godot",
                "added native visual-QA configuration inside disposable project",
            ],
            "runtimeLogs": logs,
        }
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
