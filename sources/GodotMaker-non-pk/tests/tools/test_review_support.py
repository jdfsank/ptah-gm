"""Unit contracts use synthetic reports; integration tests run the real engine."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import review_support as review

PLAN = """# Game Plan: test
**Tag:** v0.1.0
## Iteration Intent
User requirement: keep key gate; no combat. Scope awaits real user confirmation.
## Tag Mechanics
- [v0.1.0-M1] Take a key to open the gate.
## Playable Unit
Player experience: menu, key, door, exit.
| Mechanic | Expected | Evidence |
|---|---|---|
| v0.1.0-M1 | Gate blocks without key | old/path |
## Review Notes
A visible door without collision is not success. Human checks clarity.
## Platform Commitments
| Platform | Commitment | Evidence |
|---|---|---|
| Desktop | required | semantic_action plus actual keyboard review |
## Main Build
### Build Tasks
| Task | Mechanic | Verify |
|---|---|---|
| M01 | v0.1.0-M1 | real key/gate |
## Task Status
| # | Task | Status | Notes |
|---|---|---|---|
| M01 | Door | pending | |
"""


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "工程 with spaces"
    p.mkdir()
    (p / "project.godot").write_text('[application]\nconfig/name="unit-fixture"\n')
    (p / "PLAN.md").write_text(PLAN)
    for name in review.SPEC_DOCS:
        if name != "PLAN.md":
            (p / name).write_text(f"# {name}\nSynthetic unit-test requirement.\n")
    (p / "main.gd").write_text("extends Node\n")
    (p / "assets").mkdir()
    (p / "assets/key.dat").write_bytes(b"actual-resource")
    return p


def test_json_duplicate_nonfinite_rejected():
    for text in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
        with pytest.raises(review.ReviewError):
            review.strict_json(text)


def test_assertion_statuses():
    def report(status="PASS", required=True):
        return {"schema_version": 1, "result": status, "cases": [{"id": "one", "required": required, "status": status}]}
    assert review.validate_assertions(report(), 0) == "PASS"
    assert review.validate_assertions(report("FAIL"), 1) == "FAIL"
    assert review.validate_assertions({"schema_version": 1, "result": "PASS", "cases": []}, 0) == "BLOCKED"
    skipped = report("SKIPPED")
    skipped["result"] = "BLOCKED"
    assert review.validate_assertions(skipped, 2) == "BLOCKED"
    with pytest.raises(review.ReviewError, match="contradiction"):
        review.validate_assertions(report(), 1)
    duplicate = report()
    duplicate["cases"] *= 2
    with pytest.raises(review.ReviewError, match="duplicate"):
        review.validate_assertions(duplicate, 0)


def test_spec_ignores_status_and_evidence_only(project):
    digest = review.extract_spec(project)["spec_digest"]
    path = project / "PLAN.md"
    path.write_text(path.read_text().replace("pending", "verified").replace("old/path", "new/path"))
    assert review.extract_spec(project)["spec_digest"] == digest
    path.write_text(path.read_text().replace("Gate blocks without key", "Gate is always open"))
    assert review.extract_spec(project)["spec_digest"] != digest


def test_source_includes_dirty_untracked_assets(project):
    before = review.inventory(project)
    (project / "new.gd").write_text("extends Node2D\n")
    assert review.inventory(project) != before
    before = review.inventory(project)
    (project / "assets/key.dat").write_bytes(b"changed-resource")
    assert review.inventory(project) != before


def test_test_change_separate_from_source(project):
    (project / "e2e").mkdir()
    (project / "e2e/test_game.py").write_text("def test_game(): assert True\n")
    source, tests = review.inventory(project)
    before = review.runner_digest(project, tests)
    (project / "e2e/test_game.py").write_text("def test_game(): assert False\n")
    after_source, after_tests = review.inventory(project)
    assert source == after_source
    assert before != review.runner_digest(project, after_tests)


@pytest.mark.parametrize("name", ["Unexpected", "GoalBaselineBundle"])
def test_unknown_template_does_not_hash_empty(project, name):
    with (project / "PLAN.md").open("a") as file:
        file.write(f"\n## {name}\nMust never vanish.\n")
    with pytest.raises(review.ReviewError, match="Unsupported"):
        review.extract_spec(project)


def test_supports_published_platform_template(project):
    template = Path(__file__).resolve().parents[2] / "templates/PLAN.md"
    heading = template.read_text().split("## Platform Commitments", 1)[1].split("\n## ", 1)[0]
    assert "required" in heading
    assert review.extract_spec(project)["profiles"][0]["name"] == "Desktop"
    text = (project / "PLAN.md").read_text().replace("| Platform | Commitment | Evidence |\n|---|---|---|\n| Desktop | required | semantic_action plus actual keyboard review |", "| Platform | Commitment | Required profiles | Input evidence level | Manual check / source |\n|---|---|---|---|---|\n| Desktop | required | keyboard | semantic_action | native play |")
    (project / "PLAN.md").write_text(text)
    assert review.extract_spec(project)["profiles"][0]["name"] == "keyboard"


@pytest.mark.parametrize("name", [".env", "export_credentials.cfg", ".ssh/id_ecdsa", ".aws/credentials"])
def test_credentials_not_copied(project, name):
    path = project / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("dummy-nonsecret")
    with pytest.raises(review.ReviewError, match="Credential|credential"):
        review.inventory(project)


def test_symlinks_and_traversal_blocked(project, tmp_path):
    outside = tmp_path / "outside.gd"
    outside.write_text("extends Node\n")
    (project / "escape.gd").symlink_to(outside)
    with pytest.raises(review.ReviewError, match="Symlink"):
        review.inventory(project)
    for path in ("../outside.gd", str(outside), "bad\\path"):
        with pytest.raises(review.ReviewError):
            review.safe_child(project, path)
    alias = tmp_path / "alias"
    alias.symlink_to(project, target_is_directory=True)
    with pytest.raises(review.ReviewError, match="symlink"):
        review.inventory(alias)


def test_excluded_required_resource_blocks(project):
    (project / "data.md").write_text("resource")
    (project / "main.gd").write_text('extends Node\nvar data = preload("res://data.md")\n')
    with pytest.raises(review.ReviewError, match="excluded"):
        review.inventory(project)


def test_lock_exclusive_and_no_automatic_takeover(project):
    with review.OperationLock(project):
        with pytest.raises(review.ReviewError, match="Existing run.lock"):
            with review.OperationLock(project):
                pass
    assert not (project / ".godotmaker/run.lock").exists()
    review.write_json(project / ".godotmaker/run.lock", {"pid": 999999999, "children": []})
    with pytest.raises(review.ReviewError):
        with review.OperationLock(project):
            pass
    assert (project / ".godotmaker/run.lock").exists()


@pytest.mark.skipif(os.name != "posix", reason="Controlled process-tree runner currently POSIX only")
def test_timeout_and_normal_exit_children_cleaned(tmp_path):
    marker = tmp_path / "must-not-exist"
    child = f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('bad')"
    script = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
    result = review.execute([sys.executable, "-c", script], tmp_path, tmp_path / "logs", "timeout", 0.1)
    assert result["timed_out"]
    script = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
    result = review.execute([sys.executable, "-c", script], tmp_path, tmp_path / "logs", "orphan", 5)
    assert result["orphaned_children"]
    time.sleep(1.1)
    assert not marker.exists()


def test_doctor_readonly_and_no_game_launch(project):
    before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    with patch.object(review, "resolve_godot", return_value=(str(Path(sys.executable).resolve()), "4.6.3")):
        result = review.doctor(project)
    after = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert result["result"] == "PASS"
    assert before == after
    assert not (project / ".godotmaker").exists()


def fake_run(project):
    source, tests = review.inventory(project)
    spec = review.extract_spec(project)
    run_id = "RUN-unit-test"
    run = project / ".godotmaker/runs" / run_id
    run.mkdir(parents=True)
    review._copy_snapshot(project, run / "project", source, tests)
    python_binary = str(Path(sys.executable).resolve())
    manifest = {"schema_version": 1, "command": "check", "run_id": run_id, "tag": spec["tag"], "spec_digest": spec["spec_digest"], "source_digest": review.manifest_digest(source), "test_digest": review.runner_digest(project, tests), "source_files": source, "test_files": tests, "profiles": spec["profiles"], "result": "BLOCKED", "report_digests": {}, "suites": {}, "environment": {"godot_path": python_binary, "godot_git_identity": review.digest_file(Path(python_binary))}}
    write_manifest_identity(project, run, manifest)
    return run_id, run, manifest


def write_manifest_identity(project, run, manifest):
    """Write the synthetic run's Git-object identity sidecar and latest binding."""
    review.write_json(run / "manifest.json", manifest)
    identity = review.digest_file(run / "manifest.json")
    (run / "manifest.git").write_text(identity + "\n", encoding="ascii")
    review.write_json(project / ".godotmaker/latest-review.json",
                      {"run_id": manifest["run_id"], "manifest_digest": identity})


def test_status_readonly_returns_zero_for_pending(project):
    fake_run(project)
    before = sorted(str(p) for p in project.rglob("*"))
    result = review.status(project)
    assert result["result"] == "PASS"
    assert result["run"]["result"] == "BLOCKED"
    assert before == sorted(str(p) for p in project.rglob("*"))
    assert not (project / ".godotmaker/run.lock").exists()


def test_run_manifest_uses_git_identity_record_not_checksum_filename(project):
    run_id, run, manifest = fake_run(project)
    record = run / "manifest.git"
    assert record.is_file()
    assert record.read_text(encoding="ascii").startswith("git:blob:")
    assert not (run / "manifest.sha256").exists()
    assert manifest["environment"]["godot_git_identity"].startswith("git:blob:")
    (run / "manifest.json").write_text((run / "manifest.json").read_text() + " ", encoding="utf-8")
    result = review.gate(project, run_id)
    assert "Run manifest changed or Git identity record missing" in result["reasons"]


def test_feedback_idempotent_and_new_run_does_not_lose_denial(project):
    run_id, _, _ = fake_run(project)
    payload = {"id": "FB01", "mechanics": ["v0.1.0-M1"], "platform": "Desktop", "text": "Stopping feels wrong.", "type": "experience", "source_ref": "synthetic-unit-test"}
    first = review.add_feedback(project, run_id, payload)
    assert first["gap_task_id"] == "F-FB01"
    contents = (project / "GAP.md").read_text()
    assert review.add_feedback(project, run_id, payload)["idempotent"]
    assert contents == (project / "GAP.md").read_text()
    assert review.pending_feedback(project, "RUN-new")[0]["id"] == "FB01"
    assert review.gate(project, run_id)["result"] == "BLOCKED"
    with pytest.raises(review.ReviewError, match="immutable"):
        review.add_feedback(project, run_id, {**payload, "text": "Different"})
    (project / "GAP.md").unlink()
    review.add_feedback(project, run_id, payload)
    assert "F-FB01" in (project / "GAP.md").read_text()


def test_noninteractive_confirmation_never_records_human(project):
    with patch.object(sys.stdin, "isatty", return_value=False):
        with pytest.raises(review.ReviewError, match="needs_human"):
            review.confirm_spec(project)
    assert not (project / ".godotmaker/stage.jsonl").exists()


def test_corrupt_duplicate_events_block(project):
    stage = project / ".godotmaker/stage.jsonl"
    stage.parent.mkdir()
    stage.write_text('{"role":"gdd","ts":"2026-10-06T12:00:00Z","tag":"v0.1.0"}\n' * 2)
    with pytest.raises(review.ReviewError, match="Duplicate"):
        review.read_events(project)
    stage.write_text('{"role":"unknown","ts":"2026-10-06T12:00:00Z"}\n')
    with pytest.raises(review.ReviewError, match="Invalid"):
        review.read_events(project)


def test_cli_json_missing_engine_and_existing_output(project, tmp_path):
    cli = Path(review.__file__).with_name("gm_review.py")
    result = subprocess.run([sys.executable, str(cli), "doctor", "--project", str(project), "--godot", str(tmp_path / "missing")], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["result"] == "BLOCKED"
    result = subprocess.run([sys.executable, str(cli), "smoke", "--fixture", "one_room_loop", "--output", str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["result"] == "BLOCKED"


def test_gate_detects_scene_asset_and_snapshot_drift(project):
    run_id, run, _ = fake_run(project)
    (project / "assets/key.dat").write_text("changed")
    result = review.gate(project, run_id)
    assert any("source_digest" in reason for reason in result["reasons"])
    (run / "project/main.gd").chmod(0o600)
    (run / "project/main.gd").write_text("changed")
    result = review.gate(project, run_id)
    assert "Snapshot input drift" in result["reasons"]


def test_gate_rejects_manifest_symlink(project, tmp_path):
    run_id, run, _ = fake_run(project)
    external = tmp_path / "external.json"
    (run / "manifest.json").rename(external)
    (run / "manifest.json").symlink_to(external)
    assert review.gate(project, run_id)["result"] == "BLOCKED"


@pytest.mark.parametrize("key", ['"api_key"', 'openai_api_key', 'token'])
def test_unknown_or_secret_config_cannot_enter_snapshot(project, tmp_path, key):
    config = project / ".claude/godotmaker.yaml"
    config.parent.mkdir()
    config.write_text(f'{key}: DUMMY_NON_SECRET\n')
    source, tests = review.inventory(project)
    with pytest.raises(review.ReviewError, match="credential|Unsupported"):
        review._copy_snapshot(project, tmp_path / "snapshot", source, tests)


def test_snapshot_spec_and_config_are_bound(project):
    run_id, run, manifest = fake_run(project)
    manifest["snapshot_auxiliary"] = review.snapshot_auxiliary(run / "project")
    review.write_json(run / "manifest.json", manifest)
    target = run / "project/PLAN.md"
    target.chmod(0o600)
    target.write_text(target.read_text() + "changed")
    assert any("configuration drift" in r for r in review.gate(project, run_id)["reasons"])


def test_duplicate_platform_profiles_never_collapse(project):
    path = project / "PLAN.md"
    path.write_text(path.read_text().replace("| Desktop | required | semantic_action plus actual keyboard review |", "| Desktop | required | visual | semantic_action | review |\n| Mobile | required | visual | physical_device | review |"))
    with pytest.raises(review.ReviewError, match="unique"):
        review.extract_spec(project)


def test_package_versions_participate_in_runner_identity(project):
    _, tests = review.inventory(project)
    before = review.runner_digest(project, tests)
    with patch.object(review.importlib.metadata, "distributions", return_value=[]):
        assert review.runner_digest(project, tests) != before


def synthetic_pass_run(project):
    """Protocol-only success fixture; NEVER real gameplay or human evidence."""
    from tests.test_verify_report_fixtures import report_v2_pass
    path = project / "PLAN.md"
    text = path.read_text().replace("| Mechanic | Expected | Evidence |\n|---|---|---|\n| v0.1.0-M1 | Gate blocks without key | old/path |", "| Mechanic | Player operation / content | Expected effect | Required visible content | Evidence |\n|---|---|---|---|---|\n| v0.1.0-M1 | Move | Gate blocks without key | Door | old/path |")
    path.write_text(text.replace("pending", "verified"))
    (project / "SCENES.md").write_text("# Synthetic scene specification\n## Scene: room\nVisible door.\n")
    (project / "e2e/screenshots").mkdir(parents=True)
    (project / "e2e/test_game.py").write_text("# Synthetic protocol fixture, not a gameplay oracle.\n")
    (project / "e2e/screenshots/scene.png").write_bytes(b"synthetic-schema-test-only")
    (project / "e2e/screenshots/vqa.log").write_text("synthetic-schema-test-only")
    run_id, run, manifest = fake_run(project)
    manifest.update(result="PASS", specification=review.extract_spec(project)["text"], snapshot_auxiliary=review.snapshot_auxiliary(run / "project"))
    reports = run / "reports"
    reports.mkdir()
    review.write_json(reports / "verify.json", report_v2_pass())
    (reports / "e2e.xml").write_text('<testsuites><testsuite tests="1"><testcase classname="synthetic" name="protocol"/></testsuite></testsuites>')
    manifest["suites"] = {name: {"result": "PASS", "report": relative, "test_digest": manifest["test_digest"], "cases": 1} for name, relative in (("verify", "reports/verify.json"), ("e2e", "reports/e2e.xml"))}
    manifest["commands"] = [{"suite": name, "exit_code": 0, "timed_out": False, "orphaned_children": False} for name in ("verify", "e2e")]
    manifest["report_digests"] = {str(p.relative_to(run)): review.digest_file(p) for p in reports.iterdir()}
    write_manifest_identity(project, run, manifest)
    evaluation = {**{k: manifest[k] for k in ("tag", "run_id", "spec_digest", "source_digest", "test_digest")}, "review_kind": "self_review", "result": "approve", "playable_closed_loop": {key: True for key in ("builds_clean", "boots_main_scene", "playable_unit_coverage", "completion_fail_or_exit_reached")}, "playable_unit": {"result": "pass", "rows": {"v0.1.0-M1": {"result": "pass", "test": "e2e/test_game.py", "evidence": ["synthetic protocol fixture"]}}}, "tag_mechanics": {"v0.1.0-M1": "pass"}, "inherited_mechanics": {}, "visual_checks": {"room": {"result": "pass", "screenshot": "e2e/screenshots/scene.png", "captures": ["e2e/screenshots/scene.png"], "vqa_log": "e2e/screenshots/vqa.log", "vqa_calls": [{"ts": "2026-10-06T00:00:00Z", "mode": "question", "backend": "native", "model": "synthetic-protocol-fixture", "files": ["e2e/screenshots/scene.png"], "log": "e2e/screenshots/vqa.log", "context": "Synthetic schema fixture, not real visual evidence", "verdict": "pass", "output_summary": "Synthetic protocol fixture only"}]}}, "e2e_tests": {"total": 1, "passed": 1, "failed": 0}, "critical_issues": [], "orphan_tests": [], "phase4_review": [{"category": "synthetic protocol", "verdict": "Not an actual experience review"}]}
    review.write_json(project / ".godotmaker/evaluation.json", evaluation)
    return run_id, run, manifest, evaluation


def test_synthetic_bound_flow_can_pass_and_denial_invalidates(project):
    run_id, run, manifest, _ = synthetic_pass_run(project)
    assert review.bind_evaluation(project, run_id)["result"] == "PASS"
    evaluation_identity = run / "evaluation-binding.git"
    assert evaluation_identity.is_file()
    assert evaluation_identity.read_text(encoding="ascii").startswith("git:blob:")
    assert not (run / "evaluation-binding.sha256").exists()
    assert review.bind_evaluation(project, run_id)["idempotent"]
    with patch.object(review, "interactive_confirmation", return_value=None):
        review.confirm_spec(project)
        assert review.gate(project, run_id, require_accept=False)["result"] == "PASS"
        assert review.decision(project, run_id, "accept", ["Desktop"])["result"] == "PASS"
        assert review.gate(project, run_id)["result"] == "PASS"
        assert review.decision(project, run_id, "changes_requested", [])["result"] == "PASS"
        assert review.gate(project, run_id)["result"] == "BLOCKED"
    assert (run / "evaluation-binding.json").exists()


def test_evaluator_unbound_report_and_missing_visuals_never_approve(project):
    run_id, _, _, evaluation = synthetic_pass_run(project)
    evaluation.pop("run_id")
    review.write_json(project / ".godotmaker/evaluation.json", evaluation)
    with pytest.raises(review.ReviewError, match="unbound"):
        review.bind_evaluation(project, run_id)
    evaluation["run_id"] = run_id
    evaluation["visual_checks"] = {}
    review.write_json(project / ".godotmaker/evaluation.json", evaluation)
    with pytest.raises(review.ReviewError, match="visual"):
        review.bind_evaluation(project, run_id)


def test_acceptance_rechecks_after_human_prompt(project):
    run_id, _, _, _ = synthetic_pass_run(project)
    review.bind_evaluation(project, run_id)
    with patch.object(review, "interactive_confirmation", return_value=None):
        review.confirm_spec(project)
    def editor_change(*args):
        (project / "main.gd").write_text("changed during user review")
    with patch.object(review, "interactive_confirmation", side_effect=editor_change):
        assert review.decision(project, run_id, "accept", ["Desktop"])["result"] == "BLOCKED"
    assert not any(e["role"] == "accept" for e in review.read_events(project))


def test_no_evaluator_binding_and_missing_suite_path_block_gate(project):
    run_id, run, manifest, _ = synthetic_pass_run(project)
    with patch.object(review, "interactive_confirmation", return_value=None):
        review.confirm_spec(project)
    assert any("gm-evaluate" in r for r in review.gate(project, run_id, require_accept=False)["reasons"])
    manifest["suites"]["verify"].pop("report")
    write_manifest_identity(project, run, manifest)
    assert any("raw report" in r for r in review.gate(project, run_id, require_accept=False)["reasons"])


@pytest.mark.parametrize("mutation", ["phase4", "vqa", "scene_coverage"])
def test_evaluation_cannot_skip_original_experience_or_visual_records(project, mutation):
    run_id, _, _, evaluation = synthetic_pass_run(project)
    if mutation == "phase4":
        evaluation["phase4_review"] = []
    elif mutation == "vqa":
        evaluation["visual_checks"]["room"]["vqa_calls"] = [None]
    else:
        evaluation["visual_checks"]["different"] = evaluation["visual_checks"].pop("room")
    review.write_json(project / ".godotmaker/evaluation.json", evaluation)
    with pytest.raises(review.ReviewError):
        review.bind_evaluation(project, run_id)


def test_synthetic_rejection_is_not_overwritten_by_auto_report(project):
    run_id, _, _, _ = synthetic_pass_run(project)
    review.bind_evaluation(project, run_id)
    original = (project / ".godotmaker/evaluation.json").read_bytes()
    with patch.object(review, "interactive_confirmation", return_value=None):
        review.confirm_spec(project)
        review.decision(project, run_id, "changes_requested", [])
    assert (project / ".godotmaker/evaluation.json").read_bytes() == original
    assert review.gate(project, run_id)["result"] == "BLOCKED"


def test_fixed_oracle_cannot_drop_required_mechanics():
    report = {"schema_version": 1, "result": "PASS", "cases": [{"id": "one", "required": True, "status": "PASS", "mechanic": "FX-M1"}]}
    assert review.validate_assertions(report, 0, {"one": "FX-M1", "two": "FX-M2"}) == "BLOCKED"
    with pytest.raises(review.ReviewError, match="oracle"):
        review.validate_assertions(report, 0, {"one": "FX-M2"})


def test_snapshot_has_minimal_local_verifier_config_without_changing_original(project, tmp_path):
    source, tests = review.inventory(project)
    snapshot = tmp_path / "snapshot"
    review._copy_snapshot(project, snapshot, source, tests)
    assert (snapshot / ".godotmaker/config.yaml").read_text() == "agent: claude-code\n"
    assert not (project / ".godotmaker").exists()
    assert review.inventory(snapshot) == (source, tests)
    assert ".godotmaker/config.yaml" in review.snapshot_auxiliary(snapshot)


def test_published_doctor_creates_no_bytecode_or_project_files(tmp_path):
    import shutil
    published = tmp_path / "published"
    published.mkdir()
    (published / "project.godot").write_text('[application]\nconfig/name="readonly-doctor-test"\n')
    tools = published / "tools"
    shutil.copytree(Path(review.__file__).parent, tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    before = {str(p.relative_to(published)): p.read_bytes() for p in published.rglob("*") if p.is_file()}
    process = subprocess.run([sys.executable, str(tools / "gm_review.py"), "doctor", "--project", str(published), "--godot", str(tmp_path / "missing-engine")], cwd=published, capture_output=True, text=True)
    assert process.returncode == 2
    assert json.loads(process.stdout)["result"] == "BLOCKED"
    after = {str(p.relative_to(published)): p.read_bytes() for p in published.rglob("*") if p.is_file()}
    assert before == after
    assert not list(published.rglob("__pycache__"))


def test_fixture_arrows_use_logical_keys_and_wasd_remain_physical():
    fixture = Path(__file__).resolve().parents[2] / "tests/fixtures/one_room_loop/project.godot"
    text = fixture.read_text()
    for code in (4194319, 4194320, 4194321, 4194322):
        assert f'Object(InputEventKey,"keycode":{code})' in text
        assert f'Object(InputEventKey,"physical_keycode":{code})' not in text
    for code in (65, 68, 87, 83):
        assert f'Object(InputEventKey,"physical_keycode":{code})' in text
