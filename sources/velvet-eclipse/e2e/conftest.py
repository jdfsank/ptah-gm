import os
import pytest
from godot_e2e import GodotE2E

GODOT_PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
GODOT_CONFIG = os.path.join(GODOT_PROJECT, '.agents', 'godotmaker.yaml')
GODOT_PATH = '/usr/local/bin/godot'

@pytest.fixture(scope='module')
def _game_process():
    with GodotE2E.launch(GODOT_PROJECT, godot_path=GODOT_PATH, timeout=15.0) as game:
        game.wait_for_node('/root/Main', timeout=10.0)
        yield game

@pytest.fixture(scope='function')
def game(_game_process):
    _game_process.reload_scene()
    _game_process.wait_for_node('/root/Main', timeout=5.0)
    yield _game_process
