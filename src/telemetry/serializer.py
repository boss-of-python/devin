"""Telemetry schema definitions and run persistence (STEP_01, STEP_30, STEP_31)."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

SAMPLE_RATE_HZ = 20
SAMPLE_INTERVAL = 1.0 / SAMPLE_RATE_HZ
SCHEMA_VERSION = 1

SAVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "saves",
)


@dataclass(slots=True)
class Actions:
    """Discrete action flags sampled alongside kinematic state."""

    fire: bool = False
    jump: bool = False
    slide: bool = False
    weapon_id: str = "carbine"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fire": bool(self.fire),
            "jump": bool(self.jump),
            "slide": bool(self.slide),
            "weapon_id": self.weapon_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Actions:
        return cls(
            fire=bool(raw.get("fire", False)),
            jump=bool(raw.get("jump", False)),
            slide=bool(raw.get("slide", False)),
            weapon_id=str(raw.get("weapon_id", "carbine")),
        )


@dataclass(slots=True)
class TelemetryFrame:
    """A single 20Hz snapshot of the operative's state."""

    t: float
    pos: tuple[float, float, float]
    rot_y: float
    pitch: float
    actions: Actions = field(default_factory=Actions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 4),
            "pos": [round(v, 4) for v in self.pos],
            "rot_y": round(self.rot_y, 3),
            "pitch": round(self.pitch, 3),
            "actions": self.actions.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TelemetryFrame:
        pos = raw["pos"]
        return cls(
            t=float(raw["t"]),
            pos=(float(pos[0]), float(pos[1]), float(pos[2])),
            rot_y=float(raw["rot_y"]),
            pitch=float(raw["pitch"]),
            actions=Actions.from_dict(raw.get("actions", {})),
        )


@dataclass(slots=True)
class RunMetadata:
    """Summary statistics describing a completed incursion."""

    run_id: str
    duration: float
    outcome: str = "death"
    shots_fired: int = 0
    shots_hit: int = 0
    damage_dealt: float = 0.0
    rooms_breached: int = 0
    loadout: str = "carbine"
    shards: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def accuracy(self) -> float:
        return self.shots_hit / self.shots_fired if self.shots_fired else 0.0


@dataclass(slots=True)
class RunRecord:
    """A serialized run: metadata plus the telemetry track an Echo replays."""

    meta: RunMetadata
    frames: list[TelemetryFrame]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self.meta)
        payload["accuracy"] = round(self.meta.accuracy, 4)
        return {
            "schema_version": SCHEMA_VERSION,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "meta": payload,
            "frames": [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunRecord:
        m = dict(raw.get("meta", {}))
        m.pop("accuracy", None)
        known = {f for f in RunMetadata.__dataclass_fields__}
        meta = RunMetadata(**{k: v for k, v in m.items() if k in known})
        return cls(meta=meta, frames=[TelemetryFrame.from_dict(f) for f in raw.get("frames", [])])


def save_run(record: RunRecord, save_dir: str = SAVE_DIR) -> str:
    """Dump a run to saves/run_echo_{uuid}.json and return the path."""
    os.makedirs(save_dir, exist_ok=True)
    if not record.meta.run_id:
        record.meta.run_id = uuid.uuid4().hex[:12]
    path = os.path.join(save_dir, f"run_echo_{record.meta.run_id}.json")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record.to_dict(), fh, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def load_run(path: str) -> RunRecord:
    with open(path, encoding="utf-8") as fh:
        return RunRecord.from_dict(json.load(fh))


def list_run_files(save_dir: str = SAVE_DIR) -> list[str]:
    if not os.path.isdir(save_dir):
        return []
    return sorted(
        os.path.join(save_dir, n)
        for n in os.listdir(save_dir)
        if n.startswith("run_echo_") and n.endswith(".json")
    )


def load_ghost_runs(count: int = 3, save_dir: str = SAVE_DIR) -> list[RunRecord]:
    """Corrupted ghost selector: the top `count` runs ranked by survival duration."""
    records: list[RunRecord] = []
    for path in list_run_files(save_dir):
        try:
            records.append(load_run(path))
        except (OSError, ValueError, KeyError):
            continue
    records.sort(key=lambda r: r.meta.duration, reverse=True)
    return records[:count]


def prune_runs(keep: int = 25, save_dir: str = SAVE_DIR) -> int:
    """Delete the oldest run files beyond `keep`; returns the number removed."""
    files = list_run_files(save_dir)
    if len(files) <= keep:
        return 0
    files.sort(key=lambda p: os.path.getmtime(p))
    removed = 0
    for path in files[: len(files) - keep]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def frames_to_dicts(frames: Iterable[TelemetryFrame]) -> list[dict[str, Any]]:
    return [f.to_dict() for f in frames]
