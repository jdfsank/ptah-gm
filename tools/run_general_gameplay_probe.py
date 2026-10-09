"""Run backend-authored gameplay assertions against an exact test candidate.

Source comes from Git archive, not a mutable production checkout. The supplied
workflow evidence must explicitly identify isolated test data and no human
acceptance. This is a fixture probe, not a universal gameplay certification.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = Path("/Applications/Godot.app/Contents/MacOS/Godot")


def run(evidence: Path, round_index: int | None, kind: str, output: Path, fixture: Path | None):
    record = json.loads(evidence.read_text())
    if (record.get("testData") is not True or record.get("productionAuthorized") is not False
            or record.get("humanAcceptance") != "NOT PERFORMED" or record.get("status") != "PASS"):
        raise ValueError("successful isolated test evidence is required")
    snapshot = record["rounds"][round_index]["snapshot"] if round_index is not None else record["snapshot"]
    repo = Path(record["stateRoot"]) / "projects" / snapshot["projectId"]
    commit = snapshot["sourceCommit"]
    result = {"testData": True, "productionAuthorized": False, "humanAcceptance": "NOT PERFORMED",
              "sourceCommit": commit, "projectId": snapshot["projectId"], "kind": kind,
              "scope": "backend-authored fixture-specific input/state assertions; no visual or human acceptance",
              "status": "FAIL", "commands": []}
    harness = ROOT / "evidence/workflow/general/harnesses" / (kind + "_gameplay.gd")
    archive = subprocess.run(["git", "archive", commit], cwd=repo, check=True, capture_output=True).stdout
    try:
        with tempfile.TemporaryDirectory(prefix="gm-gameplay-") as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
                for member in contents.getmembers():
                    path = Path(member.name)
                    if (path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir())
                            or path.parts[0] in {".git", ".godot", ".godotmaker"}):
                        raise ValueError("unsafe fixture archive member")
                contents.extractall(project)
            if fixture:
                if fixture.exists():
                    raise ValueError("fixture output already exists; preserve prior evidence")
                shutil.copytree(project, fixture)
            shutil.copyfile(harness, project / "backend_gameplay.gd")
            for name, args, timeout in (
                ("fresh_import", ["--editor", "--import", "--quit"], 45),
                ("gameplay", ["--script", "res://backend_gameplay.gd"], 45),
            ):
                command = [str(ENGINE), "--headless", "--path", str(project), *args]
                process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
                result["commands"].append({"name": name, "argv": command, "returnCode": process.returncode,
                                           "stdout": process.stdout, "stderr": process.stderr})
                if process.returncode or "SCRIPT ERROR:" in process.stdout + process.stderr:
                    raise RuntimeError(name + " failed")
            markers = ("BACKEND_GAMEPLAY_PROBE_PASS ", "BACKEND_GAMEPLAY_PROBE: ")
            observed = [json.loads(line[len(marker):]) for marker in markers
                        for line in process.stdout.splitlines() if line.startswith(marker)]
            if len(observed) != 1 or (isinstance(observed[0], dict) and observed[0].get("status") != "PASS"):
                raise RuntimeError("independent gameplay observations missing")
            details = observed[0]
            result.update(status="PASS", checks=details["checks"] if isinstance(details, dict) else details,
                          observations=details if isinstance(details, dict) else {},
                          fixturePath=str(fixture) if fixture else None)
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(result["status"], kind, commit, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--round", type=int, dest="round_index")
    parser.add_argument("--kind", choices=["bridge", "puzzle"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    arguments = parser.parse_args()
    run(arguments.evidence, arguments.round_index, arguments.kind, arguments.output, arguments.fixture)
