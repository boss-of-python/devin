"""Monospaced CRT boot terminal, hub and pause overlays (STEP_45)."""
from __future__ import annotations

from ursina import Entity, Text, camera, color, held_keys

from ..core.state_manager import PerkTree

NEON = color.rgb32(0, 220, 255)
DIM = color.rgb32(0, 110, 140)
MONO = "VeraMono.ttf"

BOOT_LINES = [
    "HYPERION QUANTUM NETWORK // NEURAL LOOM v20.88",
    "> integrity check ......... RECURSIVE COLLAPSE",
    "> operative ............... VECTOR",
    "> immune response ......... ECHO PROJECTION ONLINE",
    "",
    "  E C H O - B R E A C H",
    "",
]


class TypingText(Text):
    """Text that reveals itself character by character."""

    def __init__(self, full_text: str, speed: float = 90.0, **kwargs):
        super().__init__(text="", font=MONO, **kwargs)
        self.full_text = full_text
        self.speed = speed
        self._revealed = 0.0

    def step(self, dt: float) -> bool:
        if self._revealed >= len(self.full_text):
            return True
        self._revealed = min(len(self.full_text), self._revealed + self.speed * dt)
        self.text = self.full_text[: int(self._revealed)]
        return self._revealed >= len(self.full_text)

    def skip(self) -> None:
        self._revealed = len(self.full_text)
        self.text = self.full_text


class BootMenu(Entity):
    """Scene 0 - CRT terminal with loadout selection."""

    LOADOUTS = ("carbine", "pistol", "plasma")

    def __init__(self, **kwargs):
        super().__init__(parent=camera.ui, **kwargs)
        self.scanlines = Entity(parent=self, model="quad", scale=(2.2, 1.2), color=color.rgb32(0, 40, 55), alpha=0.12, z=0.5)
        self.banner = TypingText("\n".join(BOOT_LINES), position=(-0.62, 0.4), scale=1.0, color=NEON, parent=self)
        self.menu = Text(parent=self, text="", position=(-0.62, -0.02), scale=1.0, color=NEON, font=MONO)
        self.hint = Text(
            parent=self,
            text="<azure>[1/2/3] LOADOUT   [ENTER] INJECT   [ESC] DISCONNECT</azure>",
            position=(-0.62, -0.4),
            scale=0.8,
            color=DIM,
            font=MONO,
        )
        self.loadout_index = 0
        self.ready = False

    @property
    def loadout(self) -> str:
        return self.LOADOUTS[self.loadout_index]

    def skip(self) -> None:
        self.banner.skip()
        self.ready = True

    def select(self, index: int) -> None:
        self.loadout_index = index % len(self.LOADOUTS)

    def step(self, dt: float, profile=None) -> None:
        self.ready = self.banner.step(dt)
        rows = []
        for i, name in enumerate(self.LOADOUTS):
            marker = ">" if i == self.loadout_index else " "
            rows.append(f"{marker} [{i + 1}] {name.upper()}")
        if profile is not None:
            rows += [
                "",
                f"  RUNS LOGGED   {profile.runs_completed}",
                f"  BEST SURVIVAL {profile.best_duration:.1f}s",
                f"  DATA SHARDS   {profile.perks.shards}",
            ]
        self.menu.text = "\n".join(rows)


class HubMenu(Entity):
    """Scene 1 - Staging Hub: perk tree and telemetry review."""

    PERKS = ("sprint", "magazine", "vitality")

    def __init__(self, **kwargs):
        super().__init__(parent=camera.ui, **kwargs)
        self.panel = Entity(parent=self, model="quad", scale=(1.1, 0.9), color=color.rgb32(6, 9, 14), alpha=0.9)
        self.body = Text(parent=self, text="", position=(-0.5, 0.34), scale=0.95, color=NEON, font=MONO)
        self.hint = Text(
            parent=self,
            text="<azure>[F1/F2/F3] BUY PERK   [ENTER] BREACH SECTOR   [ESC] BOOT MENU</azure>",
            position=(-0.5, -0.38),
            scale=0.75,
            color=DIM,
            font=MONO,
        )
        self.feedback = ""

    def buy(self, perks: PerkTree, index: int) -> bool:
        perk = self.PERKS[index]
        if perks.purchase(perk):
            self.feedback = f"<lime>{perk.upper()} RANK {perks.rank_of(perk)} INSTALLED</lime>"
            return True
        self.feedback = "<red>INSUFFICIENT DATA SHARDS</red>"
        return False

    def render(self, profile, ghost_count: int, threat: float) -> None:
        perks = profile.perks
        self.body.text = "\n".join(
            [
                "// STAGING HUB - MEMORY CACHE",
                "",
                f"  DATA SHARDS        {perks.shards}",
                f"  GHOSTS LOADED      {ghost_count}",
                f"  NEXT ECHO THREAT   {threat:.0f} HP",
                "",
                f"  [F1] SPRINT   RANK {perks.sprint_rank}/5  COST {perks.cost_of('sprint')}   (+{(perks.sprint_multiplier - 1) * 100:.0f}% SPEED)",
                f"  [F2] MAGAZINE RANK {perks.magazine_rank}/5  COST {perks.cost_of('magazine')}   (+{perks.magazine_bonus} ROUNDS)",
                f"  [F3] VITALITY RANK {perks.vitality_rank}/5  COST {perks.cost_of('vitality')}   (+{perks.health_bonus:.0f} HP)",
                "",
                f"  {self.feedback}",
            ]
        )


class PauseOverlay(Entity):
    def __init__(self, **kwargs):
        super().__init__(parent=camera.ui, **kwargs)
        Entity(parent=self, model="quad", scale=(2.2, 1.2), color=color.black, alpha=0.6)
        Text(
            parent=self,
            text="// SIMULATION SUSPENDED\n\n[ESC] RESUME\n[Q] ABORT TO HUB",
            position=(-0.16, 0.08),
            scale=1.2,
            color=NEON,
            font=MONO,
        )


def any_key_pressed(keys: tuple[str, ...]) -> bool:
    return any(held_keys[k] for k in keys)
