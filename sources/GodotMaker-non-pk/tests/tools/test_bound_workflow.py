"""Regressions for bounded event writes, early feedback, and archive gates."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stage = load("bounded_stage_test", "tools/append_stage_event.py")
seal = load("bounded_seal_test", "tools/seal_tag.py")
prereqs = load("bounded_prereq_test", "hooks/check_stage_prerequisites.py")


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".godotmaker").mkdir()
    return tmp_path


@pytest.mark.parametrize("args", [
    ["invented"], ["scaffold", "--role=accept"], ["scaffold", "--ts=2020-01-01T00:00:00Z"],
    ["gdd", "--tag=v0.1.0", "--tag=v0.2.0"], ["scaffold", "--unexpected=yes"],
    ["accept"], ["accept", "--decision=made_up"], ["rescue", "--conclusion=unknown"],
    ["accept", "--decision=accept", "--actor=human"],
    ["accept", "--decision=accept", '--provenance={"kind":"local_interactive"}'],
    ["accept", "--decision=accept", '--reviewed_profiles="desktop"'],
    ["accept", "--decision=accept", '--reviewed_profiles=["desktop", "desktop"]'],
    ["fixgap", "--outcome=handoff"], ["gdd", "--tag=../../wrong"],
])
def test_bad_cli_has_no_side_effect(project, args):
    assert stage.main([*args, "--project-path", str(project)]) == 2
    assert not (project / ".godotmaker/stage.jsonl").exists()
    assert not (project / ".godotmaker/evaluation-runs").exists()


@pytest.mark.parametrize("fields", [{"tag": 4}, {"tag": False}, {"tag": []},
                                         {"tag": ""}, {"ts": "arbitrary"}])
def test_internal_types_and_reserved_fields_rejected(project, fields):
    with pytest.raises(ValueError):
        stage.append_event(project, "gdd", fields)
    assert not (project / ".godotmaker/stage.jsonl").exists()


def acceptance_fields():
    return {"tag": "v0.1.0", "decision": "accept", "run_id": "run-1",
            "spec_digest": "sha256:" + "1" * 64, "source_digest": "sha256:" + "2" * 64,
            "test_digest": "sha256:" + "3" * 64,
            "evidence_ref": ".godotmaker/runs/run-1/manifest.json",
            "reviewed_profiles": ["desktop"]}


def test_bound_accept_cannot_use_legacy_or_cli_human_claim(project):
    (project / ".godotmaker/runs").mkdir()
    assert stage.main(["accept", "--decision=accept", "--project-path", str(project)]) == 2
    fields = acceptance_fields()
    with pytest.raises(ValueError, match="provenance"):
        stage.append_event(project, "accept", fields)
    event = stage.append_event(project, "accept", fields,
                               decision_provenance=stage.LOCAL_PROVENANCE)
    assert event["provenance"] == stage.LOCAL_PROVENANCE
    assert event["test_digest"] == fields["test_digest"]


@pytest.mark.parametrize("missing", ["run_id", "tag", "spec_digest", "source_digest",
                                     "evidence_ref", "reviewed_profiles", "decision"])
def test_bound_accept_needs_every_binding(project, missing):
    fields = acceptance_fields()
    del fields[missing]
    with pytest.raises(ValueError):
        stage.append_event(project, "accept", fields,
                           decision_provenance=stage.LOCAL_PROVENANCE)


def test_resolution_needs_interactive_current_evidence(project):
    fields = {"feedback_id": "door", "resolved_run_id": "run-2", "resolution": "verified",
              "spec_digest": "1" * 64, "source_digest": "2" * 64, "test_digest": "3" * 64}
    with pytest.raises(ValueError):
        stage.append_event(project, "fixgap", fields)
    assert stage.append_event(project, "fixgap", fields,
                              decision_provenance=stage.LOCAL_PROVENANCE)["resolution"] == "verified"


def ready_project(project):
    for source, _ in seal.ARCHIVE_MAP:
        path = project / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"result": "approve"}) if source.endswith(".json") else "# doc\n")
    (project / "PLAN.md").write_text("# Plan\n**Tag:** v0.1.0\n")
    (project / ".godotmaker/runs/run-1/reports").mkdir(parents=True)
    (project / ".godotmaker/runs/run-1/manifest.json").write_text('{"run_id":"run-1"}')
    (project / ".godotmaker/runs/run-1/reports/assertions.log").write_text("raw checks\n")
    (project / ".godotmaker/latest-review.json").write_text('{"run_id":"run-1"}')
    (project / ".godotmaker/stage.jsonl").write_text('{"role":"accept","decision":"accept"}\n')
    (project / ".godotmaker/feedback").mkdir()
    (project / ".godotmaker/feedback/door.json").write_text('{"id":"door"}')
    (project / "GAP.md").write_text("# GAP\nF-door verified\n")
    return project / "docs/tags/v0.1.0"


def mocked_review(monkeypatch, result="PASS"):
    held = []
    calls = []

    class Lock:
        def __init__(self, project):
            self.project = project

        def __enter__(self):
            assert not held
            held.append(self.project)

        def __exit__(self, *exc):
            held.pop()

    def gate(project, **kwargs):
        assert held == [project]
        assert kwargs == {"require_accept": True, "locked": True}
        calls.append(project)
        return {"result": result, "run_id": "run-1", "reasons": ["needs_human"]}

    monkeypatch.setattr(seal, "_review_module", lambda: SimpleNamespace(OperationLock=Lock, gate=gate))
    return calls


def test_bound_archive_and_reset_preserve_hashed_evidence(project, monkeypatch):
    dest = ready_project(project)
    calls = mocked_review(monkeypatch)
    assert seal.cmd_archive(project, "v0.1.0") == 0
    archived = dest / "evidence/review/.godotmaker"
    assert (archived / "runs/run-1/reports/assertions.log").read_text() == "raw checks\n"
    assert (archived / "feedback/door.json").is_file()
    assert (archived / "latest-review.json").is_file()
    assert (archived / "stage.jsonl").read_text()
    assert (dest / "evidence/review/GAP.md").is_file()
    manifest = json.loads((dest / "evidence/manifest.json").read_text())
    assert manifest["review_binding"]["kind"] == "bound_review"
    assert seal.cmd_reset(project) == 2  # evidence exists, but not sealed yet
    (dest / "CHANGELOG.md").write_text("# Shipped\n")
    assert seal.cmd_index(project, "v0.1.0") == 0
    assert seal.cmd_reset(project) == 0
    assert not (project / ".godotmaker/stage.jsonl").read_text()
    assert (archived / "stage.jsonl").read_text()
    assert len(calls) == 4


def test_guard_failure_never_copies_or_clears(project, monkeypatch):
    dest = ready_project(project)
    mocked_review(monkeypatch, "BLOCKED")
    before = (project / ".godotmaker/stage.jsonl").read_bytes()
    assert seal.cmd_archive(project, "v0.1.0") == 2
    assert not dest.exists()
    assert seal.cmd_reset(project) == 2
    assert (project / ".godotmaker/stage.jsonl").read_bytes() == before


@pytest.mark.parametrize("change", ["feedback", "report", "new_file", "archive_corruption"])
def test_changed_evidence_blocks_seal(project, monkeypatch, change):
    dest = ready_project(project)
    mocked_review(monkeypatch)
    assert seal.cmd_archive(project, "v0.1.0") == 0
    (dest / "CHANGELOG.md").write_text("# Shipped\n")
    paths = {"feedback": project / ".godotmaker/feedback/door.json",
             "report": project / ".godotmaker/runs/run-1/reports/assertions.log",
             "new_file": project / ".godotmaker/feedback/new.json",
             "archive_corruption": dest / "evidence/review/.godotmaker/stage.jsonl"}
    paths[change].write_text("changed")
    assert seal.cmd_index(project, "v0.1.0") == 2
    assert not json.loads((dest / "evidence/manifest.json").read_text())["sealed"]


def test_legacy_archive_cannot_claim_bound_provenance(project):
    for source, _ in seal.ARCHIVE_MAP:
        path = project / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}' if source.endswith('.json') else '# doc\n')
    assert seal.cmd_archive(project, "v0.1.0") == 0
    manifest = json.loads((project / "docs/tags/v0.1.0/evidence/manifest.json").read_text())
    assert manifest["review_binding"] == {"kind": "legacy_unbound", "gate_result": "UNVERIFIED"}


def feedback_project(project):
    (project / "project.godot").write_text('[application]\n')
    (project / "PLAN.md").write_text('**Tag:** v0.1.0\n')
    (project / ".godotmaker/feedback").mkdir()
    item = {"schema_version": 1, "id": "door", "tag": "v0.1.0", "run_id": "early-run",
            "mechanics": ["v0.1.0-M3"], "platform": "desktop", "text": "Door opens without key",
            "type": "implementation", "source": "user", "created_at": "2026-10-06T00:00:00Z",
            "gap_task_id": "F-door", "provenance": {"kind": "host_supplied", "source_ref": "message:123",
                                                       "identity_assurance": "audit_only"}}
    path = project / ".godotmaker/feedback/door.json"
    path.write_text(json.dumps(item))
    (project / "GAP.md").write_text('## Feedback door\n\n- Task: F-door\n'
                                  '- Source: .godotmaker/feedback/door.json\n'
                                  '- Reproduction: reports/door.log shows exit reachable without key\n'
                                  '- Observed gap: door collision disabled at start\n'
                                  '- Expected behavior: PLAN v0.1.0-M3 blocks until key collected\n')
    return item, path


def test_user_feedback_can_dispatch_before_evaluate(project, monkeypatch):
    feedback_project(project)
    monkeypatch.chdir(project)
    assert not (project / ".godotmaker/evaluation.json").exists()
    assert prereqs._feedback_repair_ready()


@pytest.mark.parametrize("invalid", ["source", "id", "tag", "provenance", "pending", "design_change", "test_error"])
def test_invalid_or_unreproduced_feedback_cannot_bypass(project, monkeypatch, invalid):
    item, path = feedback_project(project)
    if invalid == "pending":
        gap = project / "GAP.md"
        gap.write_text(gap.read_text().replace('reports/door.log shows exit reachable without key', 'pending'))
    elif invalid in {"design_change", "test_error"}:
        item["type"] = invalid
    else:
        item[invalid] = "wrong"
    path.write_text(json.dumps(item))
    monkeypatch.chdir(project)
    assert not prereqs._feedback_repair_ready()


@pytest.mark.parametrize("choice", ["changes_requested", "design_change", "defer", "fix", "done"])
def test_nonaccept_decision_can_record_without_reviewed_profiles(project, choice):
    (project / ".godotmaker/runs").mkdir()
    stage.append_event(project, "accept", acceptance_fields(),
                       decision_provenance=stage.LOCAL_PROVENANCE)
    fields = acceptance_fields()
    fields.update(decision=choice, reviewed_profiles=[])
    event = stage.append_event(project, "accept", fields,
                               decision_provenance=stage.LOCAL_PROVENANCE)
    assert event["decision"] == choice
    assert event["reviewed_profiles"] == []
    entries = (project / ".godotmaker/stage.jsonl").read_text().splitlines()
    assert json.loads(entries[-1])["decision"] != "accept"


def test_plan_and_dispatch_keep_one_scope_authority():
    plan = (ROOT / "templates/PLAN.md").read_text()
    for title in ("Iteration Intent", "Review Notes", "Platform Commitments"):
        assert plan.count("## " + title + "\n") == 1
    for field in ("Goal / player value", "Non-goals", "Must preserve", "Source", "Confirmation"):
        assert field in plan
    for level in ("semantic_action", "engine_event", "physical_device"):
        assert level in plan
    dispatch = (ROOT / "skills/core/_shared/worker-dispatch.md").read_text()
    for field in ("Task ID", "Mechanic ID(s)", "Player value", "Allowed files", "Must preserve",
                  "Required checks", "Stop condition"):
        assert field in dispatch
    assert "one bounded worker at a time" in dispatch
    assert "Max 3 parallel workers" not in dispatch
    fixgap = (ROOT / "skills/core/gm-fixgap/SKILL.md").read_text()
    assert "before evaluation and after automatic approval" in fixgap
    assert "Never rewrite approve to reject" in fixgap
    assert "Recreate/reproduce" in fixgap
    assert "F-<id>" in fixgap


@pytest.mark.parametrize("report", [None, {"result": "pass"}, {"schema_version": 2, "status": "PASS"}])
def test_verify_appender_cannot_bypass_report_guard(project, report):
    if report is not None:
        (project / ".godotmaker/verify_report.json").write_text(json.dumps(report))
    assert stage.main(["verify", "--project-path", str(project)]) == 2
    assert not (project / ".godotmaker/stage.jsonl").exists()


def evaluation_fields():
    fields = acceptance_fields()
    fields.pop("decision")
    fields.pop("reviewed_profiles")
    fields["evaluation_digest"] = "sha256:" + "4" * 64
    return fields


def test_bound_evaluator_event_retains_original_role_without_human_claim(project):
    event = stage.append_event(project, "evaluate", evaluation_fields())
    assert event["role"] == "evaluate"
    assert event["evaluation_digest"] == "sha256:" + "4" * 64
    assert "provenance" not in event
    archive = project / ".godotmaker/evaluation-runs/latest.json"
    assert archive.is_file()


@pytest.mark.parametrize("missing", ["tag", "run_id", "spec_digest", "source_digest", "test_digest",
                                     "evidence_ref", "evaluation_digest"])
def test_bound_evaluator_event_requires_complete_input_and_report_identity(project, missing):
    fields = evaluation_fields()
    del fields[missing]
    with pytest.raises(ValueError, match="bound evaluate missing"):
        stage.append_event(project, "evaluate", fields)
    assert not (project / ".godotmaker/stage.jsonl").exists()


def test_accept_can_bind_exact_evaluation_digest(project):
    fields = acceptance_fields()
    fields["evaluation_digest"] = "sha256:" + "4" * 64
    event = stage.append_event(project, "accept", fields,
                               decision_provenance=stage.LOCAL_PROVENANCE)
    assert event["evaluation_digest"] == fields["evaluation_digest"]
    fields["evaluation_digest"] = "not-a-report-digest"
    with pytest.raises(ValueError, match="SHA-256"):
        stage.append_event(project, "accept", fields,
                           decision_provenance=stage.LOCAL_PROVENANCE)


def test_evaluator_workflow_keeps_original_checks_and_rebinds_after_test_changes():
    text = (ROOT / "skills/core/gm-evaluate/SKILL.md").read_text()
    assert "After authoring or changing E2E tests" in text
    assert "gm_review.py check --project . --suite all" in text
    assert "gm_review.py bind-evaluation --project . --run <run_id>" in text
    assert "playable_closed_loop" in text and '"visual_checks"' in text
    assert "original playable-unit, mechanics, visual, and gameplay review" in text
    assert "legacy unbound automatic approve" in text


def symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


@pytest.mark.parametrize("unsafe", ["screenshots_root", "e2e_parent", "unreferenced_file",
                                    "nested_directory", "dangling_file", "evaluation_json",
                                    "archive_root", "latest_pointer", "stage_log", "godotmaker_parent"])
def test_evaluation_archive_refuses_all_symlink_inputs_and_outputs(project, unsafe):
    outside = project.parent / (project.name + "-outside")
    outside.mkdir()
    secret = outside / "dummy.txt"
    secret.write_text("outside dummy content must not be copied or modified")
    screenshot_root = project / "e2e/screenshots"
    screenshot_root.mkdir(parents=True)
    (screenshot_root / "ordinary.png").write_text("ordinary image")
    archive_root = project / ".godotmaker/evaluation-runs"
    if unsafe == "screenshots_root":
        (screenshot_root / "ordinary.png").unlink()
        screenshot_root.rmdir()
        symlink_or_skip(screenshot_root, outside, directory=True)
    elif unsafe == "e2e_parent":
        (screenshot_root / "ordinary.png").unlink()
        screenshot_root.rmdir()
        screenshot_root.parent.rmdir()
        symlink_or_skip(screenshot_root.parent, outside, directory=True)
    elif unsafe == "unreferenced_file":
        symlink_or_skip(screenshot_root / "unreferenced.txt", secret)
    elif unsafe == "nested_directory":
        symlink_or_skip(screenshot_root / "nested", outside, directory=True)
    elif unsafe == "dangling_file":
        symlink_or_skip(screenshot_root / "missing.txt", outside / "does-not-exist")
    elif unsafe == "evaluation_json":
        symlink_or_skip(project / ".godotmaker/evaluation.json", secret)
    elif unsafe == "archive_root":
        symlink_or_skip(archive_root, outside, directory=True)
    elif unsafe == "latest_pointer":
        archive_root.mkdir()
        symlink_or_skip(archive_root / "latest.json", secret)
    elif unsafe == "stage_log":
        symlink_or_skip(project / ".godotmaker/stage.jsonl", secret)
    else:
        (project / ".godotmaker").rmdir()
        symlink_or_skip(project / ".godotmaker", outside, directory=True)
    assert stage.main(["evaluate", "--tag=v0.1.0", "--project-path", str(project)]) == 2
    assert secret.read_text() == "outside dummy content must not be copied or modified"
    assert sorted(path.name for path in outside.iterdir()) == ["dummy.txt"]
    if archive_root.exists() and not archive_root.is_symlink():
        assert not [path for path in archive_root.iterdir() if path.name != "latest.json"]
    if unsafe != "stage_log":
        assert not (project / ".godotmaker/stage.jsonl").exists()


def test_every_stage_role_refuses_symlink_log_before_appending(project):
    outside = project.parent / (project.name + "-stage-dummy")
    outside.write_text("unchanged")
    symlink_or_skip(project / ".godotmaker/stage.jsonl", outside)
    assert stage.main(["scaffold", "--project-path", str(project)]) == 2
    assert outside.read_text() == "unchanged"


@pytest.mark.parametrize("location", ["e2e/screenshots/unused.pipe", ".godotmaker/evaluation.json",
                                      ".godotmaker/stage.jsonl"])
def test_archive_refuses_special_files_without_opening_them(project, location):
    import os
    if not hasattr(os, "mkfifo"):
        pytest.skip("named pipes unavailable")
    path = project / location
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(path)
    assert stage.main(["evaluate", "--tag=v0.1.0", "--project-path", str(project)]) == 2
    assert not (project / ".godotmaker/evaluation-runs").exists()


def test_archive_validates_before_creating_output(project):
    screenshots = project / "e2e/screenshots"
    screenshots.mkdir(parents=True)
    # A directory in place of evaluation.json is not an absent optional file.
    (project / ".godotmaker/evaluation.json").mkdir()
    assert stage.main(["evaluate", "--tag=v0.1.0", "--project-path", str(project)]) == 2
    assert not (project / ".godotmaker/evaluation-runs").exists()
