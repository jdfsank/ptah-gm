# One-room loop fixture

A source-only Godot 4.6.3 project for a real local smoke test. See [SPEC.md](SPEC.md)
for mechanic IDs, mutation semantics, and the evidence boundary.

Run the playable fixture:

```sh
godot --path tests/fixtures/one_room_loop
```

Run the identical headless journey used for baseline and faults:

```sh
mkdir -p /tmp/godotmaker-fixture
XDG_DATA_HOME=/tmp/godotmaker-fixture/data \
XDG_CONFIG_HOME=/tmp/godotmaker-fixture/config \
XDG_CACHE_HOME=/tmp/godotmaker-fixture/cache \
godot --headless --fixed-fps 60 --path tests/fixtures/one_room_loop \
  --script res://tests/smoke_runner.gd \
  -- --report /tmp/godotmaker-fixture/assertions.json
```

The writable XDG paths avoid restricted home-directory failures in a sandbox.
`--fixed-fps 60` speeds up the test while retaining deterministic physics steps;
the test also runs without that option. No addons or downloaded assets are
required. The scene uses built-in polygons and GUI controls.

For each mutation, copy the source to a fresh directory, set `variant.gd`'s
`NAME` to one of `always_open_door`, `stale_hud`, `pause_input_leak`, or
`dirty_restart`, and run the same command against that copy. Do not edit the
smoke runner. The baseline must exit 0; each fault must exit 1 and write a FAIL
report containing at least one failed required mechanic assertion.

The journey covers Start, real movement and wall/gate collisions, key pickup,
HUD updates, a navigable pause menu, resume, normal exit, result, and clean
restart. It is a fixed test fixture, not a generated game or visual proof.
