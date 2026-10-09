#!/usr/bin/env python3
"""Run the existing /gm-verify checklist with evidence-backed v2 results.

Exit status is the verification result: PASS=0, FAIL=1, BLOCKED=2, ERROR=3.
A disabled optional check is skipped. A missing prerequisite or zero/ skipped
required tests blocks verification; a failed invocation is not an assertion.
The JSON on stdout preserves raw diagnostics and is written verbatim by gm-verify.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from agent_runtime import (
    godot_log_file, prefer_console_godot_path, read_godot_path,
)
from godot_output import classify_godot_headless_output

STATIC_CHECK_FLAGS = ["--build", "--ecs", "--tests", "--plan", "--mcp"]
BUILD_TIMEOUT = 60
UNIT_TIMEOUT = 600
STATIC_TIMEOUT = 60
STATUS_EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "ERROR": 3}
REQUIRED_CHECKS = ("build", "unit_tests", "static_check")
CHECK_ARRAYS = {"build": "errors", "unit_tests": "failures", "lint": "issues",
                "static_check": "issues"}


def _resolve_project_path(arg: str | None) -> Path:
    return Path(arg).resolve() if arg else Path.cwd()


def _now_iso_utc() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tooling_note(tool: str, crashed_on: str, error: str,
                  fallback: str = "escalate") -> dict:
    return {"tool": tool, "crashed_on": crashed_on, "error": error,
            "suggested_fallback": fallback, "narrowed_command": None,
            "rule_name": None, "check_name": None}


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        # taskkill is a Windows system utility, not downloaded software.
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _run_process(cmd: list[str], *, cwd: str, timeout: float):
    """Bound the whole process group, including the static check's Godot child."""
    kwargs = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", **kwargs)
    previous_handlers = {}

    def interrupted(signum, frame):
        # The caller may cancel run_verify before this check's own timeout.
        # Unwind through BaseException cleanup so its separate group cannot leak.
        raise SystemExit(3)

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, interrupted)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
        except BaseException:
            _kill_process_tree(proc)
            proc.communicate()
            raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _execute(cmd: list[str], project_dir: Path, timeout: float) -> dict:
    evidence = {"command": cmd, "cwd": str(project_dir.resolve()),
                "timeout_seconds": timeout, "returncode": None,
                "stdout": "", "stderr": "", "timed_out": False,
                "started_at": _now_iso_utc()}
    started = time.monotonic()
    try:
        proc = _run_process(cmd, cwd=evidence["cwd"], timeout=timeout)
        evidence.update(returncode=proc.returncode, stdout=_text(proc.stdout),
                        stderr=_text(proc.stderr))
    except subprocess.TimeoutExpired as exc:
        evidence.update(timed_out=True, stdout=_text(exc.output),
                        stderr=_text(exc.stderr), error=f"timed out after {timeout}s")
    except FileNotFoundError as exc:
        evidence.update(missing_dependency=True, error=str(exc))
    except OSError as exc:
        evidence["error"] = str(exc)
    evidence["duration_seconds"] = round(time.monotonic() - started, 6)
    return evidence


def _empty(name: str, result: str, reason: str = "", execution=None) -> dict:
    body = {"result": result, "required": name in REQUIRED_CHECKS,
            CHECK_ARRAYS[name]: []}
    if name == "unit_tests":
        body.update(total=0, passed=0, failed=0, skipped=0)
    if name == "lint":
        body["format_drift"] = None
    if reason:
        body["reason"] = reason
    if execution is not None:
        body["execution"] = execution
    return body


def _problem(name: str, tool: str, reason: str, *, result="error",
             execution=None, location="<prerequisite>") -> tuple[dict, dict]:
    return (_empty(name, result, reason, execution),
            _tooling_note(tool, location, reason))


def _execution_problem(name: str, tool: str, execution: dict):
    if "error" not in execution:
        return None
    return _problem(name, tool, execution["error"], execution=execution,
                    result="blocked" if execution.get("missing_dependency") else "error",
                    location=execution["command"][0])


def check_build(godot_path: str, project_dir: Path) -> tuple[dict, dict | None]:
    if not (project_dir / "project.godot").is_file():
        return _problem("build", "godot", "project.godot is missing", result="blocked")
    command = [godot_path, "--headless", "--path", str(project_dir),
               "--log-file", godot_log_file(project_dir, "build"), "--quit"]
    execution = _execute(command, project_dir, BUILD_TIMEOUT)
    problem = _execution_problem("build", "godot", execution)
    if problem:
        return problem
    combined = execution["stdout"] + execution["stderr"]
    # The classifier's synthetic nonzero diagnostic is not a project assertion.
    classified = classify_godot_headless_output(combined, returncode=0)
    body = _empty("build", "pass", execution=execution)
    body["errors"] = [{"file": item.file, "line": item.line,
                       "message": item.message} for item in classified.blockers]
    if body["errors"]:
        body["result"] = "fail"
    elif execution["returncode"] != 0:
        return _problem("build", "godot", f"godot exited with code {execution['returncode']} "
                        "without a recognized blocking diagnostic", execution=execution)
    elif not re.search(r"Godot Engine|Setting Up MainLoop", combined):
        return _problem("build", "godot", "missing Godot startup diagnostics; exit 0 alone "
                        "does not prove a headless build", execution=execution)
    if classified.shutdown_notes:
        body["warnings"] = classified.shutdown_notes
    return body, None


_GDUNIT_SUMMARY_CASES = re.compile(
    r"(\d+)\s+test\s*cases?\s*\|\s*(\d+)\s+errors?\s*\|\s*(\d+)\s+failures?", re.I)
_GDUNIT_OVERALL_SUMMARY_CASES = re.compile(
    r"Overall\s+Summary:\s*(\d+)\s+test\s*cases?\s*\|\s*(\d+)\s+errors?\s*\|\s*(\d+)\s+failures?", re.I)
_GDUNIT_SUMMARY_PF = re.compile(r"Tests?\s+Passed:\s*(\d+).*?Tests?\s+Failed:\s*(\d+)", re.I | re.S)
_GDUNIT_FAILURE = re.compile(r"^\s*FAILED:\s*(.+?)\s+-\s+(.+)$", re.M)
_GDUNIT_ORPHAN_WARNING = re.compile(r"Found\s+\d+\s+possible\s+orphan\s+nodes?\.?", re.I)


def _gdunit_warning_messages(combined: str, returncode: int) -> list[str]:
    warnings = list(dict.fromkeys(m.group(0).strip()
                                 for m in _GDUNIT_ORPHAN_WARNING.finditer(combined)))
    if returncode == 101 and not warnings:
        warnings.append("gdUnit exited with warning code 101")
    return warnings


def _int_attr(element: ET.Element, name: str, default=0) -> int:
    value = element.attrib.get(name, str(default))
    if not re.fullmatch(r"\d+", value):
        raise ValueError(f"invalid {name} count: {value!r}")
    return int(value)


def _failure_message(node: ET.Element) -> str:
    message = (node.attrib.get("message") or "").strip()
    detail = " ".join((node.text or "").split())
    return f"{message}: {detail}" if message and detail and detail not in message else message or detail or node.tag


def _parse_gdunit_xml(results_xml: Path) -> dict:
    return _parse_gdunit_root(ET.parse(results_xml).getroot())


def _parse_gdunit_root(root: ET.Element) -> dict:
    if root.tag not in {"testsuites", "testsuite"} or "tests" not in root.attrib:
        raise ValueError("expected JUnit testsuites/testsuite with test counters")
    total = _int_attr(root, "tests")
    failures = _int_attr(root, "failures")
    errors = _int_attr(root, "errors", sum(_int_attr(s, "errors") for s in root if s.tag == "testsuite"))
    skipped = _int_attr(root, "skipped", sum(_int_attr(s, "skipped") for s in root if s.tag == "testsuite"))
    failed = failures + errors
    if failed + skipped > total:
        raise ValueError("JUnit failed + skipped counts exceed total")
    cases = list(root.iter("testcase"))
    if len(cases) != total:
        raise ValueError(f"JUnit declared {total} tests but contains {len(cases)} testcase records")
    observed = {"failure": 0, "error": 0, "skipped": 0}
    entries = []
    for case in cases:
        outcomes = [c for c in case if c.tag in observed]
        if len(outcomes) > 1:
            raise ValueError("JUnit testcase has contradictory outcomes")
        for child in outcomes:
            observed[child.tag] += 1
            if child.tag != "skipped":
                name = case.attrib.get("name", "").strip()
                cls = case.attrib.get("classname", "").strip()
                entries.append({"test": f"{cls}::{name}" if cls else name,
                                "message": _failure_message(child)})
    if (observed["failure"], observed["error"], observed["skipped"]) != (failures, errors, skipped):
        raise ValueError("JUnit counters contradict testcase outcomes")
    result = "blocked" if not total or skipped else "fail" if failed else "pass"
    body = _empty("unit_tests", result)
    body.update(total=total, passed=total - failed - skipped, failed=failed,
                skipped=skipped, failures=entries)
    if result == "blocked":
        body["reason"] = "zero required test cases" if not total else "required test cases were skipped"
    return body


def _find_gdunit_results_xml(report_dir: Path) -> Path | None:
    matches = list(report_dir.rglob("results.xml"))
    if len(matches) > 1:
        raise ValueError("multiple gdUnit results.xml reports in one isolated run")
    return matches[0] if matches else None


def _parse_gdunit_stdout(combined: str, returncode: int) -> dict | None:
    """Diagnostic compatibility parser; stdout never substitutes for the XML."""
    m = _GDUNIT_OVERALL_SUMMARY_CASES.search(combined)
    if not m:
        matches = list(_GDUNIT_SUMMARY_CASES.finditer(combined))
        m = matches[-1] if matches else None
    if m:
        total, errors, failures = map(int, m.groups())
        return {"total": total, "failed": errors + failures}
    m = _GDUNIT_SUMMARY_PF.search(combined)
    if m:
        passed, failed = map(int, m.groups())
        return {"total": passed + failed, "failed": failed}
    return None


def check_unit_tests(godot_path: str, project_dir: Path) -> tuple[dict, dict | None]:
    addon = project_dir / "addons/gdUnit4/bin/GdUnitCmdTool.gd"
    if not addon.is_file():
        return _problem("unit_tests", "gdunit", "gdUnit4 runner dependency is missing",
                        result="blocked", location=str(addon))
    if not (project_dir / "test").is_dir():
        return _problem("unit_tests", "gdunit", "required test/ directory is missing",
                        result="blocked")
    with tempfile.TemporaryDirectory(prefix="godotmaker-gdunit-") as report_dir:
        command = [godot_path, "--headless", "--path", str(project_dir),
                   "--log-file", godot_log_file(project_dir, "gdunit"),
                   "-s", "res://addons/gdUnit4/bin/GdUnitCmdTool.gd", "--ignoreHeadlessMode",
                   "--add", "res://test/", "--report-directory", report_dir]
        execution = _execute(command, project_dir, UNIT_TIMEOUT)
        problem = _execution_problem("unit_tests", "gdunit", execution)
        if problem:
            return problem
        combined = execution["stdout"] + execution["stderr"]
        try:
            results_xml = _find_gdunit_results_xml(Path(report_dir))
            if results_xml is None:
                raise ValueError("missing gdUnit4 XML report (stdout alone is not verification)")
            # Preserve the report before its temporary directory is removed.
            execution["report_xml"] = results_xml.read_text(encoding="utf-8")
            parsed = _parse_gdunit_xml(results_xml)
        except (OSError, UnicodeError, ET.ParseError, ValueError) as exc:
            return _problem("unit_tests", "gdunit", f"could not parse gdUnit4 XML report: {exc}",
                            execution=execution)
        parsed["execution"] = execution
        rc = execution["returncode"]
        # gdUnit assertion exits may be 1 or 100; 101 is warnings only.
        if (parsed["failed"] and rc not in (1, 100)) or (not parsed["failed"] and rc not in (0, 101)):
            return _problem("unit_tests", "gdunit", f"gdUnit exited with code {rc} "
                            "inconsistent with XML test outcomes", execution=execution)
        # Per-suite stdout is not an overall report; only compare explicit overall totals.
        if _GDUNIT_OVERALL_SUMMARY_CASES.search(combined) or _GDUNIT_SUMMARY_PF.search(combined):
            summary = _parse_gdunit_stdout(combined, rc)
            if summary and (summary["total"] != parsed["total"] or summary["failed"] != parsed["failed"]):
                return _problem("unit_tests", "gdunit", "stdout summary contradicts XML report",
                                execution=execution)
        warnings = _gdunit_warning_messages(combined, rc)
        if warnings:
            parsed["warnings"] = warnings
        if parsed["result"] == "blocked":
            return parsed, _tooling_note("gdunit", "res://test/", parsed["reason"])
        return parsed, None


def check_lint() -> dict:
    return _empty("lint", "skipped", "gdtoolkit is disabled (optional lint)")


_STATIC_LINE = re.compile(r"^\[(PASS|FAIL|WARN)\]\s+(.+)$", re.M)
_STATIC_DEPENDENCY = re.compile(r"addon.*(?:not found|missing)|addons/.*missing|godot_path missing|"
                                r"godot executable not found|git executable not found", re.I)
_STATIC_SKIP = re.compile(r"skipping|skipped|cannot check", re.I)
_STATIC_ERROR = re.compile(r"timed out|did not finish within|without a recognized blocking diagnostic", re.I)


def check_static(project_dir: Path) -> tuple[dict, dict | None]:
    script = Path(__file__).parent / "check_project.py"
    if not script.is_file():
        return _problem("static_check", "check_project", "check_project.py not found alongside run_verify.py",
                        result="blocked", location=str(script))
    cmd = [sys.executable, str(script), str(project_dir)] + STATIC_CHECK_FLAGS
    execution = _execute(cmd, project_dir, STATIC_TIMEOUT)
    problem = _execution_problem("static_check", "check_project", execution)
    if problem:
        return problem
    combined = execution["stdout"] + execution["stderr"]
    lines = _STATIC_LINE.findall(combined)
    if not lines:
        return _problem("static_check", "check_project", "missing static check results; "
                        f"exited with code {execution['returncode']}: {combined}", execution=execution)
    body = _empty("static_check", "pass", execution=execution)
    blocked = []
    errors = []
    for status, detail in lines:
        if _STATIC_ERROR.search(detail):
            errors.append(detail)
        elif _STATIC_DEPENDENCY.search(detail) or (status == "WARN" and _STATIC_SKIP.search(detail)):
            blocked.append(detail)
        elif status == "FAIL":
            name, separator, rest = detail.partition(":")
            body["issues"].append({"check": name.strip() if separator else "static_check",
                                   "detail": rest.strip() if separator else detail})
    failed_lines = any(status == "FAIL" for status, _ in lines)
    if execution["returncode"] not in (0, 1) or (execution["returncode"] == 1) != failed_lines:
        errors.append(f"exit code {execution['returncode']} contradicts static check results")
    if errors or blocked:
        body["result"] = "error" if errors else "blocked"
        body["reason"] = "; ".join(errors or blocked)
        return body, _tooling_note("check_project", str(project_dir), body["reason"])
    if body["issues"]:
        body["result"] = "fail"
    body["assertions"] = len([item for item in lines if item[0] in ("PASS", "FAIL")])
    if not body["assertions"]:
        body["result"] = "blocked"
        body["reason"] = "zero required static assertions"
        return body, _tooling_note("check_project", str(project_dir), body["reason"])
    return body, None


def _overall(checks: dict) -> str:
    results = {body.get("result") if isinstance(body.get("result"), str) else "error"
               for body in checks.values() if isinstance(body, dict)}
    for status in ("error", "blocked", "fail"):
        if status in results:
            return status.upper()
    if any(isinstance(checks.get(name), dict) and checks[name].get("result") == "skipped" for name in REQUIRED_CHECKS):
        return "BLOCKED"
    return "PASS"


def build_report(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    godot_path = prefer_console_godot_path(read_godot_path(project_dir, default="godot"))
    build, build_note = check_build(godot_path, project_dir)
    unit, unit_note = check_unit_tests(godot_path, project_dir)
    static, static_note = check_static(project_dir)
    checks = {"build": build, "unit_tests": unit, "lint": check_lint(), "static_check": static}
    status = _overall(checks)
    return {"schema_version": 2, "status": status, "result": status.lower(),
            "exit_code": STATUS_EXIT_CODES[status], "ts": _now_iso_utc(),
            "provenance": {"kind": "local_execution", "producer": "run_verify.py"},
            "checks": checks, "tooling_notes": [n for n in (build_note, unit_note, static_note) if n]}


def validate_report(report: Any) -> list[str]:
    """Validate v2 evidence shape and cross-field invariants, never upgrade history."""
    if not isinstance(report, dict):
        return ["verify report must be a JSON object"]
    if type(report.get("schema_version")) is not int or report.get("schema_version") != 2:
        return ["legacy/unversioned verify report is unverified; run verification again"]
    issues = []
    status = report.get("status")
    if not isinstance(status, str) or status not in STATUS_EXIT_CODES:
        issues.append("status must be PASS, FAIL, BLOCKED or ERROR")
    elif (report.get("result") != status.lower() or type(report.get("exit_code")) is not int
          or report.get("exit_code") != STATUS_EXIT_CODES[status]):
        issues.append("result/status/exit_code are inconsistent")
    if not isinstance(report.get("ts"), str) or not report["ts"]:
        issues.append("ts is required")
    if report.get("provenance") != {"kind": "local_execution", "producer": "run_verify.py"}:
        issues.append("missing mechanical execution provenance")
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return issues + ["checks must be an object"]
    if set(checks) != set(CHECK_ARRAYS):
        issues.append("checks must contain exactly build, unit_tests, lint and static_check")
    for name, array in CHECK_ARRAYS.items():
        body = checks.get(name)
        if not isinstance(body, dict):
            issues.append(f"checks.{name} is required")
            continue
        result = body.get("result")
        if not isinstance(result, str) or result not in {"pass", "fail", "blocked", "error", "skipped"}:
            issues.append(f"checks.{name}.result is invalid")
        if body.get("required") is not (name in REQUIRED_CHECKS):
            issues.append(f"checks.{name}.required cannot relax the checklist")
        if not isinstance(body.get(array), list):
            issues.append(f"checks.{name}.{array} must be a list")
        if result == "skipped" and (not isinstance(body.get("reason"), str) or not body["reason"]):
            issues.append(f"checks.{name} skip requires a reason")
        if name == "lint" and result != "skipped":
            issues.append("disabled lint must be skipped, never passed")
        if isinstance(result, str) and result in {"pass", "fail"}:
            execution = body.get("execution")
            if not isinstance(execution, dict):
                issues.append(f"checks.{name} requires execution evidence")
            else:
                cmd = execution.get("command")
                if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
                    issues.append(f"checks.{name}.execution.command must be a nonempty argv array")
                for key in ("cwd", "stdout", "stderr"):
                    if not isinstance(execution.get(key), str):
                        issues.append(f"checks.{name}.execution.{key} must be a string")
                if not isinstance(execution.get("returncode"), int) or isinstance(execution.get("returncode"), bool):
                    issues.append(f"checks.{name}.execution.returncode must be an int")
                if execution.get("timed_out") is not False or execution.get("error"):
                    issues.append(f"checks.{name} cannot pass/fail a failed invocation")
                timeout = execution.get("timeout_seconds")
                if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
                    issues.append(f"checks.{name}.execution.timeout_seconds must be positive")
                if name == "unit_tests":
                    try:
                        parsed = _parse_gdunit_root(ET.fromstring(execution.get("report_xml", "")))
                        for key in ("result", "total", "passed", "failed", "skipped", "failures"):
                            if body.get(key) != parsed[key]:
                                issues.append(f"checks.unit_tests.{key} contradicts raw XML evidence")
                        rc = execution.get("returncode")
                        if (parsed["failed"] and rc not in (1, 100)) or (not parsed["failed"] and rc not in (0, 101)):
                            issues.append("checks.unit_tests exit code contradicts raw XML evidence")
                    except (ET.ParseError, ValueError, TypeError) as exc:
                        issues.append(f"checks.unit_tests requires valid raw XML evidence: {exc}")
                if result == "fail" and name == "build":
                    raw = _text(execution.get("stdout")) + _text(execution.get("stderr"))
                    blockers = classify_godot_headless_output(raw).blockers
                    expected = [{"file": item.file, "line": item.line, "message": item.message}
                                for item in blockers]
                    if not expected or body.get("errors") != expected:
                        issues.append("checks.build FAIL requires actual blocking diagnostics")
                if result == "fail" and name == "static_check":
                    raw = _text(execution.get("stdout")) + _text(execution.get("stderr"))
                    if execution.get("returncode") != 1 or not any(kind == "FAIL" for kind, _ in _STATIC_LINE.findall(raw)):
                        issues.append("checks.static_check FAIL requires actual assertion failures")
                if result == "pass" and name in {"build", "static_check"}:
                    raw = _text(execution.get("stdout")) + _text(execution.get("stderr"))
                    if execution.get("returncode") != 0:
                        issues.append(f"checks.{name} PASS requires exit 0")
                    if name == "build":
                        if classify_godot_headless_output(raw).blockers or not re.search(r"Godot Engine|Setting Up MainLoop", raw):
                            issues.append("checks.build PASS contradicts raw diagnostics")
                    else:
                        lines = _STATIC_LINE.findall(raw)
                        if not any(kind == "PASS" for kind, _ in lines) or any(
                            kind == "FAIL" or _STATIC_ERROR.search(detail) or _STATIC_DEPENDENCY.search(detail)
                            or (kind == "WARN" and _STATIC_SKIP.search(detail)) for kind, detail in lines
                        ):
                            issues.append("checks.static_check PASS contradicts raw diagnostics")
        if name == "unit_tests":
            counters = [body.get(key) for key in ("total", "passed", "failed", "skipped")]
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counters):
                issues.append("checks.unit_tests counters must be nonnegative integers")
            else:
                total, passed, failed, skipped = counters
                if passed + failed + skipped != total:
                    issues.append("checks.unit_tests counters are inconsistent")
                if result == "pass" and (not total or failed or skipped):
                    issues.append("checks.unit_tests PASS requires nonzero cases and no failures/skips")
                if result == "fail" and not failed:
                    issues.append("checks.unit_tests FAIL requires an actual failed test")
    if len(checks) == len(CHECK_ARRAYS) and set(checks) == set(CHECK_ARRAYS) and _overall(checks) != status:
        issues.append("overall status contradicts check results")
    notes = report.get("tooling_notes")
    if not isinstance(notes, list):
        issues.append("tooling_notes must be an array")
    else:
        if status == "PASS" and notes:
            issues.append("PASS requires empty tooling_notes")
        operands = {"exclude_file": "crashed_on", "scope_narrow": "narrowed_command",
                    "add_gdlintrc_rule": "rule_name", "skip_check": "check_name"}
        for index, note in enumerate(notes):
            if not isinstance(note, dict):
                issues.append(f"tooling_notes[{index}] must be an object")
                continue
            for field in ("tool", "crashed_on", "error", "suggested_fallback"):
                if not isinstance(note.get(field), str) or not note[field]:
                    issues.append(f"tooling_notes[{index}].{field} is required")
            fallback = note.get("suggested_fallback")
            operand = operands.get(fallback) if isinstance(fallback, str) else None
            if operand and not note.get(operand):
                issues.append(f"tooling_notes[{index}] requires {operand}; use escalate instead")
            if fallback == "skip_check" and note.get("check_name") in REQUIRED_CHECKS:
                issues.append("required checks cannot be disabled by a tooling fallback")
    return issues


def normalize_report(report: Any) -> dict:
    """Read-only compatibility: retain the original claim, never invent provenance."""
    if not isinstance(report, dict):
        return {"status": "ERROR", "result": "error", "exit_code": 3,
                "reported_status": None, "verification_state": "unverified",
                "validation_issues": ["verify report must be an object"]}
    normalized = copy.deepcopy(report)
    if report.get("schema_version") != 2:
        normalized["reported_status"] = report.get("reported_status", report.get("status", report.get("result")))
        normalized.update(status="BLOCKED", result="blocked", exit_code=2,
                          verification_state="unverified",
                          validation_issues=["legacy report is unverified; rerun run_verify.py"])
        return normalized
    issues = validate_report(report)
    if issues:
        normalized["reported_status"] = report.get("reported_status", report.get("status", report.get("result")))
        normalized.update(status="ERROR", result="error", exit_code=3,
                          verification_state="unverified", validation_issues=issues)
    return normalized


def _json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite JSON number: {value}")
    return number


def _json_constant(value: str):
    raise ValueError(f"non-standard JSON constant: {value}")


def load_report(path: str | Path) -> dict:
    try:
        return normalize_report(json.loads(
            Path(path).read_text(encoding="utf-8"), object_pairs_hook=_json_object,
            parse_float=_json_float, parse_constant=_json_constant,
        ))
    except (OSError, ValueError, UnicodeError) as exc:
        return {"status": "ERROR", "result": "error", "exit_code": 3,
                "verification_state": "unverified", "validation_issues": [str(exc)]}


def verification_issues(path: str | Path, require_pass: bool = True) -> list[str]:
    report = load_report(path)
    issues = list(report.get("validation_issues", []))
    if require_pass and report.get("status") != "PASS":
        issues.append(f"verification is {report.get('status', 'ERROR')}; a fresh v2 PASS is required")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run /gm-verify checks and emit a v2 report")
    parser.add_argument("--project-path", default=None, help="project root (default: cwd)")
    args = parser.parse_args(argv)
    project_dir = _resolve_project_path(args.project_path)
    if not (project_dir / ".godotmaker").is_dir():
        print(f"error: {project_dir} is not a godotmaker project (.godotmaker/ missing)", file=sys.stderr)
        return 2
    try:
        report = build_report(project_dir)
        json.dump(report, sys.stdout, indent=2, allow_nan=False)
        sys.stdout.write("\n")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: verification failed: {exc}", file=sys.stderr)
        return 3
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
