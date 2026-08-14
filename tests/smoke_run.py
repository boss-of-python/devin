"""Windowed smoke test: boots the app, plays a scripted run, then exits.

Requires a display (or `--window-type offscreen`). Not part of the headless
unittest suite; run it manually:

    python tests/smoke_run.py --frames 300
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--offscreen", action="store_true")
    args = parser.parse_args(argv)

    from ursina import Ursina, application, held_keys

    from main import Game
    from src.core.engine import configure_window
    from src.core.state_manager import GameState

    Ursina(
        title="ECHO-BREACH smoke",
        borderless=False,
        fullscreen=False,
        size=(1280, 720),
        vsync=False,
        development_mode=False,
        window_type="offscreen" if args.offscreen else "onscreen",
    )
    configure_window(borderless=False)
    game = Game(seed=args.seed)

    game.boot_menu.skip()
    game.input("enter")  # boot menu -> hub
    game.input("enter")  # hub -> run
    assert game.state.state is GameState.IN_RUN, "run did not start"
    assert game.player is not None and game.arena is not None

    taskmgr = application.base.taskMgr
    for frame in range(args.frames):
        held_keys["w"] = 1 if frame % 90 < 60 else 0
        held_keys["shift"] = 1 if 30 <= frame % 90 < 60 else 0
        held_keys["left mouse"] = 1 if frame % 12 == 0 else 0
        if frame == 120:
            game.input("space")
        if frame == 150:
            game.input("r")
        taskmgr.step()

    held_keys["w"] = held_keys["shift"] = held_keys["left mouse"] = 0
    print(f"frames={args.frames} state={game.state.state.value}")
    print(f"player_pos={game.player.world_position} health={game.player.health:.0f}")
    print(f"ammo={game.weapon.current_mag}/{game.weapon.reserve} shots={game.state.stats.shots_fired}")
    print(f"telemetry_frames={len(game.recorder.frames)} elapsed={game.recorder.elapsed:.2f}s")
    print(f"echoes={len(game.echoes)} terminals={len(game.arena.terminals)} rooms={len(game.arena.layout.rooms)}")

    game.end_run("death")
    print(f"post_run_state={game.state.state.value} saved_frames={len(game.last_record.frames)}")
    application.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
