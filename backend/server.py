"""Same-origin loopback HTTP boundary for the independent GM Studio UI.

The service never accepts a client supplied cwd, command, or host path. Project
ownership and workflow state stay in the coordinator; this module serves static
files, validates request envelopes, protects mutations, and owns uploaded bytes.
"""

from __future__ import annotations

import argparse
import binascii
import hmac
import json
import math
import mimetypes
import re
import secrets
from dataclasses import asdict, is_dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
STUDIO_ROOT = REPO_ROOT / "frontend" / "studio"
LEGACY_ROOT = REPO_ROOT / "frontend" / "dist"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ASSET_JSON_BYTES = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 16_384
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
ASSET_MIME = {
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/webp": (
        ".webp",
        lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    ),
}


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def validate_upload(
    *, name: str, mime_type: str, data_base64: str, purpose: str
) -> bytes:
    """Validate media at the HTTP boundary before coordinator-owned storage."""
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 255
        or Path(name).name != name
        or any(ord(c) < 32 for c in name)
    ):
        raise RequestError(400, "Image filename is invalid.")
    if purpose not in {"reference", "style", "layout", "asset"}:
        raise RequestError(
            400, "Image purpose must be reference, style, layout, or asset."
        )
    if mime_type not in ASSET_MIME:
        raise RequestError(415, "Only PNG, JPEG, and WebP images are supported.")
    if not isinstance(data_base64, str) or len(data_base64) > MAX_ASSET_JSON_BYTES:
        raise RequestError(413, "Image exceeds the upload limit.")
    try:
        import base64

        data = base64.b64decode(data_base64, validate=True)
    except (ValueError, binascii.Error):
        raise RequestError(400, "Image data is not valid base64.") from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise RequestError(413, "Image must be between 1 byte and 5 MB.")
    _extension, signature_check = ASSET_MIME[mime_type]
    if not signature_check(data):
        raise RequestError(415, "Image bytes do not match the declared image type.")
    return data


class StudioContext:
    def __init__(
        self, coordinator, *, operator_id: str | None = None, token: str | None = None
    ):
        self.coordinator = coordinator
        self.operator_id = operator_id or getattr(coordinator, "operator_id", None)
        if not isinstance(self.operator_id, str) or not self.operator_id:
            raise ValueError("Coordinator must provide its registered operator_id.")
        self.token = token or secrets.token_urlsafe(32)


def _jsonable(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    raise TypeError(
        f"Coordinator returned unsupported JSON value: {type(value).__name__}"
    )


def _required_string(
    value, label: str, *, max_length: int = 200, pattern: re.Pattern | None = None
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
        or (pattern and not pattern.fullmatch(value))
    ):
        raise RequestError(400, f"{label} is invalid.")
    return value


def _exact_fields(body: dict, allowed: set[str], required: set[str]) -> None:
    keys = set(body)
    unknown = keys - allowed
    missing = required - keys
    if unknown:
        raise RequestError(
            400, f"Unknown request fields: {', '.join(sorted(unknown))}."
        )
    if missing:
        raise RequestError(
            400, f"Missing request fields: {', '.join(sorted(missing))}."
        )


def _reject_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numbers must be finite.")
    return number


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address,
        context: StudioContext,
        *,
        studio_root=STUDIO_ROOT,
        legacy_root=LEGACY_ROOT,
    ):
        self.context = context
        self.studio_root = Path(studio_root).resolve()
        self.legacy_root = Path(legacy_root).resolve()
        super().__init__(address, StudioRequestHandler)


class StudioRequestHandler(SimpleHTTPRequestHandler):
    server: StudioHTTPServer
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        # Avoid logging concept text, uploaded filenames, or authorization tokens.
        return

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def _same_origin(self, *, mutation: bool) -> bool:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host", "").lower() != expected_host:
            return False
        origin = self.headers.get("Origin")
        expected_origin = f"http://{expected_host}"
        if origin is not None and origin != expected_origin:
            return False
        if mutation and origin != expected_origin:
            return False
        fetch_site = self.headers.get("Sec-Fetch-Site")
        return not (fetch_site and fetch_site not in {"same-origin", "none"})

    def _authorized_mutation(self) -> bool:
        token = self.headers.get("X-Workbench-Token", "")
        return self._same_origin(mutation=True) and hmac.compare_digest(
            token, self.server.context.token
        )

    def _send_json(self, status: int, value):
        payload = json.dumps(
            _jsonable(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, message: str):
        self._send_json(status, {"error": message})

    def _read_json(self, *, max_bytes=MAX_JSON_BYTES) -> dict:
        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type != "application/json":
            raise RequestError(415, "JSON content type required.")
        if self.headers.get("Transfer-Encoding"):
            raise RequestError(400, "Chunked request bodies are not supported.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise RequestError(400, "Invalid Content-Length.") from None
        if size <= 0:
            raise RequestError(400, "JSON request body is required.")
        if size > max_bytes:
            raise RequestError(413, "Request body exceeds the size limit.")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise RequestError(400, "Request body is incomplete.")
        try:
            value = json.loads(
                raw.decode("utf-8"),
                parse_constant=_reject_json_constant,
                parse_float=_finite_json_float,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeError, ValueError):
            raise RequestError(400, "Request body must be valid UTF-8 JSON.") from None
        if not isinstance(value, dict):
            raise RequestError(400, "JSON request body must be an object.")
        return value

    def _static(self, root: Path, relative: str):
        decoded = unquote(relative)
        candidate = (root / decoded).resolve()
        lexical = root / decoded
        if not lexical.is_relative_to(root) or any(
            part.is_symlink() for part in (lexical, *lexical.parents) if part != root
        ):
            self._error(404, "Not found")
            return
        candidate = lexical.resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            self._error(404, "Not found")
            return
        self.send_response(200)
        content_type = (
            mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        )
        if content_type in {
            "text/html",
            "text/css",
            "application/javascript",
            "text/javascript",
        }:
            content_type += "; charset=utf-8"
        size = candidate.stat().st_size
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Cache-Control",
            "no-cache"
            if root == self.server.studio_root or candidate.suffix in {".html"}
            else "private, max-age=300",
        )
        self.end_headers()
        if self.command != "HEAD":
            with candidate.open("rb") as stream:
                while True:
                    chunk = stream.read(128 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def _path(self):
        parsed = urlsplit(self.path)
        # Studio restores project/stage from the page URL; API paths stay exact.
        if parsed.fragment or (parsed.query and parsed.path != "/studio/"):
            raise RequestError(
                400, "Query parameters are not accepted on this endpoint."
            )
        return parsed.path

    def do_GET(self):
        if not self._same_origin(mutation=False):
            return self._error(403, "Only the configured loopback origin is allowed.")
        try:
            path = self._path()
            scoped_project = None
            project_route = re.fullmatch(r"/api/projects/([^/]+)(/.*)", path)
            if project_route:
                scoped_project = unquote(project_route.group(1))
                _required_string(scoped_project, "projectId", pattern=ID_RE)
                path = project_route.group(2)
            if path == "/workspace" and scoped_project:
                return self._send_json(200, self.server.context.coordinator.project_workspace(scoped_project))
            if path == "/workbench" and scoped_project:
                return self._send_json(200, self.server.context.coordinator.workbench(scoped_project))
            if scoped_project and not re.match(r"/(?:assets|proposals|packets|jobs)(?:/|$)", path):
                raise RequestError(404, "Unknown project-scoped route.")
            if scoped_project and path.startswith("/") and path not in {"/settings", "/workspace"}:
                path = "/api" + path
            if path in {"/studio", "/legacy"}:
                self.send_response(308)
                self.send_header("Location", path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/session":
                return self._send_json(
                    200,
                    {
                        "token": self.server.context.token,
                        "operatorId": self.server.context.operator_id,
                    },
                )
            if path == "/api/workspace":
                summarize = getattr(self.server.context.coordinator, "workspace_summary", None)
                result = summarize() if callable(summarize) else self.server.context.coordinator.workspace()
                if isinstance(result, dict):
                    result = {**result, "jobs": [], "proposals": [], "packets": []}
                if isinstance(result, dict) and "capabilities" not in result:
                    result = {
                        **result,
                        "capabilities": self.server.context.coordinator.capabilities(),
                    }
                return self._send_json(200, result)
            match = re.fullmatch(r"/api/proposals/([^/]+)", path)
            if match:
                proposal_id = unquote(match.group(1))
                _required_string(proposal_id, "proposalId", pattern=ID_RE)
                if not scoped_project:
                    raise RequestError(404, "Project-scoped route required.")
                proposal = self.server.context.coordinator.require_project_resource(scoped_project, "proposal", proposal_id)
                self.server.context.coordinator.validate_project_assets(scoped_project, proposal.get("assets", []))
                return self._send_json(200, self.server.context.coordinator.get_proposal(proposal_id))
            match = re.fullmatch(r"/api/assets/([^/]+)", path)
            if match:
                asset_id = unquote(match.group(1))
                _required_string(asset_id, "assetId", pattern=ID_RE)
                if not scoped_project:
                    raise RequestError(404, "Project-scoped route required.")
                self.server.context.coordinator.require_project_asset(scoped_project, asset_id)
                file_path, mime_type = self.server.context.coordinator.asset_file(
                    asset_id
                )
                file_path = Path(file_path)
                if (
                    mime_type not in ASSET_MIME
                    or file_path.is_symlink()
                    or not file_path.is_file()
                ):
                    raise RequestError(404, "Image reference is unavailable.")
                data = file_path.read_bytes()
                if len(data) > MAX_IMAGE_BYTES:
                    raise RequestError(404, "Image reference is unavailable.")
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/studio/":
                return self._static(self.server.studio_root, "index.html")
            if path.startswith("/studio/"):
                return self._static(
                    self.server.studio_root, path.removeprefix("/studio/")
                )
            if path == "/legacy/":
                return self._static(self.server.legacy_root, "index.html")
            if path.startswith("/legacy/"):
                return self._static(
                    self.server.legacy_root, path.removeprefix("/legacy/")
                )
            match = re.fullmatch(r"/api/jobs/([^/]+)", path)
            if match:
                job_id = unquote(match.group(1))
                _required_string(job_id, "jobId", pattern=ID_RE)
                if not scoped_project:
                    raise RequestError(404, "Project-scoped route required.")
                self.server.context.coordinator.require_project_resource(scoped_project, "job", job_id)
                return self._send_json(
                    200, self.server.context.coordinator.get_job(job_id)
                )
            match = re.fullmatch(r"/api/packets/([^/]+)", path)
            if match:
                packet_id = unquote(match.group(1))
                _required_string(packet_id, "packetId", pattern=ID_RE)
                if not scoped_project:
                    raise RequestError(404, "Project-scoped route required.")
                packet = self.server.context.coordinator.require_project_resource(scoped_project, "packet", packet_id)
                self.server.context.coordinator.validate_project_assets(scoped_project, packet.get("assets", []))
                return self._send_json(200, packet)
            match = re.fullmatch(r"/api/projects/([^/]+)/workbench", path)
            if match:
                project_id = unquote(match.group(1))
                _required_string(project_id, "projectId", pattern=ID_RE)
                return self._send_json(
                    200, self.server.context.coordinator.workbench(project_id)
                )
            if path.startswith("/api/"):
                return self._error(404, "Unknown API route.")
            return self._error(404, "Not found.")
        except RequestError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:  # noqa: BLE001 - HTTP boundary returns a controlled failure.
            self._coordinator_error(exc)

    def do_HEAD(self):
        if not self._same_origin(mutation=False):
            return self._error(403, "Only the configured loopback origin is allowed.")
        try:
            path = self._path()
            if path == "/studio/":
                return self._static(self.server.studio_root, "index.html")
            if path.startswith("/studio/"):
                return self._static(
                    self.server.studio_root, path.removeprefix("/studio/")
                )
            if path == "/legacy/":
                return self._static(self.server.legacy_root, "index.html")
            if path.startswith("/legacy/"):
                return self._static(
                    self.server.legacy_root, path.removeprefix("/legacy/")
                )
            self._error(404, "Not found.")
        except RequestError as exc:
            self._error(exc.status, str(exc))

    def do_POST(self):
        if not self._authorized_mutation():
            return self._error(
                403,
                "Invalid loopback origin or workbench session. Reconnect before changing project state.",
            )
        try:
            path = self._path()
            scoped_project = None
            project_route = re.fullmatch(r"/api/projects/([^/]+)(/.*)", path)
            if project_route:
                scoped_project = unquote(project_route.group(1))
                _required_string(scoped_project, "projectId", pattern=ID_RE)
                path = project_route.group(2)
            if scoped_project and path != "/settings" and not re.match(r"/(?:assets|proposals|packets|jobs|concepts)(?:/|$)", path):
                raise RequestError(404, "Unknown project-scoped route.")
            if scoped_project and path.startswith("/") and path != "/settings":
                path = "/api" + path
            if path == "/api/projects" and scoped_project is None:
                body = self._read_json()
                _exact_fields(body, {"title", "workflow"}, {"title", "workflow"})
                if body["workflow"] != "objects-v1":
                    raise RequestError(400, "New projects must use objects-v1.")
                project = self.server.context.coordinator.create_project(
                    operator_id=self.server.context.operator_id, title=body["title"], workflow=body["workflow"])
                return self._send_json(201, {"project": project})
            if path == "/settings" and scoped_project:
                body = self._read_json()
                _exact_fields(body, {"title", "archived"}, set())
                if not body:
                    raise RequestError(400, "Provide at least one project setting.")
                project = self.server.context.coordinator.update_project_settings(
                    operator_id=self.server.context.operator_id, project_id=scoped_project,
                    title=body.get("title"), archived=body.get("archived"))
                return self._send_json(200, {"project": project})
            if path.startswith("/api/") and not scoped_project and path not in {"/api/projects", "/api/workspace"}:
                # Resource mutations must carry an explicit project scope.
                raise RequestError(404, "Project-scoped route required.")
            if path == "/api/assets":
                body = self._read_json(max_bytes=MAX_ASSET_JSON_BYTES)
                _exact_fields(
                    body,
                    {"name", "mimeType", "dataBase64", "purpose"},
                    {"name", "mimeType", "dataBase64", "purpose"},
                )
                validate_upload(
                    name=body["name"],
                    mime_type=body["mimeType"],
                    data_base64=body["dataBase64"],
                    purpose=body["purpose"],
                )
                asset = self.server.context.coordinator.upload_asset(
                    operator_id=self.server.context.operator_id,
                    name=body["name"],
                    mime_type=body["mimeType"],
                    data_base64=body["dataBase64"],
                    purpose=body["purpose"],
                    project_id=scoped_project,
                )
                return self._send_json(201, {"asset": asset})

            if path == "/api/concepts":
                body = self._read_json()
                _exact_fields(
                    body,
                    {"text", "projectId", "assetIds", "expectedPublicationRevision", "workflow", "changeRequest"},
                    {"text"},
                )
                text = body["text"]
                structured_change = body.get("changeRequest")
                has_structured_change = (body.get("projectId") is not None and
                    isinstance(structured_change, dict) and
                    bool(structured_change.get("fields") or structured_change.get("feedback")))
                if not isinstance(text, str) or len(text) > 5000 or (not text.strip() and not has_structured_change):
                    raise RequestError(
                        400, "Provide concept text or explicit object fields/feedback for an existing project."
                    )
                project_id = body.get("projectId")
                if scoped_project:
                    if project_id is not None and project_id != scoped_project:
                        raise RequestError(404, "Project-scoped route required.")
                    project_id = scoped_project
                if project_id is None:
                    raise RequestError(400, "Create a project before submitting a concept.")
                if project_id is not None:
                    _required_string(project_id, "projectId", pattern=ID_RE)
                workflow = body.get("workflow")
                if workflow is not None and workflow not in {"objects-v1", "collect-loop-v1"}:
                    raise RequestError(400, "Unsupported workflow version.")
                change_request = body.get("changeRequest")
                if change_request is not None and not isinstance(change_request, dict):
                    raise RequestError(400, "changeRequest must be a structured object.")
                asset_ids = body.get("assetIds", [])
                if (
                    not isinstance(asset_ids, list)
                    or len(asset_ids) > 6
                    or any(
                        not isinstance(asset_id, str) or not ID_RE.fullmatch(asset_id)
                        for asset_id in asset_ids
                    )
                    or len(set(asset_ids)) != len(asset_ids)
                ):
                    raise RequestError(
                        400, "assetIds must contain up to six unique opaque IDs."
                    )
                expected_pub = body.get("expectedPublicationRevision")
                if expected_pub is not None and (
                    type(expected_pub) is not int or expected_pub < 0
                ):
                    raise RequestError(
                        400,
                        "expectedPublicationRevision must be a non-negative integer.",
                    )
                result = self.server.context.coordinator.create_concept(
                    operator_id=self.server.context.operator_id,
                    text=text.strip(),
                    project_id=project_id,
                    asset_ids=asset_ids,
                    expected_publication_revision=expected_pub,
                    **({"workflow": workflow} if workflow is not None else {}),
                    **({"change_request": change_request} if change_request is not None else {}),
                )
                return self._send_json(201, result)

            match = re.fullmatch(r"/api/proposals/([^/]+)/(cancel|reconcile)", path)
            if match:
                proposal_id, action = unquote(match.group(1)), match.group(2)
                _required_string(proposal_id, "proposalId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "proposal", proposal_id)
                body = self._read_json()
                _exact_fields(body, set(), set())
                handler = getattr(self.server.context.coordinator, action + "_proposal")
                result = handler(operator_id=self.server.context.operator_id, proposal_id=proposal_id)
                return self._send_json(200, result)

            match = re.fullmatch(r"/api/proposals/([^/]+)/answers", path)
            if match:
                proposal_id = unquote(match.group(1))
                _required_string(proposal_id, "proposalId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "proposal", proposal_id)
                body = self._read_json()
                _exact_fields(
                    body,
                    {"expectedRevision", "answers"},
                    {"expectedRevision", "answers"},
                )
                if (
                    type(body["expectedRevision"]) is not int
                    or body["expectedRevision"] < 0
                    or not isinstance(body["answers"], dict)
                    or len(body["answers"]) > 64
                ):
                    raise RequestError(
                        400, "Proposal answers or expected revision are invalid."
                    )
                for key, value in body["answers"].items():
                    _required_string(key, "answer key", max_length=120)
                    if (
                        not isinstance(value, (str, int, float, bool, list, dict))
                        or len(json.dumps(value, ensure_ascii=False, allow_nan=False))
                        > 2000
                    ):
                        raise RequestError(
                            400, "An answer value is unsupported or too large."
                        )
                result = self.server.context.coordinator.answer_proposal(
                    operator_id=self.server.context.operator_id,
                    proposal_id=proposal_id,
                    expected_revision=body["expectedRevision"],
                    answers=body["answers"],
                )
                return self._send_json(200, result)

            match = re.fullmatch(r"/api/proposals/([^/]+)/freeze", path)
            if match:
                proposal_id = unquote(match.group(1))
                _required_string(proposal_id, "proposalId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "proposal", proposal_id)
                body = self._read_json()
                _exact_fields(
                    body,
                    {
                        "expectedRevision",
                        "expectedPublicationRevision",
                        "reviewedProposal",
                    },
                    {
                        "expectedRevision",
                        "expectedPublicationRevision",
                        "reviewedProposal",
                    },
                )
                revision = body["expectedRevision"]
                publication_revision = body["expectedPublicationRevision"]
                reviewed = body["reviewedProposal"]
                if (
                    type(revision) is not int
                    or revision < 0
                    or type(publication_revision) is not int
                    or publication_revision < 0
                    or not isinstance(reviewed, dict)
                ):
                    raise RequestError(
                        400, "Freeze request versions or proposal are invalid."
                    )
                if (
                    reviewed.get("id") != proposal_id
                    or reviewed.get("revision") != revision
                ):
                    raise RequestError(
                        409,
                        "The reviewed proposal does not match this path and revision.",
                    )
                result = self.server.context.coordinator.freeze_proposal(
                    operator_id=self.server.context.operator_id,
                    proposal_id=proposal_id,
                    expected_revision=revision,
                    expected_publication_revision=publication_revision,
                    reviewed_proposal=reviewed,
                )
                return self._send_json(201, result)

            if path == "/api/jobs":
                body = self._read_json()
                _exact_fields(
                    body, {"packetId", "idempotencyKey"}, {"packetId", "idempotencyKey"}
                )
                packet_id = _required_string(
                    body["packetId"], "packetId", pattern=ID_RE
                )
                self.server.context.coordinator.require_project_resource(scoped_project, "packet", packet_id)
                idempotency_key = _required_string(
                    body["idempotencyKey"], "idempotencyKey", max_length=200
                )
                result = self.server.context.coordinator.create_job(
                    operator_id=self.server.context.operator_id,
                    packet_id=packet_id,
                    idempotency_key=idempotency_key,
                )
                return self._send_json(202, result)

            match = re.fullmatch(r"/api/jobs/([^/]+)/preview", path)
            if match:
                job_id = unquote(match.group(1))
                _required_string(job_id, "jobId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "job", job_id)
                body = self._read_json()
                _exact_fields(body, set(), set())
                result = self.server.context.coordinator.preview_job(
                    operator_id=self.server.context.operator_id, job_id=job_id
                )
                return self._send_json(202, result)

            match = re.fullmatch(r"/api/jobs/([^/]+)/reconcile", path)
            if match:
                job_id = unquote(match.group(1))
                _required_string(job_id, "jobId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "job", job_id)
                body = self._read_json()
                _exact_fields(body, set(), set())
                result = self.server.context.coordinator.reconcile_job(
                    operator_id=self.server.context.operator_id, job_id=job_id
                )
                return self._send_json(200, result)

            match = re.fullmatch(r"/api/jobs/([^/]+)/cancel", path)
            if match:
                job_id = unquote(match.group(1))
                _required_string(job_id, "jobId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "job", job_id)
                body = self._read_json()
                _exact_fields(body, set(), set())
                result = self.server.context.coordinator.cancel_job(
                    operator_id=self.server.context.operator_id, job_id=job_id
                )
                return self._send_json(200, result)

            match = re.fullmatch(r"/api/jobs/([^/]+)/decision", path)
            if match:
                job_id = unquote(match.group(1))
                _required_string(job_id, "jobId", pattern=ID_RE)
                self.server.context.coordinator.require_project_resource(scoped_project, "job", job_id)
                body = self._read_json()
                _exact_fields(
                    body,
                    {"decision", "candidateCommit", "expectedPublicationRevision"},
                    {"decision", "candidateCommit", "expectedPublicationRevision"},
                )
                if body["decision"] not in {"accept", "reject"}:
                    raise RequestError(400, "decision must be accept or reject.")
                candidate_commit = _required_string(
                    body["candidateCommit"], "candidateCommit", max_length=128
                )
                revision = body["expectedPublicationRevision"]
                if type(revision) is not int or revision < 0:
                    raise RequestError(
                        400,
                        "expectedPublicationRevision must be a non-negative integer.",
                    )
                result = self.server.context.coordinator.decide_job(
                    operator_id=self.server.context.operator_id,
                    job_id=job_id,
                    decision=body["decision"],
                    candidate_commit=candidate_commit,
                    expected_publication_revision=revision,
                )
                return self._send_json(200, result)

            return self._error(
                404, "Unknown API route. The legacy workbench is read-only."
            )
        except RequestError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:  # noqa: BLE001 - HTTP boundary returns a controlled failure.
            self._coordinator_error(exc)

    def _coordinator_error(self, exc: Exception):
        status_value = getattr(exc, "status", None)
        if isinstance(status_value, int) and 400 <= status_value <= 599:
            serializer = getattr(exc, "as_dict", None)
            if callable(serializer):
                try:
                    return self._send_json(status_value, serializer())
                except Exception as serialization_error:  # noqa: BLE001 - Fall back to the safe error envelope.
                    self.log_error(
                        "Coordinator error serialization failed: %s",
                        type(serialization_error).__name__,
                    )
            self._send_json(
                status_value,
                {"error": str(exc) or "The request could not be completed."},
            )
            return
        name = type(exc).__name__.lower()
        if name in {"notfound", "notfounderror"} or name.endswith("notfound"):
            status = 404
        elif (
            name in {"conflict", "concurrencyconflict", "staleproposal"}
            or "conflict" in name
        ):
            status = 409
        elif name in {"blocked", "capabilityblocked"} or "blocked" in name:
            status = 423
        elif isinstance(exc, (ValueError, TypeError)):
            status = 400
        else:
            status = 503
        message = (
            str(exc).strip()
            or "The local workflow service could not complete this request."
        )
        if status == 503 and len(message) > 500:
            message = "The local workflow service is unavailable. Its state was not confirmed."
        self._send_json(status, {"error": message})


def make_server(
    coordinator,
    *,
    host="127.0.0.1",
    port=8765,
    studio_root=STUDIO_ROOT,
    legacy_root=LEGACY_ROOT,
):
    if host != "127.0.0.1":
        raise ValueError(
            "Studio is a local-only service and can bind only to 127.0.0.1."
        )
    context = StudioContext(coordinator)
    return StudioHTTPServer(
        (host, port), context, studio_root=studio_root, legacy_root=legacy_root
    )


def main():
    parser = argparse.ArgumentParser(
        description="Start the local-only GM Studio API and frontend."
    )
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="Server-owned project directory. The API never accepts a client project path.",
    )
    parser.add_argument("--state-root", help="Private service data directory.")
    parser.add_argument(
        "--test-data",
        action="store_true",
        help="Mark decisions and publication as test-only; this does not stand in for production approval.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    from .coordinator import Coordinator

    coordinator = Coordinator(
        Path(args.project_root).resolve(),
        state_root=Path(args.state_root).resolve() if args.state_root else None,
        test_data=args.test_data,
    )
    server = make_server(coordinator, host=args.host, port=args.port)
    print(f"GM Studio is available at http://127.0.0.1:{server.server_port}/studio/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        close = getattr(coordinator, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
