"""Tests for tools/run_verify.py — the mechanical /gm-verify runner.

Subprocess is mocked at the process-group wrapper (`run_verify._run_process`)
to avoid actually launching godot. The composed report is then validated
against `tests/test_verify_report_fixtures.validate_report` so producer
output stays pinned to the schema the build/fixgap consumers expect.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "run_verify.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _load_run_verify():
    spec = importlib.util.spec_from_file_location("run_verify_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_verify = _load_run_verify()

# Reuse the schema validator that pins the producer/consumer contract.
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_verify_report_fixtures import validate_report  # noqa: E402



def _legacy_fields(body):
    return {key: value for key, value in body.items() if key not in {
        "required", "execution", "reason", "total", "skipped", "assertions", "warnings",
    }}

def _make_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    p = MagicMock()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


def _write_gdunit_xml_from_cmd(cmd: list, xml: str) -> Path:
    report_dir = Path(cmd[cmd.index("--report-directory") + 1])
    results_xml = report_dir / "report_1" / "results.xml"
    results_xml.parent.mkdir(parents=True, exist_ok=True)
    results_xml.write_text(xml, encoding="utf-8")
    return results_xml


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".godotmaker").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "godotmaker.yaml").write_text(
        'godot_path: "/usr/bin/godot"\n'
    )
    (tmp_path / "project.godot").write_text("[application]\n")
    addon = tmp_path / "addons/gdUnit4/bin/GdUnitCmdTool.gd"
    addon.parent.mkdir(parents=True)
    addon.write_text("# test runner fixture\n")
    (tmp_path / "test").mkdir()
    return tmp_path


# ---------- build ----------

def test_check_build_pass(project_dir):
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout="Setting Up MainLoop...\nDone.\n")
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)
    assert _legacy_fields(result) == {"result": "pass", "errors": []}
    assert note is None


def test_check_build_fail_with_errors_and_locations(project_dir):
    output = (
        "ERROR: Parse Error: Identifier 'bar' not declared.\n"
        "   at: GDScript::reload (src/foo.gd:42)\n"
        "ERROR: Failed loading resource: res://scenes/main.tscn.\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)
    assert result["result"] == "fail"
    assert len(result["errors"]) == 2
    assert result["errors"][0]["file"] == "src/foo.gd"
    assert result["errors"][0]["line"] == 42
    assert "Identifier 'bar'" in result["errors"][0]["message"]
    # Second ERROR has no GDScript location → file empty, line 0
    assert result["errors"][1]["file"] == ""
    assert result["errors"][1]["line"] == 0
    assert note is None


def test_check_build_ignores_headless_shutdown_diagnostics(project_dir):
    output = "Godot Engine v4.5\nERROR: 7 resources still in use at exit (run with --verbose for details).\n"
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert _legacy_fields(result) == {"result": "pass", "errors": []}
    assert note is None


def test_check_build_ignores_headless_display_and_objectdb_noise(project_dir):
    output = (
        "Godot Engine v4.5\nERROR: Screen index 0 is invalid.\n"
        "ERROR: ObjectDB instances leaked at exit (run with --verbose for details).\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert _legacy_fields(result) == {"result": "pass", "errors": []}
    assert note is None


def test_check_build_engine_cpp_location_remains_blocking_without_file_pointer(project_dir):
    output = (
        "ERROR: Cannot open file 'res://bad_scene.tscn'.\n"
        "   at: load (scene/resources/resource_format_text.cpp:123)\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stderr=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "fail"
    assert result["errors"] == [{
        "file": "",
        "line": 0,
        "message": "Cannot open file 'res://bad_scene.tscn'.",
    }]
    assert note is None


def test_check_build_shutdown_note_plus_real_error_fails(project_dir):
    output = (
        "ERROR: 7 resources still in use at exit (run with --verbose for details).\n"
        "ERROR: Failed loading resource: res://scenes/main.tscn.\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "fail"
    assert result["errors"] == [{
        "file": "",
        "line": 0,
        "message": "Failed loading resource: res://scenes/main.tscn.",
    }]
    assert note is None


def test_check_build_shutdown_note_plus_nonzero_exit_fails(project_dir):
    output = "Godot Engine v4.5\nERROR: 7 resources still in use at exit (run with --verbose for details).\n"
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output, returncode=1)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "error"
    assert result["errors"] == []
    assert "without a recognized" in note["error"]


def test_check_build_script_error_still_fails(project_dir):
    output = (
        "SCRIPT ERROR: Parse Error: Identifier 'BirdController' not declared.\n"
        "   at: GDScript::reload (src/bird.gd:12)\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stderr=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "fail"
    assert result["errors"] == [{
        "file": "src/bird.gd",
        "line": 12,
        "message": "Parse Error: Identifier 'BirdController' not declared.",
    }]
    assert note is None


def test_check_build_unknown_error_with_zero_exit_fails(project_dir):
    output = "ERROR: Provider emitted an uncategorized runtime diagnostic.\n"
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stderr=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "fail"
    assert result["errors"] == [{
        "file": "",
        "line": 0,
        "message": "Provider emitted an uncategorized runtime diagnostic.",
    }]
    assert note is None


def test_check_build_shader_error_with_zero_exit_fails(project_dir):
    output = (
        "SHADER ERROR: Invalid shader code.\n"
        "   at: GDScript::reload (res://shaders/card.gdshader:3)\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stderr=output, returncode=0)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "fail"
    assert result["errors"] == [{
        "file": "res://shaders/card.gdshader",
        "line": 3,
        "message": "Invalid shader code.",
    }]
    assert note is None


def test_check_build_unknown_error_with_nonzero_exit_fails(project_dir):
    output = "ERROR: Provider emitted an uncategorized runtime diagnostic.\n"
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stderr=output, returncode=1)
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)

    assert result["result"] == "fail"
    assert result["errors"] == [{
        "file": "",
        "line": 0,
        "message": "Provider emitted an uncategorized runtime diagnostic.",
    }]
    assert note is None


def test_check_build_locations_are_scoped_to_each_error(project_dir):
    """A GDScript location after ERROR_B must not be attributed to ERROR_A."""
    output = (
        "ERROR: Cannot open file 'res://scenes/main.tscn'.\n"
        "ERROR: Parse Error.\n"
        "   at: GDScript::reload (src/bar.gd:7)\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output)
        result, _ = run_verify.check_build("/usr/bin/godot", project_dir)
    assert result["errors"][0]["file"] == ""
    assert result["errors"][0]["line"] == 0
    assert result["errors"][1]["file"] == "src/bar.gd"
    assert result["errors"][1]["line"] == 7


def test_check_build_timeout_returns_escalate(project_dir):
    with patch.object(
        run_verify, "_run_process",
        side_effect=subprocess.TimeoutExpired(cmd="godot", timeout=60),
    ):
        result, note = run_verify.check_build("/usr/bin/godot", project_dir)
    assert result["result"] == "error"
    assert result["errors"] == []
    assert note["tool"] == "godot"
    assert note["suggested_fallback"] == "escalate"


def test_check_build_missing_binary_returns_escalate(project_dir):
    with patch.object(
        run_verify, "_run_process", side_effect=FileNotFoundError("no godot"),
    ):
        result, note = run_verify.check_build("nope-godot", project_dir)
    assert result["result"] == "blocked"
    assert note["tool"] == "godot"
    assert note["crashed_on"] == "nope-godot"


def test_check_build_redirects_log_into_godotmaker_logs(project_dir: Path):
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout="Done.\n")
        run_verify.check_build("/usr/bin/godot", project_dir)
    cmd = run.call_args.args[0]
    assert "--log-file" in cmd
    log_path = Path(cmd[cmd.index("--log-file") + 1])
    assert log_path.parent == project_dir / ".godotmaker" / "logs"
    assert log_path.name.startswith("godot-build-")
    assert log_path.suffix == ".log"


# ---------- unit tests ----------

def _unit_xml(total=3, failed=0, skipped=0, errors=0):
    import xml.etree.ElementTree as ET
    root = ET.Element("testsuites", tests=str(total), failures=str(failed),
                      errors=str(errors), skipped=str(skipped))
    for index in range(total):
        case = ET.SubElement(root, "testcase", name=f"test_{index}", classname="suite")
        if index < failed:
            ET.SubElement(case, "failure", message="expected 10, got 0")
        elif index < failed + errors:
            ET.SubElement(case, "error", message="runtime exception")
        elif index < failed + errors + skipped:
            ET.SubElement(case, "skipped")
    return ET.tostring(root, encoding="unicode")


def _unit_run(xml, stdout="", returncode=0):
    def run(cmd, **kwargs):
        if xml is not None:
            _write_gdunit_xml_from_cmd(cmd, xml)
        return _make_proc(stdout=stdout, returncode=returncode)
    return run


def test_check_unit_tests_uses_official_gdunit_cmdtool_args(project_dir):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml())) as run:
        result, note = run_verify.check_unit_tests("/usr/bin/godot", project_dir)
    cmd = run.call_args.args[0]
    assert "res://addons/gdUnit4/bin/GdUnitCmdTool.gd" in cmd
    assert "--ignoreHeadlessMode" in cmd
    assert "--report-directory" in cmd
    assert cmd[cmd.index("--add") + 1] == "res://test/"
    assert run.call_args.kwargs["cwd"] == str(project_dir)
    assert run.call_args.kwargs["timeout"] == run_verify.UNIT_TIMEOUT
    assert Path(cmd[cmd.index("--log-file") + 1]).parent == project_dir / ".godotmaker/logs"
    assert result["result"] == "pass"
    assert result["passed"] == 3
    assert note is None
    assert result["execution"]["report_xml"] == _unit_xml()


@pytest.mark.parametrize("stdout", ["", "267 test cases | 0 errors | 0 failures", "Tests Passed: 274 | Tests Failed: 0"])
@pytest.mark.parametrize("rc", [0, 100])
def test_unit_stdout_never_substitutes_for_missing_xml(project_dir, stdout, rc):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(None, stdout, rc)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "error"
    assert result["failed"] == 0
    assert "missing" in note["error"]
    assert result["execution"]["stdout"] == stdout


@pytest.mark.parametrize("failed,errors,rc", [(1, 0, 100), (0, 1, 1)])
def test_unit_actual_failures_keep_details(project_dir, failed, errors, rc):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml(failed=failed, errors=errors), returncode=rc)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "fail"
    assert result["passed"] == 2
    assert result["failed"] == 1
    assert result["failures"][0]["test"] == "suite::test_0"
    assert note is None


@pytest.mark.parametrize("rc", [1, 100, 103, -9])
def test_unit_passing_xml_nonzero_is_error(project_dir, rc):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml(), returncode=rc)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "error"
    assert result["failed"] == 0
    assert "inconsistent" in note["error"]


def test_unit_failing_xml_zero_exit_is_error(project_dir):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml(failed=1))):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "error"
    assert "inconsistent" in note["error"]


def test_unit_orphan_warning_remains_nonblocking(project_dir):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml(), "Found 4 possible orphan nodes.", 101)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "pass"
    assert result["warnings"] == ["Found 4 possible orphan nodes."]
    assert note is None


@pytest.mark.parametrize("xml", ["<broken", '<testsuites tests="3" />', '<testsuites tests="NaN" />', '<not_a_report />', _unit_xml().replace('failures="0"', 'failures="5"')])
def test_corrupt_or_inconsistent_xml_is_error(project_dir, xml):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(xml)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "error"
    assert "could not parse" in note["error"]
    assert result["execution"]["report_xml"] == xml


@pytest.mark.parametrize("xml", [_unit_xml(total=0), _unit_xml(skipped=1), _unit_xml(skipped=3)])
def test_zero_or_required_skip_is_blocked(project_dir, xml):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(xml)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "blocked"
    assert result["failed"] == 0
    assert note["suggested_fallback"] == "escalate"


def test_unit_missing_dependency_is_blocked(project_dir):
    (project_dir / "addons/gdUnit4/bin/GdUnitCmdTool.gd").unlink()
    with patch.object(run_verify, "_run_process") as run:
        result, note = run_verify.check_unit_tests("godot", project_dir)
    run.assert_not_called()
    assert result["result"] == "blocked"
    assert "dependency" in note["error"]


def test_unit_overall_summary_contradiction_is_error(project_dir):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml(), "Overall Summary: 3 test cases | 0 errors | 1 failures")):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "error"
    assert "contradicts" in note["error"]


def test_unit_partial_suite_summary_does_not_override_xml(project_dir):
    with patch.object(run_verify, "_run_process", side_effect=_unit_run(_unit_xml(failed=1), "Statistics: 1 test cases | 0 errors | 0 failures", 100)):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "fail"
    assert result["passed"] == 2
    assert note is None


def test_check_unit_tests_timeout_is_error(project_dir):
    with patch.object(run_verify, "_run_process", side_effect=subprocess.TimeoutExpired(cmd=["godot"], timeout=600, output="before timeout", stderr="raw err")):
        result, note = run_verify.check_unit_tests("godot", project_dir)
    assert result["result"] == "error"
    assert result["failed"] == 0
    assert result["execution"]["stdout"] == "before timeout"
    assert result["execution"]["stderr"] == "raw err"
    assert note["suggested_fallback"] == "escalate"


# ---------- lint ----------

def test_check_lint_is_skipped_with_null_format_drift():
    result = run_verify.check_lint()
    assert result["result"] == "skipped"
    assert result["required"] is False
    assert result["reason"]
    assert result["format_drift"] is None


# ---------- static check ----------

def test_check_static_pass(project_dir):
    output = "[PASS] project.godot exists\n[PASS] tests directory exists\n"
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output)
        result, note = run_verify.check_static(project_dir)
    assert _legacy_fields(result) == {"result": "pass", "issues": []}
    assert note is None


def test_check_static_fail_parses_check_name_prefix(project_dir):
    output = (
        "[PASS] project.godot exists\n"
        "[FAIL] missing_unit_test: s_hud has no test file\n"
        "[FAIL] orphan_test: test_x.gd refers to deleted system\n"
    )
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output, returncode=1)
        result, note = run_verify.check_static(project_dir)
    assert result["result"] == "fail"
    assert result["issues"] == [
        {"check": "missing_unit_test", "detail": "s_hud has no test file"},
        {"check": "orphan_test", "detail": "test_x.gd refers to deleted system"},
    ]
    assert note is None


def test_check_static_fail_without_check_prefix(project_dir):
    output = "[FAIL] something generic went wrong\n"
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(stdout=output, returncode=1)
        result, _ = run_verify.check_static(project_dir)
    assert result["issues"] == [
        {"check": "static_check", "detail": "something generic went wrong"},
    ]


def test_check_static_timeout_is_error(project_dir):
    with patch.object(
        run_verify, "_run_process",
        side_effect=subprocess.TimeoutExpired(cmd="check_project", timeout=60),
    ):
        result, note = run_verify.check_static(project_dir)
    assert result["result"] == "error"
    assert result["issues"] == []
    assert note["tool"] == "check_project"


def test_check_static_nonzero_without_fail_output_is_error(project_dir):
    with patch.object(run_verify, "_run_process") as run:
        run.return_value = _make_proc(
            stderr="Traceback (most recent call last):\nImportError: broken\n",
            returncode=2,
        )
        result, note = run_verify.check_static(project_dir)

    assert _legacy_fields(result) == {"result": "error", "issues": []}
    assert note["tool"] == "check_project"
    assert note["suggested_fallback"] == "escalate"
    assert "exited with code 2" in note["error"]
    assert "ImportError: broken" in note["error"]


# ---------- godot_path resolution ----------

def test_read_godot_path_returns_configured_value(project_dir: Path):
    assert run_verify.read_godot_path(project_dir, default="godot") == "/usr/bin/godot"


def test_read_godot_path_falls_back_to_godot_when_missing(tmp_path: Path):
    """SKILL says fall back to plain 'godot' when the yaml is absent."""
    (tmp_path / ".godotmaker").mkdir()
    assert run_verify.read_godot_path(tmp_path, default="godot") == "godot"


def test_read_godot_path_falls_back_when_field_empty(tmp_path: Path):
    (tmp_path / ".godotmaker").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "godotmaker.yaml").write_text("godot_path: \n")
    assert run_verify.read_godot_path(tmp_path, default="godot") == "godot"


def test_read_godot_path_uses_codex_runtime_config(tmp_path: Path):
    (tmp_path / ".godotmaker").mkdir()
    (tmp_path / ".godotmaker" / "config.yaml").write_text("agent: codex\n")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "godotmaker.yaml").write_text(
        "godot_path: /opt/codex-godot\n"
    )
    assert run_verify.read_godot_path(tmp_path, default="godot") == "/opt/codex-godot"


def test_prefer_console_godot_path_uses_existing_sibling(tmp_path: Path):
    gui = tmp_path / "Godot_v4.5-stable_win64.exe"
    console = tmp_path / "Godot_v4.5-stable_win64_console.exe"
    gui.write_text("", encoding="utf-8")
    console.write_text("", encoding="utf-8")

    assert run_verify.prefer_console_godot_path(str(gui)) == str(console)


def test_prefer_console_godot_path_keeps_original_when_missing(tmp_path: Path):
    gui = tmp_path / "Godot_v4.5-stable_win64.exe"
    gui.write_text("", encoding="utf-8")

    assert run_verify.prefer_console_godot_path(str(gui)) == str(gui)


# ---------- build_report composition ----------

def _fake_run_factory(*, build="ok", unit="ok", static="ok"):
    """Build a subprocess.run fake. Each arg selects per-tool behaviour:

    - "ok"      → clean pass output
    - "fail"    → output that parses to a failing result
    - "timeout" → raise TimeoutExpired
    """
    BUILD_OK = "Setting Up MainLoop...\nDone.\n"
    BUILD_FAIL = "ERROR: Cannot open file 'res://x.tscn'.\n"
    UNIT_OK = "100 test cases | 0 errors | 0 failures (10 suites, exit 0)\n"
    UNIT_FAIL = (
        "100 test cases | 0 errors | 1 failures (10 suites, exit 1)\n"
        "FAILED: test_x::test_y - boom\n"
    )
    STATIC_OK = "[PASS] all good\n"
    STATIC_FAIL = "[FAIL] missing_unit_test: s_hud has no test file\n"

    def fake_run(cmd, *args, **kwargs):
        # Identify which check this call is from.
        cmd_str = " ".join(str(c) for c in cmd)
        if "GdUnitCmdTool" in cmd_str:
            if unit == "timeout":
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=600)
            _write_gdunit_xml_from_cmd(cmd, _unit_xml(total=100, failed=1 if unit == "fail" else 0))
            return _make_proc(stdout=UNIT_FAIL if unit == "fail" else UNIT_OK, returncode=100 if unit == "fail" else 0)
        if "check_project.py" in cmd_str:
            if static == "timeout":
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=60)
            return _make_proc(stdout=STATIC_FAIL if static == "fail" else STATIC_OK, returncode=1 if static == "fail" else 0)
        # Otherwise: godot --headless --quit
        if build == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=60)
        return _make_proc(stdout=BUILD_FAIL if build == "fail" else BUILD_OK)
    return fake_run


def test_build_report_all_pass_is_schema_valid(project_dir: Path):
    with patch.object(run_verify, "_run_process",
                      side_effect=_fake_run_factory()):
        report = run_verify.build_report(project_dir)
    assert report["result"] == "pass"
    assert report["tooling_notes"] == []
    assert report["checks"]["lint"]["format_drift"] is None
    assert validate_report(report) == []


def test_build_report_shutdown_note_keeps_overall_pass(project_dir: Path):
    base_fake = _fake_run_factory()

    def fake_run(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        if "GdUnitCmdTool" not in cmd_str and "check_project.py" not in cmd_str:
            return _make_proc(
                stdout=(
                    "Godot Engine v4.5\nERROR: 7 resources still in use at exit "
                    "(run with --verbose for details).\n"
                ),
                returncode=0,
            )
        return base_fake(cmd, *args, **kwargs)

    with patch.object(run_verify, "_run_process", side_effect=fake_run):
        report = run_verify.build_report(project_dir)

    assert report["result"] == "pass"
    assert _legacy_fields(report["checks"]["build"]) == {"result": "pass", "errors": []}
    assert validate_report(report) == []


def test_build_report_unit_fail_makes_overall_fail(project_dir: Path):
    with patch.object(run_verify, "_run_process",
                      side_effect=_fake_run_factory(unit="fail")):
        report = run_verify.build_report(project_dir)
    assert report["result"] == "fail"
    assert report["checks"]["unit_tests"]["failed"] == 1
    assert validate_report(report) == []


def test_build_report_build_timeout_pairs_with_tooling_note(project_dir: Path):
    with patch.object(run_verify, "_run_process",
                      side_effect=_fake_run_factory(build="timeout")):
        report = run_verify.build_report(project_dir)
    assert report["result"] == "error"
    assert report["checks"]["build"]["result"] == "error"
    notes = report["tooling_notes"]
    assert len(notes) == 1
    assert notes[0]["tool"] == "godot"
    assert notes[0]["suggested_fallback"] == "escalate"
    assert validate_report(report) == []


def test_build_report_multiple_tool_errors_emit_multiple_notes(project_dir: Path):
    """build + static both timing out → 2 entries in tooling_notes."""
    with patch.object(
        run_verify, "_run_process",
        side_effect=_fake_run_factory(build="timeout", static="timeout"),
    ):
        report = run_verify.build_report(project_dir)
    assert report["result"] == "error"
    tools = sorted(n["tool"] for n in report["tooling_notes"])
    assert tools == ["check_project", "godot"]
    assert validate_report(report) == []


def test_build_report_static_fail_is_schema_valid(project_dir: Path):
    with patch.object(run_verify, "_run_process",
                      side_effect=_fake_run_factory(static="fail")):
        report = run_verify.build_report(project_dir)
    assert report["result"] == "fail"
    assert report["checks"]["static_check"]["issues"][0]["check"] == "missing_unit_test"
    assert validate_report(report) == []


# ---------- main / CLI ----------

def test_main_missing_godotmaker_dir_returns_blocked(tmp_path: Path, capsys):
    rc = run_verify.main(["--project-path", str(tmp_path)])
    assert rc == 2
    assert "not a godotmaker project" in capsys.readouterr().err


def test_main_emits_json_to_stdout(project_dir: Path, capsys):
    with patch.object(run_verify, "_run_process",
                      side_effect=_fake_run_factory()):
        rc = run_verify.main(["--project-path", str(project_dir)])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert validate_report(parsed) == []
    assert parsed["result"] == "pass"
    assert "ts" in parsed and parsed["ts"].endswith("Z")


def test_main_defaults_to_cwd(project_dir: Path, capsys, monkeypatch):
    monkeypatch.chdir(project_dir)
    with patch.object(run_verify, "_run_process",
                      side_effect=_fake_run_factory()):
        rc = run_verify.main([])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["result"] == "pass"


def test_main_subprocess_invocation_real(project_dir: Path):
    """End-to-end via real subprocess — godot/gdunit/check_project all fail
    to launch, so we expect rc=0 with a JSON whose checks.* are 'error'.

    Important: this guards against the script breaking at import time
    (syntax errors, missing imports) — the rest of the file mocks at
    module level and would miss those.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-path", str(project_dir)],
        capture_output=True, text=True, timeout=30,
        # Avoid hitting a real godot on the dev machine: point PATH at an
        # empty dir for this call.
        env={**os.environ, "PATH": str(project_dir)},
    )
    assert proc.returncode == 2, proc.stderr
    parsed = json.loads(proc.stdout)
    # godot not on PATH → build + unit are 'error'. Lint stub-passes.
    assert parsed["checks"]["build"]["result"] == "blocked"
    assert parsed["checks"]["unit_tests"]["result"] == "blocked"
    assert parsed["checks"]["lint"]["result"] == "skipped"
    # check_project.py runs (sys.executable is still found) so static_check
    # depends on whether it errors out on the empty project; tolerate
    # either pass or fail/error here — the assertion that matters is that
    # the script ran end-to-end and produced a schema-valid JSON.
    assert validate_report(parsed) == []


# ---------- godot log-file retention ----------

def test_godot_log_file_keeps_five_newest_per_kind(project_dir: Path):
    logs = project_dir / ".godotmaker" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    seeded = []
    for i in range(6):
        p = logs / f"godot-build-seed{i}.log"
        p.write_text("x")
        os.utime(p, (1000 + i, 1000 + i))  # ascending mtime: seed5 newest
        seeded.append(p)
    # A different kind must survive build-kind pruning.
    untouched = logs / "godot-gdunit-seed.log"
    untouched.write_text("x")

    new_path = Path(run_verify.godot_log_file(project_dir, "build"))
    new_path.write_text("new")  # the caller (godot) writes the returned path

    build_logs = list(logs.glob("godot-build-*.log"))
    assert len(build_logs) == 5  # 4 newest seeds + the new one
    assert not seeded[0].exists()
    assert not seeded[1].exists()
    assert seeded[5].exists()
    assert untouched.exists()


@pytest.mark.parametrize("stdout,rc,expected", [
    ("", 0, "error"),
    ("[WARN] no checks available\n", 0, "blocked"),
    ("[PASS] project exists\n[WARN] git executable not found - skipping HEAD check\n", 0, "blocked"),
    ("[FAIL] addons/gecs/ missing\n", 1, "blocked"),
    ("[FAIL] godot --headless --quit did not finish within 60s\n", 1, "error"),
    ("[FAIL] assertion failed\n", 0, "error"),
    ("[PASS] assertion passed\n", 1, "error"),
])
def test_static_true_outcome_semantics(project_dir, stdout, rc, expected):
    with patch.object(run_verify, "_run_process", return_value=_make_proc(stdout=stdout, returncode=rc)):
        result, note = run_verify.check_static(project_dir)
    assert result["result"] == expected
    assert note is not None
    assert result["execution"]["stdout"] == stdout


@pytest.mark.parametrize("status,expected", [("PASS", 0), ("FAIL", 1), ("BLOCKED", 2), ("ERROR", 3)])
def test_cli_exit_code_is_result(project_dir, capsys, status, expected):
    with patch.object(run_verify, "build_report", return_value={"status": status, "exit_code": expected}):
        assert run_verify.main(["--project-path", str(project_dir)]) == expected
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_build_empty_success_output_is_error(project_dir):
    with patch.object(run_verify, "_run_process", return_value=_make_proc()):
        result, note = run_verify.check_build("godot", project_dir)
    assert result["result"] == "error"
    assert "exit 0 alone" in note["error"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_timeout_kills_descendants_and_retains_diagnostics(tmp_path):
    import time
    marker = tmp_path / "child-survived"
    child = "import time,pathlib;time.sleep(0.7);pathlib.Path(%r).write_text('alive')" % str(marker)
    program = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]);"
        "print('raw before timeout',flush=True);"
        "print('stderr before timeout',file=sys.stderr,flush=True);"
        "time.sleep(10)"
    )
    execution = run_verify._execute([sys.executable, "-c", program], tmp_path, 0.2)
    assert execution["timed_out"] is True
    assert "raw before timeout" in execution["stdout"]
    assert "stderr before timeout" in execution["stderr"]
    assert execution["cwd"] == str(tmp_path)
    time.sleep(0.8)
    assert not marker.exists(), "timeout left a child process running"


@pytest.mark.skipif(os.name == "nt", reason="POSIX cancellation regression")
def test_outer_cancellation_cleans_separate_check_group(tmp_path):
    import signal
    import time
    ready = tmp_path / "ready"
    marker = tmp_path / "survived"
    child = (
        "import pathlib,time;"
        f"pathlib.Path({str(ready)!r}).write_text('ready');"
        "time.sleep(0.7);"
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    program = (
        "import sys;"
        f"sys.path.insert(0,{str(REPO_ROOT / 'tools')!r});"
        "import run_verify;"
        f"run_verify._run_process([sys.executable,'-c',{child!r}],cwd={str(tmp_path)!r},timeout=10)"
    )
    proc = subprocess.Popen([sys.executable, "-c", program], start_new_session=True)
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        os.killpg(proc.pid, signal.SIGTERM)
        assert proc.wait(timeout=3) == 3
        time.sleep(0.8)
        assert not marker.exists(), "outer cancellation leaked an independent check group"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
