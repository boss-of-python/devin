"""Ghost agents replaying past-run telemetry (STEP_32, STEP_34 - STEP_36)."""
from __future__ import annotations

import math
import random

from ursina import Entity, Vec3, color, destroy, lerp, raycast

from ..core.event_bus import EventBus, Topics, bus as default_bus
from ..telemetry.replayer import TrajectoryReplayer
from ..telemetry.serializer import RunRecord

GHOST_PALETTE = (color.cyan, color.magenta, color.rgb32(120, 255, 200))
CHASE_TRIGGER_DISTANCE = 6.0
CHASE_SPEED = 5.5
FIRE_RANGE = 45.0
GLITCH_DURATION = 0.25


class EchoGhost(Entity):
    """A translucent wireframe copy of a past run.

    Default behaviour replays the recorded trajectory verbatim; if the live
    player blocks the recorded path the ghost falls back to a direct
    pursue-and-shoot state (STEP_35).
    """

    def __init__(
        self,
        record: RunRecord,
        health: float = 100.0,
        reaction_time: float = 0.4,
        palette_index: int = 0,
        event_bus: EventBus | None = None,
        audio=None,
        damage: float = 9.0,
        **kwargs,
    ):
        super().__init__(model=None, **kwargs)
        self.bus = event_bus or default_bus
        self.audio = audio
        self.record = record
        self.replayer = TrajectoryReplayer(record.frames, loop=True)
        self.tint = GHOST_PALETTE[palette_index % len(GHOST_PALETTE)]
        self.max_health = health
        self.health = health
        self.reaction_time = reaction_time
        self.damage = damage
        self.state = "REPLAY"
        self.alive = True

        self.torso = Entity(parent=self, model="cube", scale=(0.55, 1.1, 0.3), y=1.15, color=self.tint, alpha=0.45, collider="box")
        self.head = Entity(parent=self, model="sphere", scale=0.36, y=1.85, color=self.tint, alpha=0.55)
        self.legs = Entity(parent=self, model="cube", scale=(0.45, 0.9, 0.28), y=0.45, color=self.tint, alpha=0.3)
        self.aura = Entity(parent=self, model="cube", scale=(0.7, 2.0, 0.5), y=1.0, color=self.tint, alpha=0.08)
        self.torso.damage_receiver = self
        self.head.damage_receiver = self
        self.legs.damage_receiver = self

        self._last_playhead = 0.0
        self._fire_cooldown = 0.0
        self._glitch_timer = 0.0
        self._chase_grace = 0.0

        if not self.replayer.is_empty:
            first = self.replayer.sample_at(0.0)
            self.position = Vec3(*first.pos)

    # -- damage ------------------------------------------------------------
    def take_damage(self, amount: float, source: str = "player") -> None:
        if not self.alive:
            return
        self.health -= amount
        self._glitch_timer = GLITCH_DURATION
        self.bus.emit(Topics.ENTITY_DAMAGED, target=self, amount=amount, source=source)
        if self.health <= 0:
            self.destroy_ghost()

    def destroy_ghost(self) -> None:
        self.alive = False
        self.bus.emit(Topics.ECHO_DESTROYED, position=self.world_position, record=self.record)
        if self.audio:
            self.audio.play("glitch_hit.wav", position=self.world_position, volume=0.8)
        for part in (self.torso, self.head, self.legs, self.aura):
            part.animate_scale(0.01, duration=0.18)
        destroy(self, delay=0.2)

    # -- behaviour ---------------------------------------------------------
    def _apply_glitch(self, dt: float) -> None:
        if self._glitch_timer <= 0:
            for part in (self.torso, self.head, self.legs):
                part.x = lerp(part.x, 0, min(1.0, 10 * dt))
            return
        self._glitch_timer -= dt
        flicker = 0.15 + random.random() * 0.5
        for part in (self.torso, self.head, self.legs):
            part.alpha = flicker
            part.x = random.uniform(-0.06, 0.06)
            part.z = random.uniform(-0.06, 0.06)

    def _path_blocked_by(self, player) -> bool:
        if player is None:
            return False
        to_player = player.world_position - self.world_position
        distance = to_player.length()
        if distance > CHASE_TRIGGER_DISTANCE:
            return False
        forward = Vec3(math.sin(math.radians(self.rotation_y)), 0, math.cos(math.radians(self.rotation_y)))
        if distance < 0.001:
            return True
        return forward.normalized().dot(to_player.normalized()) > 0.5

    def _chase(self, player, dt: float) -> None:
        to_player = player.world_position - self.world_position
        to_player.y = 0
        distance = to_player.length()
        if distance > 2.0:
            self.position += to_player.normalized() * CHASE_SPEED * dt
        self.rotation_y = math.degrees(math.atan2(to_player.x, to_player.z))
        self._try_fire(player, dt, aim_at_player=True)

    def _try_fire(self, player, dt: float, aim_at_player: bool = False) -> None:
        self._fire_cooldown -= dt
        if self._fire_cooldown > 0 or player is None:
            return
        to_player = player.world_position + Vec3(0, 1.2, 0) - (self.world_position + Vec3(0, 1.5, 0))
        distance = to_player.length()
        if distance > FIRE_RANGE:
            return
        direction = to_player.normalized()
        if not aim_at_player:
            aim = Vec3(
                math.sin(math.radians(self.rotation_y)),
                math.sin(math.radians(-self.torso.rotation_x)),
                math.cos(math.radians(self.rotation_y)),
            ).normalized()
            if aim.dot(direction) < 0.94:  # recorded shot was not pointed at the player
                self._fire_cooldown = self.reaction_time
                self._muzzle_flash(aim)
                return
        self._fire_cooldown = self.reaction_time
        self._muzzle_flash(direction)
        hit = raycast(
            self.world_position + Vec3(0, 1.5, 0),
            direction,
            distance=FIRE_RANGE,
            ignore=(self, self.torso, self.head, self.legs, self.aura),
        )
        blocked = hit.hit and hit.entity not in (player, *getattr(player, "children", ()))
        if not blocked:
            player.take_damage(self.damage, source="echo")

    def _muzzle_flash(self, direction: Vec3) -> None:
        flash = Entity(model="quad", billboard=True, scale=0.5, position=self.world_position + Vec3(0, 1.5, 0) + direction * 0.6, color=self.tint)
        destroy(flash, delay=0.05)
        if self.audio:
            self.audio.play("shot_laser.wav", position=self.world_position, volume=0.35, pitch=0.85)

    def step(self, dt: float, player=None) -> None:
        if not self.alive:
            return
        self._apply_glitch(dt)

        if self._path_blocked_by(player):
            self.state = "CHASE"
            self._chase_grace = 1.5
        elif self._chase_grace > 0:
            self._chase_grace -= dt
        else:
            self.state = "REPLAY"

        if self.state == "CHASE":
            self._chase(player, dt)
            return

        sample = self.replayer.advance(dt)
        if sample is None:
            return
        target = Vec3(float(sample.pos[0]), float(sample.pos[1]), float(sample.pos[2]))
        self.position = target
        self.rotation_y = sample.rot_y
        self.torso.rotation_x = sample.pitch * 0.25

        played = self.replayer.playhead
        window_start = self._last_playhead if played >= self._last_playhead else -1.0
        for frame in self.replayer.actions_between(window_start, played):
            if frame.actions.fire:
                self._try_fire(player, 0.0)
                break
        self._last_playhead = played
