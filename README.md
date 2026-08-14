# ECHO-BREACH

Cyberpunk roguelite FPS in Python/Ursina. Every failed incursion is serialized as
20Hz telemetry; the next run replays those tracks as autonomous **Echoes** —
ghosts that walk your old paths, fire at your old timings, and switch to a
direct chase when you block them.

```
saves/run_echo_*.json  ->  top 3 by survival  ->  Hermite spline playback  ->  EchoGhost
```

## Run it

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py                 # optional: --seed 42 --echoes 3 --windowed
```

## Controls

| Input | Action |
| --- | --- |
| `WASD` | move |
| `Shift` | sprint (1.6x) |
| `Ctrl` while sprinting | slide (camera drops to Y=0.9) |
| `Space` | jump |
| `LMB` | fire |
| `R` | reload |
| `1/2/3` | swap carbine / sidearm / plasma |
| `E` (hold 3s) | breach a memory core |
| `Esc` | pause, then `Q` to abort to hub |
| `Enter` | boot menu -> hub -> start run; dismiss post-run screen |
| `F1/F2/F3` | buy sprint / magazine / vitality perks in the hub |

## Layout

```
src/core/        engine.py (Ursina context, asset cache, 3D audio, culling)
                 state_manager.py (FSM, threat curve, perk tree, profile)
                 event_bus.py (pub/sub)
src/entities/    player.py, weapon.py, echo_agent.py
src/telemetry/   recorder.py (20Hz ring buffer), replayer.py (Hermite), serializer.py
src/procedural/  grid_builder.py (BSP), room_generator.py (3D arena, terminals)
src/ui/          hud.py (HUD, vignette, telemetry map), terminal_menu.py (CRT menus)
tests/           test_core.py, test_sync.py (10-Echo headless stress test)
```

Everything under `src/core/state_manager.py`, `src/telemetry/` and
`src/procedural/grid_builder.py` is ursina-free, so the maths and data pipeline
run headlessly in CI.

## Key models

- **Threat curve** — `Threat(R) = T0 * (1 + 0.35*ln(R+1)) + 0.5*Accuracy*T0`, scaling
  Echo health with your run count and lifetime accuracy.
- **Telemetry** — `collections.deque(maxlen=12000)` (10 min at 20Hz), frames dropped
  while displacement < 0.02 m and rotation < 0.5 deg.
- **Playback** — cubic Hermite with Catmull-Rom tangents, exact through every
  keyframe; yaw uses shortest-arc interpolation.
- **Levels** — recursive BSP over a 50x50 grid, corridors between leaf centres,
  player and Echoes spawned at maximal Euclidean separation.

## Tests

```bash
python -m unittest discover -s tests -v
```

`tests/test_sync.py` replays 10 concurrent Echoes for 20 s of simulated time at
60 FPS, asserting no playhead desync, a bounded allocation budget, and playback
cost well under the frame budget.

## Packaging

```bash
pip install pyinstaller
python build_executable.py --backend pyinstaller --onefile
```

## Assets

`assets/` ships empty on purpose: the game is fully playable on procedural
primitives, and `AssetCache` returns `None` for missing textures/audio instead of
raising. Drop `.png`/`.wav` files in (`shot_laser.wav`, `glitch_hit.wav`,
`reload.wav`, ...) and they are picked up automatically.
