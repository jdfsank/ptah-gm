#!/usr/bin/env python3
"""Append a stage event to .godotmaker/stage.jsonl with a server-generated UTC timestamp.

Used in SKILL "When Done" sections instead of having the agent hand-write the
event JSON. Moving timestamp generation off the agent eliminates the corruption
pattern observed in 2026-05-09 e2e (every fixgap and late-iter evaluate event
had a fabricated `ts`; verify events written under simpler agent contexts were
honest) — the root cause was agents producing `ts` from model output under
context pressure rather than calling the system clock.

Usage:
    python tools/append_stage_event.py <role> [--key=value ...]

Examples:
    python tools/append_stage_event.py scaffold
    python tools/append_stage_event.py gdd --tag=v0.1.0
    python tools/append_stage_event.py accept --decision=accept
    python tools/append_stage_event.py rescue --conclusion=defect

Exit codes:
    0  appended successfully
    1  .godotmaker/ directory does not exist under project root
    2  bad CLI usage (malformed extra arg)
"""
import argparse
import datetime
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path


def _validate_local_path(project_path: Path, path: Path, *, directory: bool) -> bool:
    """Reject links/special files in a project-relative path before reading it.

    This protects the entire archive input, including unreferenced media. It
    deliberately does not resolve a link and then inspect the escaped target.
    Missing leaf/parents are allowed for optional inputs and new outputs.
    """
    root, candidate = project_path.absolute(), path.absolute()
    relative = candidate.relative_to(root)
    if ".." in relative.parts:
        raise ValueError(f"archive path escapes project: {path}")
    current = root
    for index, part in enumerate((None, *relative.parts)):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return False
        reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise ValueError(f"symlink/reparse point is not permitted: {current}")
        expected_dir = index < len(relative.parts) or directory
        valid = stat.S_ISDIR(info.st_mode) if expected_dir else stat.S_ISREG(info.st_mode)
        if not valid:
            kind = "directory" if expected_dir else "regular file"
            raise ValueError(f"expected {kind}, refusing special/mismatched file: {current}")
    return True


def _validate_screenshot_tree(project_path: Path, root: Path) -> None:
    if not _validate_local_path(project_path, root, directory=True):
        return

    def failed(error):
        raise error

    for folder, directories, files in os.walk(root, followlinks=False, onerror=failed):
        for name in directories:
            _validate_local_path(project_path, Path(folder) / name, directory=True)
        for name in files:
            _validate_local_path(project_path, Path(folder) / name, directory=False)


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe or "untagged"


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def _unique_dir(base: Path) -> Path:
    if base.is_symlink():
        raise ValueError(f"archive output is a symlink: {base}")
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = base.with_name(f"{base.name}-{index}")
        if candidate.is_symlink():
            raise ValueError(f"archive output is a symlink: {candidate}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique archive directory under {base.parent}")


def _archive_evaluation_run(
    project_path: Path,
    event: dict[str, object],
) -> None:
    if event.get("role") != "evaluate":
        return

    tag = str(event.get("tag") or "untagged")
    ts = str(event["ts"])
    run_id = f"{ts.replace(':', '').replace('-', '')}_{_safe_name(tag)}"
    archive_root = project_path / ".godotmaker" / "evaluation-runs"
    screenshots_src = project_path / "e2e" / "screenshots"
    evaluation_src = project_path / ".godotmaker" / "evaluation.json"
    # Preflight everything before creating an archive or touching latest/stage.
    _validate_screenshot_tree(project_path, screenshots_src)
    _validate_local_path(project_path, evaluation_src, directory=False)
    _validate_local_path(project_path, archive_root, directory=True)
    _validate_local_path(project_path, archive_root / "latest.json", directory=False)
    run_dir = _unique_dir(archive_root / run_id)
    _validate_local_path(project_path, run_dir, directory=True)
    run_dir.mkdir(parents=True, exist_ok=False)

    screenshots_dst = run_dir / "screenshots"
    if screenshots_src.is_dir():
        shutil.copytree(screenshots_src, screenshots_dst)
    else:
        screenshots_dst.mkdir(parents=True, exist_ok=True)

    if evaluation_src.is_file():
        shutil.copy2(evaluation_src, run_dir / "evaluation.json")

    manifest = {
        "role": "evaluate",
        "tag": tag,
        "stage_event_ts": ts,
        "archive_path": str(run_dir.relative_to(project_path)).replace("\\", "/"),
        "screenshots_path": str(screenshots_dst.relative_to(project_path)).replace("\\", "/"),
        "screenshot_files": _count_files(screenshots_dst),
        "evaluation_json": (
            str((run_dir / "evaluation.json").relative_to(project_path)).replace("\\", "/")
            if (run_dir / "evaluation.json").is_file()
            else None
        ),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (archive_root / "latest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


# The stage log remains the pipeline trace, not a second task database.
ROLE_FIELDS = {
    "scaffold": set(),
    "gdd": {"tag", "spec_digest", "provenance"},
    "asset": {"tag"},
    "build": {"tag"},
    "verify": {"tag", "run_id", "spec_digest", "source_digest", "test_digest", "evidence_ref"},
    "evaluate": {"tag", "run_id", "spec_digest", "source_digest", "test_digest", "evidence_ref",
                 "evaluation_digest"},
    "fixgap": {"tag", "outcome", "next_role", "reason", "feedback_id", "resolved_run_id",
               "source_digest", "spec_digest", "test_digest", "resolution", "provenance"},
    "accept": {"tag", "decision", "run_id", "spec_digest", "source_digest", "test_digest",
               "evidence_ref", "reviewed_profiles", "provenance", "evaluation_digest"},
    "finalize": {"tag", "run_id"},
    "rescue": {"conclusion"},
}
BINDING_FIELDS = {"run_id", "spec_digest", "source_digest", "test_digest",
                  "evidence_ref", "reviewed_profiles", "evaluation_digest"}
LOCAL_PROVENANCE = {"kind": "local_interactive", "input": "tty", "recorded_by": "gm_review"}


def validate_fields(role: str, fields: dict[str, object]) -> None:
    """Validate a role's supplied fields before any filesystem side effect."""
    if role not in ROLE_FIELDS:
        raise ValueError(f"unknown role: {role!r}")
    unknown = fields.keys() - ROLE_FIELDS[role]
    if unknown:
        raise ValueError(f"unknown or reserved fields for {role}: {', '.join(sorted(unknown))}")
    for key, value in fields.items():
        if key == "reviewed_profiles":
            if (not isinstance(value, list)
                    or (not value and fields.get("decision") == "accept")
                    or any(not isinstance(v, str) or not v.strip() for v in value)
                    or len(value) != len(set(value))):
                raise ValueError("reviewed_profiles must be a list of unique strings (nonempty for accept)")
        elif key == "provenance":
            if value != LOCAL_PROVENANCE:
                raise ValueError("provenance must come from the local interactive decision entry")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty string")
        if key.endswith("_digest") and not re.fullmatch(r"git:blob:(?:[0-9a-f]{40}|[0-9a-f]{64})", str(value)):
            raise ValueError(f"{key} must be a Git blob identity (40- or 64-hex object ID)")
    if "tag" in fields and not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", str(fields["tag"])):
        raise ValueError("tag must be a SemVer tag such as v0.1.0")
    if "run_id" in fields and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(fields["run_id"])):
        raise ValueError("run_id must be a single safe path component")
    if "evidence_ref" in fields:
        ref = str(fields["evidence_ref"])
        if (Path(ref).is_absolute() or ".." in Path(ref).parts
                or "\\" in ref or ":" in ref):
            raise ValueError("evidence_ref must be a project-relative path")
    if role == "accept":
        if fields.get("decision") not in {"accept", "fix", "done", "changes_requested", "design_change", "defer"}:
            raise ValueError("accept requires decision=accept|fix|done|changes_requested|design_change|defer")
        if BINDING_FIELDS.intersection(fields):
            required = {"tag", "run_id", "spec_digest", "source_digest", "evidence_ref",
                        "reviewed_profiles", "provenance", "decision"}
            missing = required - fields.keys()
            if missing:
                raise ValueError("bound accept missing: " + ", ".join(sorted(missing)))
    if role == "evaluate" and BINDING_FIELDS.intersection(fields):
        required = {"tag", "run_id", "spec_digest", "source_digest", "test_digest",
                    "evidence_ref", "evaluation_digest"}
        missing = required - fields.keys()
        if missing:
            raise ValueError("bound evaluate missing: " + ", ".join(sorted(missing)))
    if role == "gdd" and "spec_digest" in fields and "provenance" not in fields:
        raise ValueError("bound specification confirmation requires local interactive provenance")
    if role == "rescue" and fields.get("conclusion") not in {"defect", "external", "insufficient"}:
        raise ValueError("rescue requires conclusion=defect|external|insufficient")
    if role == "fixgap" and {"outcome", "next_role", "reason"}.intersection(fields):
        if (fields.get("outcome"), fields.get("next_role"), fields.get("reason")) != (
                "handoff", "evaluate", "evaluator_owned_e2e"):
            raise ValueError("fixgap handoff requires outcome=handoff, next_role=evaluate, reason=evaluator_owned_e2e")

    if role == "fixgap" and {"feedback_id", "resolved_run_id", "resolution"}.intersection(fields):
        required = {"feedback_id", "resolved_run_id", "spec_digest", "source_digest", "test_digest",
                    "resolution", "provenance"}
        if required - fields.keys() or fields.get("resolution") != "verified":
            raise ValueError("feedback resolution requires current bound evidence and interactive provenance")


def append_event(
    project_path: Path,
    role: str,
    fields: dict[str, object] | None = None,
    *,
    decision_provenance: dict[str, str] | None = None,
) -> dict[str, object]:
    """Append a validated event; controlled interactive callers supply provenance.

    The caller owns the review operation lock and obtains real TTY input before
    providing decision_provenance. This is an audit boundary for trusted local
    collaboration, not authentication against same-permission Python callers.
    """
    fields = dict(fields or {})
    if "provenance" in fields:
        raise ValueError("provenance cannot be supplied as an ordinary event field")
    if decision_provenance is not None:
        fields["provenance"] = decision_provenance
    validate_fields(role, fields)
    stage_dir = project_path / ".godotmaker"
    _validate_local_path(project_path, stage_dir, directory=True)
    _validate_local_path(project_path, stage_dir / "stage.jsonl", directory=False)
    if not stage_dir.is_dir():
        raise FileNotFoundError(f"{stage_dir} does not exist")
    if role == "verify":
        tools_dir = str(Path(__file__).resolve().parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from run_verify import verification_issues
        issues = verification_issues(stage_dir / "verify_report.json", require_pass=True)
        if issues:
            raise ValueError("verify cannot complete: " + "; ".join(issues))
    if role == "accept" and ((stage_dir / "runs").exists()
                             or (stage_dir / "latest-review.json").exists()):
        if not BINDING_FIELDS.intersection(fields) or decision_provenance is None:
            raise ValueError("new-format accept requires a bound gm_review interactive decision")
    event = {"role": role, "ts": datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"), **fields}
    _archive_evaluation_run(project_path, event)
    with (stage_dir / "stage.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a validated stage event", allow_abbrev=False)
    parser.add_argument("role", help="pipeline role name")
    parser.add_argument("--project-path", default=None)
    args, extras = parser.parse_known_args(argv)
    fields: dict[str, object] = {}
    try:
        for extra in extras:
            if not extra.startswith("--") or "=" not in extra:
                raise ValueError(f"extra args must be in --key=value form (got: {extra!r})")
            key, _, value = extra[2:].partition("=")
            if not key:
                raise ValueError(f"empty key in {extra!r}")
            if key in {"role", "ts", "provenance", "actor"}:
                raise ValueError(f"reserved field cannot be supplied: {key}")
            if key in fields:
                raise ValueError(f"duplicate field: {key}")
            if key == "reviewed_profiles":
                value = json.loads(value)
            fields[key] = value
        project_path = Path(args.project_path) if args.project_path else Path.cwd()
        append_event(project_path, args.role, fields)
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
