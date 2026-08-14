"""Weapon archetypes, ballistics, recoil and hit FX (STEP_05, STEP_06, STEP_21 - STEP_26)."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from ursina import (
    Entity,
    Vec3,
    camera,
    color,
    destroy,
    lerp,
    raycast,
)

from ..core.event_bus import EventBus, Topics, bus as default_bus

MUZZLE_FLASH_LIFETIME = 0.03
TRACER_LIFETIME = 0.08
DECAL_LIFETIME = 12.0
RECOIL_STIFFNESS = 120.0
RECOIL_DAMPING = 14.0


@dataclass(frozen=True)
class WeaponArchetype:
    """Static ballistics table entry."""

    weapon_id: str
    name: str
    damage: float
    fire_rate: float  # rounds per second
    mag_capacity: int
    reserve_ammo: int
    reload_time: float
    recoil_pitch: float
    recoil_yaw: float
    spread: float
    range: float
    hitscan: bool = True
    projectile_speed: float = 0.0
    tint: Any = color.cyan

    @property
    def shot_interval(self) -> float:
        return 1.0 / self.fire_rate


ARCHETYPES: dict[str, WeaponArchetype] = {
    "carbine": WeaponArchetype(
        weapon_id="carbine",
        name="VX-9 CARBINE",
        damage=18.0,
        fire_rate=8.0,
        mag_capacity=30,
        reserve_ammo=150,
        reload_time=1.6,
        recoil_pitch=1.4,
        recoil_yaw=0.5,
        spread=0.6,
        range=120.0,
        tint=color.cyan,
    ),
    "pistol": WeaponArchetype(
        weapon_id="pistol",
        name="ND-2 SIDEARM",
        damage=32.0,
        fire_rate=3.5,
        mag_capacity=12,
        reserve_ammo=96,
        reload_time=1.1,
        recoil_pitch=2.2,
        recoil_yaw=0.8,
        spread=0.25,
        range=90.0,
        tint=color.azure,
    ),
    "plasma": WeaponArchetype(
        weapon_id="plasma",
        name="HELIOS PLASMA",
        damage=55.0,
        fire_rate=1.6,
        mag_capacity=6,
        reserve_ammo=36,
        reload_time=2.2,
        recoil_pitch=3.4,
        recoil_yaw=1.2,
        spread=0.0,
        range=140.0,
        hitscan=False,
        projectile_speed=48.0,
        tint=color.magenta,
    ),
}


class Projectile(Entity):
    """Newtonian plasma charge integrated per frame (STEP_06)."""

    def __init__(self, origin: Vec3, direction: Vec3, speed: float, damage: float, owner, bus: EventBus, **kwargs):
        super().__init__(
            model="sphere",
            scale=0.18,
            color=color.magenta,
            position=origin,
            **kwargs,
        )
        self.velocity = direction.normalized() * speed
        self.damage = damage
        self.owner = owner
        self.bus = bus
        self.lifetime = 4.0

    def step(self, dt: float) -> bool:
        """Advance one tick; returns False once the projectile should be destroyed."""
        self.lifetime -= dt
        if self.lifetime <= 0:
            return False
        travel = self.velocity * dt
        hit = raycast(self.world_position, travel.normalized(), distance=travel.length(), ignore=(self, self.owner))
        if hit.hit:
            target = getattr(hit.entity, "damage_receiver", None)
            if target is not None:
                target.take_damage(self.damage, source="plasma")
                self.bus.emit(Topics.ENTITY_DAMAGED, target=target, amount=self.damage, source="plasma")
            return False
        self.position += travel
        return True


class Weapon(Entity):
    """Camera-parented viewmodel with sway, recoil spring, ammo and hitscan."""

    def __init__(
        self,
        archetype: WeaponArchetype | str = "carbine",
        event_bus: EventBus | None = None,
        audio=None,
        magazine_bonus: int = 0,
        **kwargs,
    ):
        super().__init__(parent=camera.ui if kwargs.pop("ui_parent", False) else camera, **kwargs)
        self.bus = event_bus or default_bus
        self.audio = audio
        self.magazine_bonus = magazine_bonus
        self.projectiles: list[Projectile] = []

        self.chassis = Entity(parent=self, model="cube", scale=(0.12, 0.1, 0.55), color=color.rgb32(74, 86, 116))
        self.barrel = Entity(parent=self.chassis, model="cube", scale=(0.35, 0.35, 0.6), z=0.7, color=color.rgb32(40, 48, 66))
        self.rail = Entity(parent=self.chassis, model="cube", scale=(0.5, 0.12, 0.45), y=0.6, z=-0.1, color=color.rgb32(0, 190, 240))
        self.emitter = Entity(parent=self.chassis, model="cube", scale=(0.5, 0.5, 0.08), z=1.02, color=color.cyan)
        self.rest_position = Vec3(0.35, -0.28, 0.75)
        self.position = self.rest_position
        self.rotation = Vec3(0, 0, 0)

        self._recoil_offset = 0.0
        self._recoil_velocity = 0.0
        self._sway = Vec3(0, 0, 0)
        self.cooldown = 0.0
        self.reload_timer = 0.0
        self.fired_this_tick = False

        self.archetype = ARCHETYPES["carbine"]
        self.current_mag = 0
        self.reserve = 0
        self.equip(archetype)

    # -- loadout -----------------------------------------------------------
    @property
    def mag_capacity(self) -> int:
        return self.archetype.mag_capacity + self.magazine_bonus

    def equip(self, archetype: WeaponArchetype | str) -> None:
        self.archetype = ARCHETYPES[archetype] if isinstance(archetype, str) else archetype
        self.current_mag = self.mag_capacity
        self.reserve = self.archetype.reserve_ammo
        self.cooldown = 0.0
        self.reload_timer = 0.0
        self.emitter.color = self.archetype.tint

    @property
    def is_reloading(self) -> bool:
        return self.reload_timer > 0

    def reload(self) -> bool:
        if self.is_reloading or self.current_mag >= self.mag_capacity or self.reserve <= 0:
            return False
        self.reload_timer = self.archetype.reload_time
        if self.audio:
            self.audio.play("reload.wav", volume=0.5)
        return True

    def _finish_reload(self) -> None:
        needed = self.mag_capacity - self.current_mag
        loaded = min(needed, self.reserve)
        self.current_mag += loaded
        self.reserve -= loaded
        self.bus.emit(Topics.WEAPON_RELOADED, weapon_id=self.archetype.weapon_id, mag=self.current_mag)

    # -- firing ------------------------------------------------------------
    def can_fire(self) -> bool:
        return self.cooldown <= 0 and not self.is_reloading and self.current_mag > 0

    def fire(self, owner) -> dict[str, Any] | None:
        """Fire one round from screen center; returns a hit report or None."""
        if not self.can_fire():
            if self.current_mag == 0:
                self.reload()
            return None

        self.current_mag -= 1
        self.cooldown = self.archetype.shot_interval
        self.fired_this_tick = True
        self._apply_recoil()

        origin = camera.world_position
        direction = self._spread_direction(camera.forward)
        report: dict[str, Any] = {"hit": False, "damage": 0.0, "point": None, "entity": None}

        if self.archetype.hitscan:
            hit = raycast(origin, direction, distance=self.archetype.range, ignore=(owner, self, self.chassis, self.barrel, self.emitter))
            end = hit.world_point if hit.hit else origin + direction * self.archetype.range
            if hit.hit:
                receiver = getattr(hit.entity, "damage_receiver", None)
                report.update(hit=True, point=end, entity=hit.entity)
                if receiver is not None:
                    receiver.take_damage(self.archetype.damage, source=self.archetype.weapon_id)
                    report["damage"] = self.archetype.damage
                self.spawn_impact(end, hit.normal)
            self.spawn_tracer(origin + direction * 0.6, end)
        else:
            self.projectiles.append(
                Projectile(origin + direction * 0.8, direction, self.archetype.projectile_speed, self.archetype.damage, owner, self.bus)
            )

        self.spawn_muzzle_flash()
        if self.audio:
            self.audio.play("shot_laser.wav", position=origin, volume=0.6)
        self.bus.emit(
            Topics.WEAPON_FIRED,
            weapon_id=self.archetype.weapon_id,
            origin=origin,
            direction=direction,
            report=report,
        )
        return report

    def _spread_direction(self, forward: Vec3) -> Vec3:
        spread = self.archetype.spread / 100.0
        if spread <= 0:
            return Vec3(*forward).normalized()
        jitter = Vec3(random.uniform(-spread, spread), random.uniform(-spread, spread), 0)
        return (Vec3(*forward) + camera.right * jitter.x + camera.up * jitter.y).normalized()

    def _apply_recoil(self) -> None:
        self._recoil_velocity += self.archetype.recoil_pitch * 8.0
        camera.rotation_x -= self.archetype.recoil_pitch * 0.35
        camera.rotation_y += random.uniform(-1, 1) * self.archetype.recoil_yaw * 0.2

    # -- FX ----------------------------------------------------------------
    def spawn_muzzle_flash(self) -> Entity:
        flash = Entity(
            parent=self.chassis,
            model="quad",
            billboard=True,
            scale=1.6,
            z=1.2,
            color=self.archetype.tint,
        )
        destroy(flash, delay=MUZZLE_FLASH_LIFETIME)
        return flash

    def spawn_tracer(self, start: Vec3, end: Vec3) -> Entity:
        delta = end - start
        distance = max(0.01, delta.length())
        tracer = Entity(
            model="cube",
            scale=(0.02, 0.02, distance),
            position=start + delta * 0.5,
            color=self.archetype.tint,
        )
        tracer.look_at(end)
        destroy(tracer, delay=TRACER_LIFETIME)
        return tracer

    def spawn_impact(self, point: Vec3, normal: Vec3) -> None:
        decal = Entity(model="quad", scale=0.22, position=Vec3(*point) + Vec3(*normal) * 0.01, color=color.rgb32(90, 220, 255))
        decal.look_at(Vec3(*point) + Vec3(*normal))
        destroy(decal, delay=DECAL_LIFETIME)
        for _ in range(4):
            spark = Entity(
                model="cube",
                scale=0.05,
                position=point,
                color=self.archetype.tint,
            )
            spark.animate_position(
                Vec3(*point) + Vec3(random.uniform(-1, 1), random.uniform(0, 1.2), random.uniform(-1, 1)) * 0.6,
                duration=0.25,
            )
            destroy(spark, delay=0.25)
        if self.audio:
            self.audio.play("glitch_hit.wav", position=point, volume=0.4)

    # -- per-frame ---------------------------------------------------------
    def step(self, dt: float, moving: bool = False) -> None:
        self.fired_this_tick = False
        if self.cooldown > 0:
            self.cooldown -= dt
        if self.reload_timer > 0:
            self.reload_timer -= dt
            if self.reload_timer <= 0:
                self._finish_reload()

        # damped spring recoil recovery
        self._recoil_velocity += (-RECOIL_STIFFNESS * self._recoil_offset - RECOIL_DAMPING * self._recoil_velocity) * dt
        self._recoil_offset += self._recoil_velocity * dt

        # viewmodel sway lags behind camera rotation
        sway_target = Vec3(-camera.rotation_y * 0.0008, camera.rotation_x * 0.0008, 0)
        self._sway = Vec3(
            lerp(self._sway.x, sway_target.x, min(1.0, 8 * dt)),
            lerp(self._sway.y, sway_target.y, min(1.0, 8 * dt)),
            0,
        )
        self.position = self.rest_position + self._sway + Vec3(0, 0, -self._recoil_offset * 0.01)
        self.chassis.rotation_x = -self._recoil_offset * 0.5

        alive: list[Projectile] = []
        for projectile in self.projectiles:
            if projectile.step(dt):
                alive.append(projectile)
            else:
                destroy(projectile)
        self.projectiles = alive
