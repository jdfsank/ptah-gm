"""Tests for config/addon_versions.json — validates structure and tag existence."""
import json
import os
import re
import subprocess

import pytest

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "addon_versions.json",
)

REQUIRED_ADDON_FIELDS = {"repo", "tag", "install_path"}
GODOT_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def godot_versions(config):
    return config["godot_versions"]


# ---------------------------------------------------------------------------
# Structure validation (offline)
# ---------------------------------------------------------------------------

class TestConfigStructure:
    def test_config_file_exists(self):
        assert os.path.isfile(CONFIG_PATH), f"Config not found: {CONFIG_PATH}"

    def test_has_godot_versions_key(self, config):
        assert "godot_versions" in config, "Missing top-level 'godot_versions' key"

    def test_godot_versions_not_empty(self, godot_versions):
        assert len(godot_versions) > 0, "godot_versions is empty"

    def test_godot_version_format(self, godot_versions):
        for version in godot_versions:
            assert GODOT_VERSION_PATTERN.match(version), (
                f"Godot version '{version}' is not valid semver-like (expected x.y)"
            )

    def test_addon_entries_have_required_fields(self, godot_versions):
        for gd_ver, addons in godot_versions.items():
            for addon_name, entry in addons.items():
                missing = REQUIRED_ADDON_FIELDS - set(entry.keys())
                assert not missing, (
                    f"godot {gd_ver} / {addon_name}: missing fields {missing}"
                )

    def test_repo_format(self, godot_versions):
        """repo should look like 'owner/name'."""
        for gd_ver, addons in godot_versions.items():
            for addon_name, entry in addons.items():
                repo = entry["repo"]
                assert re.match(r"^[\w.-]+/[\w.-]+$", repo), (
                    f"godot {gd_ver} / {addon_name}: "
                    f"repo '{repo}' doesn't match owner/name format"
                )

    def test_tag_not_empty(self, godot_versions):
        for gd_ver, addons in godot_versions.items():
            for addon_name, entry in addons.items():
                assert entry["tag"].strip(), (
                    f"godot {gd_ver} / {addon_name}: tag is empty"
                )

    def test_install_path_not_empty(self, godot_versions):
        for gd_ver, addons in godot_versions.items():
            for addon_name, entry in addons.items():
                assert entry["install_path"].strip(), (
                    f"godot {gd_ver} / {addon_name}: install_path is empty"
                )


# ---------------------------------------------------------------------------
# Network validation — verify tags actually exist on GitHub
# ---------------------------------------------------------------------------

def _collect_unique_repo_tags(godot_versions: dict) -> list[tuple[str, str, str]]:
    """Return deduplicated list of (repo, tag, display_label) tuples."""
    seen = set()
    result = []
    for gd_ver, addons in godot_versions.items():
        for addon_name, entry in addons.items():
            key = (entry["repo"], entry["tag"])
            if key not in seen:
                seen.add(key)
                label = f"{addon_name} ({entry['repo']}@{entry['tag']})"
                result.append((entry["repo"], entry["tag"], label))
    return result


def _git_tag_exists(repo: str, tag: str) -> bool:
    """Check whether a git tag exists on GitHub via ls-remote."""
    url = f"https://github.com/{repo}.git"
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url, tag],
            capture_output=True, text=True, timeout=30,
        )
        # ls-remote prints matching refs; empty output means tag not found
        return result.returncode == 0 and tag in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture(scope="module")
def unique_repo_tags(godot_versions):
    return _collect_unique_repo_tags(godot_versions)


@pytest.mark.network
class TestGitTagsExist:
    """Verify every referenced git tag exists on its GitHub repo.

    Run with:  pytest -m network
    Skip with: pytest -m 'not network'
    """

    def test_all_tags_exist(self, unique_repo_tags):
        failures = []
        for repo, tag, label in unique_repo_tags:
            if not _git_tag_exists(repo, tag):
                failures.append(label)
        assert not failures, (
            "The following addon tags do NOT exist on GitHub:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )
