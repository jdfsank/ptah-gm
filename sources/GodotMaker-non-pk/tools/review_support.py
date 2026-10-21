"""Small local review helpers; PLAN/GAP remain the task authorities.

Trust boundary: cooperating local processes, not a same-user security sandbox.
No installation, generation, network request, or automatic approval occurs here.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import uuid

from agent_runtime import detect_agent, godotmaker_yaml, read_godot_path
from append_stage_event import validate_fields
from git_baseline import identity_bytes, identity_file
from frontend_approval import (
    ApprovalContext, ApprovalError, consume_frontend_approval,
    validate_durable_approval_record,
)

BASELINE = "1d4702caa2ac5fdbe1b0139e1787691cb52ae290"
RESULT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "ERROR": 3}
VARIANTS = ("baseline", "always_open_door", "stale_hud", "pause_input_leak", "dirty_restart")
NOT_PROVEN = ["generated_game_quality", "visual_layout", "audio_output", "physical_devices", "human_experience_acceptance"]
DOCS = {"SPEC.md", "GDD.md", "PLAN.md", "STRUCTURE.md", "DESIGN.md", "SCENES.md", "ASSETS.md", "GAP.md", "MEMORY.md", "ROADMAP.md", "TOC.md"}
SPEC_DOCS = ("GDD.md", "PLAN.md", "STRUCTURE.md", "DESIGN.md", "SCENES.md", "ASSETS.md")
IGNORED_DIRS = {".git", ".godot", ".godotmaker", ".claude", ".agents", ".opencode", ".pi", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv", "node_modules", "docs", "memory"}
TEST_DIRS = {"test", "tests", "e2e"}
PLAN_SECTIONS = {"Game Description", "Iteration Intent", "Tag Mechanics", "Inherited Mechanics", "Playable Unit", "Risk Tasks", "Main Build", "Task Status", "Review Notes", "Platform Commitments", "Component Coverage"}
REQUIRED_SECTIONS = {"Iteration Intent", "Tag Mechanics", "Playable Unit", "Main Build", "Task Status", "Review Notes", "Platform Commitments"}


class ReviewError(Exception):
    def __init__(self, message: str, result: str = "ERROR"):
        super().__init__(message)
        self.result = result


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest_bytes(data: bytes) -> str:
    """Legacy field adapter; values are Git blob identities, never SHA checks."""
    return identity_bytes(data)


def digest_file(path: Path) -> str:
    """Legacy field adapter; values are Git blob identities, never SHA checks."""
    return identity_file(path)


def canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def strict_json(text: str):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ReviewError(f"Duplicate JSON key: {key}")
            value[key] = item
        return value

    def invalid(value):
        raise ReviewError(f"Non-finite JSON number: {value}")

    try:
        def number(raw):
            value = float(raw)
            if not math.isfinite(value):
                raise ReviewError("Non-finite JSON number")
            return value
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReviewError(f"Invalid JSON: {exc}") from exc


def load_json(path: Path):
    try:
        return strict_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewError(f"Cannot read report {path.name}: {exc}") from exc


def write_json(path: Path, value, *, exclusive: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(data)
    else:
        temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(temporary, path)


def safe_child(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ReviewError(f"Unsafe relative path: {relative}")
    root = root.resolve()
    candidate = root / rel
    for current in (candidate, *candidate.parents):
        if current == root:
            break
        if current.is_symlink():
            raise ReviewError(f"Symlink is not reproducible: {relative}", "BLOCKED")
    if not candidate.resolve().is_relative_to(root):
        raise ReviewError(f"Path escapes root: {relative}")
    return candidate


def project_path(path: str | Path) -> Path:
    original = Path(path).absolute()
    if original.is_symlink():
        raise ReviewError("Project root must not be a symlink", "BLOCKED")
    result = original.resolve()
    if not result.is_dir() or not (result / "project.godot").is_file():
        raise ReviewError("Missing Godot project.godot", "BLOCKED")
    safe_child(result, "project.godot")
    return result


class OperationLock:
    """Exclusive cooperative lock. Stale/unknown owners are never auto-adopted."""
    def __init__(self, project: Path):
        self.project = project
        self.path = safe_child(project, ".godotmaker/run.lock")
        self.token = uuid.uuid4().hex
        self.children: set[int] = set()
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_json(self.path, {"pid": os.getpid(), "host": platform.node(), "token": self.token, "created_at": now(), "children": []}, exclusive=True)
        except FileExistsError as exc:
            raise ReviewError("Existing run.lock: inspect its owner/children and confirm they stopped before explicit recovery; no automatic retry", "BLOCKED") from exc
        self.held = True
        return self

    def record_child(self, pid: int, active: bool):
        if active:
            self.children.add(pid)
        else:
            self.children.discard(pid)
        data = load_json(self.path)
        if data.get("token") != self.token:
            raise ReviewError("Operation lock ownership changed")
        data["children"] = sorted(self.children)
        write_json(self.path, data)

    def __exit__(self, *exc):
        if self.held and not self.children and load_json(self.path).get("token") == self.token:
            self.path.unlink()
        self.held = False


def execute(argv: list[str], cwd: Path, report_dir: Path, label: str, timeout: float, *, env: dict | None = None, lock: OperationLock | None = None) -> dict:
    """Run an argv array in its own process group and retain stdout/stderr."""
    if os.name != "posix":
        raise ReviewError("Controlled process-tree cleanup is currently supported on POSIX hosts only", "BLOCKED")
    report_dir.mkdir(parents=True, exist_ok=True)
    output, errors = report_dir / f"{label}.stdout.log", report_dir / f"{label}.stderr.log"
    started = now()
    proc = None
    timed_out = False
    orphaned_children = False
    with output.open("wb") as stdout, errors.open("wb") as stderr:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=(os.name == "posix"))
            if lock:
                lock.record_child(proc.pid, True)
            try:
                code = proc.wait(timeout=timeout)
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        orphaned_children = True
                        os.killpg(proc.pid, signal.SIGKILL)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                timed_out = True
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait(timeout=5)
                code = proc.returncode
                # A group leader may exit while descendants ignore SIGTERM.
                if os.name == "posix":
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
            finally:
                if lock and proc.poll() is not None:
                    lock.record_child(proc.pid, False)
        except FileNotFoundError as exc:
            raise ReviewError(f"Missing executable: {argv[0]}", "BLOCKED") from exc
        except OSError as exc:
            raise ReviewError(f"Cannot execute {argv[0]}: {exc}") from exc
    return {"argv": argv, "cwd": str(cwd), "started_at": started, "finished_at": now(), "exit_code": code, "timed_out": timed_out, "orphaned_children": orphaned_children, "stdout": output.name, "stderr": errors.name}


def isolated_env(run_dir: Path) -> dict:
    env = os.environ.copy()
    home = run_dir / "user-data"
    for variable, child in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache")):
        folder = home / child
        folder.mkdir(parents=True, exist_ok=True)
        env[variable] = str(folder)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GODOT_SILENCE_ROOT_WARNING"] = "1"
    return env


def resolve_godot(project: Path, explicit: str | None = None) -> tuple[str, str]:
    # Match check_env's configured-path then PATH policy, without guessed paths.
    from check_env import _get_version_from_path, get_version, parse_version
    configured = explicit or read_godot_path(project)
    if configured:
        binary = str(Path(configured).resolve()) if Path(configured).is_file() else shutil.which(configured)
        version = _get_version_from_path(configured)
    else:
        binary = None
        version = None
        for command in ("godot", "godot4"):
            found = shutil.which(command)
            if found:
                binary, version = found, get_version(command)
                break
    if not binary or not version:
        raise ReviewError(f"Godot missing or unreadable; configure godot_path in {godotmaker_yaml(project)}", "BLOCKED")
    if parse_version(version) < (4, 4):
        raise ReviewError(f"Godot {version} is unsupported; Godot >=4.4 required", "BLOCKED")
    return str(Path(binary).resolve()), version


def doctor(project: Path, explicit: str | None = None) -> dict:
    result = {"schema_version": 1, "variant": "gm-non-pk", "command": "doctor", "project": str(project.resolve()), "framework_source": BASELINE, "result": "PASS", "reasons": [], "capabilities": {}}
    try:
        project = project_path(project)
        binary, version = resolve_godot(project, explicit)
        result["environment"] = {"godot_path": binary, "godot_version": version, "godot_git_identity": digest_file(Path(binary)), "python": platform.python_version(), "host": platform.system(), "agent": detect_agent(project)}
        for capability, module in (("python_tests", "pytest"), ("godot_e2e", "godot_e2e")):
            available = importlib.util.find_spec(module) is not None
            result["capabilities"][capability] = {"available": available, "reason": None if available else f"{module} is not installed; no installation attempted"}
        result["capabilities"]["headless"] = {"available": True, "reason": "Godot version probe only; no game was run"}
        result["capabilities"]["native_display"] = {"available": bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.name == "nt" or sys.platform == "darwin"), "reason": "Environment hint only; rendering not tested"}
        result["capabilities"]["generation"] = {"available": None, "reason": "Host gm-* skills required; doctor does not invoke a model"}
        result["historical_planner_state"] = (project / "tmp_plan").exists()
    except ReviewError as exc:
        result.update(result=exc.result, reasons=[str(exc)])
    return result


def inventory(project: Path) -> tuple[dict[str, str], dict[str, str]]:
    if project.is_symlink():
        raise ReviewError("Snapshot/project root symlink blocked", "BLOCKED")
    source, tests = {}, {}
    for folder, dirs, files in os.walk(project, followlinks=False):
        base = Path(folder)
        for name in list(dirs):
            child = base / name
            if name.lower() in {".aws", ".ssh", ".azure", ".gcloud", ".gnupg", ".kube", ".config"}:
                raise ReviewError(f"Credential/config directory cannot enter snapshot: {child.relative_to(project)}", "BLOCKED")
            if child.is_symlink():
                raise ReviewError(f"Symlink directory blocked: {child.relative_to(project)}", "BLOCKED")
            if name in IGNORED_DIRS or (base.relative_to(project).parts[:1] == ("e2e",) and name == "screenshots"):
                dirs.remove(name)
        for name in sorted(files):
            path = base / name
            relative = path.relative_to(project).as_posix()
            safe_child(project, relative)
            if not path.is_file():
                raise ReviewError(f"Special file blocked: {relative}", "BLOCKED")
            if name.startswith(".env") or name.lower() in {"credentials", "credentials.json", "credentials.yaml", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".netrc", ".npmrc", "export_credentials.cfg"} or path.suffix.lower() in {".pem", ".p12", ".pfx", ".key"}:
                raise ReviewError(f"Possible credential file excluded; relocate or explicitly review before binding: {relative}", "BLOCKED")
            if name in DOCS or path.suffix.lower() in {".md", ".log", ".pyc"} or name in {"LICENSE", "VERSION", ".DS_Store"}:
                continue
            if name.startswith(".") and name not in {".gdignore", ".gitattributes"}:
                continue
            if name in {"report.xml", "results.xml"} or name.endswith((".import", ".tmp")):
                continue
            target = tests if path.relative_to(project).parts[0] in TEST_DIRS or path.suffix == ".py" else source
            target[relative] = digest_file(path)
    if "project.godot" not in source:
        raise ReviewError("No effective project source", "BLOCKED")
    # Explicit resource references may not disappear behind ignore rules.
    for relative in source:
        if Path(relative).suffix in {".godot", ".gd", ".tscn", ".tres", ".gdshader"}:
            text = (project / relative).read_text(encoding="utf-8", errors="replace")
            for ref in re.findall(r'["\']res://([^"\'\n]+)["\']', text):
                if any(c in ref for c in ("%", "{", "*")):
                    continue
                path = safe_child(project, ref)
                if path.is_file() and ref not in source and ref not in tests:
                    raise ReviewError(f"Referenced resource excluded from snapshot: {ref}", "BLOCKED")
                if not path.exists():
                    raise ReviewError(f"Referenced resource missing: {ref}", "BLOCKED")
            if re.search(r'(?:path|run/main_scene)\s*=\s*"(?:/|[A-Za-z]:[\\/])', text):
                raise ReviewError(f"External resource path cannot be bound: {relative}", "BLOCKED")
    return dict(sorted(source.items())), dict(sorted(tests.items()))


def manifest_digest(files: dict) -> str:
    return digest_bytes(canonical(files))


def parse_sections(text: str) -> dict[str, list[str]]:
    sections, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            if current in sections:
                raise ReviewError(f"Duplicate PLAN section: {current}", "BLOCKED")
            sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def extract_spec(project: Path) -> dict:
    plan = safe_child(project, "PLAN.md")
    if not plan.is_file():
        raise ReviewError("PLAN missing; use original gm-gdd first", "BLOCKED")
    text = plan.read_text(encoding="utf-8")
    sections = parse_sections(text)
    missing, unknown = REQUIRED_SECTIONS - sections.keys(), sections.keys() - PLAN_SECTIONS
    if missing or unknown:
        raise ReviewError(f"Unsupported PLAN template; missing={sorted(missing)}, unknown={sorted(unknown)}", "BLOCKED")
    tag = re.search(r"\*\*Tag:\*\*\s*(v\d+\.\d+\.\d+(?:[-+][\w.-]+)?)", text)
    if not tag:
        raise ReviewError("PLAN tag is missing/unsupported", "BLOCKED")
    if not re.search(r"^- \[[^\]]+-M\d+\] .+", "\n".join(sections["Tag Mechanics"]), re.M):
        raise ReviewError("PLAN mechanics are empty/unsupported", "BLOCKED")
    normalized = {"tag": tag.group(1)}
    for name, lines in sections.items():
        if name == "Task Status":
            continue
        if not any(line.strip() and not line.lstrip().startswith("<!--") for line in lines):
            raise ReviewError(f"Empty normative PLAN section: {name}", "BLOCKED")
        evidence_column = None
        clean = []
        for line in lines:
            if name == "Playable Unit" and line.strip().startswith("|"):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if "Evidence" in cells:
                    evidence_column = cells.index("Evidence")
                if evidence_column is not None and len(cells) > evidence_column:
                    cells.pop(evidence_column)
                line = "|" + "|".join(cells) + "|"
            clean.append(line.rstrip())
        normalized[name] = "\n".join(clean).strip()
    docs = {"PLAN.md": normalized}
    for name in SPEC_DOCS:
        if name == "PLAN.md":
            continue
        path = safe_child(project, name)
        if not path.is_file():
            raise ReviewError(f"Required source document missing: {name}", "BLOCKED")
        docs[name] = path.read_text(encoding="utf-8").strip()
        if not docs[name]:
            raise ReviewError(f"Empty specification: {name}", "BLOCKED")
    # SPEC.md is an additional normative binding for generated generic plans;
    # legacy non-pk projects remain compatible when they do not have the file.
    optional_spec = safe_child(project, "SPEC.md")
    if optional_spec.is_file():
        docs["SPEC.md"] = optional_spec.read_text(encoding="utf-8").strip()
        if not docs["SPEC.md"]:
            raise ReviewError("Empty specification: SPEC.md", "BLOCKED")
    profiles = []
    for line in sections["Platform Commitments"]:
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) in {3, 5} and cells[1] == "required":
                if len(cells) == 3:
                    profiles.append({"name": cells[0], "platform": cells[0], "evidence": cells[2]})
                else:
                    for name in cells[2].split(","):
                        if name.strip():
                            profiles.append({"name": name.strip(), "platform": cells[0], "evidence": cells[3], "manual_check": cells[4]})
    if not profiles:
        raise ReviewError("Platform Commitments needs a required profile (supported three/five-column fixed table)", "BLOCKED")
    names = [profile["name"] for profile in profiles]
    if len(names) != len(set(names)) or any(not name.strip() or "{" in name or "}" in name for name in names):
        raise ReviewError("Required platform profile identities must be unique and explicit", "BLOCKED")
    return {"tag": tag.group(1), "spec_digest": digest_bytes(canonical(docs)), "text": docs, "profiles": profiles}


def spec_git_ref(spec: dict, project: Path) -> str:
    """Git blob identity for canonical normative spec text, independent of legacy digest fields."""
    try:
        return identity_bytes(canonical(spec["text"]))
    except Exception as exc:
        raise ReviewError("Cannot derive Git identity for current specification", "BLOCKED") from exc


def frontend_approval_binding(project: Path) -> dict:
    """Load the backend-prepared confirmation at its fixed project path."""
    path = safe_child(project, ".godotmaker/frontend-approval.json")
    if not path.is_file():
        raise ReviewError("Backend frontend approval binding is missing", "BLOCKED")
    binding = load_json(path)
    required = {"schemaVersion", "decisionRef", "eventId", "projectId", "phase", "action", "gitSpecRef",
                "testData", "productionAuthorized", "proposalId", "packetId", "jobId", "candidateId", "revision"}
    if not isinstance(binding, dict) or set(binding) != required or binding["schemaVersion"] != 2:
        raise ReviewError("Backend frontend approval binding has an unsupported schema", "BLOCKED")
    if type(binding["testData"]) is not bool or type(binding["productionAuthorized"]) is not bool:
        raise ReviewError("Backend approval authorization flags must be booleans", "BLOCKED")
    for field in ("decisionRef", "eventId", "projectId", "phase", "action", "gitSpecRef", "proposalId", "packetId", "jobId", "revision"):
        if not isinstance(binding[field], str) or not binding[field].strip():
            raise ReviewError(f"Backend approval binding has invalid {field}", "BLOCKED")
    if binding["phase"] != "specification" or binding["action"] != "approve":
        raise ReviewError("Backend confirmation does not approve a specification", "BLOCKED")
    return binding


class SQLiteFrontendApprovalStore:
    """Read/consume the registered approval table with a single-use transaction."""
    def __init__(self, path: Path):
        self.path = path

    def get(self, event_id: str):
        uri = self.path.as_uri() + "?mode=ro"
        connection = None
        try:
            connection = sqlite3.connect(uri, uri=True)
            row = connection.execute(
                "SELECT payload FROM approvals WHERE id = ? AND consumed = 0", (event_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise ReviewError(f"Cannot read registered frontend approval: {exc}", "BLOCKED") from exc
        finally:
            if connection is not None:
                connection.close()
        return strict_json(row[0]) if row else None

    def consume_once(self, event_id: str) -> bool:
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE approvals SET consumed = 1 WHERE id = ? AND consumed = 0", (event_id,)
                )
                connection.commit()
                return cursor.rowcount == 1
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ReviewError(f"Cannot consume registered frontend approval: {exc}", "BLOCKED") from exc

    def get_consumed(self, event_id: str):
        connection = None
        try:
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            row = connection.execute(
                "SELECT payload, consumed FROM approvals WHERE id = ?", (event_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise ReviewError(f"Cannot verify consumed frontend approval: {exc}", "BLOCKED") from exc
        finally:
            if connection is not None:
                connection.close()
        return strict_json(row[0]) if row and row[1] == 1 else None


def consume_registered_frontend_approval(project: Path, event_id: str, spec: dict) -> dict:
    binding = frontend_approval_binding(project)
    if binding["testData"] or not binding["productionAuthorized"]:
        raise ReviewError("Test-mode or unauthorized approvals cannot confirm production specifications", "BLOCKED")
    if event_id != binding["eventId"] or binding["gitSpecRef"] != spec_git_ref(spec, project):
        raise ReviewError("Backend confirmation is stale or belongs to another event", "BLOCKED")
    return {
        "event_id": event_id,
        "phase": "specification",
        "action": "approve",
        "provenance": {
            "kind": "interactive_frontend", "input": "frontend",
            "recorded_by": "approval_service", "event_id": event_id,
            "phase": "specification", "project_id": binding["projectId"],
            "production_authorized": True, "test_data": False,
            "decision_ref": binding["decisionRef"],
        },
    }

def runner_digest(project: Path, tests: dict) -> str:
    tools = {p.name: digest_file(p) for p in Path(__file__).parent.glob("*.py")}
    configs = {}
    for path in (godotmaker_yaml(project), project / ".godotmaker/config.yaml", project / "pytest.ini", project / "pyproject.toml"):
        if path.is_file():
            safe_child(project, str(path.relative_to(project)))
            configs[str(path.relative_to(project))] = digest_file(path)
    hook_root = next((root for root in (Path(__file__).parent.parent / "hooks", project / ".godotmaker/hooks") if (root / "playability_contract.py").is_file()), None)
    validator = digest_file(hook_root / "playability_contract.py") if hook_root else None
    packages = {distribution.metadata["Name"]: distribution.version for distribution in importlib.metadata.distributions() if distribution.metadata.get("Name")}
    return digest_bytes(canonical({"tests": tests, "runner": tools, "configs": configs, "python": platform.python_version(), "packages": packages, "playability_validator": validator}))


def validate_assertions(report: dict, returncode: int, expected_cases: dict | None = None) -> str:
    if not isinstance(report, dict) or report.get("schema_version") != 1 or not isinstance(report.get("cases"), list):
        raise ReviewError("Unsupported assertion report")
    cases, ids = report["cases"], set()
    if not cases:
        return "BLOCKED"
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] or case["id"] in ids:
            raise ReviewError("Invalid/duplicate assertion ID")
        ids.add(case["id"])
        if case.get("status") not in {"PASS", "FAIL", "SKIPPED", "BLOCKED", "ERROR"} or not isinstance(case.get("required"), bool):
            raise ReviewError("Invalid assertion status/required flag")
    if expected_cases is not None:
        if set(expected_cases) - ids:
            return "BLOCKED"
        if ids - set(expected_cases) or any(case.get("mechanic") != expected_cases[case["id"]] or case["required"] is not True for case in cases):
            raise ReviewError("Fixture assertion identities differ from the fixed required oracle")
    statuses = [case["status"] for case in cases if case["required"]]
    result = "ERROR" if "ERROR" in statuses else "FAIL" if "FAIL" in statuses else "BLOCKED" if not statuses or any(s in {"SKIPPED", "BLOCKED"} for s in statuses) else "PASS"
    if report.get("result") != result or returncode != RESULT_CODES[result]:
        raise ReviewError(f"Assertion result/exit contradiction: derived={result}, reported={report.get('result')}, exit={returncode}")
    return result


def smoke(fixture: Path, output: Path, variant: str, godot: str | None = None, timeout: float = 40) -> dict:
    if variant not in VARIANTS:
        raise ReviewError("Unsupported fixture variant", "BLOCKED")
    if output.exists() or output.is_symlink():
        raise ReviewError("Output already exists; evidence is never overwritten", "BLOCKED")
    if not output.is_absolute() or output.resolve().is_relative_to(fixture.resolve()):
        raise ReviewError("Output must be an absolute new directory outside fixture", "BLOCKED")
    for parent in output.parents:
        if parent.is_symlink():
            raise ReviewError("Output parent symlink blocked", "BLOCKED")
    binary, version = resolve_godot(fixture, godot)
    if version != "4.6.3":
        raise ReviewError(f"Fixed fixture requires validated Godot 4.6.3, observed {version}", "BLOCKED")
    original = inventory(fixture)
    output.mkdir(parents=True, exist_ok=False)
    project = output / "project"
    project.mkdir()
    for rel in {**original[0], **original[1]}:
        dst = safe_child(project, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture / rel, dst)
    variant_path = project / "variant.gd"
    content = variant_path.read_text()
    if 'const NAME: String = "baseline"' not in content:
        raise ReviewError("Fixture variant seam missing")
    variant_path.write_text(content.replace('const NAME: String = "baseline"', f'const NAME: String = "{variant}"'), encoding="utf-8")
    before = inventory(project)
    spec_path = fixture / "SPEC.md"
    result = {"schema_version": 1, "variant": "gm-non-pk", "fixture_variant": variant, "command": "smoke", "run_id": output.name, "result": "ERROR", "fixture_spec_digest": digest_file(spec_path), "source_digest": manifest_digest(before[0]), "test_digest": digest_bytes(canonical({"tests": before[1], "runner": {name: digest_file(Path(__file__).parent / name) for name in ("gm_review.py", "review_support.py")}, "godot_version": version})), "source_files": before[0], "test_files": before[1], "environment": {"host": platform.platform(), "godot_version": version, "godot_path": binary, "godot_git_identity": digest_file(Path(binary)), "input_source": "semantic_action"}, "claims": [], "not_proven": NOT_PROVEN, "raw_report": "reports/assertions.json", "started_at": now(), "commands": []}
    try:
        env = isolated_env(output)
        reports = output / "reports"
        imported = execute([binary, "--headless", "--path", str(project), "--editor", "--import"], project, reports, "import", timeout, env=env)
        result["commands"].append(imported)
        if imported["timed_out"] or imported["orphaned_children"] or imported["exit_code"] != 0:
            raise ReviewError("Godot import failed or timed out")
        report = reports / "assertions.json"
        command = execute([binary, "--headless", "--path", str(project), "--script", "res://tests/smoke_runner.gd", "--", "--report", str(report)], project, reports, "smoke", timeout, env=env)
        result["commands"].append(command)
        if command["timed_out"] or command["orphaned_children"]:
            raise ReviewError("Smoke timed out; process group terminated")
        oracle = load_json(project / "tests/cases.json")
        if oracle.get("schema_version") != 1 or not isinstance(oracle.get("required_cases"), dict) or not oracle["required_cases"]:
            raise ReviewError("Fixed fixture oracle is empty or invalid")
        result["result"] = validate_assertions(load_json(report), command["exit_code"], oracle["required_cases"])
        if result["result"] == "PASS":
            result["claims"] = ["fixture.core_loop.semantic_input"]
        if inventory(project) != before or inventory(fixture) != original:
            raise ReviewError("Source/test input drift during execution")
    except ReviewError as exc:
        result.update(result=exc.result, reason=str(exc), claims=[])
    result["finished_at"] = now()
    result["report_digests"] = {str(p.relative_to(output)): digest_file(p) for p in (output / "reports").glob("*") if p.is_file()}
    write_json(output / "manifest.json", result, exclusive=True)
    return result


def read_events(project: Path) -> list[dict]:
    path = safe_child(project, ".godotmaker/stage.jsonl")
    if not path.exists():
        return []
    events, seen = [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = strict_json(line)
        if not isinstance(value, dict) or not isinstance(value.get("role"), str) or not isinstance(value.get("ts"), str):
            raise ReviewError(f"Invalid stage event on line {number}")
        try:
            dt.datetime.fromisoformat(value["ts"].replace("Z", "+00:00"))
            validate_fields(value["role"], {k: v for k, v in value.items() if k not in {"role", "ts"}})
        except (ValueError, TypeError) as exc:
            raise ReviewError(f"Invalid stage event on line {number}: {exc}") from exc
        fingerprint = digest_bytes(canonical(value))
        if fingerprint in seen:
            raise ReviewError(f"Duplicate stage event on line {number}")
        seen.add(fingerprint)
        events.append(value)
    return events


def _run_path(project: Path, run_id: str | None) -> Path:
    if run_id is None:
        latest = load_json(safe_child(project, ".godotmaker/latest-review.json"))
        run_id = latest.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"RUN-[A-Za-z0-9_-]+", run_id):
        raise ReviewError("Invalid or missing run_id", "BLOCKED")
    return safe_child(project, f".godotmaker/runs/{run_id}")


def _copy_snapshot(project: Path, destination: Path, source: dict, tests: dict):
    destination.mkdir()
    for relative in {**source, **tests}:
        target = safe_child(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(safe_child(project, relative), target)
    for name in SPEC_DOCS:
        shutil.copy2(project / name, destination / name)
    # Only scalar, explicitly known non-secret runtime configuration is copied.
    # Unknown keys/nested blocks need review, rather than a leaky secret denylist.
    allowed = {"agent", "agent_runtime", "godot_path", "vqa_model", "vqa_fallback_model",
               "asset_image_model", "worker_model", "verifier_model", "reviewer_model",
               "analyst_model", "auditor_model", "decomposer_model", "asset_producer_model",
               "reasoning_effort"}
    for config in (godotmaker_yaml(project), project / ".godotmaker/config.yaml"):
        if config.is_file():
            scalars = {}
            for raw in config.read_text(encoding="utf-8").splitlines():
                if not raw.strip() or raw.lstrip().startswith("#"):
                    continue
                match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*):\s*(.+)", raw)
                if not match or match[1] not in allowed:
                    raise ReviewError(f"Unsupported/credential-like snapshot config key in {config.name}; review it explicitly", "BLOCKED")
                key, value = match[1], match[2].strip()
                if key in scalars:
                    raise ReviewError(f"Duplicate configuration key: {key}", "BLOCKED")
                if value.startswith('"'):
                    try:
                        value = json.loads(value)
                    except ValueError as exc:
                        raise ReviewError("Unsupported quoted config scalar", "BLOCKED") from exc
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                else:
                    value = value.split("#", 1)[0].strip()
                if not isinstance(value, str) or not value:
                    raise ReviewError("Unsupported config scalar", "BLOCKED")
                scalars[key] = value
            target = safe_child(destination, config.relative_to(project).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(f"{key}: {json.dumps(value)}\n" for key, value in scalars.items()), encoding="utf-8")
    runtime_config = destination / ".godotmaker/config.yaml"
    runtime_config.parent.mkdir(parents=True, exist_ok=True)
    if not runtime_config.exists():
        runtime_config.write_text("agent: " + detect_agent(project) + "\n", encoding="utf-8")
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode & ~0o222)


def snapshot_auxiliary(project: Path) -> dict[str, str]:
    """Bind copied normative documents and actual normalized runner configuration."""
    files = {}
    for name in SPEC_DOCS:
        path = safe_child(project, name)
        if path.is_file():
            files[name] = digest_file(path)
    for path in (godotmaker_yaml(project), project / ".godotmaker/config.yaml"):
        relative = path.relative_to(project).as_posix()
        safe_child(project, relative)
        if path.is_file():
            files[relative] = digest_file(path)
    return files


def check(project: Path, *, suite: str = "all", timeout: float = 600, godot: str | None = None) -> dict:
    project = project_path(project)
    with OperationLock(project) as lock:
        spec = extract_spec(project)
        source, tests = inventory(project)
        binary, version = resolve_godot(project, godot)
        test_digest = runner_digest(project, tests)
        run_id = "RUN-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
        run = safe_child(project, f".godotmaker/runs/{run_id}")
        run.mkdir(parents=True, exist_ok=False)
        snapshot = run / "project"
        _copy_snapshot(project, snapshot, source, tests)
        if inventory(project) != (source, tests) or inventory(snapshot) != (source, tests) or extract_spec(project)["spec_digest"] != spec["spec_digest"]:
            raise ReviewError("Input drift while copying snapshot")
        # Snapshot includes no runtime credentials. Probe/configure only its local Godot path.
        config = godotmaker_yaml(snapshot)
        config.parent.mkdir(parents=True, exist_ok=True)
        if config.exists():
            config.chmod(0o600)
            text = config.read_text(encoding="utf-8")
            text = re.sub(r"(?m)^godot_path:.*$", "", text)
        else:
            text = ""
        config.write_text(text + "\ngodot_path: " + json.dumps(binary) + "\n", encoding="utf-8")
        config.chmod(0o400)
        manifest = {"schema_version": 1, "command": "check", "variant": "gm-non-pk", "run_id": run_id, "tag": spec["tag"], "spec_digest": spec["spec_digest"], "source_digest": manifest_digest(source), "test_digest": test_digest, "source_files": source, "test_files": tests, "specification": spec["text"], "profiles": spec["profiles"], "environment": {"godot_version": version, "godot_git_identity": digest_file(Path(binary)), "godot_path": binary, "python": platform.python_version(), "host": platform.platform(), "input_source": "semantic_action"}, "suite": suite, "suites": {}, "started_at": now(), "result": "ERROR", "not_proven": ["visual_layout", "audio_output", "physical_devices", "human_experience_acceptance"], "commands": []}
        manifest["snapshot_auxiliary"] = snapshot_auxiliary(snapshot)
        reports = run / "reports"
        env = isolated_env(run)
        env["GODOT_E2E_PROJECT_PATH"] = str(snapshot)
        try:
            if suite in {"verify", "all"}:
                from run_verify import normalize_report, validate_report
                command = execute([sys.executable, str(Path(__file__).parent / "run_verify.py"), "--project-path", str(snapshot)], snapshot, reports, "verify", timeout, env=env, lock=lock)
                command["suite"] = "verify"
                manifest["commands"].append(command)
                if command["timed_out"] or command["orphaned_children"]:
                    raise ReviewError("verify timed out")
                raw = load_json(reports / command["stdout"])
                normalized = normalize_report(raw)
                issues = validate_report(normalized)
                if issues:
                    raise ReviewError("Invalid verify report: " + "; ".join(issues))
                status = normalized.get("status", "ERROR")
                if command["exit_code"] != RESULT_CODES.get(status, 3):
                    raise ReviewError("Verify report/exit contradiction")
                write_json(reports / "verify.json", normalized, exclusive=True)
                manifest["suites"]["verify"] = {"result": status, "report": "reports/verify.json", "test_digest": test_digest}
            if suite in {"e2e", "all"}:
                if importlib.util.find_spec("godot_e2e") is None or importlib.util.find_spec("pytest") is None:
                    manifest["suites"]["e2e"] = {"result": "BLOCKED", "reason": "Installed pytest and godot-e2e are required"}
                elif not (snapshot / "e2e").is_dir() or not list((snapshot / "e2e").glob("test_*.py")):
                    manifest["suites"]["e2e"] = {"result": "BLOCKED", "reason": "No evaluator-authored e2e tests"}
                else:
                    xml = reports / "e2e.xml"
                    command = execute([sys.executable, "-m", "pytest", "e2e", "-q", "--junitxml", str(xml), "-p", "no:cacheprovider"], snapshot, reports, "e2e", timeout, env=env, lock=lock)
                    command["suite"] = "e2e"
                    manifest["commands"].append(command)
                    if command["timed_out"] or command["orphaned_children"]:
                        raise ReviewError("e2e timed out")
                    if not xml.is_file():
                        raise ReviewError("e2e report missing")
                    # pytest's outer testsuites wrapper is parsed independently of gdUnit.
                    import xml.etree.ElementTree as ET
                    root = ET.parse(xml).getroot()
                    cases = list(root.iter("testcase"))
                    identities = [(c.get("classname"), c.get("name")) for c in cases]
                    if len(identities) != len(set(identities)):
                        raise ReviewError("Duplicate E2E testcase identity")
                    if any(c.find("error") is not None for c in cases):
                        status = "ERROR"
                    elif any(c.find("failure") is not None for c in cases):
                        status = "FAIL"
                    elif not cases or any(c.find("skipped") is not None for c in cases):
                        status = "BLOCKED"
                    else:
                        status = "PASS"
                    expected = {"PASS": {0}, "FAIL": {1}, "BLOCKED": {0, 5}, "ERROR": {1, 2, 3, 4}}
                    if command["exit_code"] not in expected[status]:
                        raise ReviewError("E2E report/exit contradiction")
                    manifest["suites"]["e2e"] = {"result": status, "report": "reports/e2e.xml", "cases": len(cases), "test_digest": test_digest}
            statuses = [item["result"] for item in manifest["suites"].values()]
            manifest["result"] = next((state for state in ("ERROR", "FAIL", "BLOCKED") if state in statuses), "PASS") if statuses else "BLOCKED"
            if inventory(project) != (source, tests) or inventory(snapshot) != (source, tests) or snapshot_auxiliary(snapshot) != manifest["snapshot_auxiliary"] or extract_spec(project)["spec_digest"] != spec["spec_digest"] or runner_digest(project, tests) != test_digest:
                raise ReviewError("Run inputs drifted; evidence is not current")
        except ReviewError as exc:
            manifest.update(result=exc.result, reason=str(exc))
        except Exception as exc:
            manifest.update(result="ERROR", reason=f"{type(exc).__name__}: {exc}")
        manifest["finished_at"] = now()
        manifest["report_digests"] = {str(p.relative_to(run)): digest_file(p) for p in reports.glob("*") if p.is_file()}
        write_json(run / "manifest.json", manifest, exclusive=True)
        (run / "manifest.git").write_text(digest_file(run / "manifest.json") + "\n", encoding="ascii")
        write_json(project / ".godotmaker/latest-review.json", {"run_id": run_id, "manifest_digest": digest_file(run / "manifest.json")})
        return manifest


def _gap_verified(project: Path, task: str) -> bool:
    candidates = [project / "GAP.md", *sorted((project / ".godotmaker").glob("GAP*.md")), *sorted((project / ".godotmaker/gaps").glob("**/GAP.md")), *sorted((project / "docs/tags").glob("**/GAP*.md"))]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        safe_child(project, candidate.relative_to(project).as_posix())
        sections = parse_sections(candidate.read_text(encoding="utf-8"))
        for line in sections.get("Task Status", []):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0] == task and cells[2] == "verified":
                return True
    return False


def pending_feedback(project: Path, run_id: str | None = None) -> list[dict]:
    events = read_events(project)
    for archived in sorted((project / "docs/tags").glob("*/evidence/review/.godotmaker/stage.jsonl")):
        safe_child(project, archived.relative_to(project).as_posix())
        for line in archived.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = strict_json(line)
                if not isinstance(event, dict):
                    raise ReviewError("Invalid archived stage event")
                events.append(event)
    pending = []
    directory = safe_child(project, ".godotmaker/feedback")
    for path in sorted(directory.glob("*.json")):
        item = load_json(safe_child(project, path.relative_to(project).as_posix()))
        required = {"id", "tag", "run_id", "mechanics", "platform", "text", "type", "source", "provenance", "created_at", "gap_task_id"}
        if not isinstance(item, dict) or not required.issubset(item) or item["id"] != path.stem or item["gap_task_id"] != "F-" + item["id"]:
            raise ReviewError(f"Invalid feedback file: {path.name}")
        resolved = any(e.get("role") == "fixgap" and e.get("feedback_id") == item["id"] and e.get("resolution") == "verified" and e.get("provenance", {}).get("kind") == "local_interactive" and (run_id is None or e.get("resolved_run_id") == run_id or item.get("tag") != extract_spec(project)["tag"]) for e in events)
        if not resolved or not _gap_verified(project, item["gap_task_id"]):
            pending.append(item)
    return pending


def _spec_confirmation_matches(event: dict, spec: dict, current_git_ref: str, project: Path) -> bool:
    if event.get("role") != "gdd" or event.get("tag") != spec["tag"] or event.get("spec_digest") != spec["spec_digest"]:
        return False
    provenance = event.get("provenance", {})
    if provenance.get("kind") == "local_interactive":
        return True
    if not (
        provenance.get("kind") == "interactive_frontend"
        and provenance.get("phase") == "specification"
        and provenance.get("production_authorized") is True
        and provenance.get("test_data") is False
        and bool(provenance.get("event_id"))
        and bool(provenance.get("decision_ref"))
        and event.get("git_spec_ref") == current_git_ref
    ):
        return False
    try:
        binding = frontend_approval_binding(project)
        return (
            binding["testData"] is False
            and binding["productionAuthorized"] is True
            and binding["eventId"] == provenance["event_id"]
            and binding["projectId"] == provenance["project_id"]
            and binding["decisionRef"] == provenance["decision_ref"]
            and binding["gitSpecRef"] == current_git_ref
            and binding["action"] == "approve"
        )
    except (ReviewError, OSError, TypeError, KeyError):
        return False


def _gate_unlocked(project: Path, run_id: str | None, require_accept: bool) -> dict:
    reasons = []
    run = _run_path(project, run_id)
    manifest = load_json(safe_child(run, "manifest.json"))
    if manifest.get("command") != "check" or manifest.get("schema_version") != 1:
        raise ReviewError("A fixture or legacy report is not project acceptance evidence", "BLOCKED")
    identity_record = safe_child(run, "manifest.git")
    if not identity_record.is_file() or identity_record.read_text(encoding="ascii").strip() != digest_file(run / "manifest.json"):
        reasons.append("Run manifest changed or Git identity record missing")
    latest_path = safe_child(project, ".godotmaker/latest-review.json")
    if latest_path.is_file():
        latest = load_json(latest_path)
        if latest.get("run_id") == manifest.get("run_id") and latest.get("manifest_digest") != digest_file(run / "manifest.json"):
            reasons.append("Latest manifest binding is stale")
    spec = extract_spec(project)
    source, tests = inventory(project)
    current = {"spec_digest": spec["spec_digest"], "source_digest": manifest_digest(source), "test_digest": runner_digest(project, tests)}
    task_rows = []
    for line in parse_sections((project / "PLAN.md").read_text(encoding="utf-8")).get("Task Status", []):
        if line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0] != "#" and not re.fullmatch(r"[-:]+", cells[0]):
                task_rows.append(cells)
    if not task_rows or any(row[2] != "verified" for row in task_rows):
        reasons.append("Current PLAN Task Status is incomplete/unsupported")
    engine = manifest.get("environment", {})
    engine_path = Path(engine.get("godot_path", ""))
    if not engine_path.is_file() or digest_file(engine_path) != engine.get("godot_git_identity"):
        reasons.append("Checked Godot binary is unavailable or changed")
    if manifest.get("tag") != spec["tag"]:
        reasons.append("Run tag differs from current PLAN")
    for key, value in current.items():
        if manifest.get(key) != value:
            reasons.append(f"Current {key} differs from checked run")
    if inventory(run / "project") != (manifest.get("source_files"), manifest.get("test_files")):
        reasons.append("Snapshot input drift")
    if not manifest.get("snapshot_auxiliary") or snapshot_auxiliary(run / "project") != manifest["snapshot_auxiliary"]:
        reasons.append("Snapshot specification/configuration drift or missing binding")
    for relative, expected in manifest.get("report_digests", {}).items():
        path = safe_child(run, relative)
        if not path.is_file() or digest_file(path) != expected:
            reasons.append(f"Report changed or missing: {relative}")
    if not manifest.get("report_digests") or manifest.get("result") != "PASS":
        reasons.append("Current run does not have actual PASS evidence")
    for name in ("verify", "e2e"):
        suite = manifest.get("suites", {}).get(name, {})
        if suite.get("result") != "PASS":
            reasons.append(f"Required {name} evidence missing/not PASS")
        report_ref = suite.get("report")
        if not isinstance(report_ref, str) or not report_ref.startswith("reports/") or report_ref not in manifest.get("report_digests", {}):
            reasons.append(f"Required {name} raw report reference/digest missing")
        if suite.get("test_digest") != manifest.get("test_digest"):
            reasons.append(f"Required {name} test binding missing/stale")
        invocations = [command for command in manifest.get("commands", []) if command.get("suite") == name]
        if len(invocations) != 1 or invocations[0].get("exit_code") != 0 or invocations[0].get("timed_out") is not False or invocations[0].get("orphaned_children") is not False:
            reasons.append(f"Required {name} successful invocation missing")
    # Hashes detect accidental edits; reparse facts instead of trusting summary flags.
    from run_verify import validate_report
    verification = manifest.get("suites", {}).get("verify", {})
    if verification.get("report"):
        raw = load_json(safe_child(run, verification["report"]))
        reasons.extend(validate_report(raw))
        if raw.get("status") != "PASS":
            reasons.append("Raw verification evidence is not PASS")
    e2e = manifest.get("suites", {}).get("e2e", {})
    if e2e.get("report"):
        import xml.etree.ElementTree as ET
        try:
            cases = list(ET.parse(safe_child(run, e2e["report"])).getroot().iter("testcase"))
            identities = [(c.get("classname"), c.get("name")) for c in cases]
            if not cases or len(identities) != len(set(identities)) or any(c.find(kind) is not None for c in cases for kind in ("failure", "error", "skipped")):
                reasons.append("Raw E2E evidence is empty, duplicate or not PASS")
        except ET.ParseError as exc:
            raise ReviewError(f"Corrupt E2E report: {exc}") from exc
    evaluation_issues, evaluation_digest = evaluation_gate_issues(project, run, manifest)
    reasons.extend(evaluation_issues)
    events = read_events(project)
    current_spec_git_ref = spec_git_ref(spec, project)
    confirmed = any(_spec_confirmation_matches(e, spec, current_spec_git_ref, project) for e in events)
    if not confirmed:
        reasons.append("needs_human: current GDD/PLAN specification confirmation")
    feedback = pending_feedback(project, manifest["run_id"])
    if feedback:
        reasons.append("Unresolved feedback: " + ", ".join(item["id"] for item in feedback))
    if require_accept:
        decisions = [e for e in events if e.get("role") == "accept" and e.get("tag") == spec["tag"]]
        decision = decisions[-1] if decisions else {}
        if decision.get("decision") != "accept" or decision.get("run_id") != manifest["run_id"] or any(decision.get(k) != v for k, v in current.items()) or decision.get("provenance", {}).get("kind") != "local_interactive":
            reasons.append("needs_human: current run has no applicable user acceptance")
        required_profiles = {p["name"] for p in spec["profiles"]}
        if not required_profiles.issubset(set(decision.get("reviewed_profiles", []))):
            reasons.append("Required platform/manual evidence not reviewed")
        if decision.get("evaluation_digest") != evaluation_digest:
            reasons.append("User acceptance evaluator binding is missing/stale")
        if decision.get("evidence_ref") != f".godotmaker/runs/{manifest['run_id']}/manifest.json":
            reasons.append("User acceptance evidence reference is missing/stale")
    return {"schema_version": 1, "command": "gate", "run_id": manifest["run_id"], "result": "BLOCKED" if reasons else "PASS", "ok": not reasons, "reasons": reasons, "current": current, "tag": spec["tag"]}


def gate(project: Path, run_id: str | None = None, require_accept: bool = True, *, locked: bool = False) -> dict:
    try:
        project = project_path(project)
        if locked:
            return _gate_unlocked(project, run_id, require_accept)
        with OperationLock(project):
            return _gate_unlocked(project, run_id, require_accept)
    except ReviewError as exc:
        return {"schema_version": 1, "command": "gate", "result": exc.result, "ok": False, "reasons": [str(exc)]}
    except Exception as exc:
        return {"schema_version": 1, "command": "gate", "result": "ERROR", "ok": False, "reasons": [f"Invalid review state: {exc}"]}


def status(project: Path) -> dict:
    project = project_path(project)
    result = {"schema_version": 1, "command": "status", "result": "PASS", "project": str(project), "read_only": True, "run": None, "issues": [], "lock_present": (project / ".godotmaker/run.lock").exists()}
    try:
        latest = project / ".godotmaker/latest-review.json"
        if latest.exists():
            run = _run_path(project, None)
            manifest = load_json(safe_child(run, "manifest.json"))
            result["run"] = {key: manifest.get(key) for key in ("run_id", "tag", "result", "started_at", "finished_at", "profiles", "not_proven")}
        result["pending_feedback"] = pending_feedback(project)
        result["task_authorities"] = {name: (project / name).read_text(encoding="utf-8") if (project / name).is_file() else None for name in ("PLAN.md", "GAP.md")}
        read_events(project)
    except ReviewError as exc:
        result["issues"].append(str(exc))
    return result


def add_feedback(project: Path, run_id: str, supplied: dict) -> dict:
    project = project_path(project)
    with OperationLock(project):
        run = _run_path(project, run_id)
        manifest = load_json(safe_child(run, "manifest.json"))
        if manifest.get("command") != "check":
            raise ReviewError("Feedback needs a project run, not a smoke fixture", "BLOCKED")
        required = {"id", "mechanics", "platform", "text", "type", "source_ref"}
        if not isinstance(supplied, dict) or set(supplied) != required:
            raise ReviewError("Feedback requires exactly id, mechanics, platform, text, type, source_ref", "BLOCKED")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", supplied["id"]):
            raise ReviewError("Invalid feedback id", "BLOCKED")
        if supplied["type"] not in {"implementation", "experience", "design_change", "test_error", "capability"} or not isinstance(supplied["mechanics"], list) or not supplied["mechanics"] or any(not isinstance(v, str) or not v for v in supplied["mechanics"]):
            raise ReviewError("Invalid feedback type/mechanics", "BLOCKED")
        if any(not isinstance(supplied[k], str) or not supplied[k].strip() for k in ("platform", "text", "source_ref")):
            raise ReviewError("Feedback content/source must be nonempty", "BLOCKED")
        item = {"schema_version": 1, **supplied, "tag": manifest["tag"], "run_id": run_id, "source": "user", "provenance": {"kind": "host_supplied", "source_ref": supplied["source_ref"], "identity_assurance": "audit_only"}, "created_at": now(), "gap_task_id": "F-" + supplied["id"]}
        path = safe_child(project, f".godotmaker/feedback/{item['id']}.json")
        if path.exists():
            existing = load_json(path)
            if any(existing.get(key) != item.get(key) for key in (*required, "tag", "run_id")):
                raise ReviewError("Feedback ID already exists with different immutable content", "BLOCKED")
            item = existing
            gap_existing = safe_child(project, "GAP.md")
            if gap_existing.exists() and re.search(r"(?m)^\| " + re.escape(item["gap_task_id"]) + r" \|", gap_existing.read_text(encoding="utf-8")):
                return {"result": "PASS", "feedback_id": item["id"], "idempotent": True}
        else:
            write_json(path, item, exclusive=True)
        gap = safe_child(project, "GAP.md")
        text = gap.read_text(encoding="utf-8") if gap.exists() else f"# Gap Plan\n\n**Tag:** {manifest['tag']}\n"
        task = item["gap_task_id"]
        route = {"implementation": "Reproduce, then original gm-fixgap worker", "experience": "Reproduce experience and scope adjustment; do not invent a critical bug", "design_change": "Stop writers; obtain confirmed GDD/PLAN change before implementation", "test_error": "Evaluator must review and revise test with justification", "capability": "Keep BLOCKED until necessary capability is available"}[item["type"]]
        text += f"\n## Feedback {item['id']}\n\n- Task: {task}\n- Source: .godotmaker/feedback/{item['id']}.json\n- Run: {run_id}\n- Reproduction: pending; user observation is not yet a verified defect.\n- Observed gap: read the immutable user text at the Source above.\n- Expected behavior: current PLAN mechanics {', '.join(item['mechanics'])}.\n- Route: {route}\n"
        row = f"| {task} | User feedback {item['id']} | pending | Reproduce first; source above |"
        if "## Task Status" not in text:
            text += "\n## Task Status\n\n| # | Task | Status | Notes |\n|---|---|---|---|\n" + row + "\n"
        else:
            start = text.index("## Task Status")
            end = text.find("\n## ", start + 1)
            end = len(text) if end == -1 else end
            text = text[:end].rstrip() + "\n" + row + "\n" + text[end:]
        gap.write_text(text, encoding="utf-8")
        return {"result": "PASS", "feedback_id": item["id"], "gap_task_id": task, "route": route, "idempotent": False}


def interactive_confirmation(prompt: str, expected: str):
    if not sys.stdin.isatty():
        raise ReviewError("needs_human: local interactive TTY confirmation required", "BLOCKED")
    print(prompt, file=sys.stderr)
    print(f"Type {expected!r} to confirm: ", file=sys.stderr, end="", flush=True)
    if sys.stdin.readline().strip() != expected:
        raise ReviewError("Human confirmation deferred", "BLOCKED")


def confirm_spec(project: Path, frontend_event_id: str | None = None) -> dict:
    from append_stage_event import append_event
    project = project_path(project)
    with OperationLock(project):
        spec = extract_spec(project)
        if frontend_event_id is not None:
            approval = consume_registered_frontend_approval(project, frontend_event_id, spec)
            event = append_event(
                project, "gdd",
                {"tag": spec["tag"], "spec_digest": spec["spec_digest"],
                 "git_spec_ref": spec_git_ref(spec, project)},
                decision_provenance=approval["provenance"],
            )
            return {"result": "PASS", "event": event}
        interactive_confirmation(f"Confirm the current GDD and PLAN are consistent and these exact requirements/platforms are approved:\n{spec['text']['PLAN.md']}", spec["spec_digest"])
        if extract_spec(project)["spec_digest"] != spec["spec_digest"]:
            raise ReviewError("Specification changed during confirmation", "BLOCKED")
        event = append_event(project, "gdd", {"tag": spec["tag"], "spec_digest": spec["spec_digest"]}, decision_provenance={"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"})
        return {"result": "PASS", "event": event}


def decision(project: Path, run_id: str, choice: str, profiles: list[str]) -> dict:
    from append_stage_event import append_event
    project = project_path(project)
    with OperationLock(project):
        manifest = load_json(safe_child(_run_path(project, run_id), "manifest.json"))
        if choice == "accept":
            checked = gate(project, run_id, require_accept=False, locked=True)
            if checked["result"] != "PASS":
                return checked
            required = {profile["name"] for profile in manifest["profiles"]}
            if not required.issubset(set(profiles)):
                raise ReviewError("needs_human: explicitly review all required profiles", "BLOCKED")
        interactive_confirmation(f"Decision {choice} for {run_id}. Confirm you actually reviewed the required platform/visible experience: {profiles}. Headless tests do not prove them.", run_id)
        if choice == "accept":
            rechecked = gate(project, run_id, require_accept=False, locked=True)
            if rechecked["result"] != "PASS":
                return rechecked
        fields = {key: manifest[key] for key in ("tag", "run_id", "spec_digest", "source_digest", "test_digest")}
        fields.update(decision=choice, evidence_ref=f".godotmaker/runs/{run_id}/manifest.json", reviewed_profiles=profiles)
        binding = safe_child(_run_path(project, run_id), "evaluation-binding.json")
        if binding.is_file():
            fields["evaluation_digest"] = load_json(binding)["evaluation_digest"]
        event = append_event(project, "accept", fields, decision_provenance={"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"})
        return {"result": "PASS", "event": event}


def resolve_feedback(project: Path, run_id: str, feedback_id: str) -> dict:
    from append_stage_event import append_event
    project = project_path(project)
    with OperationLock(project):
        run = _run_path(project, run_id)
        manifest = load_json(safe_child(run, "manifest.json"))
        item = load_json(safe_child(project, f".godotmaker/feedback/{feedback_id}.json"))
        if manifest.get("result") != "PASS" or not _gap_verified(project, item["gap_task_id"]):
            raise ReviewError("Feedback requires current PASS evidence and original GAP verified task", "BLOCKED")
        spec = extract_spec(project)
        source, tests = inventory(project)
        if any(manifest[key] != value for key, value in {"source_digest": manifest_digest(source), "test_digest": runner_digest(project, tests), "spec_digest": spec["spec_digest"]}.items()):
            raise ReviewError("Feedback resolution evidence is stale", "BLOCKED")
        interactive_confirmation(f"Confirm feedback {feedback_id} was addressed in {run_id}: {item['text']}", feedback_id)
        fields = {"tag": manifest["tag"], "feedback_id": feedback_id, "resolved_run_id": run_id, "resolution": "verified", **{key: manifest[key] for key in ("spec_digest", "source_digest", "test_digest")}}
        event = append_event(project, "fixgap", fields, decision_provenance={"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"})
        return {"result": "PASS", "event": event}


def play(project: Path, run_id: str, *, timeout: float = 3600) -> dict:
    project = project_path(project)
    with OperationLock(project):
        run = _run_path(project, run_id)
        manifest = load_json(safe_child(run, "manifest.json"))
        snapshot = run / "project"
        if inventory(snapshot) != (manifest.get("source_files"), manifest.get("test_files")) or snapshot_auxiliary(snapshot) != manifest.get("snapshot_auxiliary"):
            raise ReviewError("Snapshot drift; refusing preview", "BLOCKED")
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.name == "nt" or sys.platform == "darwin"):
            raise ReviewError("Native display unavailable; headless is not a substitute for visual play", "BLOCKED")
        preview = run / ("preview-" + uuid.uuid4().hex[:10])
        preview.mkdir()
        # Do not block later editing after the snapshot has been validated.
        binary = manifest["environment"]["godot_path"]
        if digest_file(Path(binary)) != manifest["environment"]["godot_git_identity"]:
            raise ReviewError("Godot binary differs from checked environment", "BLOCKED")
    command = execute([binary, "--path", str(snapshot)], snapshot, preview, "native-play", timeout, env=isolated_env(preview))
    drifted = inventory(snapshot) != (manifest["source_files"], manifest["test_files"]) or snapshot_auxiliary(snapshot) != manifest.get("snapshot_auxiliary")
    result = {"result": "ERROR" if command["timed_out"] or command["orphaned_children"] or drifted or command["exit_code"] != 0 else "PASS", "run_id": run_id, "command": "play", "process": command, "input_drift": drifted, "meaning": "Window process completed; this is not user acceptance", "not_proven": NOT_PROVEN}
    write_json(preview / "session.json", result, exclusive=True)
    return result


def recover_lock(project: Path) -> dict:
    """Explicit dead-owner recovery; never kill/adopt an unknown writer."""
    project = project_path(project)
    path = safe_child(project, ".godotmaker/run.lock")
    data = load_json(path)
    fingerprint = digest_file(path)
    if data.get("host") != platform.node():
        raise ReviewError("Lock host differs/unknown; writer status cannot be established", "BLOCKED")
    pids = [data.get("pid"), *data.get("children", [])]
    for pid in pids:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ReviewError("Lock process identity is invalid/unknown", "BLOCKED")
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise ReviewError("Cannot establish previous writer status", "BLOCKED") from exc
        else:
            raise ReviewError(f"Process {pid} is still present; stop it through its owning session", "BLOCKED")
    interactive_confirmation("All recorded local PIDs are absent. Confirm no unrecorded writer remains; this only removes the lock and never reruns work.", "recover")
    if digest_file(path) != fingerprint:
        raise ReviewError("Lock changed during recovery", "BLOCKED")
    path.unlink()
    return {"result": "PASS", "command": "recover-lock", "restarted": False}


def _evaluation_issues(project: Path, run: Path, report: dict, *, require_approve: bool) -> list[str]:
    """Reuse the original playable-unit contract, then bind its evidence paths."""
    manifest = load_json(safe_child(run, "manifest.json"))
    issues = []
    for key in ("tag", "run_id", "spec_digest", "source_digest", "test_digest"):
        if report.get(key) != manifest.get(key):
            issues.append(f"Evaluation {key} is unbound/stale")
    if report.get("review_kind") not in {"self_review", "independent_review"}:
        issues.append("Evaluation must disclose self_review or independent_review")
    if report.get("review_kind") == "independent_review" and not report.get("reviewer_ref"):
        issues.append("Independent review needs a reviewer reference")
    if require_approve and report.get("result") != "approve":
        issues.append("Original evaluator has not approved this run")
    rows = report.get("playable_unit", {}).get("rows", {})
    if not isinstance(rows, dict):
        return issues + ["Evaluation playable_unit.rows is invalid"]
    for value in rows.values():
        if not isinstance(value, dict):
            issues.append("Invalid evaluator row")
            continue
        test = value.get("test")
        if not isinstance(test, str) or test not in manifest.get("test_files", {}) or not test.startswith("e2e/"):
            issues.append("Evaluation row test must be part of the executed snapshot")
        else:
            safe_child(run / "project", test)
    hook_roots = (Path(__file__).parent.parent / "hooks", project / ".godotmaker/hooks")
    hooks = next((path for path in hook_roots if (path / "playability_contract.py").is_file()), None)
    if hooks is None:
        return issues + ["Original playability contract helper is unavailable"]
    # The original validator resolves test references relative to cwd.
    script = "import json,sys; from playability_contract import check_evaluation_playable_unit_complete as check; print(json.dumps(check(sys.argv[1],sys.argv[2])))"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(hooks)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    checked = subprocess.run([sys.executable, "-c", script, str(run / "project/PLAN.md"), str(project / ".godotmaker/evaluation.json")], cwd=run / "project", env=environment, capture_output=True, text=True, timeout=10)
    if checked.returncode != 0:
        issues.append("Original playable-unit validator failed: " + checked.stderr[-1000:])
    else:
        observed = strict_json(checked.stdout)
        if not isinstance(observed, list):
            issues.append("Invalid original validator result")
        else:
            issues.extend(str(item) for item in observed)
    if report.get("result") == "approve":
        plan = manifest["specification"]["PLAN.md"]
        for heading, field in (("Tag Mechanics", "tag_mechanics"), ("Inherited Mechanics", "inherited_mechanics")):
            expected = set(re.findall(r"\[(v\d+\.\d+\.\d+-M\d+)\]", plan.get(heading, "")))
            actual = report.get(field, {})
            if not isinstance(actual, dict) or set(actual) != expected or any(value != "pass" for value in actual.values()):
                issues.append(f"Original {field} coverage missing/failing")
        for name in ("builds_clean", "boots_main_scene", "playable_unit_coverage", "completion_fail_or_exit_reached"):
            if report.get("playable_closed_loop", {}).get(name) is not True:
                issues.append(f"Original closed-loop requirement not met: {name}")
        for field in ("critical_issues", "orphan_tests"):
            if report.get(field) != []:
                issues.append(f"Original evaluator {field} unresolved/missing")
        e2e = report.get("e2e_tests", {})
        if not isinstance(e2e.get("total"), int) or e2e.get("total", 0) <= 0 or e2e.get("passed") != e2e.get("total") or e2e.get("failed") != 0:
            issues.append("Original evaluator E2E counts are not all passing")
        if e2e.get("total") != manifest.get("suites", {}).get("e2e", {}).get("cases"):
            issues.append("Original evaluator E2E count differs from executed suite")
        phase4 = report.get("phase4_review")
        if not isinstance(phase4, list) or not phase4 or any(not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("category", "verdict")) for item in phase4):
            issues.append("Original Phase 4 experience review must contain concrete category/verdict records")
        visuals = report.get("visual_checks")
        expected_scenes = set(re.findall(r"(?m)^## Scene: (.+)$", manifest["specification"].get("SCENES.md", "")))
        if not expected_scenes or not isinstance(visuals, dict) or set(visuals) != expected_scenes:
            issues.append("Original visual checks must cover every explicit SCENES.md scene")
        if not isinstance(visuals, dict) or not visuals:
            issues.append("Original required visual evidence is missing; headless cannot replace it")
        else:
            for scene, visual in visuals.items():
                if not isinstance(visual, dict) or visual.get("result") not in {"pass", "warning"}:
                    issues.append(f"Original visual check not passing: {scene}")
                    continue
                captures = visual.get("captures") or [visual.get("screenshot")]
                if not captures or not isinstance(captures, list):
                    issues.append(f"Visual capture list missing: {scene}")
                    continue
                for relative in [*captures, visual.get("vqa_log")]:
                    if not isinstance(relative, str) or not relative.startswith("e2e/screenshots/") or not safe_child(project, relative).is_file():
                        issues.append(f"Actual visual evidence missing or out of scope: {scene}")
                if not isinstance(visual.get("vqa_calls"), list) or not visual["vqa_calls"]:
                    issues.append(f"Visual inspection record missing: {scene}")
                else:
                    for call in visual["vqa_calls"]:
                        strings = ("ts", "mode", "backend", "model", "log", "context", "verdict", "output_summary")
                        if not isinstance(call, dict) or any(not isinstance(call.get(key), str) or not call[key].strip() for key in strings):
                            issues.append(f"Malformed visual invocation record: {scene}")
                            continue
                        try:
                            timestamp = dt.datetime.fromisoformat(call["ts"].replace("Z", "+00:00"))
                            if timestamp.tzinfo is None:
                                raise ValueError("timezone required")
                        except ValueError:
                            issues.append(f"Invalid visual invocation timestamp: {scene}")
                        if call["mode"] != "question" or call["backend"] not in {"native", "codex", "gemini", "openai"} or call["verdict"] not in {"pass", "fail", "warning"}:
                            issues.append(f"Unsupported visual invocation result/backend/mode: {scene}")
                        files = call.get("files")
                        if not isinstance(files, list) or not files or any(not isinstance(item, str) or item not in captures for item in files) or call["log"] != visual.get("vqa_log"):
                            issues.append(f"Visual invocation files/log differ from captures: {scene}")
                        if call["verdict"] == "fail" and visual["result"] in {"pass", "warning"} and not visual.get("notes"):
                            issues.append(f"Visual verdict override needs recorded justification: {scene}")
    return issues


def bind_evaluation(project: Path, run_id: str) -> dict:
    """Bind an existing evaluator report; never perform or invent visual review."""
    from append_stage_event import append_event
    project = project_path(project)
    with OperationLock(project):
        run = _run_path(project, run_id)
        manifest = load_json(safe_child(run, "manifest.json"))
        spec = extract_spec(project)
        source, tests = inventory(project)
        if manifest.get("spec_digest") != spec["spec_digest"] or manifest.get("source_digest") != manifest_digest(source) or manifest.get("test_digest") != runner_digest(project, tests):
            raise ReviewError("Evaluator inputs changed; run checks again", "BLOCKED")
        path = safe_child(project, ".godotmaker/evaluation.json")
        report = load_json(path)
        if not isinstance(report, dict):
            raise ReviewError("Invalid evaluation object")
        issues = _evaluation_issues(project, run, report, require_approve=False)
        if issues:
            raise ReviewError("; ".join(issues), "BLOCKED")
        report_digest = digest_file(path)
        binding_path = safe_child(run, "evaluation-binding.json")
        if binding_path.exists():
            binding = load_json(binding_path)
            if binding.get("evaluation_digest") != report_digest:
                raise ReviewError("Evaluation binding is immutable; create a fresh checked run for a new report", "BLOCKED")
            return {"result": "PASS", "command": "bind-evaluation", "run_id": run_id, "idempotent": True}
        fields = {key: manifest[key] for key in ("tag", "run_id", "spec_digest", "source_digest", "test_digest")}
        fields.update(evidence_ref=".godotmaker/evaluation.json", evaluation_digest=report_digest)
        previous = [event for event in read_events(project) if event.get("role") == "evaluate"]
        if previous and all(previous[-1].get(key) == value for key, value in fields.items()):
            event = previous[-1]
        else:
            event = append_event(project, "evaluate", fields)
        archive = load_json(safe_child(project, ".godotmaker/evaluation-runs/latest.json"))
        report_ref = archive.get("evaluation_json")
        if not isinstance(report_ref, str) or digest_file(safe_child(project, report_ref)) != report_digest:
            raise ReviewError("Original evaluation archive differs from bound report")
        evidence = {report_ref: report_digest}
        for visual in report.get("visual_checks", {}).values():
            if not isinstance(visual, dict):
                continue
            for original in [*(visual.get("captures") or [visual.get("screenshot")]), visual.get("vqa_log")]:
                if not isinstance(original, str) or not original.startswith("e2e/screenshots/"):
                    continue
                relative = archive["screenshots_path"] + "/" + original.removeprefix("e2e/screenshots/")
                evidence[relative] = digest_file(safe_child(project, relative))
        binding = {"schema_version": 1, **fields, "report_ref": report_ref, "evidence": evidence, "evaluate_event": event, "bound_at": now()}
        write_json(binding_path, binding, exclusive=True)
        (run / "evaluation-binding.git").write_text(digest_file(binding_path) + "\n", encoding="ascii")
        return {"result": "PASS", "command": "bind-evaluation", "run_id": run_id, "evaluation_digest": report_digest, "evaluation_result": report["result"], "idempotent": False}


def evaluation_gate_issues(project: Path, run: Path, manifest: dict) -> tuple[list[str], str | None]:
    binding_path = safe_child(run, "evaluation-binding.json")
    identity_record = safe_child(run, "evaluation-binding.git")
    if not binding_path.is_file() or not identity_record.is_file():
        return ["Original gm-evaluate report has not been bound to this run"], None
    if identity_record.read_text(encoding="ascii").strip() != digest_file(binding_path):
        return ["Evaluation binding drift"], None
    binding = load_json(binding_path)
    issues = []
    for key in ("run_id", "tag", "spec_digest", "source_digest", "test_digest"):
        if binding.get(key) != manifest.get(key):
            issues.append("Evaluation binding differs from checked inputs")
    for relative, expected in binding.get("evidence", {}).items():
        path = safe_child(project, relative)
        if not path.is_file() or digest_file(path) != expected:
            issues.append(f"Original evaluation evidence drift: {relative}")
    current = safe_child(project, ".godotmaker/evaluation.json")
    if not current.is_file() or digest_file(current) != binding.get("evaluation_digest"):
        return issues + ["Latest evaluator report differs from bound evidence"], binding.get("evaluation_digest")
    events = [event for event in read_events(project) if event.get("role") == "evaluate"]
    if not events or events[-1] != binding.get("evaluate_event"):
        issues.append("Latest evaluator stage does not match this run")
    issues.extend(_evaluation_issues(project, run, load_json(current), require_approve=True))
    return issues, binding.get("evaluation_digest")
