"""Validate sub-agent definition files have correct YAML frontmatter."""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

REQUIRED_FIELDS = {"name", "description", "model"}
ALLOWED_MODEL_ALIASES = {"inherit", "opus", "sonnet", "haiku"}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _agent_files():
    return sorted(AGENTS_DIR.glob("*.md"))


def _parse_frontmatter(path: Path):
    """Parse a flat scalar `key: value` YAML frontmatter block.

    Intentionally minimal — agent frontmatter is always 3 string fields.
    Avoids a PyYAML dependency that CI doesn't install.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_agents_dir_not_empty():
    assert _agent_files(), "agents/ must contain at least one .md file"


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_frontmatter_parses(path):
    fm = _parse_frontmatter(path)
    assert isinstance(fm, dict), (
        f"{path.name}: missing or invalid frontmatter block (expected leading '---' block)"
    )


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_required_fields_present_and_non_empty(path):
    fm = _parse_frontmatter(path) or {}
    missing = REQUIRED_FIELDS - set(fm)
    assert not missing, f"{path.name}: missing required field(s) {sorted(missing)}"
    for field in REQUIRED_FIELDS:
        value = fm[field]
        assert isinstance(value, str) and value.strip(), (
            f"{path.name}: field '{field}' must be a non-empty string"
        )


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_name_matches_filename_stem(path):
    fm = _parse_frontmatter(path) or {}
    assert fm.get("name") == path.stem, (
        f"{path.name}: frontmatter name '{fm.get('name')}' must match filename stem '{path.stem}'"
    )


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_model_value_is_valid(path):
    fm = _parse_frontmatter(path) or {}
    model = fm.get("model", "")
    is_alias = model in ALLOWED_MODEL_ALIASES
    is_explicit_id = model.startswith("claude-")
    assert is_alias or is_explicit_id, (
        f"{path.name}: model '{model}' must be one of {sorted(ALLOWED_MODEL_ALIASES)} "
        "or an explicit 'claude-*' model id"
    )
