#!/usr/bin/env python3
"""Install this repository's bundled Godot MCP editor plugin into a project.

The installer only writes to the requested project directory. It does not
modify global Codex, Claude, or other client configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPOSITORY_ROOT / "addons" / "godot_mcp"
PLUGIN_CONFIG = "res://addons/godot_mcp/plugin.cfg"
DEFAULT_PROJECT = (
    'config_version=5\n\n'
    '[application]\n'
    'config/name="Godot MCP Project"\n'
)
MACOS_ROOT_ALIASES = {
    Path("/tmp"): Path("/private/tmp"),
    Path("/var"): Path("/private/var"),
}


class InstallError(ValueError):
    """The requested project cannot safely receive the bundled plugin."""


def _tree_inventory(root: Path, *, omit_hidden: bool) -> dict[str, tuple[str, bytes | None]]:
    if root.is_symlink() or not root.is_dir():
        raise InstallError(f"expected a regular directory: {root}")
    inventory: dict[str, tuple[str, bytes | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise InstallError(f"symbolic links are not supported: {path}")
        if omit_hidden and any(part.startswith(".") for part in relative.parts):
            continue
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise InstallError(f"cannot inspect {path}: {exc}") from exc
        name = relative.as_posix()
        if stat.S_ISDIR(mode):
            inventory[name] = ("directory", None)
        elif stat.S_ISREG(mode):
            try:
                inventory[name] = ("file", path.read_bytes())
            except OSError as exc:
                raise InstallError(f"cannot read {path}: {exc}") from exc
        else:
            raise InstallError(f"only regular files and directories are supported: {path}")
    return inventory


def _godot_strings(value: str) -> list[str]:
    """Parse the string arguments in a Godot PackedStringArray expression."""
    match = re.fullmatch(r"\s*PackedStringArray\s*\((.*)\)\s*", value, re.DOTALL)
    if not match:
        raise InstallError(
            "project.godot [editor_plugins] enabled must use PackedStringArray(...)"
        )
    body = match.group(1)
    result: list[str] = []
    index = 0
    while True:
        while index < len(body) and body[index].isspace():
            index += 1
        if index == len(body):
            return result
        if body[index] == ",":
            index += 1
            continue
        if body[index] != '"':
            raise InstallError("cannot safely preserve a non-string editor plugin entry")
        start = index
        index += 1
        escaped = False
        while index < len(body):
            char = body[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                index += 1
                break
            index += 1
        else:
            raise InstallError("project.godot has an unterminated editor plugin string")
        token = body[start:index]
        try:
            parsed = json.loads(token)
        except json.JSONDecodeError as exc:
            raise InstallError("cannot parse an editor plugin string safely") from exc
        if not isinstance(parsed, str):
            raise InstallError("editor plugin entries must be strings")
        result.append(parsed)
        while index < len(body) and body[index].isspace():
            index += 1
        if index < len(body) and body[index] != ",":
            raise InstallError("project.godot has an invalid editor plugin array")


def _packed_strings(values: list[str]) -> str:
    return "PackedStringArray(" + ", ".join(
        json.dumps(value, ensure_ascii=False) for value in values
    ) + ")"


def _enable_plugin(project_text: str) -> str:
    newline = "\r\n" if "\r\n" in project_text else "\n"
    lines = project_text.splitlines()
    sections = [
        index for index, line in enumerate(lines)
        if re.fullmatch(r"\s*\[editor_plugins\]\s*(?:;.*)?", line)
    ]
    if len(sections) > 1:
        raise InstallError("project.godot contains multiple [editor_plugins] sections")

    if not sections:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", "[editor_plugins]", f"enabled={_packed_strings([PLUGIN_CONFIG])}"])
        return newline.join(lines) + newline

    start = sections[0]
    end = next(
        (index for index in range(start + 1, len(lines))
         if re.fullmatch(r"\s*\[[^\]]+\]\s*(?:;.*)?", lines[index])),
        len(lines),
    )
    enabled_lines = [
        index for index in range(start + 1, end)
        if re.match(r"^\s*enabled\s*=", lines[index])
    ]
    if len(enabled_lines) > 1:
        raise InstallError("project.godot has multiple editor_plugins enabled settings")
    if not enabled_lines:
        lines.insert(start + 1, f"enabled={_packed_strings([PLUGIN_CONFIG])}")
        return newline.join(lines) + (newline if project_text.endswith(("\n", "\r")) else "")

    index = enabled_lines[0]
    key = re.match(r"^(\s*enabled\s*=\s*)(.*)$", lines[index])
    assert key is not None
    values = _godot_strings(key.group(2))
    if PLUGIN_CONFIG in values:
        return project_text
    values.append(PLUGIN_CONFIG)
    lines[index] = key.group(1) + _packed_strings(values)
    return newline.join(lines) + (newline if project_text.endswith(("\n", "\r")) else "")


def _check_project_paths(project: Path) -> tuple[Path, Path, Path]:
    if project.is_symlink():
        raise InstallError(f"project directory cannot be a symbolic link: {project}")
    if project.exists() and not project.is_dir():
        raise InstallError(f"project path is not a directory: {project}")
    settings = project / "project.godot"
    addons = project / "addons"
    plugin = addons / "godot_mcp"
    for path in (settings, addons, plugin):
        if path.is_symlink():
            raise InstallError(f"symbolic links are not supported at install paths: {path}")
    if settings.exists() and not settings.is_file():
        raise InstallError(f"project settings are not a regular file: {settings}")
    if addons.exists() and not addons.is_dir():
        raise InstallError(f"addons path is not a directory: {addons}")
    if plugin.exists() and not plugin.is_dir():
        raise InstallError(f"plugin destination is not a directory: {plugin}")
    return settings, addons, plugin


def _canonicalize_project_path(requested: Path) -> Path:
    """Reject existing path symlinks, except verified root-owned macOS aliases."""
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    requested = Path(os.path.abspath(requested))
    current = Path(requested.anchor)

    for part in requested.parts[1:]:
        candidate = current / part
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            current = candidate
            continue
        except OSError as exc:
            raise InstallError(f"cannot inspect project path {candidate}: {exc}") from exc

        if not stat.S_ISLNK(mode):
            current = candidate
            continue

        expected_target = MACOS_ROOT_ALIASES.get(candidate)
        metadata = candidate.lstat()
        if expected_target is None or metadata.st_uid != 0:
            raise InstallError(
                f"symbolic links in the project path are not supported: {candidate}"
            )
        try:
            raw_target = os.readlink(candidate)
            target = Path(raw_target)
            if not target.is_absolute():
                target = candidate.parent / target
            target = Path(os.path.normpath(target))
        except OSError as exc:
            raise InstallError(f"cannot inspect system path alias {candidate}: {exc}") from exc
        if target != expected_target:
            raise InstallError(f"unexpected target for system path alias {candidate}")

        # The verified alias must lead through real system directories. This
        # prevents another link in the exception path from becoming trusted.
        resolved = Path(expected_target.anchor)
        for target_part in expected_target.parts[1:]:
            resolved = resolved / target_part
            try:
                target_mode = resolved.lstat().st_mode
            except OSError as exc:
                raise InstallError(
                    f"cannot inspect system path alias target {resolved}: {exc}"
                ) from exc
            if stat.S_ISLNK(target_mode):
                raise InstallError(
                    f"system path alias target contains a symbolic link: {resolved}"
                )
        current = expected_target

    return current


def _copy_tree(source: Path, destination: Path) -> None:
    for relative, (kind, data) in _tree_inventory(source, omit_hidden=True).items():
        target = destination / relative
        if kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            assert data is not None
            target.write_bytes(data)
            try:
                shutil.copystat(source / relative, target, follow_symlinks=False)
            except OSError:
                # File metadata is incidental; the source bytes and paths are the bundle.
                pass


def verify_godot_mcp(project_dir: str | os.PathLike[str]) -> int:
    """Read-only check of the enabled, complete canonical bundle; return file count."""
    project = _canonicalize_project_path(Path(project_dir).expanduser())
    settings, _, plugin = _check_project_paths(project)
    expected = _tree_inventory(DEFAULT_SOURCE, omit_hidden=True)
    if _tree_inventory(plugin, omit_hidden=False) != expected:
        raise InstallError("addons/godot_mcp is incomplete or conflicts with the bundled plugin")
    text = settings.read_text(encoding="utf-8")
    if _enable_plugin(text) != text:
        raise InstallError("project.godot must enable res://addons/godot_mcp/plugin.cfg")
    return sum(kind == "file" for kind, _ in expected.values())


def install_godot_mcp(
    project_dir: str | os.PathLike[str],
    *,
    source_dir: str | os.PathLike[str] | None = None,
) -> bool:
    """Install/enable the bundled plugin; return whether project files changed."""
    source = Path(source_dir) if source_dir is not None else DEFAULT_SOURCE
    source = source.expanduser().absolute()
    source_inventory = _tree_inventory(source, omit_hidden=True)
    if "plugin.cfg" not in source_inventory or source_inventory["plugin.cfg"][0] != "file":
        raise InstallError(f"plugin source is missing plugin.cfg: {source}")

    requested = Path(project_dir).expanduser()
    project = _canonicalize_project_path(requested)
    settings, addons, plugin = _check_project_paths(project)

    if plugin.exists():
        current_inventory = _tree_inventory(plugin, omit_hidden=False)
        if current_inventory != source_inventory:
            expected = set(source_inventory)
            actual = set(current_inventory)
            different = sorted(
                path for path in expected & actual
                if source_inventory[path] != current_inventory[path]
            )
            detail = sorted((expected ^ actual) | set(different))
            raise InstallError(
                "an existing addons/godot_mcp conflicts with the bundled plugin"
                + (": " + ", ".join(detail[:20]) if detail else "")
            )

    if settings.exists():
        try:
            project_text = settings.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InstallError(f"cannot read {settings}: {exc}") from exc
    else:
        project_text = DEFAULT_PROJECT
    updated_settings = _enable_plugin(project_text)
    changed = updated_settings != project_text or not plugin.exists()

    project.mkdir(parents=True, exist_ok=True)
    addons.mkdir(parents=True, exist_ok=True)
    if not plugin.exists():
        staging = Path(tempfile.mkdtemp(prefix=".godot_mcp.install-", dir=addons))
        try:
            _copy_tree(source, staging)
            staging.rename(plugin)
        except OSError as exc:
            raise InstallError(f"cannot copy plugin into {plugin}: {exc}") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    if updated_settings != project_text or not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=".project.godot.", dir=project)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
                stream.write(updated_settings)
            temp_path.replace(settings)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path, help="existing or new Godot project directory")
    args = parser.parse_args(argv)
    try:
        changed = install_godot_mcp(args.project_dir)
    except InstallError as exc:
        print(f"Godot MCP install failed: {exc}", file=sys.stderr)
        return 2
    print(
        "Godot MCP installed and enabled."
        if changed else "Godot MCP is already installed and enabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
