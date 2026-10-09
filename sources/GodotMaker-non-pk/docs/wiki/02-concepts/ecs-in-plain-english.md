# ECS in plain English

ECS (Entity-Component-System) sounds technical but it is just a clean way to organise game logic. This page explains what it is and why your generated game uses it — no programming experience needed.

---

## The old way

In a typical Godot project, each game object is a "Node" with a script attached. That script holds everything: what the object looks like, what data it tracks, and what it does every frame. A player script might handle movement, health, animation, sound, and score — all in one file, all tangled together.

This works fine for small games. As the game grows, the scripts grow too. Adding a new feature often means editing a script you already finished, which can break things you were not expecting to break. Two scripts might both try to control the same data. Testing one behaviour in isolation becomes hard because everything is connected.

---

## The ECS way

ECS splits the three concerns apart — data, identity, and behaviour — and keeps each one in its own place.

### Entity

An entity is just an ID. It has no data and no behaviour of its own. Think of it as a sticky note with a number written on it: `enemy_42`. That number is how everything else refers to this game object.

### Component

A component is a small bag of data attached to an entity. It describes one property of that entity and nothing else. Examples:

```
Health { current: 5, max: 10 }
Position { x: 320, y: 180 }
Speed { value: 150 }
Damage { amount: 2 }
```

One entity can have many components. An enemy might have `Health`, `Position`, `Speed`, and `Damage`. A wall might only have `Position`. A score widget might only have `Score`. You mix and match.

### System

A system is a function that runs every frame. Each system looks for entities that have a specific set of components and does something with them. The system does not care which entity number it is — it just looks at the components.

Here is a pseudocode example of a damage system:

```
every frame:
    for each entity that has both Health and Damage:
        health.current = health.current - damage.amount
        if health.current <= 0:
            mark entity for removal
```

That system only needs to exist once. It works for every enemy, every projectile, every trap — anything with a `Health` and a `Damage` component.

---

## Why GodotMaker uses it

### Consistency for AI-written code

The ECS pattern gives AI-written code a predictable shape. A worker implementing a "gravity" feature knows it will create a `Gravity` component and a `GravitySystem`. A reviewer checking that code knows where to look. Every feature follows the same structure, which means far fewer surprises and far fewer bugs introduced by misunderstanding someone else's script.

### Easy to extend

Adding a new feature means adding a new component and a new system. You do not touch the existing code. If you want enemies to become stunned, you add a `Stunned` component and update the `MovementSystem` to skip entities that have it. You are not rewriting the enemy script — you are adding a small, isolated piece alongside it.

### Works well with parallel workers

GodotMaker's `/gm-build` dispatches multiple workers at the same time, each implementing a different system. Because each system lives in its own file and reads/writes its own components, workers rarely need to touch the same file. They can work in parallel without stepping on each other.

### The addon doing the work

GodotMaker uses [gecs](https://github.com/csprance/gecs), an open-source ECS addon for Godot 4. It handles all the machinery — tracking which entities have which components, running systems in the right order, managing the entity lifecycle. Your generated game simply uses its API.

---

## What you will see in the generated project

When you open the project that GodotMaker builds, the code is organised like this:

```
src/
  components/      one file per component (e.g. health.gd, position.gd, damage.gd)
  systems/         one file per system (e.g. damage_system.gd, movement_system.gd)
  entities/        helper scripts that bundle common component sets together
```

If you look inside `src/systems/damage_system.gd`, you will see it query for entities with specific components, loop over the results, and apply changes. If you look inside `src/components/health.gd`, you will see only data — no logic.

You do not need to understand the ECS machinery to play the game or extend it. But knowing this layout is there makes it much easier if you ever open the code and wonder "where does the health logic live?". The answer is always: components hold data in `src/components/`, systems hold behaviour in `src/systems/`.

---

For more about `gecs`, see the [gecs repository on GitHub](https://github.com/csprance/gecs).
