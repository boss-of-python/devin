"""Global FSM, threat scaling and meta-progression (STEP_02, STEP_04, STEP_47)."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from .event_bus import EventBus, Topics, bus as default_bus

BASE_ECHO_HEALTH = 100.0
THREAT_ALPHA = 0.35
THREAT_BETA = 0.5

PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "saves",
    "profile.json",
)


class GameState(Enum):
    BOOT_MENU = "BOOT_MENU"
    HUB = "HUB"
    IN_RUN = "IN_RUN"
    RUN_PAUSED = "RUN_PAUSED"
    RUN_DEATH = "RUN_DEATH"
    EXTRACTION = "EXTRACTION"


TRANSITIONS: dict[GameState, set[GameState]] = {
    GameState.BOOT_MENU: {GameState.HUB},
    GameState.HUB: {GameState.IN_RUN, GameState.BOOT_MENU},
    GameState.IN_RUN: {GameState.RUN_PAUSED, GameState.RUN_DEATH, GameState.EXTRACTION},
    GameState.RUN_PAUSED: {GameState.IN_RUN, GameState.HUB},
    GameState.RUN_DEATH: {GameState.HUB, GameState.BOOT_MENU},
    GameState.EXTRACTION: {GameState.HUB, GameState.BOOT_MENU},
}


def threat_coefficient(run_index: int, accuracy: float, base: float = BASE_ECHO_HEALTH) -> float:
    """Threat(R) = T0 * (1 + a*ln(R+1)) + b*Accuracy.

    `accuracy` is a 0..1 hit ratio; it is scaled to health points so a sharp
    operative faces proportionally tougher copies of themselves.
    """
    r = max(0, int(run_index))
    acc = min(max(float(accuracy), 0.0), 1.0)
    return base * (1.0 + THREAT_ALPHA * math.log(r + 1.0)) + THREAT_BETA * acc * base


@dataclass
class PerkTree:
    """Data-shard economy converting extracted memory into stat boosts (STEP_47)."""

    shards: int = 0
    sprint_rank: int = 0
    magazine_rank: int = 0
    vitality_rank: int = 0

    COSTS = {"sprint": 3, "magazine": 4, "vitality": 5}
    MAX_RANK = 5

    @property
    def sprint_multiplier(self) -> float:
        return 1.0 + 0.06 * self.sprint_rank

    @property
    def magazine_bonus(self) -> int:
        return 4 * self.magazine_rank

    @property
    def health_bonus(self) -> float:
        return 15.0 * self.vitality_rank

    def rank_of(self, perk: str) -> int:
        return int(getattr(self, f"{perk}_rank"))

    def cost_of(self, perk: str) -> int:
        return self.COSTS[perk] * (self.rank_of(perk) + 1)

    def can_purchase(self, perk: str) -> bool:
        return perk in self.COSTS and self.rank_of(perk) < self.MAX_RANK and self.shards >= self.cost_of(perk)

    def purchase(self, perk: str) -> bool:
        if not self.can_purchase(perk):
            return False
        self.shards -= self.cost_of(perk)
        setattr(self, f"{perk}_rank", self.rank_of(perk) + 1)
        return True


@dataclass
class RunStats:
    """Live counters for the incursion currently in progress."""

    elapsed: float = 0.0
    shots_fired: int = 0
    shots_hit: int = 0
    damage_dealt: float = 0.0
    echoes_destroyed: int = 0
    rooms_breached: int = 0
    shards: int = 0

    @property
    def accuracy(self) -> float:
        return self.shots_hit / self.shots_fired if self.shots_fired else 0.0

    def reset(self) -> None:
        for name, f in self.__dataclass_fields__.items():
            setattr(self, name, f.default)


@dataclass
class Profile:
    """Persistent meta-progression saved between sessions."""

    runs_completed: int = 0
    best_duration: float = 0.0
    lifetime_accuracy: float = 0.0
    perks: PerkTree = field(default_factory=PerkTree)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["perks"] = asdict(self.perks)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Profile:
        perks_raw = raw.get("perks", {})
        known = {f for f in PerkTree.__dataclass_fields__}
        perks = PerkTree(**{k: v for k, v in perks_raw.items() if k in known})
        return cls(
            runs_completed=int(raw.get("runs_completed", 0)),
            best_duration=float(raw.get("best_duration", 0.0)),
            lifetime_accuracy=float(raw.get("lifetime_accuracy", 0.0)),
            perks=perks,
        )


class StateManager:
    """Finite state machine owning run lifecycle, stats and progression."""

    def __init__(self, event_bus: EventBus | None = None, profile_path: str = PROFILE_PATH) -> None:
        self.bus = event_bus or default_bus
        self.profile_path = profile_path
        self.state = GameState.BOOT_MENU
        self.stats = RunStats()
        self.profile = self.load_profile()

    # -- FSM ---------------------------------------------------------------
    def can_transition(self, target: GameState) -> bool:
        return target in TRANSITIONS[self.state]

    def transition(self, target: GameState) -> bool:
        if not self.can_transition(target):
            return False
        previous, self.state = self.state, target
        if target is GameState.IN_RUN and previous is GameState.HUB:
            self.stats.reset()
            self.bus.emit(Topics.RUN_STARTED, run_index=self.profile.runs_completed)
        self.bus.emit(Topics.STATE_CHANGED, previous=previous, current=target)
        return True

    @property
    def is_simulating(self) -> bool:
        return self.state is GameState.IN_RUN

    # -- Difficulty --------------------------------------------------------
    def echo_health(self) -> float:
        return threat_coefficient(self.profile.runs_completed, self.profile.lifetime_accuracy)

    def echo_reaction_time(self) -> float:
        """Seconds before a reactive Echo returns fire; shrinks with run count."""
        return max(0.12, 0.55 - 0.04 * self.profile.runs_completed)

    # -- Run lifecycle -----------------------------------------------------
    def complete_run(self, outcome: str) -> None:
        prior = self.profile.runs_completed
        self.profile.runs_completed = prior + 1
        self.profile.best_duration = max(self.profile.best_duration, self.stats.elapsed)
        self.profile.lifetime_accuracy = (
            self.profile.lifetime_accuracy * prior + self.stats.accuracy
        ) / self.profile.runs_completed
        self.profile.perks.shards += self.stats.shards
        self.save_profile()
        self.bus.emit(Topics.RUN_ENDED, outcome=outcome, stats=self.stats)

    # -- Persistence -------------------------------------------------------
    def load_profile(self) -> Profile:
        try:
            with open(self.profile_path, encoding="utf-8") as fh:
                return Profile.from_dict(json.load(fh))
        except (OSError, ValueError):
            return Profile()

    def save_profile(self) -> None:
        os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as fh:
            json.dump(self.profile.to_dict(), fh, indent=2)
