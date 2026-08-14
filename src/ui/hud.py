"""Screen-space HUD, damage vignette and post-run telemetry map (STEP_42, 43, 46)."""
from __future__ import annotations

from ursina import Entity, Text, camera, color, destroy, lerp

from ..procedural.room_generator import world_to_minimap
from ..telemetry.serializer import RunRecord

NEON = color.rgb32(0, 220, 255)
WARN = color.rgb32(255, 60, 90)


class HUD(Entity):
    """Minimalist cyberpunk overlay anchored to camera.ui."""

    def __init__(self, **kwargs):
        super().__init__(parent=camera.ui, **kwargs)

        self.crosshair = Entity(parent=self, model="quad", scale=(0.004, 0.004), color=NEON)
        self.crosshair_h = Entity(parent=self, model="quad", scale=(0.03, 0.0016), color=NEON, alpha=0.6)
        self.crosshair_v = Entity(parent=self, model="quad", scale=(0.0016, 0.03), color=NEON, alpha=0.6)

        self.health_back = Entity(parent=self, model="quad", scale=(0.34, 0.022), position=(-0.52, -0.42), color=color.rgb32(20, 24, 34), origin=(-0.5, 0))
        self.health_bar = Entity(parent=self.health_back, model="quad", scale=(1, 1), origin=(-0.5, 0), position=(-0.5, 0), color=NEON, z=-0.01)
        self.health_text = Text(parent=self, text="100", position=(-0.52, -0.39), scale=0.8, color=NEON, font="VeraMono.ttf")

        self.ammo_text = Text(parent=self, text="30 / 150", position=(0.62, -0.42), scale=1.3, color=NEON, origin=(0.5, 0), font="VeraMono.ttf")
        self.weapon_text = Text(parent=self, text="VX-9 CARBINE", position=(0.62, -0.385), scale=0.7, color=color.rgb32(120, 200, 230), origin=(0.5, 0), font="VeraMono.ttf")
        self.status_text = Text(parent=self, text="", position=(0, 0.06), scale=1.1, color=WARN, origin=(0, 0), font="VeraMono.ttf")
        self.objective_text = Text(parent=self, text="", position=(-0.85, 0.45), scale=0.8, color=NEON, font="VeraMono.ttf")
        self.breach_bar_back = Entity(parent=self, model="quad", scale=(0.3, 0.016), position=(0, -0.2), color=color.rgb32(18, 22, 30), visible=False)
        self.breach_bar = Entity(parent=self.breach_bar_back, model="quad", origin=(-0.5, 0), position=(-0.5, 0), color=color.lime, z=-0.01)

        self.vignette = Entity(parent=self, model="quad", scale=(2.2, 1.2), color=WARN, alpha=0.0, z=1)
        self.aberration = Entity(parent=self, model="quad", scale=(2.2, 1.2), color=color.rgb32(90, 0, 160), alpha=0.0, z=0.9)
        self._damage_flash = 0.0

    def flash_damage(self, amount: float = 1.0) -> None:
        self._damage_flash = min(0.6, self._damage_flash + 0.12 * amount)

    def set_objective(self, text: str) -> None:
        self.objective_text.text = text

    def set_status(self, text: str) -> None:
        self.status_text.text = text

    def show_breach(self, progress: float, total: float = 3.0) -> None:
        visible = progress > 0.01
        self.breach_bar_back.visible = visible
        self.breach_bar.scale_x = max(0.001, progress / total)

    def update_from(self, player, weapon, dt: float) -> None:
        ratio = max(0.0, player.health / player.max_health)
        self.health_bar.scale_x = max(0.001, ratio)
        self.health_bar.color = NEON if ratio > 0.35 else WARN
        self.health_text.text = f"{int(player.health):3d}"

        self.ammo_text.text = f"{weapon.current_mag:02d} / {weapon.reserve:03d}"
        self.weapon_text.text = weapon.archetype.name
        if weapon.is_reloading:
            self.set_status("RELOADING...")
        elif weapon.current_mag == 0:
            self.set_status("MAGAZINE EMPTY  [R]")
        elif self.status_text.text.startswith(("RELOADING", "MAGAZINE")):
            self.set_status("")

        self._damage_flash = lerp(self._damage_flash, 0.0, min(1.0, 3 * dt))
        low_health = max(0.0, 1.0 - ratio / 0.4) if ratio < 0.4 else 0.0
        self.vignette.alpha = self._damage_flash + low_health * 0.18
        self.aberration.alpha = low_health * 0.12
        spread = 0.03 + (0.02 if getattr(player, "is_sprinting", False) else 0.0)
        self.crosshair_h.scale_x = spread
        self.crosshair_v.scale_y = spread


class TelemetryMap(Entity):
    """Post-run bird's-eye plot of player vs. Echo trajectories (STEP_46)."""

    def __init__(self, layout, **kwargs):
        super().__init__(parent=camera.ui, **kwargs)
        self.layout = layout
        self.markers: list[Entity] = []
        self.frame = Entity(parent=self, model="quad", scale=(0.68, 0.68), color=color.rgb32(8, 10, 16), alpha=0.92)
        Entity(parent=self.frame, model="quad", scale=(1.02, 1.02), color=NEON, alpha=0.25, z=0.01)
        self.title = Text(parent=self, text="TELEMETRY PLAYBACK", position=(-0.32, 0.37), scale=1.0, color=NEON, font="VeraMono.ttf")

    def clear(self) -> None:
        for marker in self.markers:
            destroy(marker)
        self.markers.clear()

    def plot(self, frames, tint, stride: int = 3, dot: float = 0.006) -> None:
        for frame in frames[::stride]:
            x, y = world_to_minimap(frame.pos, self.layout, canvas=0.32)
            self.markers.append(Entity(parent=self, model="quad", scale=dot, position=(x, y), color=tint, z=-0.02))

    def render_run(self, player_record: RunRecord, ghost_records: list[RunRecord]) -> None:
        self.clear()
        palette = (color.magenta, color.orange, color.lime)
        for i, ghost in enumerate(ghost_records):
            self.plot(ghost.frames, palette[i % len(palette)], stride=4, dot=0.005)
        self.plot(player_record.frames, NEON, stride=2, dot=0.007)


class ExtractionSummary(Entity):
    """Post-run stat breakdown shown over the telemetry map."""

    def __init__(self, **kwargs):
        super().__init__(parent=camera.ui, **kwargs)
        self.body = Text(parent=self, text="", position=(-0.85, 0.3), scale=0.9, color=NEON, font="VeraMono.ttf")

    def render(self, outcome: str, stats, shards: int, threat: float) -> None:
        acc = stats.accuracy * 100
        self.body.text = "\n".join(
            [
                f"<orange>// {outcome.upper()}</orange>",
                "",
                f"SURVIVED     {stats.elapsed:6.1f}s",
                f"ACCURACY     {acc:6.1f}%",
                f"DAMAGE       {stats.damage_dealt:6.0f}",
                f"ECHOES DOWN  {stats.echoes_destroyed:6d}",
                f"CORES        {stats.rooms_breached:6d}",
                f"SHARDS +{shards}",
                f"NEXT THREAT  {threat:6.0f} HP",
                "",
                "<azure>[ENTER] RETURN TO HUB</azure>",
            ]
        )
