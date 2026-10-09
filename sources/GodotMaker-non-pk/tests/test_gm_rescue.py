"""Structural validation for the gm-rescue skill.

gm-rescue is a diagnostic skill outside the main pipeline. The privacy
contract is part of its definition — the SKILL.md must explicitly state
that it does NOT write files, does NOT auto-submit issues, and that
any issue draft excludes project paths/code/GDD content by default.
These checks pin the contract so a future edit can't quietly relax it.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESCUE_SKILL = REPO_ROOT / "skills" / "core" / "gm-rescue" / "SKILL.md"
RESCUE_REFS = REPO_ROOT / "skills" / "core" / "gm-rescue" / "references"


def test_skill_md_exists():
    assert RESCUE_SKILL.is_file(), "skills/core/gm-rescue/SKILL.md must exist"


def test_diagnostic_checklist_exists():
    assert (RESCUE_REFS / "diagnostic-checklist.md").is_file(), \
        "skills/core/gm-rescue/references/diagnostic-checklist.md must exist"


@pytest.fixture
def skill_text():
    return RESCUE_SKILL.read_text(encoding="utf-8")


def test_frontmatter_disables_model_invocation(skill_text):
    """gm-rescue is explicit-invocation only — should not auto-trigger."""
    assert "disable-model-invocation: true" in skill_text


def test_frontmatter_name_matches(skill_text):
    assert re.search(r"^name:\s*gm-rescue\s*$", skill_text, re.MULTILINE), \
        "frontmatter must declare name: gm-rescue"


def test_no_file_writes_rule(skill_text):
    """Hard rule that this skill does not modify files (chat output only).
    Two carve-outs: .godotmaker/current_role and .godotmaker/stage.jsonl
    for self-bookkeeping. Anything else = relaxed contract.
    """
    assert "No file writes" in skill_text, \
        "SKILL.md must explicitly declare the no-file-writes rule"


def test_no_code_changes_rule(skill_text):
    assert "No code changes" in skill_text, \
        "SKILL.md must explicitly declare the no-code-changes rule"


def test_no_subagent_dispatch_rule(skill_text):
    assert "No subagent dispatch" in skill_text, \
        "SKILL.md must explicitly forbid subagent dispatch"


def test_privacy_default_excludes_named(skill_text):
    """Privacy contract: issue drafts must, by default, exclude:
    - absolute project paths
    - the user's GDD content
    - the user's project source code
    Each must be named explicitly in the Hard Rules / Privacy section so
    a future edit can't quietly drop one.
    """
    privacy_section_starts = skill_text.find("Privacy")
    assert privacy_section_starts != -1, "SKILL.md must have a Privacy section"
    # Look in the rest of the file from the privacy heading onward
    tail = skill_text[privacy_section_starts:]
    for forbidden in ("absolute project paths", "GDD content", "source code"):
        assert forbidden in tail, \
            f"Privacy contract must explicitly name '{forbidden}' as default-excluded"


def test_no_auto_submit_issue(skill_text):
    """Issue drafts go to chat only — the user copies and submits manually.
    Several phrasings should NOT appear (auto-submit would be a regression).
    """
    forbidden_phrases = [
        "gh issue create",
        "github api",
        "submit issue",
        "post issue automatically",
    ]
    text_lower = skill_text.lower()
    for phrase in forbidden_phrases:
        assert phrase not in text_lower, \
            f"SKILL.md must NOT mention '{phrase}' — issues are user-submitted only"


def test_three_conclusion_branches_present(skill_text):
    """Diagnosis must classify into one of three explicit conclusions —
    no fuzzy "I don't know" branch beyond INSUFFICIENT EVIDENCE.
    """
    for conclusion in ("GODOTMAKER DEFECT", "NOT A GODOTMAKER DEFECT",
                       "INSUFFICIENT EVIDENCE"):
        assert conclusion in skill_text, \
            f"SKILL.md must contain explicit conclusion branch: {conclusion}"


def test_writes_only_role_and_stage_files(skill_text):
    """The two permitted file mutations are current_role and stage.jsonl.
    Any other path being written would silently violate the rule.
    """
    permitted = [".godotmaker/current_role", ".godotmaker/stage.jsonl"]
    for p in permitted:
        assert p in skill_text, f"SKILL.md must mention permitted write target {p}"


def test_diagnostic_checklist_orders_layers():
    """The checklist must walk layers in highest-leverage-first order so
    a defect in hooks (which can deny every tool call) is found before
    layers that have smaller blast radii.
    """
    checklist = (RESCUE_REFS / "diagnostic-checklist.md").read_text(encoding="utf-8")
    layers_in_order = ["Hooks", "SKILL.md", "Config schemas", "Templates",
                       "Shared references", "Tools"]
    last_pos = -1
    for layer in layers_in_order:
        pos = checklist.find(layer)
        assert pos > last_pos, \
            f"Checklist must mention layers in order; '{layer}' appears out of sequence"
        last_pos = pos
