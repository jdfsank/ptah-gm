"""Version-pinned semantic workbench projection for the Casino project.

The published object document remains the authoritative project record.  This
module adds read-only semantic links from the exact source commit to a copy of
that document so the workbench can address definitions, the player start,
runtime spawning, resources, and behavior without inventing permanent runtime
instances.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

from .object_protocol import validate_document


CASINO_SOURCE_COMMIT = "a5145f960ac7dca877882ce2557ce7b40fb2f537"
CASINO_SOURCE_DOCUMENT = "design/game.json"

_CASINO_OBJECTS = {
    "project-casino": ("system", "project", None, "semantic", "项目级配置和规则；当前映射来自精确发布版本。"),
    "arena-scene": ("scene", "scene", "scripts/simulation/round_director.gd", "semantic", "场景通过程序绘制；视口边界取自 project.godot。"),
    "round-director": ("system", "runtime", "scripts/simulation/round_director.gd", "transition", "每局从环境配置池选择本轮序列，并在轮次间清理临时危险。"),
    "player": ("definition", "shared", "scripts/simulation/player.gd", "motion", "共享的玩家角色定义；实际场景实例与每局起始入口单独建模。"),
    "movement-input": ("behavior", "runtime", "scripts/input/movement_input.gd", "action", "输入只形成移动意图；方向键与 WASD 共用动作。"),
    "enemy-roster": ("spawn", "runtime", "scripts/simulation/enemy_spawner.gd", "spawn", "敌人由运行时生成规则产生，死亡或场景轮次切换后清理；没有永久放置的敌人实例。"),
    "automatic-combat": ("behavior", "runtime", "scripts/simulation/combat_system.gd", "action", "普通武器按冷却与射程内最近目标自动触发；筹码环直接做持续环绕碰撞判定，未声明统一阶段时间线。"),
    "growth-system": ("system", "runtime", "scripts/simulation/growth_system.gd", "rule", "拾取筹码积累经验；升级选择与武器成长由运行时系统处理。"),
    "dice-burst": ("behavior", "runtime", "scripts/simulation/dice_event.gd", "spawn", "依次预告、砸落并开放限时安全筹码区，随后清理。"),
    "environment-texas": ("preset", "shared", "resources/environments/texas.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-blackjack": ("preset", "shared", "resources/environments/blackjack.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-craps": ("preset", "shared", "resources/environments/craps.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-roulette": ("preset", "shared", "resources/environments/roulette.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-baccarat": ("preset", "shared", "resources/environments/baccarat.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-slots": ("preset", "shared", "resources/environments/slots.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-chip-vault": ("preset", "shared", "resources/environments/chip_vault.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-card-shuffler": ("preset", "shared", "resources/environments/card_shuffler.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-lucky-wheel": ("preset", "shared", "resources/environments/lucky_wheel.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "environment-vip": ("preset", "shared", "resources/environments/vip.tres", "semantic", "同一竞技场内轮换使用的环境规则预设，不是独立场景。"),
    "weapon-loaded-dice": ("definition", "shared", "resources/weapons/loaded_dice.tres", "action", "共享武器定义；等级变化由成长系统和自动战斗系统使用。"),
    "weapon-marked-cards": ("definition", "shared", "resources/weapons/marked_cards.tres", "action", "共享武器定义；等级变化由成长系统和自动战斗系统使用。"),
    "weapon-chip-ring": ("definition", "shared", "resources/weapons/chip_ring.tres", "motion", "共享武器定义；等级变化由成长系统和自动战斗系统使用。"),
    "weapon-rake": ("definition", "shared", "resources/weapons/rake.tres", "action", "共享武器定义；等级变化由成长系统和自动战斗系统使用。"),
    "weapon-roulette-ball": ("definition", "shared", "resources/weapons/roulette_ball.tres", "action", "共享武器定义；等级变化由成长系统和自动战斗系统使用。"),
    "character-animation": ("behavior", "runtime", "scripts/rendering/character_visual.gd", "motion", "角色状态由程序形状、位移和缩放绘制；没有绑定角色动画图片。"),
    "visual-direction": ("resource", "scene", "scripts/rendering/arena_visual.gd", "semantic", "赌场背景、敌人、危险和奖励使用程序绘制的形状、文字和颜色。"),
    "game-interface": ("system", "scene", "scripts/ui/game_interface.gd", "interaction", "界面显示运行状态、升级选项和结果；不包含场景导航过渡。"),
    "runtime-contract": ("behavior", "project", "scripts/config/casino_config.gd", "rule", "冻结字段由配置读取器接入运行时；设计数据不等同于运行验证。"),
}

_ENVIRONMENT_IDS = [
    "environment-texas", "environment-blackjack", "environment-craps", "environment-roulette",
    "environment-baccarat", "environment-slots", "environment-chip-vault",
    "environment-card-shuffler", "environment-lucky-wheel", "environment-vip",
]
_WEAPON_IDS = [
    "weapon-loaded-dice", "weapon-marked-cards", "weapon-chip-ring", "weapon-rake", "weapon-roulette-ball",
]


class WorkbenchSourceError(ValueError):
    """The requested source revision could not support the Casino projection."""


def _git_show(repo_path: Path, commit: str, source_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{commit}:{source_path}"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise WorkbenchSourceError(f"Could not read {source_path} at the requested source commit")
    return result.stdout


def _source_provenance(obj: dict, *, root_docs: tuple[str, ...] = ()) -> dict:
    paths = set(obj.get("sourceBindings", []))
    paths.update(root_docs)
    return {"kind": "fact", "sourcePaths": sorted(paths)}


def _read_canvas_source(repo_path: Path, commit: str) -> tuple[list[float], list[float], str]:
    project = _git_show(repo_path, commit, "project.godot")
    director = _git_show(repo_path, commit, "scripts/simulation/round_director.gd")
    width = re.search(r"(?m)^window/size/viewport_width=(\d+)\s*$", project)
    height = re.search(r"(?m)^window/size/viewport_height=(\d+)\s*$", project)
    bounds = re.search(r"(?m)^const BOUNDS = Rect2\(([^)]+)\)", director)
    if not (width and height and bounds and "player.reset(config, BOUNDS.get_center())" in director):
        raise WorkbenchSourceError("Casino scene viewport or player start is not declared as expected")
    try:
        x, y, w, h = (float(part.strip()) for part in bounds.group(1).split(","))
    except (TypeError, ValueError) as exc:
        raise WorkbenchSourceError("Casino playable bounds are malformed") from exc
    return [float(width.group(1)), float(height.group(1))], [x + w / 2, y + h / 2], director


def _preview(preview_type: str, label: str, stages: list[dict] | None = None,
             *, speed: float | None = None, speed_field_id: str | None = None) -> dict:
    result = {"type": preview_type, "label": label, "stages": stages or []}
    if speed is not None:
        result["speed"] = speed
    if speed_field_id is not None:
        result["speedFieldId"] = speed_field_id
    return result


def _field_values(obj: dict) -> dict:
    return {field["id"]: field["value"] for field in obj.get("fields", [])}


def _numeric_field(values: dict, field_id: str, fallback: float = 0.0) -> float:
    value = values.get(field_id, fallback)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(fallback)
    return float(value)


def _merge_source_metadata(target: dict, generated: dict, source_commit: str) -> None:
    """Refresh source-derived values while retaining explicit layout/art notes."""
    existing = target.get("workbench", {})
    preserved = {key: copy.deepcopy(existing[key]) for key in ("lock", "size", "anchor") if key in existing}
    if "facets" in existing:
        preserved_facets = copy.deepcopy(existing["facets"])
        preserved["facets"] = {**preserved_facets, **copy.deepcopy(generated.get("facets", {}))}
    generated.update(preserved)
    generated["sourceCommit"] = source_commit
    target["workbench"] = generated


def enrich_casino_document(document: object, *, repo_path: str | Path, source_commit: str) -> dict:
    """Return the validated Casino workbench projection for one exact Git version.

    Unknown projects and later revisions are left alone: the Casino model is a
    version-pinned adapter and must never infer facts from a dirty checkout or
    from a different source version.
    """
    normalized = validate_document(document)
    repo = Path(repo_path)
    if not repo.is_dir() or repo.is_symlink():
        if source_commit == CASINO_SOURCE_COMMIT:
            raise WorkbenchSourceError("Casino source repository is unavailable")
        return normalized
    try:
        source_text = _git_show(repo, source_commit, CASINO_SOURCE_DOCUMENT)
        source_document = validate_document(json.loads(source_text))
    except (WorkbenchSourceError, json.JSONDecodeError, TypeError, ValueError):
        # The version-pinned adapter is opt-in by the source document's stable
        # object identity.  Other projects or missing future mappings remain
        # untouched rather than inheriting Casino facts.
        if source_commit == CASINO_SOURCE_COMMIT:
            raise WorkbenchSourceError("Pinned Casino design document is unavailable or invalid")
        return normalized
    source_ids = {item["id"] for item in source_document["objects"]}
    required_source_ids = set(_CASINO_OBJECTS)
    if not required_source_ids <= source_ids:
        if source_commit == CASINO_SOURCE_COMMIT:
            raise WorkbenchSourceError("Pinned Casino design document does not match its expected object model")
        return normalized

    result = copy.deepcopy(normalized)
    by_id = {item["id"]: item for item in result["objects"]}
    source_by_id = {item["id"]: item for item in source_document["objects"]}
    if not {"project-casino", "arena-scene", "player", "enemy-roster"} <= set(by_id):
        return result

    viewport, player_start, director = _read_canvas_source(repo, source_commit)
    source_scene = source_by_id["arena-scene"]
    source_player = source_by_id["player"]
    source_spawner = source_by_id["enemy-roster"]
    source_director = source_by_id["round-director"]
    for object_id, (role, scope, driver, preview_type, label) in _CASINO_OBJECTS.items():
        target = by_id.get(object_id)
        source = source_by_id.get(object_id)
        if target is None or source is None:
            continue
        metadata = {
            "role": role,
            "scope": scope,
            "provenance": _source_provenance(source, root_docs=("GDD.md",)),
            "preview": _preview(preview_type, label),
        }
        if driver:
            metadata["driver"] = driver
        if object_id == "arena-scene":
            metadata["bounds"] = viewport
            metadata["provenance"] = _source_provenance(source, root_docs=("GDD.md", "project.godot"))
        elif object_id == "player":
            metadata["usage"] = ["movement-input", "automatic-combat", "growth-system"]
            metadata["provenance"] = _source_provenance(source, root_docs=("GDD.md", "scenes/arena.tscn"))
            values = _field_values(target)
            speed = _numeric_field(values, "move-speed")
            health = int(_numeric_field(values, "max-health"))
            metadata["preview"] = _preview("motion", f"玩家移动 · 速度 {speed:g} · 生命上限 {health}",
                                            speed=speed, speed_field_id="move-speed")
        elif object_id == "enemy-roster":
            metadata["usage"] = ["enemy-kind-0", "enemy-kind-1", "enemy-kind-2"]
            metadata["trigger"] = "运行时按计时器生成，受轮次难度影响，场上最多 75 个。"
            metadata["positionPolicy"] = "在场地周边抽取位置；过近时回退到远侧角落。"
            metadata["cleanup"] = "死亡后移除；环境切换时清除旧敌人。"
            metadata["lifecycle"] = "每局重置；持续按生成计时器产生临时敌人；不会作为永久场景摆放项保存。"
            metadata["provenance"] = _source_provenance(source, root_docs=("GDD.md",))
        elif object_id == "automatic-combat":
            metadata["lifecycle"] = (
                "普通武器逐帧推进冷却；冷却归零且射程内有最近目标时触发武器分支。"
                "筹码环持续做环绕碰撞判定，耙子即时扫击，骰子/卡牌/钢珠使用各自投射物命中与寿命。"
                "跨武器统一阶段时间线未声明，避免把不同分支合并成虚构的时长序列。"
            )
            metadata["provenance"] = _source_provenance(source, root_docs=("GDD.md",))
        elif object_id == "growth-system":
            metadata["driver"] = "scripts/simulation/growth_system.gd"
            metadata["guard"] = "options.is_empty() 且 experience >= cost()；cost() = first_cost + (level - 1) * cost_increment。"
            metadata["lifecycle"] = (
                "reset() 清除筹码、选项和本局经验并读取成长配置；begin_upgrade() 扣除当前 cost()、"
                "提升等级并生成至多三个可选项；choose() 应用合法选项后清空待选项。"
                "round_director 在已有升级界面处理完后继续检查超额经验。"
            )
            metadata["provenance"] = _source_provenance(
                source, root_docs=("GDD.md", "scripts/simulation/round_director.gd"))
        elif object_id == "round-director":
            metadata["usage"] = _ENVIRONMENT_IDS
            metadata["lifecycle"] = "每局从配置池抽取不重复环境；轮次切换时重置本轮临时对象。"
            metadata["provenance"] = _source_provenance(source, root_docs=("GDD.md", "scripts/config/casino_config.gd"))
            values = _field_values(target)
            rounds = int(_numeric_field(values, "rounds-per-run", 1))
            round_duration = _numeric_field(values, "round-duration")
            transition_duration = _numeric_field(values, "transition-duration")
            metadata["preview"] = _preview("transition", f"每局 {rounds} 轮；每轮依配置计时后切换环境", [
                {"label": "本轮环境", "duration": round_duration, "durationFieldId": "round-duration"},
                {"label": "环境过渡", "duration": transition_duration, "durationFieldId": "transition-duration"},
            ])
        elif object_id == "dice-burst":
            values = _field_values(target)
            warning = float(values.get("warning-duration", 0))
            reward_lifetime = float(values.get("reward-lifetime", 0))
            reward_value = int(_numeric_field(values, "reward-value"))
            metadata["lifecycle"] = "预警 → 伤害 → 安全奖励窗口 → 超时清理。"
            metadata["trigger"] = (
                "round_director.step_environment() 中环境计时器到期且当前环境为 craps 时调用 throw_dice；"
                "第三轮起再为第二点调用 throw_dice(second, 0.8)，其预警时长为 warning_duration + 0.8 秒。"
            )
            metadata["positionPolicy"] = (
                "首个落点取玩家位置并夹在场地边界内侧 90 像素；第三轮起第二点位于场地中心 y，"
                "首点在中心左侧时 x 为 center.x + 260，否则为 center.x - 260。throw_dice 将危险与奖励放在同一传入点。"
            )
            metadata["cleanup"] = (
                "预警计时结束进入 0.4 秒 active；结束后生成限时筹码与同位置安全区并移除危险。"
                "奖励芯片和安全区按 reward_lifetime 到期；每轮 start_environment() 清空 hazards/safe_zones，"
                "并删除有限生命周期的旧筹码。"
            )
            metadata["provenance"] = _source_provenance(
                source, root_docs=("GDD.md", "scripts/simulation/round_director.gd"))
            metadata["preview"] = _preview("spawn", "来源于脚本计时与冻结字段的骰子事件时间线", [
                {"label": "落点预告", "duration": warning, "durationFieldId": "warning-duration"},
                {"label": "砸落伤害", "duration": 0.4},
                {"label": f"安全 burst 筹码 · 价值 {reward_value}", "duration": reward_lifetime,
                 "durationFieldId": "reward-lifetime"},
            ])
        elif object_id in _ENVIRONMENT_IDS:
            metadata["usage"] = ["round-director"]
            metadata["lifecycle"] = "由 round-director 在同一竞技场运行时选用；配置资源不是独立场景。"
        elif object_id in _WEAPON_IDS:
            metadata["usage"] = ["growth-system", "automatic-combat"]
            metadata["lifecycle"] = "通过成长选项取得或升级；由自动战斗系统使用。"
        elif object_id == "character-animation":
            metadata["usage"] = ["player"]
            metadata["facets"] = {"art": "程序绘制形状、摆动和缩放；源码没有绑定角色图片或 SpriteFrames。"}
        elif object_id == "visual-direction":
            metadata["usage"] = ["arena-scene", "character-animation"]
            values = _field_values(target)
            colors = [values.get(key) for key in ("felt-color", "gold-color", "accent-color")]
            metadata["facets"] = {"art": "使用程序绘制的绒面、轮盘、牌面、筹码、危险预告和文字；当前绑定来源不含 PNG 美术资产。"}
            if all(isinstance(color, str) for color in colors):
                metadata["preview"] = _preview("semantic", "程序绘制配色 · 绒面 %s · 金色 %s · 强调 %s" % tuple(colors))
        elif object_id == "game-interface":
            metadata["usage"] = ["round-director", "growth-system"]
            enabled = _field_values(target).get("virtual-stick-enabled")
            if isinstance(enabled, bool):
                metadata["preview"] = _preview("interaction", "游戏界面 · 虚拟摇杆%s" % ("已启用" if enabled else "未启用"))

        # Refresh paths, preview timing, bounds, and source provenance from this
        # precise commit.  Only explicitly authored lock/layout/art details
        # survive as overrides; stale source-derived facts never do.
        _merge_source_metadata(target, metadata, source_commit)

    additions = [
        {
            "id": "growth-transition-enter-upgrade", "kind": "rule", "name": "成长状态转换 · running → upgrade",
            "description": "达到当前升级阈值后生成升级选项，并由轮次调度器打开升级选择状态。",
            "parentId": "growth-system", "relations": [],
            "sourceBindings": ["scripts/simulation/growth_system.gd", "scripts/simulation/round_director.gd"],
            "fields": [],
            "workbench": {
                "role": "state", "scope": "runtime", "driver": "scripts/simulation/growth_system.gd",
                "guard": "options.is_empty() 且 experience >= cost()；begin_upgrade() 返回 true。",
                "fromState": "running", "toState": "upgrade",
                "provenance": {"kind": "inference", "sourcePaths": [
                    "scripts/simulation/growth_system.gd", "scripts/simulation/round_director.gd"]},
                "preview": _preview("rule", "begin_upgrade() 扣除 cost()、提升等级并构造升级选项；open_upgrade() 设置 upgrade。"),
                "sourceCommit": source_commit,
            },
        },
        {
            "id": "growth-transition-choose-upgrade", "kind": "rule", "name": "成长状态转换 · upgrade → upgrade / running",
            "description": "合法选择应用后清空选项；若仍有可连续处理的升级则保留选择状态，否则返回运行状态。",
            "parentId": "growth-system", "relations": [],
            "sourceBindings": ["scripts/simulation/growth_system.gd", "scripts/simulation/round_director.gd"],
            "fields": [],
            "workbench": {
                "role": "state", "scope": "runtime", "driver": "scripts/simulation/growth_system.gd",
                "guard": "index 位于 options 范围内；武器选项需 current < 5；若为新武器，还需 combat.levels.size() < weapon_slots。",
                "fromState": "upgrade", "toState": "upgrade（仍有升级可处理）或 running（begin_upgrade() 返回 false）",
                "provenance": {"kind": "inference", "sourcePaths": [
                    "scripts/simulation/growth_system.gd", "scripts/simulation/round_director.gd"]},
                "preview": _preview("rule", "choose() 应用一项合法升级；调度器继续检查连续升级，否则恢复 running。"),
                "sourceCommit": source_commit,
            },
        },
        {
            "id": "player-arena-instance", "kind": "entity", "name": "赌场游侠 · 战斗场景实例",
            "description": "arena.tscn 中实例化的玩家节点；每局重置到可玩区域中心，之后受移动输入控制。位置展示的是重置起点，不是运行时当前位置。",
            "parentId": "arena-scene", "relations": [
                {"type": "uses_definition", "targetId": "player"},
                {"type": "starts_at", "targetId": "player-start-entry"},
            ],
            "sourceBindings": ["scenes/arena.tscn", "scenes/player.tscn", "scripts/simulation/round_director.gd", "scripts/simulation/player.gd"],
            "fields": [],
            "workbench": {
                "role": "instance", "scope": "runtime", "definitionId": "player", "sceneId": "arena-scene",
                "lock": "fixed", "position": player_start, "bounds": viewport, "anchor": [0.5, 0.5],
                "driver": "scripts/simulation/player.gd", "lifecycle": "场景加载时创建；每局重置回中心入口后可移动；失败或重新开始时状态重置。",
                "provenance": {"kind": "fact", "sourcePaths": ["scenes/arena.tscn", "scenes/player.tscn", "scripts/simulation/round_director.gd", "scripts/simulation/player.gd"]},
                "preview": _preview("motion", "程序绘制玩家实例；位置为每局重置起点，非运行时位置"),
                "sourceCommit": source_commit,
                "usage": ["movement-input", "automatic-combat", "growth-system"],
            },
        },
        {
            "id": "player-start-entry", "kind": "rule", "name": "玩家每局起始入口",
            "description": "玩家每次重置时放到 BOUNDS.get_center()；这是程序计算的起始位置，不是独立的场景节点。",
            "parentId": "arena-scene", "relations": [{"type": "starts_player", "targetId": "player-arena-instance"}],
            "sourceBindings": ["scripts/simulation/round_director.gd", "scripts/simulation/player.gd"], "fields": [],
            "workbench": {
                "role": "entry", "scope": "scene", "definitionId": "player", "sceneId": "arena-scene",
                "lock": "fixed", "position": player_start, "bounds": viewport, "anchor": [0.5, 0.5],
                "driver": "scripts/simulation/round_director.gd", "lifecycle": "reset_run() 每次调用时用场地矩形的中心重设玩家位置。",
                "provenance": {"kind": "fact", "sourcePaths": ["scripts/simulation/round_director.gd", "scripts/simulation/player.gd"]},
                "preview": _preview("semantic", "代码计算的起始位置标记；没有单独入口资源"),
                "sourceCommit": source_commit,
                "usage": ["player-arena-instance"],
            },
        },
    ]
    for index, (enemy_id, name, description) in enumerate([
        ("enemy-kind-0", "追赶型敌人 · 筹码虫", "按轮次成长的近身追赶敌人；生成类型索引 0，死亡后掉落成长筹码。"),
        ("enemy-kind-1", "预告冲刺型敌人 · 扑克牌侍从", "停顿后预告直线冲刺，再回到追赶；生成类型索引 1。"),
        ("enemy-kind-2", "高生命敌人 · 金库守卫", "移动速度较慢、生命较高；生成类型索引 2，死亡后掉落较多成长筹码。"),
    ]):
        additions.append({
            "id": enemy_id, "kind": "entity", "name": name, "description": description,
            "parentId": None, "relations": [{"type": "spawned_by", "targetId": "enemy-roster"}],
            "sourceBindings": ["scripts/simulation/enemy_spawner.gd", "scenes/enemy.tscn"], "fields": [],
            "workbench": {
                "role": "definition", "scope": "shared", "driver": "scripts/simulation/enemy_spawner.gd",
                "lifecycle": "由 enemy-roster 动态生成；仅存活于运行时，不作为永久场景实例。",
                "provenance": {"kind": "inference", "sourcePaths": ["GDD.md", "scripts/simulation/enemy_spawner.gd", "scenes/enemy.tscn"]},
                "preview": _preview("semantic", f"生成类型 {index} · 程序绘制敌人；没有独立图片资源"),
                "sourceCommit": source_commit,
                "usage": ["enemy-roster"],
            },
        })

    for item in additions:
        if item["id"] not in by_id:
            result["objects"].append(item)
            by_id[item["id"]] = item
        else:
            _merge_source_metadata(by_id[item["id"]], item["workbench"], source_commit)
    # Relations are part of the derived read-only projection.  Keep existing
    # authored relations intact and append only missing semantic links.
    links = {
        "player": [{"type": "has_scene_instance", "targetId": "player-arena-instance"}],
        "enemy-roster": [{"type": "spawns_definition", "targetId": enemy_id} for enemy_id in ("enemy-kind-0", "enemy-kind-1", "enemy-kind-2")],
        "round-director": [{"type": "selects_environment", "targetId": environment_id} for environment_id in _ENVIRONMENT_IDS],
        "growth-system": [
            {"type": "state_transition", "targetId": "growth-transition-enter-upgrade"},
            {"type": "state_transition", "targetId": "growth-transition-choose-upgrade"},
        ],
    }
    for object_id, relations in links.items():
        current = by_id.get(object_id)
        if current is None:
            continue
        existing = {(rel["type"], rel["targetId"]) for rel in current.get("relations", [])}
        current["relations"].extend(rel for rel in relations if (rel["type"], rel["targetId"]) not in existing)
    # Current Casino has one playable arena scene and ten in-arena presets.
    # Explicitly expose only scene objects here; project-view catalogs can use
    # this same projection instead of treating environment resources as rooms.
    return validate_document(result)

