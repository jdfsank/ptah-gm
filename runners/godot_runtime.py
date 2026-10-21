"""Private per-attempt Godot user, cache, settings, and temporary paths."""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import ssl
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


_SYSTEM_PATHS = (
    Path("/Library/Developer/CommandLineTools/usr/bin"),
    Path("/usr/bin"),
    Path("/bin"),
    Path("/usr/sbin"),
    Path("/sbin"),
)

_SYSTEM_CA_BUNDLE = Path("/etc/ssl/cert.pem")
_SYSTEM_CA_BUNDLE_MAX_BYTES = 16 * 1024 * 1024
_CA_INTERPOSER_SOURCE = Path(__file__).resolve().with_name("godot_ca_interposer.m")
_CLANG = Path("/Library/Developer/CommandLineTools/usr/bin/clang")
_MACOS_SDK = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk")


class GodotRuntimeError(RuntimeError):
    """A trusted runtime or CA preparation failure that must stop Godot launch."""


def _read_and_validate_system_ca_bundle() -> bytes:
    """Read, canonicalize, and validate the fixed root-owned public CA bundle.

    Some system bundle distributions place public annotations between PEM
    blocks. Only complete certificate blocks are copied; their decoded DER is
    preserved exactly and re-encoded as canonical PEM for Security.framework.
    """
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise GodotRuntimeError("platform cannot safely open the trusted system CA bundle")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(_SYSTEM_CA_BUNDLE, flags)
    except OSError as exc:
        raise GodotRuntimeError(f"trusted system CA bundle is unavailable: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or stat.S_IMODE(before.st_mode) & 0o022
                or before.st_size <= 0 or before.st_size > _SYSTEM_CA_BUNDLE_MAX_BYTES):
            raise GodotRuntimeError("trusted system CA bundle has unsafe file metadata")
        content = bytearray()
        while len(content) <= _SYSTEM_CA_BUNDLE_MAX_BYTES:
            chunk = os.read(
                descriptor,
                min(64 * 1024, _SYSTEM_CA_BUNDLE_MAX_BYTES + 1 - len(content)),
            )
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    stable_metadata = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
    ) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    )
    if not stable_metadata or len(content) != before.st_size:
        raise GodotRuntimeError("trusted system CA bundle changed while it was read")
    canonical_pem = _canonicalize_certificate_blocks(bytes(content))
    try:
        pem = canonical_pem.decode("ascii")
        certificate_blocks = pem.count("-----BEGIN CERTIFICATE-----")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=pem)
        parsed_certificates = len(context.get_ca_certs())
    except (UnicodeError, ssl.SSLError, ValueError) as exc:
        raise GodotRuntimeError("trusted system CA bundle contains no valid PEM certificate set") from exc
    if certificate_blocks <= 0 or parsed_certificates != certificate_blocks:
        raise GodotRuntimeError("trusted system CA bundle contains invalid or missing certificates")
    return canonical_pem


def _canonicalize_certificate_blocks(source: bytes) -> bytes:
    begin_marker = b"-----BEGIN CERTIFICATE-----"
    end_marker = b"-----END CERTIFICATE-----"
    marker_pattern = re.compile(rb"-----BEGIN [^-]+-----|-----END [^-]+-----")
    markers = marker_pattern.findall(source)
    if not markers or any(marker not in {begin_marker, end_marker} for marker in markers):
        raise GodotRuntimeError("trusted system CA bundle has unsupported or missing PEM markers")

    blocks: list[bytes] = []
    cursor = 0
    while True:
        begin = source.find(begin_marker, cursor)
        if begin < 0:
            if source.find(end_marker, cursor) >= 0:
                raise GodotRuntimeError("trusted system CA bundle has an unmatched certificate end marker")
            break
        if source.find(end_marker, cursor, begin) >= 0:
            raise GodotRuntimeError("trusted system CA bundle has an unmatched certificate end marker")

        body_start = begin + len(begin_marker)
        end = source.find(end_marker, body_start)
        next_begin = source.find(begin_marker, body_start)
        if end < 0 or (next_begin >= 0 and next_begin < end):
            raise GodotRuntimeError("trusted system CA bundle has incomplete or nested certificate markers")

        body = source[body_start:end]
        compact = bytearray()
        for value in body:
            if value in b" \t\r\n\v\f":
                continue
            if value not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=":
                raise GodotRuntimeError("trusted system CA bundle has invalid certificate data")
            compact.append(value)
        try:
            der = base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise GodotRuntimeError("trusted system CA bundle has invalid certificate base64") from exc
        if not der or base64.b64encode(der) != bytes(compact):
            raise GodotRuntimeError("trusted system CA bundle has non-canonical or empty certificate data")

        encoded = base64.b64encode(der)
        lines = [encoded[offset:offset + 64] for offset in range(0, len(encoded), 64)]
        blocks.append(begin_marker + b"\n" + b"\n".join(lines) + b"\n" + end_marker)
        cursor = end + len(end_marker)

    if not blocks:
        raise GodotRuntimeError("trusted system CA bundle contains no complete certificates")
    return b"\n".join(blocks) + b"\n"


def _private_file_matches(path: Path, expected: bytes) -> bool:
    if path.is_symlink() or not path.exists():
        return False
    metadata = path.stat(follow_symlinks=False)
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and path.read_bytes() == expected
    )


def _c_string_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


@dataclass(frozen=True)
class GodotRuntime:
    """A private writable home tree contained in the runner's disposable root."""

    root: Path
    home: Path
    runtime: Path
    cache: Path
    settings: Path
    data: Path
    tmp: Path
    editor_data: Path
    _ca_assets: dict[str, Path] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def create(cls, base: str | os.PathLike[str]) -> "GodotRuntime":
        raw_root = Path(base)
        if not raw_root.is_absolute():
            raise ValueError("Godot runtime root must be an absolute path")
        if raw_root.is_symlink():
            raise ValueError("Godot runtime root cannot be a symlink")
        raw_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Godot runtime root must be a directory")
        if stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise ValueError("Godot runtime root must be private (0700)")

        paths = {
            "home": root / "home",
            "runtime": root / "runtime",
            "cache": root / "cache",
            "settings": root / "settings",
            "data": root / "data",
            "tmp": root / "tmp",
            "editor_data": root / "editor_data",
        }
        for path in paths.values():
            if path.is_symlink():
                raise ValueError("Godot runtime directories cannot be symlinks")
            path.mkdir(mode=0o700, parents=False, exist_ok=True)
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                raise ValueError("Godot runtime directories must be private (0700)")

        # macOS Godot stores editor settings and help caches below HOME even
        # when XDG variables are set. Pre-create only these private locations.
        macos_dirs = (
            paths["home"] / "Library",
            paths["home"] / "Library" / "Application Support",
            paths["home"] / "Library" / "Application Support" / "Godot",
            paths["home"] / "Library" / "Caches",
            paths["home"] / "Library" / "Caches" / "Godot",
            paths["home"] / "Library" / "Preferences",
        )
        for path in macos_dirs:
            if path.is_symlink():
                raise ValueError("Godot private home cannot contain symlinked settings paths")
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise ValueError("Godot private settings directories must be private (0700)")

        return cls(root=root, **paths)

    def environment(self, source: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return a small environment with no inherited real-home or auth paths."""
        source = os.environ if source is None else source
        env = {
            "PATH": os.pathsep.join(str(path) for path in _SYSTEM_PATHS if path.is_dir()),
            "HOME": str(self.home),
            "CFFIXED_USER_HOME": str(self.home),
            "TMPDIR": str(self.tmp),
            "TMP": str(self.tmp),
            "TEMP": str(self.tmp),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_CONFIG_HOME": str(self.settings),
            "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.data / "state"),
            # Godot otherwise launches the user's login shell to reconstruct
            # its environment, escaping this deliberately minimal environment.
            "__GODOT_SHELL_ENV_SET": "1",
        }
        for name in ("LANG", "LC_ALL"):
            value = source.get(name)
            if isinstance(value, str) and value:
                env[name] = value
        return env

    def configure_editor_tls(
        self, engine_version: str, executable: str | os.PathLike[str] | None = None
    ) -> tuple[Path, Path]:
        """Point the private editor settings at the trusted private CA bundle.

        Godot's macOS editor uses ``network/tls/editor_tls_certificates``;
        unlike the project setting used by a running game, this lives in the
        self-contained editor settings resource. The bundle is the same
        root-owned public CA source used by the trusted child interposer.
        """
        match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?[^\r\n]*", engine_version)
        if match is None:
            raise ValueError("Godot engine version cannot name a private editor settings file")
        private_executable = self.private_executable(executable) if executable is not None else None
        bundle_path = self._ensure_system_ca_bundle()

        private_app = None
        if private_executable is not None:
            private_app = next(
                (parent for parent in private_executable.parents if parent.name.endswith(".app")),
                None,
            )
            if private_app is not None and not private_app.is_relative_to(self.root):
                private_app = None
        if private_app is not None:
            editor_data = private_app.parent / "editor_data"
        elif sys.platform == "darwin":
            editor_data = self.home / "Library" / "Application Support" / "Godot"
        else:
            editor_data = self.settings / "godot"
        if editor_data.is_symlink():
            raise ValueError("private Godot editor data path cannot be a symlink")
        editor_data.mkdir(mode=0o700, exist_ok=True)
        if stat.S_IMODE(editor_data.stat().st_mode) & 0o077:
            raise ValueError("private Godot editor data directory must be private (0700)")
        settings_path = editor_data / f"editor_settings-{match.group(1)}.{match.group(2)}.tres"
        if settings_path.is_symlink():
            raise ValueError("private Godot editor settings cannot be a symlink")
        settings = (
            '[gd_resource type="EditorSettings" format=3]\n\n'
            '[resource]\n'
            f"network/tls/editor_tls_certificates = {json.dumps(str(bundle_path))}\n"
        ).encode("utf-8")
        if settings_path.exists():
            settings_stat = settings_path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(settings_stat.st_mode)
                    or settings_stat.st_uid != os.getuid()
                    or stat.S_IMODE(settings_stat.st_mode) & 0o077
                    or settings_path.read_bytes() != settings):
                raise ValueError("private Godot editor settings path is unsafe or has different content")
        else:
            with settings_path.open("xb") as stream:
                stream.write(settings)
            settings_path.chmod(0o600)
        return settings_path, bundle_path

    def _ensure_system_ca_bundle(self) -> Path:
        """Materialize a private copy of the fixed host public CA bundle."""
        cached = self._ca_assets.get("bundle")
        if cached is not None:
            if not _private_file_matches(cached, _read_and_validate_system_ca_bundle()):
                raise GodotRuntimeError("private trusted CA bundle changed after runtime preparation")
            return cached

        content = _read_and_validate_system_ca_bundle()
        support_dir = self.root / "trusted-ca"
        if support_dir.is_symlink():
            raise GodotRuntimeError("private trusted CA support directory cannot be a symlink")
        support_dir.mkdir(mode=0o700, exist_ok=True)
        support_stat = support_dir.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(support_stat.st_mode) or support_stat.st_uid != os.getuid()
                or stat.S_IMODE(support_stat.st_mode) != 0o700):
            raise GodotRuntimeError("private trusted CA support directory must be user-owned (0700)")

        bundle_path = support_dir / "system-ca.pem"
        if bundle_path.is_symlink():
            raise GodotRuntimeError("private trusted CA bundle cannot be a symlink")
        if bundle_path.exists():
            if not _private_file_matches(bundle_path, content):
                raise GodotRuntimeError("private trusted CA bundle is unsafe or differs from the host bundle")
        else:
            descriptor = os.open(
                bundle_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                offset = 0
                while offset < len(content):
                    offset += os.write(descriptor, content[offset:])
            finally:
                os.close(descriptor)
            bundle_path.chmod(0o600)

        self._ca_assets.update({"support": support_dir, "bundle": bundle_path})
        return bundle_path

    def prepare_trusted_ca_interposer(self) -> tuple[Path, Path, Path]:
        """Build the fixed host-owned trust interposer before launching Godot."""
        if sys.platform != "darwin":
            raise GodotRuntimeError("trusted Godot CA interposition requires macOS")
        cached_support = self._ca_assets.get("support")
        cached_library = self._ca_assets.get("interposer")
        cached_bundle = self._ca_assets.get("bundle")
        cached_binding = self._ca_assets.get("compile_binding")
        if cached_support and cached_bundle and cached_library:
            if (cached_support.is_dir() and not cached_support.is_symlink()
                    and _private_file_matches(cached_bundle, _read_and_validate_system_ca_bundle())
                    and cached_library.is_file() and not cached_library.is_symlink()
                    and cached_binding == cached_bundle):
                return cached_support, cached_bundle, cached_library
            raise GodotRuntimeError("prepared trusted CA runtime assets changed before Godot launch")

        bundle_path = self._ensure_system_ca_bundle()
        support_dir = bundle_path.parent
        if not _CLANG.is_file() or not os.access(_CLANG, os.X_OK) or not _MACOS_SDK.is_dir():
            raise GodotRuntimeError("Apple Command Line Tools (clang and macOS SDK) are required for Godot CA interposition")
        if (_CA_INTERPOSER_SOURCE.is_symlink() or not _CA_INTERPOSER_SOURCE.is_file()
                or _CA_INTERPOSER_SOURCE.resolve().parent != Path(__file__).resolve().parent):
            raise GodotRuntimeError("trusted Godot CA interposer source is unavailable")

        library_path = support_dir / "libgodot_trusted_ca.dylib"
        pending_path = support_dir / "libgodot_trusted_ca.pending.dylib"
        if library_path.is_symlink() or pending_path.is_symlink():
            raise GodotRuntimeError("private trusted CA library path cannot be a symlink")
        if pending_path.exists():
            pending_path.unlink()
        compile_argv = [
            str(_CLANG),
            "-isysroot", str(_MACOS_SDK),
            "-fobjc-arc",
            "-dynamiclib",
            "-framework", "Foundation",
            "-framework", "Security",
            "-framework", "CoreFoundation",
            "-DSTUDIO_GODOT_CA_BUNDLE_PATH=" + _c_string_literal(str(bundle_path)),
            "-o", str(pending_path),
            str(_CA_INTERPOSER_SOURCE),
        ]
        try:
            completed = subprocess.run(
                compile_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "HOME": str(self.home),
                    "TMPDIR": str(self.tmp),
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GodotRuntimeError(f"trusted Godot CA interposer compilation could not run: {exc}") from exc
        if completed.returncode != 0 or not pending_path.is_file():
            diagnostic = (completed.stderr or completed.stdout).strip()[-2000:]
            raise GodotRuntimeError(
                "trusted Godot CA interposer compilation failed"
                + (f": {diagnostic}" if diagnostic else "")
            )
        pending_stat = pending_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(pending_stat.st_mode) or pending_stat.st_uid != os.getuid():
            raise GodotRuntimeError("compiled trusted Godot CA interposer has unsafe metadata")
        pending_path.chmod(0o700)
        os.replace(pending_path, library_path)
        self._ca_assets.update({
            "support": support_dir,
            "bundle": bundle_path,
            "interposer": library_path,
            "compile_binding": bundle_path,
        })
        return support_dir, bundle_path, library_path

    def private_executable(self, executable: str | os.PathLike[str]) -> Path:
        """Return a reusable self-contained Godot executable inside this runtime.

        Godot's macOS self-contained marker must live beside the executable.
        Copy an installed app bundle into the private runtime before launching
        it, so editor data never falls back to the real HOME. Non-app binaries
        are returned unchanged; the caller still constrains their file access.
        """
        import shutil

        source = Path(executable).resolve(strict=True)
        if not source.is_file():
            raise ValueError("Godot executable must be a regular file")
        source_app = next((parent for parent in source.parents if parent.name.endswith(".app")), None)
        if source_app is None:
            return source
        if source.is_relative_to(self.root):
            private_executable = source
            private_app = source_app
        else:
            try:
                relative_executable = source.relative_to(source_app)
            except ValueError as exc:
                raise ValueError("Godot executable must be contained by its app bundle") from exc
            private_app = self.root / source_app.name
            if private_app.is_symlink():
                raise ValueError("private Godot app bundle cannot be a symlink")
            if not private_app.exists():
                shutil.copytree(source_app, private_app, symlinks=True, copy_function=shutil.copy2)
            elif not private_app.is_dir():
                raise ValueError("private Godot app bundle path is not a directory")
            private_executable = private_app / relative_executable
        marker = private_executable.parent / "._sc_"
        if marker.is_symlink() or (marker.exists() and not marker.is_file()):
            raise ValueError("Godot self-contained marker path is invalid")
        marker.touch(mode=0o600, exist_ok=True)
        if not private_executable.is_file() or not os.access(private_executable, os.X_OK):
            raise ValueError("private Godot executable is not executable")
        return private_executable


def sandboxed_godot_argv(
    executable: str | os.PathLike[str],
    arguments: Sequence[str],
    *,
    project_root: str | os.PathLike[str],
    runtime: GodotRuntime,
    protected_paths: Sequence[str | os.PathLike[str]] = (),
    uid_write_paths: Sequence[str | os.PathLike[str]] = (),
    image_import_write_paths: Sequence[str | os.PathLike[str]] = (),
    allow_graphics: bool = False,
) -> list[str]:
    """Wrap one Godot command in a nested deny-default sandbox.

    Project source is read-only except exact missing UID outputs or image
    import metadata granted by trusted preparation in a disposable copy. The
    private runtime root owns all home, settings, cache, and temporary writes.
    Network access has no enabling option and remains denied. On macOS, a
    trusted host-built interposer supplies anchors from the fixed system CA
    bundle; Godot cannot write the bundle, library, or support directory.
    """
    from .common import _seatbelt_quote, strict_sandbox_rules

    raw_project = Path(project_root).absolute()
    if raw_project.is_symlink():
        raise ValueError("Godot project root cannot be a symlink")
    project = raw_project.resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Godot project root must be a directory")
    cache = project / ".godot"
    if cache.is_symlink():
        raise ValueError("Godot project cache cannot be a symlink")
    cache.mkdir(mode=0o700, exist_ok=True)
    if stat.S_IMODE(cache.stat().st_mode) & 0o077:
        raise ValueError("Godot project cache must be private (0700)")

    godot = runtime.private_executable(executable)
    if not godot.is_file() or not os.access(godot, os.X_OK):
        raise ValueError("Godot executable must be an executable file")
    support_dir, ca_bundle, ca_interposer = runtime.prepare_trusted_ca_interposer()
    app_roots = [godot.parent]
    for parent in godot.parents:
        if parent.name.endswith(".app"):
            app_roots.append(parent)
            break

    protected = [Path(path).resolve(strict=False) for path in protected_paths]
    uid_sidecars: set[Path] = set()
    for value in uid_write_paths:
        raw_sidecar = Path(value)
        if not raw_sidecar.is_absolute():
            raw_sidecar = raw_project / raw_sidecar
        try:
            lexical_relative = raw_sidecar.relative_to(raw_project)
        except ValueError:
            try:
                # macOS exposes common roots through aliases such as /var ->
                # /private/var. Accept the canonical spelling while still
                # checking every path component below the project root.
                lexical_relative = raw_sidecar.relative_to(project)
            except ValueError as exc:
                raise ValueError("trusted UID sidecar must stay inside the Godot project") from exc
        if any(part in {"", ".", ".."} for part in lexical_relative.parts):
            raise ValueError("trusted UID path cannot contain traversal components")
        cursor = project
        for part in lexical_relative.parts[:-1]:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("trusted UID path cannot contain symlinked directories")
        if raw_sidecar.is_symlink():
            raise ValueError("trusted UID sidecar cannot be a symlink")
        sidecar = raw_sidecar.resolve(strict=False)
        if not sidecar.is_relative_to(project):
            raise ValueError("trusted UID sidecar must stay inside the Godot project")
        relative = sidecar.relative_to(project).as_posix()
        if not relative.endswith(".gd.uid"):
            raise ValueError("trusted UID output must end in .gd.uid")
        source = Path(str(sidecar)[:-4])
        source_relative = source.relative_to(project).as_posix()
        source_parts = PurePosixPath(source_relative).parts
        trusted_source = (
            (len(source_parts) >= 2 and source_parts[0] == "scripts")
            or source_relative == "studio/runtime.gd"
        )
        if not trusted_source or source.suffix != ".gd":
            raise ValueError("trusted UID output must accompany scripts/*.gd or studio/runtime.gd")
        if source.is_symlink() or not source.is_file():
            raise ValueError("trusted UID output must accompany an existing regular .gd source")
        if sidecar.exists():
            raise ValueError("trusted UID output must be a missing sidecar")
        if any(sidecar == deny or sidecar.is_relative_to(deny) for deny in protected):
            raise ValueError("trusted UID output overlaps a protected path")
        uid_sidecars.add(sidecar)
    image_imports: set[Path] = set()
    if image_import_write_paths:
        from .image_imports import validate_import_path
        if not {'--editor', '--recovery-mode', '--import'} <= set(arguments):
            raise ValueError("image import writes require a recovery editor import")
        for value in image_import_write_paths:
            path = validate_import_path(project, value)
            if path.exists():
                raise ValueError("image import output must be a missing sidecar")
            if any(path == deny or path.is_relative_to(deny) for deny in protected):
                raise ValueError("image import output overlaps a protected path")
            image_imports.add(path)
    rules = strict_sandbox_rules(
        project,
        read_roots=[project, runtime.root],
        write_roots=[
            cache,
            runtime.home,
            runtime.runtime,
            runtime.cache,
            runtime.settings,
            runtime.data,
            runtime.tmp,
            runtime.editor_data,
        ],
        protected_paths=protected,
        extra_read_paths=app_roots,
        allow_graphics=allow_graphics,
        allow_internet=False,
    )
    # The private runtime has individual write grants for Godot settings, but
    # the trust material is immutable to every child process in the sandbox.
    rules.append(f'(deny file-write* (subpath {_seatbelt_quote(support_dir)}))')
    rules.append(f'(deny file-write* (literal {_seatbelt_quote(ca_bundle)}))')
    rules.append(f'(deny file-write* (literal {_seatbelt_quote(ca_interposer)}))')
    # A path-based deny does not protect a file if a child can hardlink it into
    # a writable directory. Godot uses atomic rename for generated files, so
    # hardlink creation is unnecessary.
    rules.append("(deny file-link)")
    # The copied app is readable/executable for launch, but is never writable
    # by Godot or a project script.
    private_app = next((parent for parent in godot.parents if parent.name.endswith(".app")), None)
    if private_app is not None and private_app.is_relative_to(runtime.root):
        rules.append(f'(deny file-write* (subpath {_seatbelt_quote(private_app)}))')
    # The generic policy supports worker processes, but a project script must
    # not use OS.execute() to start a shell, Python, Codex, or another program.
    # Godot itself remains executable for the initial sandboxed launch.
    rules = [rule for rule in rules if rule != "(allow process*)"]
    rules.append("(allow process-fork)")
    env_launcher = Path("/usr/bin/env")
    if not env_launcher.is_file():
        raise GodotRuntimeError("required /usr/bin/env launcher is unavailable")
    rules.append(f'(allow process-exec (literal {_seatbelt_quote(env_launcher)}))')
    rules.append(f'(allow process-exec (literal {_seatbelt_quote(godot)}))')
    # Preparation may write only the missing UID sidecars listed by its
    # trusted caller. Godot atomically renames a same-directory temporary file
    # whose name starts with the validated sidecar plus a hyphen. The regex is
    # anchored and cannot cross a directory boundary; no project directory or
    # source-file write grant exists.
    for path in sorted(uid_sidecars | image_imports, key=str):
        pattern = '^' + re.escape(str(path)) + r"-[^/]+$"
        pattern = pattern.replace('"', '\\"')
        rules.append(f'(allow file-write* (regex #"{pattern}"))')
        rules.append(f"(allow file-write* (literal {_seatbelt_quote(path)}))")
    sandbox = Path("/usr/bin/sandbox-exec")
    if not sandbox.is_file():
        raise FileNotFoundError("macOS sandbox-exec is unavailable")
    normalized_arguments = list(arguments)
    index = 0
    while index < len(normalized_arguments):
        argument = normalized_arguments[index]
        if argument in {"--path", "--log-file"}:
            if index + 1 >= len(normalized_arguments):
                raise ValueError(f"Godot option {argument} requires a path")
            raw_value = Path(normalized_arguments[index + 1])
            value = raw_value.resolve(strict=argument == "--path")
            if argument == "--path":
                if value != project:
                    raise ValueError("Godot --path must match the read-only project root")
            elif not value.is_relative_to(runtime.root):
                raise ValueError("Godot log files must stay inside the private runtime root")
            normalized_arguments[index + 1] = str(value)
            index += 2
            continue
        index += 1
    return [
        str(sandbox), "-p", "".join(rules), str(env_launcher),
        f"DYLD_INSERT_LIBRARIES={ca_interposer}", str(godot), *normalized_arguments,
    ]
