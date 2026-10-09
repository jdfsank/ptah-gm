"""Independent bounded verifier for the bundled Godot collect-loop project."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_RULES: dict[str, object] = {
    "initialized": False,
    "target_count": 3,
    "time_limit": 30.0,
    "player_speed": 220.0,
}
RULES_RELATIVE_PATH = "config/rules.json"
INITIALIZATION_RELATIVE_PATH = "initialization.json"
ALLOWED_FILES = {
    "initialize": frozenset({INITIALIZATION_RELATIVE_PATH}),
    "implementation": frozenset({RULES_RELATIVE_PATH}),
}
RULE_LIMITS = {
    "target_count": (1, 8),
    "time_limit": (10.0, 300.0),
    "player_speed": (60.0, 400.0),
}
_BAD_ENGINE_OUTPUT = re.compile(
    r"(?im)^\s*(?:WARNING|ERROR|SCRIPT ERROR):|Failed to load (?:script|resource)|Parse Error|Compile Error"
)


class VerificationError(ValueError):
    pass


def discover_rules_path(project_dir: str | os.PathLike[str]) -> Path:
    """Locate this template's editable rules document under a trusted project root."""
    project = Path(project_dir).expanduser().resolve()
    rules = (project / RULES_RELATIVE_PATH).resolve()
    if not rules.is_relative_to(project):
        raise VerificationError("rules path escapes project root")
    return rules


def read_rules(project_dir: str | os.PathLike[str]) -> dict[str, object]:
    path = discover_rules_path(project_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read valid rules JSON: {exc}") from exc
    _validate_rules(value)
    return value


def read_rules_baseline(
    project_dir: str | os.PathLike[str], base_commit: str
) -> dict[str, object]:
    """Read the trusted baseline through Git, without computing standalone digests."""
    project = Path(project_dir).expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(project), "show", f"{base_commit}:{RULES_RELATIVE_PATH}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise VerificationError(
            f"cannot read rules baseline from Git: {result.stderr.strip()}"
        )
    try:
        rules = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("Git baseline rules are not valid JSON") from exc
    _validate_rules(rules)
    return rules


def semantic_catalog(project_dir: str | os.PathLike[str]) -> dict[str, object]:
    """Return the template's stable workbench IDs and supported edit surface."""
    rules = read_rules(project_dir)
    return {
        "catalogVersion": "collect-loop/1",
        "projectKind": "godot_2d_collect_loop",
        "playable": bool(rules["initialized"]),
        "objects": [
            {
                "id": "player",
                "kind": "actor",
                "source": "scripts/player.gd",
                "properties": [
                    {
                        "id": "player_speed",
                        "path": "/player_speed",
                        "type": "number",
                        "editable": True,
                        "minimum": 60.0,
                        "maximum": 400.0,
                        "unit": "pixels_per_second",
                    }
                ],
            },
            {
                "id": "collectible_set",
                "kind": "goal_set",
                "source": "scripts/main.gd",
                "properties": [
                    {
                        "id": "target_count",
                        "path": "/target_count",
                        "type": "integer",
                        "editable": True,
                        "minimum": 1,
                        "maximum": 8,
                    }
                ],
            },
            {
                "id": "round_timer",
                "kind": "timer",
                "source": "scripts/main.gd",
                "properties": [
                    {
                        "id": "time_limit",
                        "path": "/time_limit",
                        "type": "number",
                        "editable": True,
                        "minimum": 10.0,
                        "maximum": 300.0,
                        "unit": "seconds",
                    }
                ],
            },
            {
                "id": "round_state",
                "kind": "state_machine",
                "source": "scripts/main.gd",
                "editable": False,
                "states": ["uninitialized", "playing", "won", "lost"],
            },
        ],
        "rules": rules,
    }


def verify_project(
    project_dir: str | os.PathLike[str],
    operation_kind: str,
    expected_rules: Mapping[str, object] | None = None,
    *,
    base_commit: str | None = None,
    godot_path: str | os.PathLike[str] | None = None,
    timeout: float = 45.0,
) -> dict[str, object]:
    """Verify one collect-loop operation using only fixed, bounded Godot commands.

    ``base_commit`` is supplied by the coordinator when a candidate commit may
    already exist. When omitted, the current HEAD is treated as the immutable
    source baseline and only uncommitted tracked changes are considered.
    """
    project = Path(project_dir).expanduser().resolve()
    operation = _normalize_operation(operation_kind)
    result: dict[str, object] = {
        "status": "FAIL",
        "requirements": [],
        "checks": [],
        "diagnostics": [],
        "commands": [],
        "catalog": None,
        "rules": None,
    }
    requirements: list[dict[str, str]] = result["requirements"]  # type: ignore[assignment]
    checks: list[str] = result["checks"]  # type: ignore[assignment]
    diagnostics: list[dict[str, object]] = result["diagnostics"]  # type: ignore[assignment]
    commands: list[dict[str, object]] = result["commands"]  # type: ignore[assignment]

    if not (project / "project.godot").is_file():
        diagnostics.append(
            {"stage": "preflight", "message": "project.godot is missing"}
        )
        requirements.append(
            _requirement("project.exists", "FAIL", "project.godot missing")
        )
        return result
    requirements.append(
        _requirement("project.exists", "PASS", str(project / "project.godot"))
    )

    try:
        rules = read_rules(project)
        result["rules"] = rules
        result["catalog"] = semantic_catalog(project)
        requirements.append(
            _requirement("rules.schema", "PASS", "rules JSON and ranges are valid")
        )
    except VerificationError as exc:
        requirements.append(_requirement("rules.schema", "FAIL", str(exc)))
        diagnostics.append({"stage": "rules", "message": str(exc)})
        return result

    try:
        scope = _verify_git_scope(
            project, operation, base_commit, rules, expected_rules
        )
        requirements.append(_requirement("git.allowlist", "PASS", scope["evidence"]))
        checks.extend(scope["checks"])
    except VerificationError as exc:
        requirements.append(_requirement("git.allowlist", "FAIL", str(exc)))
        diagnostics.append({"stage": "git_scope", "message": str(exc)})
        return result

    godot = _resolve_godot(godot_path)
    if godot is None:
        message = "Godot 4 executable was not found"
        requirements.append(_requirement("godot.available", "FAIL", message))
        diagnostics.append({"stage": "godot", "message": message})
        return result
    requirements.append(_requirement("godot.available", "PASS", godot))

    fixed_commands = [
        (
            "import",
            [
                godot,
                "--headless",
                "--path",
                str(project),
                "--editor",
                "--import",
                "--quit",
            ],
        ),
        (
            "closed_loop",
            [
                godot,
                "--headless",
                "--path",
                str(project),
                "--script",
                "res://tests/closed_loop.gd",
            ],
        ),
    ]
    expected_marker = (
        "COLLECT_LOOP_TEMPLATE_GATE_PASS"
        if operation == "initialize"
        else "COLLECT_LOOP_SCENETREE_PASS"
    )
    for name, argv in fixed_commands:
        try:
            completed = subprocess.run(
                argv,
                cwd=project,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            record: dict[str, object] = {
                "name": name,
                "argv": argv,
                "cwd": str(project),
                "returnCode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timedOut": False,
            }
            commands.append(record)
            combined = completed.stdout + "\n" + completed.stderr
            engine_issues = _BAD_ENGINE_OUTPUT.findall(combined)
            if completed.returncode != 0:
                diagnostics.append(
                    {
                        "stage": name,
                        "message": "Godot command exited nonzero",
                        "returnCode": completed.returncode,
                    }
                )
            if engine_issues:
                diagnostics.append(
                    {
                        "stage": name,
                        "message": "Godot emitted warning or error diagnostics",
                        "matches": engine_issues,
                    }
                )
            if name == "closed_loop" and expected_marker not in completed.stdout:
                diagnostics.append(
                    {
                        "stage": name,
                        "message": f"required harness marker missing: {expected_marker}",
                    }
                )
        except subprocess.TimeoutExpired as exc:
            record = {
                "name": name,
                "argv": argv,
                "cwd": str(project),
                "returnCode": None,
                "stdout": _decode_output(exc.stdout),
                "stderr": _decode_output(exc.stderr),
                "timedOut": True,
            }
            commands.append(record)
            diagnostics.append(
                {"stage": name, "message": f"Godot command timed out after {timeout}s"}
            )
            break
        except OSError as exc:
            diagnostics.append(
                {"stage": name, "message": f"could not start Godot: {exc}"}
            )
            break

    for command in commands:
        name = str(command["name"])
        if command.get("timedOut"):
            requirements.append(
                _requirement(f"godot.{name}", "FAIL", "command timed out")
            )
        elif command.get("returnCode") != 0:
            requirements.append(
                _requirement(
                    f"godot.{name}", "FAIL", f"exit {command.get('returnCode')}"
                )
            )
        elif _BAD_ENGINE_OUTPUT.search(
            str(command["stdout"]) + "\n" + str(command["stderr"])
        ):
            requirements.append(
                _requirement(f"godot.{name}", "FAIL", "warning/error output present")
            )
        elif name == "closed_loop" and expected_marker not in str(command["stdout"]):
            requirements.append(
                _requirement(f"godot.{name}", "FAIL", "required harness marker missing")
            )
        else:
            requirements.append(
                _requirement(f"godot.{name}", "PASS", "exit 0 with clean diagnostics")
            )
    if len(commands) == len(fixed_commands) and all(
        r["status"] == "PASS" for r in requirements if str(r["id"]).startswith("godot.")
    ):
        result["status"] = "PASS"
        requirements.append(_requirement("closed_loop", "PASS", expected_marker))
    else:
        requirements.append(
            _requirement("closed_loop", "FAIL", "one or more Godot checks failed")
        )
    return result


def _normalize_operation(operation_kind: str) -> str:
    aliases = {
        "initialize": "initialize",
        "initialization": "initialize",
        "implementation": "implementation",
        "implement": "implementation",
    }
    try:
        return aliases[operation_kind.lower()]
    except (KeyError, TypeError) as exc:
        raise VerificationError(
            "operation_kind must be initialize or implementation"
        ) from exc


def _validate_rules(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_RULES):
        raise VerificationError(
            "rules must contain exactly initialized, target_count, time_limit, and player_speed"
        )
    if type(value["initialized"]) is not bool:
        raise VerificationError("initialized must be boolean")
    if type(value["target_count"]) is not int or not (1 <= value["target_count"] <= 8):
        raise VerificationError("target_count must be an integer from 1 to 8")
    for key, (minimum, maximum) in RULE_LIMITS.items():
        value_for_rule = value[key]
        if isinstance(value_for_rule, bool) or not isinstance(
            value_for_rule, (int, float)
        ):
            raise VerificationError(f"{key} must be numeric")
        if not (minimum <= value_for_rule <= maximum):
            raise VerificationError(f"{key} must be from {minimum:g} to {maximum:g}")


def _verify_git_scope(
    project: Path,
    operation: str,
    base_commit: str | None,
    rules: Mapping[str, object],
    expected_rules: Mapping[str, object] | None,
) -> dict[str, object]:
    allowed = ALLOWED_FILES[operation]
    base = base_commit or "HEAD"
    changed = _git(
        project, "diff", "--no-ext-diff", "--no-renames", "--name-only", base, "--"
    ).splitlines()
    untracked = _git(
        project, "ls-files", "--others", "--exclude-standard", "--"
    ).splitlines()
    changed_set = set(changed) | set(untracked)
    extra = sorted(changed_set - allowed)
    if extra:
        raise VerificationError(
            f"operation changed files outside its allowlist: {extra}"
        )
    if operation == "initialize":
        if changed_set != {INITIALIZATION_RELATIVE_PATH}:
            raise VerificationError(
                f"initialization operation must change only {INITIALIZATION_RELATIVE_PATH}"
            )
        baseline = _git_json(project, base, RULES_RELATIVE_PATH)
        if baseline != DEFAULT_RULES or rules != DEFAULT_RULES:
            raise VerificationError(
                "initialization must preserve the trusted non-playable default rules"
            )
        if expected_rules is None or not _expected_rules_match(rules, expected_rules):
            raise VerificationError(
                "initialization rules must match the server-approved default values"
            )
        current_init = _read_initialization(project)
        baseline_init = _validate_initialization(
            _git_json(project, base, INITIALIZATION_RELATIVE_PATH), baseline=True
        )
        if current_init["prepared"] is not True:
            raise VerificationError(
                "initialization.json must record the prepared state"
            )
        if current_init["projectId"] == "unassigned":
            raise VerificationError(
                "initialization.json needs the server-assigned project ID"
            )
        if baseline_init["prepared"] is not False:
            raise VerificationError("Git baseline initialization state must be pending")
    else:
        if changed_set != {RULES_RELATIVE_PATH}:
            raise VerificationError(
                f"implementation operation must change only {RULES_RELATIVE_PATH}"
            )
        baseline_rules = _git_json(project, base, RULES_RELATIVE_PATH)
        try:
            _validate_rules(baseline_rules)
        except VerificationError as exc:
            raise VerificationError(
                f"implementation Git baseline has invalid rules: {exc}"
            ) from exc
        if baseline_rules["initialized"] is False and baseline_rules != DEFAULT_RULES:
            raise VerificationError(
                "an uninitialized implementation baseline must use trusted template defaults"
            )
        initialization = _read_initialization(project)
        if initialization.get("prepared") is not True:
            raise VerificationError(
                "implementation requires completed project preparation"
            )
        baseline_initialization = _validate_initialization(
            _git_json(project, base, INITIALIZATION_RELATIVE_PATH)
        )
        if initialization != baseline_initialization:
            raise VerificationError(
                "implementation must preserve the prepared initialization manifest"
            )
        if rules.get("initialized") is not True:
            raise VerificationError("implementation must set rules.initialized to true")
        if expected_rules is None or not _expected_rules_match(rules, expected_rules):
            raise VerificationError(
                "actual rules do not match the complete server-approved values"
            )
    return {
        "checks": [f"base={base}", f"changed={','.join(sorted(changed_set))}"],
        "evidence": {
            "baseCommit": base,
            "changedFiles": sorted(changed_set),
            "allowedFiles": sorted(allowed),
        },
    }


def _rule_values_equal(key: str, actual: object, expected: object) -> bool:
    if key == "initialized":
        return type(actual) is bool and type(expected) is bool and actual is expected
    if key == "target_count":
        return type(actual) is int and type(expected) is int and actual == expected
    return (
        not isinstance(actual, bool)
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and isinstance(expected, (int, float))
        and float(actual) == float(expected)
    )


def _read_initialization(project: Path) -> dict[str, object]:
    path = project / INITIALIZATION_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read initialization.json: {exc}") from exc
    return _validate_initialization(value)


def _validate_initialization(
    value: object, baseline: bool = False
) -> dict[str, object]:
    fields = {"templateId", "operationKind", "projectId", "prepared"}
    if not isinstance(value, dict) or set(value) != fields:
        raise VerificationError("initialization.json has an invalid schema")
    if (
        value["templateId"] != "collect-loop-v1"
        or value["operationKind"] != "INITIALIZATION"
    ):
        raise VerificationError(
            "initialization.json has invalid template or operation values"
        )
    if not isinstance(value["projectId"], str) or not value["projectId"].strip():
        raise VerificationError("initialization.json needs a project ID")
    if baseline and value["projectId"] != "unassigned":
        raise VerificationError(
            "Git template baseline must not have an assigned project ID"
        )
    if type(value["prepared"]) is not bool:
        raise VerificationError("initialization prepared flag must be boolean")
    return value


def _expected_rules_match(
    actual: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    return set(expected) == set(DEFAULT_RULES) and all(
        _rule_values_equal(key, actual.get(key), expected[key]) for key in DEFAULT_RULES
    )


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise VerificationError(f"Git baseline check failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_json(project: Path, base_commit: str, relative_path: str) -> dict[str, object]:
    try:
        value = json.loads(_git(project, "show", f"{base_commit}:{relative_path}"))
    except json.JSONDecodeError as exc:
        raise VerificationError(
            f"Git baseline file is invalid JSON: {relative_path}"
        ) from exc
    if not isinstance(value, dict):
        raise VerificationError(f"Git baseline file is not an object: {relative_path}")
    return value


def _resolve_godot(godot_path: str | os.PathLike[str] | None) -> str | None:
    if godot_path is not None:
        candidate = Path(godot_path).expanduser().resolve()
        return str(candidate) if candidate.is_file() else None
    env_path = os.environ.get("GODOT_BIN")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
    located = shutil.which("godot")
    if located:
        return located
    fallback = Path("/Applications/Godot.app/Contents/MacOS/Godot")
    return str(fallback) if fallback.is_file() else None


def _requirement(identifier: str, status: str, evidence: str) -> dict[str, str]:
    return {"id": identifier, "status": status, "evidence": evidence}


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
