"""Turns a BSP layout into 3D Ursina geometry (STEP_38 - STEP_41)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from ursina import DirectionalLight, Entity, Vec3, color, scene

from ..core.engine import SpatialCuller
from ..core.event_bus import EventBus, Topics, bus as default_bus
from .grid_builder import Layout, farthest_room_pair, generate_layout, spawn_points

TILE = 2.0  # world metres per grid cell
WALL_HEIGHT = 4.0
FOG_RANGE = (30.0, 120.0)
BREACH_HOLD_SECONDS = 3.0


def grid_to_world(x: int, z: int, size: int) -> Vec3:
    """Centre the grid on the origin so the arena spans +/- size*TILE/2."""
    offset = size * TILE * 0.5
    return Vec3(x * TILE - offset, 0, z * TILE - offset)


class ExtractionTerminal(Entity):
    """Pulsing memory core requiring a 3-second interact hold (STEP_41)."""

    def __init__(self, event_bus: EventBus | None = None, **kwargs):
        super().__init__(model="cube", scale=(1.0, 2.2, 1.0), origin_y=-0.5, color=color.rgb32(46, 60, 92), collider="box", **kwargs)
        self.bus = event_bus or default_bus
        self.core = Entity(parent=self, model="sphere", scale=0.55, y=0.75, color=color.cyan)
        self.progress = 0.0
        self.breached = False
        self._pulse = 0.0

    def step(self, dt: float, player, interacting: bool) -> None:
        self._pulse += dt * 3.0
        self.core.scale = 0.5 + 0.06 * math.sin(self._pulse)
        if self.breached or player is None:
            return
        in_range = (player.world_position - self.world_position).length() < 3.0
        if in_range and interacting:
            self.progress = min(BREACH_HOLD_SECONDS, self.progress + dt)
            self.core.color = color.lime
            if self.progress >= BREACH_HOLD_SECONDS:
                self.complete()
        else:
            self.progress = max(0.0, self.progress - dt * 2.0)
            self.core.color = color.cyan

    def complete(self) -> None:
        self.breached = True
        self.core.color = color.orange
        self.bus.emit(Topics.TERMINAL_BREACHED, position=self.world_position)


@dataclass
class Arena:
    """Everything spawned for one procedural sector."""

    layout: Layout
    entities: list[Entity] = field(default_factory=list)
    terminals: list[ExtractionTerminal] = field(default_factory=list)
    player_spawn: Vec3 = field(default_factory=lambda: Vec3(0, 1, 0))
    echo_spawns: list[Vec3] = field(default_factory=list)

    def destroy(self) -> None:
        from ursina import destroy as ursina_destroy

        for entity in self.entities + list(self.terminals):
            ursina_destroy(entity)
        self.entities.clear()
        self.terminals.clear()


def apply_atmosphere(scene_root=scene) -> None:
    """Deep-black void, key light and linear depth fog (STEP_40)."""
    from ursina import camera, window

    window.color = color.rgb32(5, 5, 10)
    scene_root.fog_color = color.rgb32(5, 5, 10)
    scene_root.fog_density = FOG_RANGE
    light = DirectionalLight(parent=scene_root, y=12, z=6, shadows=False, color=color.rgb32(120, 160, 220))
    light.look_at(Vec3(1, -1.2, 0.4))
    camera.clip_plane_far = 400


def build_arena(
    seed: int | None = None,
    size: int = 50,
    echo_count: int = 3,
    culler: SpatialCuller | None = None,
    event_bus: EventBus | None = None,
) -> Arena:
    """Instantiate floors, walls, pillars, terminals and spawn nodes."""
    layout = generate_layout(size=size, seed=seed)
    arena = Arena(layout=layout)

    floor_cells = layout.floor_cells()
    floor_parent = Entity(model=None)
    arena.entities.append(floor_parent)
    for x, z in floor_cells:
        tile = Entity(
            parent=floor_parent,
            model="cube",
            scale=(TILE, 0.2, TILE),
            position=grid_to_world(x, z, size) + Vec3(0, -0.1, 0),
            color=color.rgb32(34, 44, 68) if (x + z) % 2 else color.rgb32(22, 30, 48),
            collider="box",
        )
        arena.entities.append(tile)
        if culler:
            culler.register(tile)

    for x, z in layout.wall_cells():
        wall = Entity(
            model="cube",
            scale=(TILE, WALL_HEIGHT, TILE),
            origin_y=-0.5,
            position=grid_to_world(x, z, size),
            color=color.rgb32(42, 54, 82),
            collider="box",
        )
        Entity(parent=wall, model="cube", scale=(1.02, 0.02, 1.02), y=0.98, color=color.rgb32(0, 210, 255))
        Entity(parent=wall, model="cube", scale=(1.02, 0.015, 1.02), y=0.06, color=color.rgb32(0, 120, 190))
        arena.entities.append(wall)
        if culler:
            culler.register(wall)

    for x, z in layout.pillar_cells():
        pillar = Entity(
            model="cube",
            scale=(TILE * 0.6, 2.6, TILE * 0.6),
            origin_y=-0.5,
            position=grid_to_world(x, z, size),
            color=color.rgb32(58, 70, 104),
            collider="box",
        )
        Entity(parent=pillar, model="cube", scale=(1.05, 0.06, 1.05), y=0.6, color=color.magenta)
        arena.entities.append(pillar)
        if culler:
            culler.register(pillar)

    # spawn nodes: player and echoes at maximal separation (STEP_39)
    if len(layout.rooms) > 1:
        room_a, room_b = farthest_room_pair(layout.rooms)
        arena.player_spawn = grid_to_world(*room_a.center, size) + Vec3(0, 0.2, 0)
        echo_cells = spawn_points(layout, echo_count)
        arena.echo_spawns = [grid_to_world(x, z, size) + Vec3(0, 0.2, 0) for x, z in echo_cells]
        terminal_rooms = [room_b] + [r for r in layout.rooms if r is not room_a and r is not room_b][:2]
    else:
        room = layout.rooms[0] if layout.rooms else None
        arena.player_spawn = grid_to_world(*room.center, size) if room else Vec3(0, 1, 0)
        terminal_rooms = [room] if room else []

    for room in terminal_rooms:
        terminal = ExtractionTerminal(position=grid_to_world(*room.center, size), event_bus=event_bus)
        arena.terminals.append(terminal)

    return arena


def layout_bounds(layout: Layout) -> tuple[float, float]:
    extent = layout.size * TILE * 0.5
    return -extent, extent


def world_to_minimap(position: np.ndarray | Vec3, layout: Layout, canvas: float = 0.32) -> tuple[float, float]:
    """Project a world position into normalised minimap UI space (STEP_46)."""
    extent = layout.size * TILE * 0.5
    x = float(position[0]) if not isinstance(position, Vec3) else position.x
    z = float(position[2]) if not isinstance(position, Vec3) else position.z
    return (x / extent) * canvas, (z / extent) * canvas
