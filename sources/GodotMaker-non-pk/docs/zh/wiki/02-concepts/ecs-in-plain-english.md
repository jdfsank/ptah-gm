# 大白话讲 ECS

ECS（Entity-Component-System，实体-组件-系统）听起来很技术，但它其实只是一种组织游戏逻辑的清晰方式。这篇文章解释它是什么、为什么你生成的游戏要用它——不需要任何编程经验。

---

## 老办法

在典型的 Godot 项目里，每个游戏对象都是一个"节点"（Node），上面挂着一个脚本。脚本里塞满了所有东西：这个对象长什么样、它追踪哪些数据、每帧它要做什么。一个玩家脚本可能同时处理移动、血量、动画、音效和分数——全部挤在一个文件里，全部缠在一起。

小游戏这么干没问题。随着游戏变大，脚本也越来越膨胀。加一个新功能往往意味着要去改一个你认为早就写完的脚本，然后出现你完全没预料到的 bug。两个脚本可能会同时争着控制同一份数据。想单独测试某个行为变得很难，因为所有东西都连在一起。

---

## ECS 的办法

ECS 把三件事拆分开来——数据、身份、行为——各放各的地方。

### Entity（实体）

实体就是一个 ID，没有自己的数据，也没有自己的行为。把它想象成一张贴了数字的便利贴：`enemy_42`。那个数字就是其他所有东西引用这个游戏对象时用的标识。

### Component（组件）

组件是附在实体上的一小包数据。它只描述这个实体的某一个属性，仅此而已。举几个例子：

```
Health { current: 5, max: 10 }
Position { x: 320, y: 180 }
Speed { value: 150 }
Damage { amount: 2 }
```

一个实体可以挂很多组件。一个敌人可能有 `Health`、`Position`、`Speed`、`Damage`；一堵墙可能只有 `Position`；一个计分控件可能只有 `Score`。随意搭配组合。

### System（系统）

系统是每帧都会运行的函数。每个系统查找拥有特定组件组合的实体，然后对它们做某件事。系统不关心具体是哪个实体编号——它只看组件。

下面是一个伤害系统的伪代码示例：

```
every frame:
    for each entity that has both Health and Damage:
        health.current = health.current - damage.amount
        if health.current <= 0:
            mark entity for removal
```

这个系统只需要写一次，就能对所有敌人、所有子弹、所有陷阱通用——只要它们有 `Health` 和 `Damage` 组件就行。

---

## 为什么 GodotMaker 用它

### 让 AI 写的代码有迹可循

ECS 模式给 AI 生成的代码提供了可预期的结构。Worker（执行者）实现"重力"功能时，它知道要创建一个 `Gravity` 组件和一个 `GravitySystem`。Reviewer（评审者）检查这段代码时，知道去哪里找。每个功能都遵循同一套结构，意味着大大减少意外，大大减少因为看不懂别人的脚本而引入的 bug。

### 扩展起来很方便

加新功能 = 加一个新组件 + 加一个新系统，不用动现有代码。想让敌人有眩晕状态？加一个 `Stunned` 组件，然后让 `MovementSystem` 跳过带这个组件的实体。你不是在重写敌人脚本——你是在旁边加了一小块独立的东西。

### 和并行 Worker 天然契合

GodotMaker 的 `/gm-build` 同时派出多个 Worker，每个 Worker 实现不同的系统。由于每个系统都在自己的文件里，只读写自己的组件，Worker 们几乎不会需要改同一个文件，可以并行工作互不干扰。

### 背后干活的插件

GodotMaker 使用 [gecs](https://github.com/csprance/gecs)，一个开源的 Godot 4 ECS 插件。它处理所有底层机制——追踪哪个实体有哪些组件、按正确顺序运行系统、管理实体的生命周期。你生成的游戏直接调用它的 API 就行。

---

## 生成的项目长什么样

打开 GodotMaker 构建出的项目，代码是这样组织的：

```
src/
  components/      one file per component (e.g. health.gd, position.gd, damage.gd)
  systems/         one file per system (e.g. damage_system.gd, movement_system.gd)
  entities/        helper scripts that bundle common component sets together
```

打开 `src/systems/damage_system.gd`，你会看到它查询带有特定组件的实体，遍历结果，然后应用变化。打开 `src/components/health.gd`，你会看到只有数据——没有逻辑。

你不需要理解 ECS 的内部机制才能玩游戏或扩展它。但了解这个布局之后，如果你哪天打开代码好奇"血量逻辑在哪里"，答案永远是：组件在 `src/components/` 存数据，系统在 `src/systems/` 处理行为。

---

关于 `gecs` 的更多信息，参见 [gecs 的 GitHub 仓库](https://github.com/csprance/gecs)。
