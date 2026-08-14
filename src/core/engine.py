"""Ursina context, asset cache, clock regulation, audio and culling.

Covers STEP_09 through STEP_13 plus STEP_44 (positional audio) and
STEP_48 (spatial culling).
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from ursina import Audio, Entity, Vec3, application, camera, color, load_texture, time, window

WINDOW_SIZE = (1920, 1080)
FIELD_OF_VIEW = 90
MAX_DELTA = 1.0 / 20.0  # clamp: never integrate more than one 20Hz tick per frame
CULL_DISTANCE = 45.0
CULL_INTERVAL = 0.25
BACKGROUND = color.rgb32(5, 5, 10)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSET_DIR = os.path.join(ROOT, "assets")


def configure_window(title: str = "ECHO-BREACH", borderless: bool = False) -> None:
    """Window, vsync and camera conventions (+X right, +Y up, +Z forward)."""
    window.title = title
    window.borderless = borderless
    window.fullscreen = False
    window.exit_button.visible = False
    window.fps_counter.enabled = True
    window.color = BACKGROUND
    window.vsync = True
    application.development_mode = False
    camera.fov = FIELD_OF_VIEW
    camera.clip_plane_near = 0.05
    camera.clip_plane_far = 400


def clamped_dt() -> float:
    """Delta time clamped to avoid physics tunnelling after a frame spike."""
    return min(time.dt, MAX_DELTA)


class AssetCache:
    """Lazy loader/cache for textures and audio (STEP_11).

    Assets are optional: the game is fully playable on procedural primitives,
    so a missing file yields None instead of raising.
    """

    def __init__(self, asset_dir: str = ASSET_DIR) -> None:
        self.asset_dir = asset_dir
        self._textures: dict[str, Any] = {}
        self._audio: dict[str, Any] = {}

    def path(self, *parts: str) -> str:
        return os.path.join(self.asset_dir, *parts)

    def texture(self, name: str):
        if name not in self._textures:
            path = self.path("textures", name)
            self._textures[name] = load_texture(path) if os.path.exists(path) else None
        return self._textures[name]

    def sound(self, name: str):
        if name not in self._audio:
            path = self.path("sfx", name)
            if os.path.exists(path):
                self._audio[name] = Audio(path, autoplay=False, loop=False)
            else:
                self._audio[name] = None
        return self._audio[name]

    def preload(self, textures: Iterable[str] = (), sounds: Iterable[str] = ()) -> None:
        for name in textures:
            self.texture(name)
        for name in sounds:
            self.sound(name)


class AudioDirector:
    """3D positional playback with linear distance falloff (STEP_44)."""

    def __init__(self, cache: AssetCache, max_distance: float = 40.0) -> None:
        self.cache = cache
        self.max_distance = max_distance
        self.enabled = True

    def play(self, name: str, position: Vec3 | None = None, volume: float = 1.0, pitch: float = 1.0) -> None:
        if not self.enabled:
            return
        clip = self.cache.sound(name)
        if clip is None:
            return
        gain = volume
        if position is not None:
            distance = (Vec3(*position) - camera.world_position).length()
            gain *= max(0.0, 1.0 - distance / self.max_distance) ** 2
            if gain <= 0.001:
                return
        clip.volume = gain
        clip.pitch = pitch
        clip.play()


class SpatialCuller:
    """Disables rendering and colliders beyond CULL_DISTANCE from the camera."""

    def __init__(self, distance: float = CULL_DISTANCE, interval: float = CULL_INTERVAL) -> None:
        self.distance = distance
        self.interval = interval
        self._entities: list[Entity] = []
        self._accumulator = 0.0

    def register(self, entity: Entity) -> Entity:
        self._entities.append(entity)
        return entity

    def register_many(self, entities: Iterable[Entity]) -> None:
        self._entities.extend(entities)

    def clear(self) -> None:
        self._entities.clear()

    def update(self, dt: float) -> None:
        self._accumulator += dt
        if self._accumulator < self.interval:
            return
        self._accumulator = 0.0
        origin = camera.world_position
        cutoff = self.distance * self.distance
        alive: list[Entity] = []
        for entity in self._entities:
            if not entity or not hasattr(entity, "world_position"):
                continue
            alive.append(entity)
            delta = entity.world_position - origin
            visible = delta.length_squared() <= cutoff
            if entity.visible != visible:
                entity.visible = visible
                if getattr(entity, "collider", None) is not None:
                    entity.collision = visible
        self._entities = alive
