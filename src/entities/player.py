"""First-person operative controller (STEP_14 - STEP_20)."""
from __future__ import annotations

import math

from ursina import Entity, Vec2, Vec3, camera, clamp, held_keys, lerp, mouse, raycast

from ..core.event_bus import EventBus, Topics, bus as default_bus

EYE_HEIGHT = 1.8
SLIDE_EYE_HEIGHT = 0.9
BODY_HEIGHT = 1.8
BODY_RADIUS = 0.4
GRAVITY = -18.0
WALK_SPEED = 7.0
SPRINT_MULTIPLIER = 1.6
SLIDE_IMPULSE = 6.0
SLIDE_DURATION = 0.75
JUMP_VELOCITY = 7.2
GROUND_ACCEL = 12.0
AIR_ACCEL = 3.0
FRICTION = 10.0
MOUSE_SENSITIVITY = 40.0
PITCH_LIMIT = 89.0
BOB_FREQUENCY = 9.0
BOB_AMPLITUDE = 0.045
BASE_FOV = 90
SPRINT_FOV = 100


class Player(Entity):
    """Kinematic capsule with mouse-look, sprint, slide, jump and view bob."""

    def __init__(self, event_bus: EventBus | None = None, health: float = 100.0, sprint_multiplier: float = SPRINT_MULTIPLIER, **kwargs):
        super().__init__(
            model=None,
            collider=None,
            position=Vec3(0, 1, 0),
            **kwargs,
        )
        self.bus = event_bus or default_bus
        self.max_health = health
        self.health = health
        self.sprint_multiplier = sprint_multiplier

        self.body = Entity(parent=self, model="cube", scale=(BODY_RADIUS * 2, BODY_HEIGHT, BODY_RADIUS * 2), origin_y=-0.5, visible=False, collider="box")
        self.camera_pivot = Entity(parent=self, y=EYE_HEIGHT)
        camera.parent = self.camera_pivot
        camera.position = Vec3(0, 0, 0)
        camera.rotation = Vec3(0, 0, 0)

        self.velocity = Vec3(0, 0, 0)
        self.is_grounded = False
        self.is_sprinting = False
        self.is_sliding = False
        self.slide_timer = 0.0
        self.jump_requested = False
        self.mouse_enabled = True
        self._bob_phase = 0.0

    # -- input -------------------------------------------------------------
    @property
    def move_input(self) -> Vec2:
        return Vec2(
            held_keys["d"] - held_keys["a"],
            held_keys["w"] - held_keys["s"],
        )

    def handle_mouse_look(self, dt: float) -> None:
        if not self.mouse_enabled:
            return
        self.rotation_y += mouse.velocity[0] * MOUSE_SENSITIVITY
        self.camera_pivot.rotation_x = clamp(
            self.camera_pivot.rotation_x - mouse.velocity[1] * MOUSE_SENSITIVITY,
            -PITCH_LIMIT,
            PITCH_LIMIT,
        )

    # -- kinematics --------------------------------------------------------
    def planar_target_velocity(self) -> Vec3:
        move = self.move_input
        if move.length() > 1:
            move = move.normalized()
        direction = (self.right * move.x + self.forward * move.y)
        if direction.length() > 0:
            direction = direction.normalized()
        speed = WALK_SPEED
        if self.is_sprinting:
            speed *= self.sprint_multiplier
        return direction * speed

    def ground_check(self) -> bool:
        hit = raycast(
            self.world_position + Vec3(0, 0.1, 0),
            Vec3(0, -1, 0),
            distance=0.25,
            ignore=(self, self.body),
        )
        return bool(hit.hit) or self.y <= 0.001

    def jump(self) -> None:
        if not self.is_grounded:
            return
        self.velocity.y = JUMP_VELOCITY
        self.is_grounded = False
        self.jump_requested = True
        self.bus.emit(Topics.PLAYER_JUMPED, position=self.world_position)

    def start_slide(self) -> None:
        if self.is_sliding or not self.is_grounded:
            return
        planar = Vec3(self.velocity.x, 0, self.velocity.z)
        if planar.length() < 1.0:
            return
        self.is_sliding = True
        self.slide_timer = SLIDE_DURATION
        self.velocity += planar.normalized() * SLIDE_IMPULSE
        self.bus.emit(Topics.PLAYER_SLID, position=self.world_position)

    def take_damage(self, amount: float, source: str = "echo") -> None:
        if self.health <= 0:
            return
        self.health = max(0.0, self.health - amount)
        self.bus.emit(Topics.ENTITY_DAMAGED, target=self, amount=amount, source=source)
        if self.health <= 0:
            self.bus.emit(Topics.PLAYER_DIED, position=self.world_position)

    # -- per-frame ---------------------------------------------------------
    def step(self, dt: float) -> None:
        self.handle_mouse_look(dt)

        self.is_grounded = self.ground_check()
        self.is_sprinting = bool(held_keys["shift"]) and self.move_input.length() > 0 and not self.is_sliding

        if held_keys["control"] and self.is_sprinting:
            self.start_slide()

        if self.is_sliding:
            self.slide_timer -= dt
            if self.slide_timer <= 0:
                self.is_sliding = False

        target = self.planar_target_velocity()
        accel = GROUND_ACCEL if self.is_grounded else AIR_ACCEL
        if self.is_sliding:
            accel = FRICTION * 0.25  # keep momentum: slides decay slowly
        self.velocity.x = lerp(self.velocity.x, target.x, min(1.0, accel * dt))
        self.velocity.z = lerp(self.velocity.z, target.z, min(1.0, accel * dt))

        self.velocity.y += GRAVITY * dt
        self.move(self.velocity * dt)

        if self.y < 0:
            self.y = 0
            self.velocity.y = 0
            self.is_grounded = True
        elif self.is_grounded and self.velocity.y < 0:
            self.velocity.y = 0

        self.apply_view_effects(dt)

    def move(self, delta: Vec3) -> None:
        """Axis-separated movement so a wall on one axis does not stop the other."""
        for axis, amount in (("x", delta.x), ("y", delta.y), ("z", delta.z)):
            if amount == 0:
                continue
            direction = Vec3(*(amount if a == axis else 0 for a in ("x", "y", "z"))).normalized()
            distance = abs(amount) + BODY_RADIUS
            origin = self.world_position + Vec3(0, BODY_HEIGHT * 0.5, 0)
            hit = raycast(origin, direction, distance=distance, ignore=(self, self.body))
            if hit.hit and axis != "y":
                setattr(self.velocity, axis, 0)
                continue
            setattr(self, axis, getattr(self, axis) + amount)

    def apply_view_effects(self, dt: float) -> None:
        planar_speed = Vec3(self.velocity.x, 0, self.velocity.z).length()
        target_eye = SLIDE_EYE_HEIGHT if self.is_sliding else EYE_HEIGHT
        self.camera_pivot.y = lerp(self.camera_pivot.y, target_eye, min(1.0, 12 * dt))

        if self.is_grounded and planar_speed > 0.5:
            self._bob_phase += dt * BOB_FREQUENCY * (planar_speed / WALK_SPEED)
        bob = math.sin(self._bob_phase) * BOB_AMPLITUDE * min(1.0, planar_speed / WALK_SPEED)
        camera.y = bob
        camera.x = math.cos(self._bob_phase * 0.5) * BOB_AMPLITUDE * 0.5

        target_fov = SPRINT_FOV if self.is_sprinting else BASE_FOV
        camera.fov = lerp(camera.fov, target_fov, min(1.0, 6 * dt))

    # -- telemetry ---------------------------------------------------------
    @property
    def pitch(self) -> float:
        return float(self.camera_pivot.rotation_x)

    def aim_direction(self) -> Vec3:
        yaw = math.radians(self.rotation_y)
        pitch = math.radians(-self.camera_pivot.rotation_x)
        return Vec3(
            math.sin(yaw) * math.cos(pitch),
            math.sin(pitch),
            math.cos(yaw) * math.cos(pitch),
        ).normalized()

    def consume_jump_flag(self) -> bool:
        flag, self.jump_requested = self.jump_requested, False
        return flag
