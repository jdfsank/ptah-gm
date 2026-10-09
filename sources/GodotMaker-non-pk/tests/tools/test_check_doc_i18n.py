"""Tests for check_doc_i18n.py."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from check_doc_i18n import check_paths, required_chinese_mirror  # noqa: E402


def test_required_chinese_mirror_for_user_docs():
    assert required_chinese_mirror("README.md") == "README.zh-CN.md"
    assert required_chinese_mirror("docs/index.md") == "docs/zh/index.md"
    assert (
        required_chinese_mirror("docs/wiki/05-tools/check-env.md")
        == "docs/zh/wiki/05-tools/check-env.md"
    )


def test_no_mirror_required_for_internal_docs():
    assert required_chinese_mirror("docs/update/next.md") is None
    assert required_chinese_mirror("docs/decisions/disable-gdtoolkit.md") is None
    assert required_chinese_mirror("docs/contributing/shared-refs.md") is None
    assert required_chinese_mirror("docs/zh/wiki/05-tools/check-env.md") is None


def test_check_paths_passes_when_mirror_changed(tmp_path):
    (tmp_path / "docs/zh/wiki/05-tools").mkdir(parents=True)
    (tmp_path / "docs/zh/wiki/05-tools/check-env.md").write_text(
        "# check-env\n",
        encoding="utf-8",
    )

    errors = check_paths(
        [
            "docs/wiki/05-tools/check-env.md",
            "docs/zh/wiki/05-tools/check-env.md",
        ],
        tmp_path,
    )

    assert errors == []


def test_check_paths_fails_when_existing_mirror_not_changed(tmp_path):
    (tmp_path / "docs/zh/wiki/05-tools").mkdir(parents=True)
    (tmp_path / "docs/zh/wiki/05-tools/check-env.md").write_text(
        "# check-env\n",
        encoding="utf-8",
    )

    errors = check_paths(["docs/wiki/05-tools/check-env.md"], tmp_path)

    assert errors == [
        "docs/wiki/05-tools/check-env.md changed but "
        "docs/zh/wiki/05-tools/check-env.md was not changed in the same diff."
    ]


def test_check_paths_fails_when_mirror_is_missing(tmp_path):
    errors = check_paths(["docs/wiki/05-tools/check-env.md"], tmp_path)

    assert errors == [
        "docs/wiki/05-tools/check-env.md changed but required Chinese mirror "
        "docs/zh/wiki/05-tools/check-env.md does not exist."
    ]
