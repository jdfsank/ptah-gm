import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _scaffold_conftest_template() -> str:
    text = _text("skills/core/gm-scaffold/SKILL.md")
    marker = "Write the following to `e2e/conftest.py`:\n```python\n"
    start = text.index(marker) + len(marker)
    end = text.index("\n```", start)
    return text[start:end] + "\n"


def test_e2e_conftest_templates_pass_configured_godot_path():
    paths = [
        "skills/core/gm-scaffold/SKILL.md",
        "skills/core/godot-e2e/SKILL.md",
        "skills/core/godot-e2e/references/api-reference.md",
    ]
    for path in paths:
        text = _text(path)
        assert (
            'GODOT_CONFIG = os.path.join(GODOT_PROJECT, ".claude", "godotmaker.yaml")'
            in text
        )
        assert "def _read_godot_path():" in text
        assert "godot_path=GODOT_PATH" in text


def test_scaffold_conftest_template_passes_godot_path_in_temp_project(tmp_path):
    project = tmp_path / "project"
    e2e = project / "e2e"
    e2e.mkdir(parents=True)
    (project / ".claude").mkdir()
    (project / ".claude" / "godotmaker.yaml").write_text(
        'godot_path: "C:/Godot/Godot_v4.5.1-stable_mono_win64.exe"\n',
        encoding="utf-8",
    )
    (e2e / "conftest.py").write_text(_scaffold_conftest_template(), encoding="utf-8")
    (e2e / "godot_e2e.py").write_text(
        """
class _Game:
    def __init__(self, project_path, godot_path, timeout):
        self.project_path = project_path
        self.godot_path = godot_path
        self.timeout = timeout

    def wait_for_node(self, *_args, **_kwargs):
        return None

    def reload_scene(self):
        return None


class _LaunchContext:
    def __init__(self, project_path, godot_path, timeout):
        self.game = _Game(project_path, godot_path, timeout)

    def __enter__(self):
        return self.game

    def __exit__(self, *_args):
        return False


class GodotE2E:
    @staticmethod
    def launch(project_path, *, godot_path=None, timeout=10.0, **_kwargs):
        return _LaunchContext(project_path, godot_path, timeout)
""".lstrip(),
        encoding="utf-8",
    )
    (e2e / "test_launch_path.py").write_text(
        """
def test_configured_godot_path_reaches_launch(game):
    assert game.godot_path == "C:/Godot/Godot_v4.5.1-stable_mono_win64.exe"
    assert game.timeout == 15.0
""".lstrip(),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(e2e) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "e2e", "-q"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
