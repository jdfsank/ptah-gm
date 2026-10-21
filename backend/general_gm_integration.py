"""Narrow adapter to the pinned GodotMaker-non-pk approval consumer.

The legacy Velvet adapter remains independent. Generic projects always use the
repository's exact ``sources/GodotMaker-non-pk/tools`` consumer and fixed
project-relative binding path; callers cannot select alternate tool paths.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import uuid
import shutil
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from .gm_module_loading import PINNED_MODULE_LOCK
from .frontend_approval import ApprovalContext, ApprovalError, validate_durable_approval_record

REPO_ROOT = Path(__file__).resolve().parents[1]
GM_TOOLS = REPO_ROOT / "sources" / "GodotMaker-non-pk" / "tools"
GM_REVIEW = GM_TOOLS / "gm_review.py"
APPROVAL_BINDING_REL = Path(".godotmaker") / "frontend-approval.json"
_LOAD_LOCK = PINNED_MODULE_LOCK


class GMIntegrationError(RuntimeError):
    """The project or trusted GM integration could not be safely used."""


def _load_review_support():
    path = GM_TOOLS / "review_support.py"
    if not path.is_file() or path.resolve() != path:
        raise GMIntegrationError("Pinned GM review support is unavailable")
    name = "_ptah_pinned_general_gm_review_support"
    # review_support uses historical bare imports. Temporarily bind those names
    # to the exact pinned sibling modules, then restore the host interpreter's
    # namespace so another project cannot inherit these aliases.
    dependencies = ("agent_runtime", "git_baseline", "frontend_approval", "append_stage_event")
    with _LOAD_LOCK:
        module = sys.modules.get(name)
        if module is not None:
            return module
        saved = {dep: sys.modules.get(dep) for dep in dependencies}
        try:
            for dep in dependencies:
                dep_path = GM_TOOLS / f"{dep}.py"
                if not dep_path.is_file() or dep_path.resolve() != dep_path:
                    raise GMIntegrationError(
                        f"Pinned GM dependency is unavailable: {dep}"
                    )
                dep_spec = importlib.util.spec_from_file_location(dep, dep_path)
                if dep_spec is None or dep_spec.loader is None:
                    raise GMIntegrationError(
                        f"Pinned GM dependency cannot be loaded: {dep}"
                    )
                dep_module = importlib.util.module_from_spec(dep_spec)
                sys.modules[dep] = dep_module
                dep_spec.loader.exec_module(dep_module)
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise GMIntegrationError("Pinned GM review support cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(name, None)
                raise
            return module
        finally:
            for dep, prior in saved.items():
                if prior is None:
                    sys.modules.pop(dep, None)
                else:
                    sys.modules[dep] = prior


def _project(project_dir: Path) -> Path:
    path = Path(project_dir).resolve(strict=True)
    if not path.is_dir():
        raise GMIntegrationError("GM project directory is unavailable")
    return path


def spec_ref(project_dir: Path) -> str:
    """Return the current GM-normalized specification's Git object identity."""
    project = _project(project_dir)
    review = _load_review_support()
    try:
        spec = review.extract_spec(project)
        return review.spec_git_ref(spec, project)
    except Exception as exc:
        raise GMIntegrationError(
            f"Current project specification is not GM-ready: {exc}"
        ) from exc


def _required_packet_value(packet: Mapping[str, object], key: str) -> str:
    value = packet.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GMIntegrationError(f"Approval packet is missing {key}")
    return value


def prepare_trusted_confirmation(
    project_dir: Path,
    packet: Mapping[str, object],
    approval_record: Mapping[str, object],
    context: ApprovalContext,
    *,
    decision_ref: str | None = None,
) -> Path:
    """Write a minimal GM confirmation after backend-side record validation.

    No database path, operator identity, or user credential crosses into the
    project. The workflow must revalidate the durable backend record whenever
    a report is consumed; this materialized file is only a scoped GM input.
    """
    project = _project(project_dir)
    if not isinstance(packet, Mapping):
        raise GMIntegrationError("Approval packet is invalid")
    try:
        event_id = approval_record.get("eventId")
        validated = validate_durable_approval_record(str(event_id or ""), approval_record, context)
    except (ApprovalError, AttributeError, TypeError) as exc:
        raise GMIntegrationError(f"Backend approval record is invalid: {exc}") from exc
    project_id = context.project_id
    test_data, production_authorized = context.test_data, context.production_authorized
    if test_data == production_authorized:
        raise GMIntegrationError(
            "Approval packet flags must identify exactly one environment"
        )
    if packet.get("projectId") != project_id or context.phase != "specification":
        raise GMIntegrationError("Approval packet belongs to a different project")
    packet_spec_ref = packet.get("gmSpecRef")
    if packet_spec_ref is not None and packet_spec_ref != spec_ref(project):
        raise GMIntegrationError("Approval packet GM specification identity is stale")

    if validated["action"] != "approve" or test_data or not production_authorized:
        raise GMIntegrationError("Only a production specification approval can confirm GM scope")
    if context.git_spec_ref != packet_spec_ref:
        raise GMIntegrationError("Approval decision does not match the frozen GM specification")
    binding = {
        "schemaVersion": 2,
        "decisionRef": decision_ref or "gm-confirmation-" + uuid.uuid4().hex,
        "eventId": event_id,
        "projectId": project_id,
        "phase": "specification",
        "action": validated["action"],
        "gitSpecRef": packet_spec_ref,
        "testData": test_data,
        "productionAuthorized": production_authorized,
        "proposalId": _required_packet_value(packet, "proposalId"),
        "packetId": _required_packet_value(packet, "packetId"),
        "jobId": _required_packet_value(packet, "jobId"),
        "candidateId": packet.get("candidateId"),
        "revision": str(packet.get("proposalRevision")),
    }
    if binding["candidateId"] is not None and not isinstance(
        binding["candidateId"], str
    ):
        raise GMIntegrationError("Approval packet candidateId is invalid")
    destination = project / APPROVAL_BINDING_REL
    parent = destination.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or destination.is_symlink():
        raise GMIntegrationError("Approval binding path cannot contain symlinks")
    payload = (
        json.dumps(
            binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )
    temporary = parent / ".frontend-approval.json.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return destination


def register(
    project_dir: Path,
    store_path: Path,
    operator_id: str,
    project_id: str,
    packet: Mapping[str, object],
) -> Path:
    """Trusted legacy backend wrapper that consumes and narrows one approval.

    The old workflow still passes its private approval-store path and actor to
    this backend function. They are used only here to validate the exact
    durable event; neither value is materialized into the project.
    """
    project = _project(project_dir)
    if not isinstance(packet, Mapping):
        raise GMIntegrationError("Approval packet is invalid")
    requested_store = Path(store_path)
    if requested_store.is_symlink():
        raise GMIntegrationError("Approval store must not be a symbolic link")
    store = requested_store.resolve(strict=True)
    info = store.stat()
    if not store.is_file() or stat.S_IMODE(info.st_mode) & 0o077:
        raise GMIntegrationError("Approval store must be a private regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise GMIntegrationError("Approval store must be owned by the current user")
    if not isinstance(operator_id, str) or not operator_id.strip() or packet.get("projectId") != project_id:
        raise GMIntegrationError("Approval actor or project identity is invalid")
    if packet.get("gmSpecRef") != spec_ref(project):
        raise GMIntegrationError("Approval packet GM specification identity is stale")
    event_id = packet.get("approvalEventId")
    if not isinstance(event_id, str) or not event_id.strip():
        raise GMIntegrationError("Approval packet is missing approvalEventId")
    try:
        connection = sqlite3.connect(store, timeout=5)
        row = connection.execute("SELECT payload,consumed FROM approvals WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise GMIntegrationError("No durable approval matches this frozen packet")
        record = json.loads(row[0])
        test_data = packet.get("testData", False)
        production = packet.get("productionAuthorized", True)
        if type(test_data) is not bool or type(production) is not bool or test_data == production:
            raise GMIntegrationError("Approval packet authorization flags are invalid")
        # Synthetic test records are diagnostic only. They never get passed to
        # the production confirmation validator or consumed as approval.
        if test_data or not production:
            if (record.get("eventId") != event_id or record.get("projectId") != project_id
                    or record.get("testData") is not True or record.get("productionAuthorized") is not False):
                raise GMIntegrationError("Synthetic approval record does not match diagnostic context")
            binding = {
                "schemaVersion": 2, "decisionRef": "gm-diagnostic-" + _required_packet_value(packet, "jobId"),
                "eventId": event_id, "projectId": project_id, "phase": "specification", "action": "approve",
                "gitSpecRef": packet["gmSpecRef"], "testData": True, "productionAuthorized": False,
                "proposalId": _required_packet_value(packet, "proposalId"),
                "packetId": _required_packet_value(packet, "packetId"),
                "jobId": _required_packet_value(packet, "jobId"),
                "candidateId": packet.get("candidateId"), "revision": str(packet.get("proposalRevision")),
            }
            destination = project / APPROVAL_BINDING_REL
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if destination.parent.is_symlink() or destination.is_symlink():
                raise GMIntegrationError("Approval binding path cannot contain symlinks")
            temporary = destination.parent / ".frontend-approval.json.tmp"
            temporary.write_text(json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            return destination
        context = ApprovalContext(
            operator_id=operator_id, project_id=project_id, phase="specification",
            proposal_id=_required_packet_value(packet, "proposalId"),
            packet_id=_required_packet_value(packet, "packetId"),
            job_id=_required_packet_value(packet, "jobId"),
            candidate_id=packet.get("candidateId"),
            revision=str(packet.get("proposalRevision")),
            git_spec_ref=str(packet["gmSpecRef"]), test_data=test_data,
            production_authorized=production,
        )
        try:
            validated = validate_durable_approval_record(event_id, record, context)
        except ApprovalError as exc:
            raise GMIntegrationError(f"Backend approval record is invalid: {exc}") from exc
        if validated["action"] != "approve":
            raise GMIntegrationError("Only an approval can confirm GM scope")
        if row[1] == 0:
            changed = connection.execute("UPDATE approvals SET consumed=1 WHERE id=? AND consumed=0", (event_id,)).rowcount
            if changed != 1:
                raise GMIntegrationError("Approval event was concurrently consumed")
            connection.commit()
    except sqlite3.Error as exc:
        raise GMIntegrationError(f"Cannot consume backend approval: {exc}") from exc
    finally:
        if "connection" in locals():
            connection.close()
    return prepare_trusted_confirmation(project, packet, record, context,
        decision_ref="gm-confirmation-" + _required_packet_value(packet, "jobId"))


def prepare_input(coordinator, packet: Mapping[str, object], job: Mapping[str, object]) -> dict:
    """Idempotently materialize the approved GM input in the private artifact vault.

    The coordinator owns the transaction and supplies its already durable
    decision. Preparation can be retried after a crash because the artifact ID
    is derived from the job, and a complete artifact is revalidated on replay.
    """
    if not isinstance(packet, Mapping) or not isinstance(job, Mapping):
        raise GMIntegrationError("Packet and job are required for runner input preparation")
    for key in ("id", "projectId", "approvalEventId", "gmSpecRef", "proposalId", "proposalRevision"):
        if not isinstance(packet.get(key), (str, int)) or str(packet[key]) == "":
            raise GMIntegrationError(f"Frozen packet is missing {key}")
    job_id = job.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise GMIntegrationError("Production job identity is invalid")
    try:
        decision = coordinator._get("input_decision", "input-decision:" + job_id)
    except Exception as exc:
        raise GMIntegrationError("Persistent production input decision is unavailable") from exc
    if (decision.get("status") != "APPROVED" or decision.get("projectId") != packet.get("projectId")
            or decision.get("packetId") != packet.get("id")
            or decision.get("approvalEventId") != packet.get("approvalEventId")):
        raise GMIntegrationError("Persistent input decision does not match this frozen packet")
    row = coordinator.db.execute("SELECT payload,consumed FROM approvals WHERE id=?",
                                 (packet["approvalEventId"],)).fetchone()
    if row is None or row[1] != 1:
        raise GMIntegrationError("Backend has not durably consumed the specification decision")
    approval_record = json.loads(row[0])
    context = ApprovalContext(
        operator_id=coordinator.operator_id, project_id=str(packet["projectId"]),
        phase="specification", proposal_id=str(packet["proposalId"]),
        packet_id=str(packet["id"]), job_id=job_id,
        candidate_id=packet.get("candidateId"), revision=str(packet["proposalRevision"]),
        git_spec_ref=str(packet["gmSpecRef"]),
        test_data=packet.get("testData", False),
        production_authorized=packet.get("productionAuthorized", True),
    )
    try:
        validate_durable_approval_record(str(packet["approvalEventId"]), approval_record, context)
    except ApprovalError as exc:
        raise GMIntegrationError(f"Durable backend decision no longer matches the frozen packet: {exc}") from exc
    artifacts = Path(coordinator.state_root) / "artifacts"
    artifacts.mkdir(mode=0o700, parents=True, exist_ok=True)
    artifact_id = "input-" + job_id
    final = artifacts / artifact_id
    temporary = artifacts / (".preparing-" + job_id)

    def git(project: Path, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(project), *args], capture_output=True,
                                text=True, timeout=30, check=False)
        if result.returncode:
            raise GMIntegrationError("Input Git operation failed: " + result.stderr.strip())
        return result.stdout.strip()

    def return_existing(root: Path) -> dict:
        project = _project(root / "repository")
        input_commit = git(project, "rev-parse", "--verify", "HEAD^{commit}")
        if git(project, "status", "--porcelain"):
            raise GMIntegrationError("Previously prepared input repository is dirty")
        template = Path(coordinator.root) / "backend" / "templates" / "general_2d"
        if coordinator._template_inventory(template) != packet.get("templateInventory"):
            raise GMIntegrationError("Template baseline changed after approval")
        plan_dir = (Path(coordinator.state_root) / "planning" / str(packet["proposalId"])
                    / f"spec-{packet['proposalRevision']}")
        from tools.git_baseline import capture_inventory
        from .generic_workflow import SPEC_FILES
        if capture_inventory(plan_dir, SPEC_FILES) != packet.get("specInventory"):
            raise GMIntegrationError("Frozen GM specification files changed after approval")
        base_commit = packet.get("baseCommit")
        source_refs = packet.get("sourceRefs", {})
        if not isinstance(source_refs, dict):
            raise GMIntegrationError("Frozen source references are invalid")
        if source_refs and not isinstance(base_commit, str):
            raise GMIntegrationError("Frozen source references have no base commit")
        for name, expected in source_refs.items():
            actual = "git:blob:" + git(project, "rev-parse", "--verify", f"{base_commit}:{name}")
            if actual != expected:
                raise GMIntegrationError("Frozen source reference changed after approval")
        if packet.get("assetBundle"):
            from .imagegen_assets import load_bundle, ImageAssetError
            try:
                ref, bound, _ = load_bundle(coordinator.state_root, packet["assetBundle"]["bundleId"], expected=packet["assetBundle"])
                if bound["document"] != packet["document"] or bound["tasks"] != packet["tasks"] or bound["projectId"] != packet["projectId"]:
                    raise ImageAssetError("Prepared image bundle intent changed.")
                for name, expected in ref["sourceRefs"].items():
                    if "git:blob:" + git(project, "rev-parse", input_commit + ":" + name) != expected:
                        raise ImageAssetError("Prepared image asset differs from the reviewed bundle.")
            except ImageAssetError as exc:
                raise GMIntegrationError(str(exc)) from exc
        prepared_path = root / "prepared.json"
        if prepared_path.is_symlink() or not prepared_path.is_file():
            raise GMIntegrationError("Previously prepared input commit record is missing")
        try:
            prepared_record = json.loads(prepared_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GMIntegrationError("Previously prepared input commit record is malformed") from exc
        if (not isinstance(prepared_record, dict) or set(prepared_record) != {"inputCommit"}
                or prepared_record.get("inputCommit") != input_commit):
            raise GMIntegrationError("Previously prepared input HEAD no longer matches prepared.json")
        confirmation_path = project / APPROVAL_BINDING_REL
        if not confirmation_path.is_file() or confirmation_path.is_symlink():
            raise GMIntegrationError("Previously prepared confirmation is missing")
        try:
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GMIntegrationError("Previously prepared confirmation is malformed") from exc
        expected_binding = {
            "schemaVersion": 2, "decisionRef": "gm-confirmation-" + job_id,
            "eventId": packet["approvalEventId"], "projectId": packet["projectId"],
            "phase": "specification", "action": "approve", "gitSpecRef": packet["gmSpecRef"],
            "testData": False, "productionAuthorized": True,
            "proposalId": packet["proposalId"], "packetId": packet["id"], "jobId": job_id,
            "candidateId": packet.get("candidateId"), "revision": str(packet["proposalRevision"]),
        }
        if confirmation != expected_binding:
            raise GMIntegrationError("Previously prepared input belongs to another frozen approval binding")
        review = _load_review_support()
        try:
            spec = review.extract_spec(project)
            current_ref = review.spec_git_ref(spec, project)
            stage_path = project / ".godotmaker" / "stage.jsonl"
            if stage_path.is_symlink() or not stage_path.is_file():
                raise GMIntegrationError("Previously prepared GM stage confirmation is missing")
            events = review.read_events(project)
            confirmed = any(
                event.get("role") == "gdd"
                and event.get("provenance", {}).get("event_id") == packet["approvalEventId"]
                and event.get("provenance", {}).get("decision_ref") == confirmation["decisionRef"]
                and event.get("provenance", {}).get("project_id") == str(packet["projectId"])
                and review._spec_confirmation_matches(event, spec, current_ref, project)
                for event in events
            )
        except GMIntegrationError:
            raise
        except Exception as exc:
            raise GMIntegrationError(f"Previously prepared GM stage confirmation is invalid: {exc}") from exc
        if current_ref != packet["gmSpecRef"] or not confirmed or not spec_confirmed(project):
            raise GMIntegrationError("Previously prepared input no longer has the exact GM specification confirmation")
        service_content = confirmation_path.read_text(encoding="utf-8")
        stage_content = stage_path.read_text(encoding="utf-8")
        attempt_id = str(job.get("attemptId") or job_id)
        artifact_ref = {"artifactId": artifact_id, "projectId": packet["projectId"],
                        "jobId": job_id, "attemptId": attempt_id,
                        "sourceCommit": input_commit, "inputCommit": input_commit,
                        "packetId": packet["id"]}
        return {"inputCommit": input_commit, "inputArtifactRef": artifact_ref,
                "gmConfirmationRef": confirmation["decisionRef"],
                "protectedFiles": list((packet.get("assetBundle") or {}).get("paths", [])),
                "serviceRecords": {".godotmaker/frontend-approval.json": service_content,
                                   ".godotmaker/stage.jsonl": stage_content}}

    if final.exists():
        return return_existing(final)
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(mode=0o700, parents=True)
    repo_path = Path(coordinator.state_root) / "projects" / str(packet["projectId"])
    template = Path(coordinator.root) / "backend" / "templates" / "general_2d"
    if coordinator._template_inventory(template) != packet.get("templateInventory"):
        raise GMIntegrationError("Template baseline changed after approval")
    if repo_path.exists():
        if repo_path.is_symlink() or not repo_path.is_dir():
            raise GMIntegrationError("Project repository path is unsafe")
        original_base = packet.get("baseCommit")
        if not isinstance(original_base, str) or not original_base:
            raise GMIntegrationError("Existing project requires a frozen baseCommit")
        git(repo_path, "rev-parse", "--verify", f"{original_base}^{{commit}}")
        clone = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-local",
                                "--no-checkout", str(repo_path), str(temporary / "repository")],
                               capture_output=True, text=True, timeout=60, check=False)
        if clone.returncode:
            raise GMIntegrationError("Cannot create private input repository: " + clone.stderr.strip())
        project = temporary / "repository"
        git(project, "remote", "remove", "origin")
        git(project, "checkout", "--detach", original_base)
    else:
        project = temporary / "repository"
        project.mkdir(parents=True, mode=0o700)
        shutil.copytree(template, project, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".godot", "__pycache__", ".git"))
        git(project, "init", "--quiet", "-b", "main")
        git(project, "config", "user.name", "Studio Input Preparer")
        git(project, "config", "user.email", "studio@localhost")
        ignore_path = project / ".gitignore"
        lines = ignore_path.read_text(encoding="utf-8").splitlines() if ignore_path.exists() else []
        for entry in (".godot/", ".godotmaker/"):
            if entry not in lines:
                lines.append(entry)
        ignore_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        files = [p.relative_to(project).as_posix() for p in project.rglob("*")
                 if p.is_file() and ".git" not in p.parts]
        git(project, "add", "--", *sorted(files))
        git(project, "commit", "--quiet", "-m", "Prepare trusted general 2D baseline")
        original_base = git(project, "rev-parse", "HEAD")

    for name, expected in packet.get("sourceRefs", {}).items():
        actual = "git:blob:" + git(project, "rev-parse", f"{original_base}:{name}")
        if actual != expected:
            raise GMIntegrationError("Frozen source reference changed after approval")
    plan_dir = Path(coordinator.state_root) / "planning" / str(packet["proposalId"]) / f"spec-{packet['proposalRevision']}"
    from tools.git_baseline import capture_inventory
    from .generic_workflow import SPEC_FILES
    if capture_inventory(plan_dir, SPEC_FILES) != packet.get("specInventory"):
        raise GMIntegrationError("Frozen GM specification files changed after approval")
    for name in SPEC_FILES:
        destination = project / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((plan_dir / name).read_bytes())
    design = project / "design" / "game.json"
    design.parent.mkdir(parents=True, exist_ok=True)
    design.write_text(json.dumps(packet["document"], ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    if spec_ref(project) != packet["gmSpecRef"]:
        raise GMIntegrationError("Prepared project GM specification does not match approved specification")

    from .imagegen_assets import import_bundle, ImageAssetError
    try:
        imported_assets = import_bundle(coordinator.state_root, packet, project)
    except ImageAssetError as exc:
        raise GMIntegrationError(str(exc)) from exc

    binding_path = prepare_trusted_confirmation(
        project, packet, approval_record, context, decision_ref="gm-confirmation-" + job_id
    )
    # Let the pinned GM consumer create the exact local stage event that
    # verification will later re-read. A trusted JSON binding alone is not a
    # completed specification confirmation.
    confirm_spec(project, str(packet["approvalEventId"]))
    protected = [*SPEC_FILES, "design/game.json", *imported_assets]
    git(project, "add", "--", *protected)
    git(project, "commit", "--quiet", "--allow-empty", "-m", "Prepare approved runner input " + job_id)
    input_commit = git(project, "rev-parse", "HEAD")
    if git(project, "status", "--porcelain"):
        raise GMIntegrationError("Prepared input repository is not clean")
    (temporary / "prepared.json").write_text(json.dumps({"inputCommit": input_commit}, sort_keys=True) + "\n")
    os.chmod(temporary / "prepared.json", 0o600)
    os.replace(temporary, final)
    return return_existing(final)


def confirm_spec(project_dir: Path, event_id: str) -> dict:
    """Consume a frontend event through the actual pinned production GM CLI."""
    project = _project(project_dir)
    review = _load_review_support()
    try:
        binding = review.frontend_approval_binding(project)
    except Exception as exc:
        raise GMIntegrationError(f"Pinned GM approval binding is unavailable or invalid: {exc}") from exc
    if binding["testData"] is True or binding["productionAuthorized"] is not True:
        raise GMIntegrationError(
            "Test or unauthorized approvals cannot enter the production GM gate"
        )
    if not isinstance(event_id, str) or not event_id.strip():
        raise GMIntegrationError("Frontend approval event id is required")
    if not GM_REVIEW.is_file() or GM_REVIEW.resolve() != GM_REVIEW:
        raise GMIntegrationError("Pinned GM review command is unavailable")
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(GM_REVIEW),
                "confirm-spec",
                "--project",
                str(project),
                "--frontend-event-id",
                event_id,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GMIntegrationError(
            f"Pinned GM specification confirmation failed to run: {exc}"
        ) from exc
    try:
        response = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GMIntegrationError(
            "Pinned GM specification confirmation returned invalid JSON"
        ) from exc
    if (
        result.returncode != 0
        or not isinstance(response, dict)
        or response.get("result") != "PASS"
    ):
        reason = (
            response.get("reason", "GM specification confirmation was rejected")
            if isinstance(response, dict)
            else "GM specification confirmation was rejected"
        )
        raise GMIntegrationError(str(reason))
    return response


def spec_confirmed(project_dir: Path) -> bool:
    """Ask GM's own matching predicate whether the current spec is confirmed."""
    project = _project(project_dir)
    review = _load_review_support()
    try:
        spec = review.extract_spec(project)
        current_ref = review.spec_git_ref(spec, project)
        events = review.read_events(project)
        return any(
            event.get("role") == "gdd"
            and review._spec_confirmation_matches(event, spec, current_ref, project)
            for event in events
        )
    except Exception as exc:  # noqa: BLE001 - Inspection errors still block production.
        raise GMIntegrationError(f"GM 规格确认记录复核失败：{exc}") from exc


__all__ = [
    "GMIntegrationError",
    "confirm_spec",
    "register",
    "prepare_trusted_confirmation",
    "spec_confirmed",
    "spec_ref",
]
