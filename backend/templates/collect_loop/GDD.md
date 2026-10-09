# Game Design Document

## Concept
A compact top-down collect-loop game that demonstrates a complete, understandable play cycle in one arena.

## Player experience
The player moves a teal avatar with WASD or arrow keys, collects gold tokens, and races a visible countdown. Collecting all required tokens wins; time running out loses. R restarts either result.

## Scope
One 640×360 logical viewport, one arena, procedural geometric art, keyboard input, and three tunable gameplay values. No enemies, progression, persistence, networking, audio, external assets, or export pipeline are part of this MVP.

## Lifecycle
The trusted template starts locked. A separately verified implementation sets `initialized` and the server-approved count, time limit, and player speed. Preparation metadata alone never enables play.
