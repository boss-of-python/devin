"""ECHO-BREACH bootloader: wires the FSM, scenes and per-frame simulation."""
from __future__ import annotations

import argparse
import sys

from ursina import Entity, Ursina, Vec3, application, camera, destroy, held_keys, mouse

from src.core.engine import (
    AssetCache,
    AudioDirector,
    SpatialCuller,
    clamped_dt,
    configure_window,
)
from src.core.event_bus import EventBus, Topics
from src.core.state_manager import GameState, StateManager
from src.entities.echo_agent import EchoGhost
from src.entities.player import Player
from src.entities.weapon import ARCHETYPES, Weapon
from src.procedural.room_generator import apply_atmosphere, build_arena
from src.telemetry.recorder import TelemetryRecorder, frame_from_player
from src.telemetry.serializer import load_ghost_runs, prune_runs, save_run
from src.ui.hud import HUD, ExtractionSummary, TelemetryMap
from src.ui.terminal_menu import BootMenu, HubMenu, PauseOverlay

MAX_ECHOES = 3


class Game(Entity):
    """Owns every scene and routes input/update by current game state.

    Ursina calls `update()` and `input()` on every enabled entity, so the game
    controller is itself an entity rather than a set of module-level hooks.
    """

    def __init__(self, seed: int | None = None, echo_count: int = MAX_ECHOES) -> None:
        super().__init__()
        self.bus = EventBus()
        self.state = StateManager(event_bus=self.bus)
        self.assets = AssetCache()
        self.audio = AudioDirector(self.assets)
        self.culler = SpatialCuller()
        self.seed = seed
        self.echo_count = echo_count

        self.boot_menu = BootMenu()
        self.hub_menu = HubMenu(enabled=False)
        self.pause_overlay = PauseOverlay(enabled=False)
        self.hud: HUD | None = None
        self.telemetry_map: TelemetryMap | None = None
        self.summary: ExtractionSummary | None = None

        self.player: Player | None = None
        self.weapon: Weapon | None = None
        self.arena = None
        self.echoes: list[EchoGhost] = []
        self.recorder = TelemetryRecorder()
        self.ghost_records = load_ghost_runs(self.echo_count)
        self.last_record = None

        self._camera_home = camera.parent
        self._camera_home_position = camera.position
        mouse.locked = False
        self._subscribe()

    # -- events ------------------------------------------------------------
    def _subscribe(self) -> None:
        self.bus.subscribe(Topics.ENTITY_DAMAGED, self._on_damage)
        self.bus.subscribe(Topics.ECHO_DESTROYED, self._on_echo_destroyed)
        self.bus.subscribe(Topics.PLAYER_DIED, lambda **kw: self.end_run("death"))
        self.bus.subscribe(Topics.TERMINAL_BREACHED, self._on_terminal_breached)
        self.bus.subscribe(Topics.WEAPON_FIRED, self._on_weapon_fired)

    def _on_weapon_fired(self, report=None, **kwargs) -> None:
        self.state.stats.shots_fired += 1
        if report and report.get("damage"):
            self.state.stats.shots_hit += 1

    def _on_damage(self, target=None, amount: float = 0.0, source: str = "", **kwargs) -> None:
        if target is self.player:
            if self.hud:
                self.hud.flash_damage(amount / 10.0)
        else:
            self.state.stats.damage_dealt += amount

    def _on_echo_destroyed(self, **kwargs) -> None:
        self.state.stats.echoes_destroyed += 1
        self.state.stats.shards += 2

    def _on_terminal_breached(self, **kwargs) -> None:
        self.state.stats.rooms_breached += 1
        self.state.stats.shards += 3
        if self.hud:
            self.hud.set_status("<lime>MEMORY CORE EXTRACTED</lime>")
        if all(t.breached for t in self.arena.terminals):
            self.end_run("extraction")

    # -- scene lifecycle ---------------------------------------------------
    def enter_hub(self) -> None:
        self.teardown_run()
        self.boot_menu.enabled = False
        self.hub_menu.enabled = True
        mouse.locked = False
        self.ghost_records = load_ghost_runs(self.echo_count)
        self.hub_menu.render(self.state.profile, len(self.ghost_records), self.state.echo_health())

    def start_run(self, loadout: str) -> None:
        if not self.state.transition(GameState.IN_RUN):
            return
        self.hub_menu.enabled = False
        self.boot_menu.enabled = False
        if self.summary:
            destroy(self.summary)
            self.summary = None
        if self.telemetry_map:
            destroy(self.telemetry_map)
            self.telemetry_map = None

        apply_atmosphere()
        self.culler.clear()
        self.arena = build_arena(
            seed=self.seed,
            echo_count=self.echo_count,
            culler=self.culler,
            event_bus=self.bus,
        )

        perks = self.state.profile.perks
        self.player = Player(
            event_bus=self.bus,
            health=100.0 + perks.health_bonus,
            sprint_multiplier=1.6 * perks.sprint_multiplier,
        )
        self.player.position = self.arena.player_spawn + Vec3(0, 0.2, 0)
        self.player.damage_receiver = self.player
        self.weapon = Weapon(
            archetype=loadout,
            event_bus=self.bus,
            audio=self.audio,
            magazine_bonus=perks.magazine_bonus,
        )

        self.echoes = []
        for i, record in enumerate(self.ghost_records):
            spawn = self.arena.echo_spawns[i % len(self.arena.echo_spawns)] if self.arena.echo_spawns else Vec3(0, 0, 0)
            ghost = EchoGhost(
                record=record,
                health=self.state.echo_health(),
                reaction_time=self.state.echo_reaction_time(),
                palette_index=i,
                event_bus=self.bus,
                audio=self.audio,
                position=spawn,
            )
            self.echoes.append(ghost)

        self.hud = HUD()
        self.hud.set_objective(
            f"BREACH {len(self.arena.terminals)} MEMORY CORES  //  HOLD [E]\nECHOES ACTIVE: {len(self.echoes)}"
        )
        self.recorder.start()
        mouse.locked = True

    def teardown_run(self) -> None:
        for ghost in self.echoes:
            destroy(ghost)
        self.echoes.clear()
        if self.arena:
            self.arena.destroy()
            self.arena = None
        if self.weapon:
            destroy(self.weapon)
            self.weapon = None
        if self.player:
            camera.parent = self._camera_home
            camera.position = self._camera_home_position
            camera.rotation = Vec3(0, 0, 0)
            destroy(self.player)
            self.player = None
        if self.hud:
            destroy(self.hud)
            self.hud = None
        self.culler.clear()

    def end_run(self, outcome: str) -> None:
        if self.state.state is not GameState.IN_RUN:
            return
        target = GameState.EXTRACTION if outcome == "extraction" else GameState.RUN_DEATH
        self.state.transition(target)
        self.recorder.stop()
        self.state.stats.elapsed = self.recorder.elapsed

        record = self.recorder.build_record(
            outcome,
            shots_fired=self.state.stats.shots_fired,
            shots_hit=self.state.stats.shots_hit,
            damage_dealt=self.state.stats.damage_dealt,
            rooms_breached=self.state.stats.rooms_breached,
            loadout=self.weapon.archetype.weapon_id if self.weapon else "carbine",
            shards=self.state.stats.shards,
        )
        if len(record.frames) > 1:
            save_run(record)
            prune_runs()
        self.last_record = record

        layout = self.arena.layout if self.arena else None
        self.state.complete_run(outcome)
        self.teardown_run()
        mouse.locked = False

        if layout is not None:
            self.telemetry_map = TelemetryMap(layout)
            self.telemetry_map.render_run(record, self.ghost_records)
        self.summary = ExtractionSummary()
        self.summary.render(outcome, self.state.stats, self.state.stats.shards, self.state.echo_health())

    # -- input -------------------------------------------------------------
    def input(self, key: str) -> None:  # noqa: A003 - ursina hook
        if key.endswith((" up", " hold")):
            return
        state = self.state.state
        if state is GameState.BOOT_MENU:
            if key in ("1", "2", "3"):
                self.boot_menu.select(int(key) - 1)
            elif key == "enter":
                if not self.boot_menu.ready:
                    self.boot_menu.skip()
                    return
                self.state.transition(GameState.HUB)
                self.enter_hub()
            elif key == "escape":
                application.quit()
        elif state is GameState.HUB:
            if key in ("f1", "f2", "f3"):
                self.hub_menu.buy(self.state.profile.perks, int(key[1]) - 1)
                self.state.save_profile()
                self.hub_menu.render(self.state.profile, len(self.ghost_records), self.state.echo_health())
            elif key == "enter":
                self.start_run(self.boot_menu.loadout)
            elif key == "escape":
                self.state.transition(GameState.BOOT_MENU)
                self.hub_menu.enabled = False
                self.boot_menu.enabled = True
        elif state is GameState.IN_RUN:
            if key == "escape":
                self.state.transition(GameState.RUN_PAUSED)
                self.pause_overlay.enabled = True
                mouse.locked = False
            elif key == "space" and self.player:
                self.player.jump()
            elif key == "r" and self.weapon:
                self.weapon.reload()
            elif key in ("1", "2", "3") and self.weapon:
                self.weapon.equip(list(ARCHETYPES)[int(key) - 1])
        elif state is GameState.RUN_PAUSED:
            if key == "escape":
                self.state.transition(GameState.IN_RUN)
                self.pause_overlay.enabled = False
                mouse.locked = True
            elif key == "q":
                self.pause_overlay.enabled = False
                self.end_run("abort")
                self.state.transition(GameState.HUB)
                self.enter_hub()
        elif state in (GameState.RUN_DEATH, GameState.EXTRACTION):
            if key == "enter":
                if self.summary:
                    destroy(self.summary)
                    self.summary = None
                if self.telemetry_map:
                    destroy(self.telemetry_map)
                    self.telemetry_map = None
                self.state.transition(GameState.HUB)
                self.enter_hub()

    # -- frame -------------------------------------------------------------
    def update(self) -> None:  # noqa: D102 - ursina hook
        dt = clamped_dt()
        state = self.state.state

        if state is GameState.BOOT_MENU:
            self.boot_menu.step(dt, self.state.profile)
            return
        if state in (GameState.HUB, GameState.RUN_PAUSED, GameState.RUN_DEATH, GameState.EXTRACTION):
            return
        if not self.player or not self.weapon:
            return

        self.player.step(dt)
        moving = self.player.move_input.length() > 0
        self.weapon.step(dt, moving=moving)

        if held_keys["left mouse"]:
            self.weapon.fire(self.player)

        for ghost in list(self.echoes):
            if not ghost.alive:
                self.echoes.remove(ghost)
                continue
            ghost.step(dt, self.player)

        interacting = bool(held_keys["e"])
        progress = 0.0
        for terminal in self.arena.terminals:
            terminal.step(dt, self.player, interacting)
            progress = max(progress, terminal.progress)
        if self.hud:
            self.hud.show_breach(progress)
            self.hud.update_from(self.player, self.weapon, dt)

        self.culler.update(dt)
        self.bus.flush()

        weapon_id = self.weapon.archetype.weapon_id
        firing = self.weapon.fired_this_tick
        self.recorder.tick(dt, lambda t: frame_from_player(t, self.player, weapon_id, firing))
        self.state.stats.elapsed = self.recorder.elapsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ECHO-BREACH")
    parser.add_argument("--seed", type=int, default=None, help="deterministic level seed")
    parser.add_argument("--echoes", type=int, default=MAX_ECHOES, help="max ghosts replayed per run")
    parser.add_argument("--windowed", action="store_true", help="run in a window instead of borderless")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = Ursina(title="ECHO-BREACH", borderless=False, fullscreen=False, vsync=True, development_mode=False)
    configure_window(borderless=not args.windowed)

    Game(seed=args.seed, echo_count=args.echoes)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
