# 绯月赌城 · Velvet Eclipse

Original, single-player Gothic-casino action exploration game. Godot 4.6.3 Compatibility, desktop keyboard, five connected rooms, sword/cards/dodge, earned Moonstep, shrine checkpoints, a two-phase boss and ending. No installation or account is needed to play the exported Web bundle through a local HTTP server. No audio is included in this release.

## Play the Web build locally

1. Extract the Web archive, keeping all `index.*` files together.
2. Open a terminal in that folder and run:

   ```sh
   python3 -m http.server 8765 --bind 127.0.0.1
   ```

   Windows users may use `py -m http.server 8765 --bind 127.0.0.1`.
3. Open **http://127.0.0.1:8765/index.html** in a desktop browser with WebAssembly and WebGL 2 support. Wait for the loading screen, then click the game canvas once to give it keyboard focus. Use the same address and port on later visits if you want to Continue the same save.
4. Stop the local server with Ctrl-C when finished. Do not open `index.html` using a `file://` URL. The server binds only to your own computer; this is not public hosting.

From the source project, the equivalent command is:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory build/web-v2
```

The nine engine-exported files are `index.html`, `index.js`, `index.wasm`, `index.pck`, `index.png`, `index.icon.png`, `index.apple-touch-icon.png`, `index.audio.worklet.js`, and `index.audio.position.worklet.js`. Keep even the engine's audio support files with the bundle. The WASM file must be served as `application/wasm`; Python's standard server was checked with that MIME type. Nothing is downloaded from a CDN by the game.

## Controls and route

- A / D or Left / Right: move
- Space / W: jump; after earning Moonstep, press again in midair for a second jump
- J: sword; K: card throw (uses regenerating card energy)
- Shift / L: dodge
- E: interact with the selected nearby grounded doorway, relic, or shrine
- M: discovered-room map; M or Escape closes it
- Escape: pause/resume; menus also support Up / Down, Enter, and mouse clicks

Start opens a fresh run in the Lobby. Explore the Gallery and Clocktower to find Moonstep, then backtrack to the Lobby's upper door. Rest and save at the shrine before entering the Throne. Watch the boss's attack warnings. The map records only visited rooms and cannot teleport. Paused and map states freeze gameplay, including attacks, projectiles and animation; fresh input is required on resume. Death offers the current checkpoint or title. Victory offers a fresh restart or title.

## Saving and Continue

Native play stores a versioned JSON file in Godot's `user://velvet_eclipse_save.json`. Web play uses the application's single localStorage key `velvet_eclipse_save_v1`. Save data is bounded to 64 KiB and validated for schema/version, types, known room/spawn/checkpoint, discovered rooms and coherent progression. Missing/corrupt/unsupported saves disable Continue safely. Starting a new run does not delete or immediately overwrite the existing stored save; a later successful shrine/victory save replaces it.

The browser adapter uses documented `JavaScriptBridge.eval`. All localStorage access, including the property lookup, is inside `try/catch`; embedded JSON is safely encoded as a JavaScript string. It uses `setItem`, then checks an exact `getItem` readback and returns a JSON status string. Null/malformed responses, unavailable JavaScript bridge, policy/quota exceptions, and readback mismatches report failure. A failed disk/browser write still keeps the current session's checkpoint for Retry. It does not delete the old entry first, use private engine filesystem globals, claim success after a timer, or contact a remote save service.

“已存入本浏览器” means that this browser acknowledged the exact saved data. It is not a permanent backup. Saves belong to this browser profile and origin (scheme, host, and port). Private windows, blocking site storage, clearing browser data, profile changes or browser storage eviction can remove/prevent persistence. Use one game tab at a time; simultaneous tabs share the same key and the latest successful save wins. Native and Web saves are separate. Refresh/reopen durability must be checked in the actual target browser; native adapter mocks do not establish it.

Primary API references:
- [Godot JavaScriptBridge eval interface](https://docs.godotengine.org/en/4.6/tutorials/platform/web/javascript_bridge.html#the-eval-interface)
- [MDN localStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage)

## Run or export the source

Open `project.godot` in Godot **4.6.3** and run the main scene, or run:

```sh
godot --path .
```

`scenes/main.tscn` is the title-first player entry. `scenes/game_world.tscn` is a reusable gameplay-entry scene used for isolated system fixtures. Both use the same registered ECS systems and ordinary input/progression path.

The checked-in Web preset is single-threaded, without GDExtension support, and uses the exact official 4.6.3 templates. This delivery environment stores them at `/workspace/shared/velvet-export-tools/4.6.3.stable/web_nothreads_debug.zip` and `web_nothreads_release.zip`. On another machine, change only the two custom-template paths in the Web export preset to your official 4.6.3 files. No engine/dependency patches are needed.

Exact export command used from the source project root:

```sh
HOME="$PWD/.godotmaker/scratch/home" \
XDG_DATA_HOME="$PWD/.godotmaker/scratch/data" \
XDG_CONFIG_HOME="$PWD/.godotmaker/scratch/config" \
XDG_CACHE_HOME="$PWD/.godotmaker/scratch/cache" \
/usr/local/bin/godot --headless --path . --export-release Web build/web-v2/index.html
```

The preset explicitly includes `data/rooms/*.json` for runtime FileAccess, plus all dynamically referenced runtime resources. It excludes tests, generation evidence, reference artwork, docs and tool artifacts. Autoload/runtime dependencies remain included. Chinese UI binds the supplied Noto Sans CJK font; its license is in `assets/fonts/NotoSansCJK-LICENSE.txt`.

## Verification records

The Web v2 delivery moves the boss health panel into the upper HUD area, below the current notice. It leaves the ground-level heroine and sword visible during melee. Panel layout follows the top HUD’s actual height, including the acquired Moonstep row and wrapped objective text. The original Web v1 export remains a separate frozen artifact.

The integrated native headless suite passed **78 of 78 tests across 22 suites**, with zero errors, failures, skips or orphans, including the ordinary five-room route and both boss phases. The v2 suite includes all 77 prior tests plus a boss-panel/notice/ground-lane bounds regression. The implementation provides UI/session/input/storage unit coverage alongside all 62 original gameplay regressions (the two original Main tests now assert the declared title-first flow). Test-only fixtures are labeled and do not grant player-facing damage, ability, or victory shortcuts. Actual browser acceptance is **BLOCKED**: the independent cloud-browser review returned `ERR_BLOCKED_BY_CLIENT` when navigating to the local test URL. Browser boot/rendering, real browser input, and refresh/reopen persistence therefore remain unverified. Native tests, the real export, and exported-PCK native boot do not prove those browser behaviors. No alternate host/route or public hosting was used.

For source verification with the installed engine:

```sh
godot --headless --path . --editor --import
godot --headless --path . --quit-after 120
godot --headless --path . -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd \
  --add res://test/ --ignoreHeadlessMode --report-directory res://reports/m03/all
```

Headless logical engine-event/GUI tests are useful, but do not replace actual browser keyboard, focus and refresh tests. Export versions are frozen once passed to browser review; any later game change requires a new bundle and hash inventory.
