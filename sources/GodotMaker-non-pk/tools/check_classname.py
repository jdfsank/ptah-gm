#!/usr/bin/env python3
"""Check GDScript files for class_name declarations that conflict with Godot built-in names.

Used in two contexts:
1. As a GodotMaker repo unittest to validate scaffold templates
2. As a hook/check after workers generate code in game projects

Usage:
    python tools/check_classname.py <project_dir>
    python tools/check_classname.py <project_dir> --json
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Comprehensive blacklist of Godot built-in class names and common enums.
# Declaring a class_name that shadows any of these will cause hard-to-debug
# errors in the Godot editor and at runtime.
GODOT_RESERVED_NAMES: set[str] = {
    # Core base types
    "Object", "RefCounted", "Resource", "Node", "Node2D", "Node3D",
    "Control", "CanvasItem", "CanvasLayer",
    # Common node types
    "Sprite2D", "Sprite3D", "AnimatedSprite2D", "AnimatedSprite3D",
    "Camera2D", "Camera3D", "Timer", "Label", "Button", "TextureRect",
    "RichTextLabel", "LineEdit", "TextEdit", "Panel", "PanelContainer",
    "MarginContainer", "HBoxContainer", "VBoxContainer", "GridContainer",
    "ScrollContainer", "TabContainer", "ColorRect", "TextureButton",
    "CheckBox", "CheckButton", "OptionButton", "SpinBox", "Slider",
    "HSlider", "VSlider", "ProgressBar", "Tree", "ItemList",
    # Physics
    "Area2D", "Area3D", "StaticBody2D", "StaticBody3D",
    "RigidBody2D", "RigidBody3D", "CharacterBody2D", "CharacterBody3D",
    "CollisionShape2D", "CollisionShape3D", "CollisionPolygon2D",
    "RayCast2D", "RayCast3D", "PhysicsBody2D", "PhysicsBody3D",
    # Audio / visual
    "AudioStreamPlayer", "AudioStreamPlayer2D", "AudioStreamPlayer3D",
    "Light2D", "PointLight2D", "DirectionalLight2D",
    "WorldEnvironment", "SubViewport", "SubViewportContainer",
    "GPUParticles2D", "GPUParticles3D", "CPUParticles2D", "CPUParticles3D",
    # Resources
    "Texture2D", "PackedScene", "Script", "Shader", "Material",
    "ShaderMaterial", "StandardMaterial3D", "Theme", "Font",
    "AudioStream", "Animation", "AnimationPlayer", "AnimationTree",
    "Mesh", "ArrayMesh", "MultiMesh", "MultiMeshInstance2D",
    # Navigation / pathfinding
    "NavigationAgent2D", "NavigationAgent3D",
    "NavigationRegion2D", "NavigationRegion3D",
    "TileMap", "TileSet",
    # Networking / misc
    "HTTPRequest", "WebSocketPeer", "FileAccess", "DirAccess",
    # Common global singletons / autoloads
    "Input", "Engine", "OS", "ProjectSettings", "DisplayServer",
    "RenderingServer", "PhysicsServer2D", "PhysicsServer3D",
    "Time", "Performance", "ClassDB", "ResourceLoader", "ResourceSaver",
    # Core variant types that can clash
    "Signal", "Callable", "Array", "Dictionary",
    "Vector2", "Vector3", "Vector4", "Rect2", "Transform2D", "Transform3D",
    "Color", "Basis", "AABB", "Plane", "Quaternion",
    "StringName", "NodePath",
    # Common enums / error types
    "Error", "Key", "MouseButton", "JoyButton", "JoyAxis",
    "PropertyHint", "PropertyUsageFlags", "MethodFlags",
    "Variant", "GDScript",
    # Dangerous short names that shadow engine classes
    "World", "World2D", "World3D", "Viewport", "Window",
    "Tween", "SceneTree", "MainLoop",
    "System",
}

# Directories to skip when scanning
SKIP_DIRS = {"addons", ".godot", ".claude", ".git", "__pycache__"}

# Regex to match: class_name SomeName
CLASS_NAME_RE = re.compile(r"^\s*class_name\s+(\w+)", re.MULTILINE)


def scan_project(project_dir: str) -> list[dict]:
    """Scan all .gd files in project_dir, return list of conflict dicts."""
    conflicts = []
    root = Path(project_dir)

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place so os.walk won't descend
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            if not fname.endswith(".gd"):
                continue
            filepath = os.path.join(dirpath, fname)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            for match in CLASS_NAME_RE.finditer(content):
                cname = match.group(1)
                if cname in GODOT_RESERVED_NAMES:
                    rel = os.path.relpath(filepath, project_dir)
                    conflicts.append({
                        "file": rel.replace("\\", "/"),
                        "class_name": cname,
                        "conflicts_with": cname,
                    })

    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check GDScript class_name declarations for Godot built-in conflicts."
    )
    parser.add_argument("project_dir", help="Path to the Godot project directory")
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output machine-readable JSON"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.project_dir):
        print(f"Error: '{args.project_dir}' is not a directory", file=sys.stderr)
        return 2

    conflicts = scan_project(args.project_dir)
    clean = len(conflicts) == 0

    if args.json_output:
        result = {"conflicts": conflicts, "clean": clean}
        print(json.dumps(result, indent=2))
    else:
        if clean:
            print("[PASS] No class_name conflicts with Godot built-in names.")
        else:
            print(f"[FAIL] Found {len(conflicts)} class_name conflict(s):\n")
            for c in conflicts:
                print(f"  {c['file']}: class_name '{c['class_name']}' "
                      f"conflicts with Godot built-in '{c['conflicts_with']}'")

    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
