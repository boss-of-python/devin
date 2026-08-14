"""Hermite spline playback of recorded telemetry (STEP_33).

Pure math + numpy: no ursina import, so playback is unit-testable headlessly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .serializer import Actions, TelemetryFrame


def hermite(p0: np.ndarray, m0: np.ndarray, p1: np.ndarray, m1: np.ndarray, t: float) -> np.ndarray:
    """P(t) = (2t^3-3t^2+1)P0 + (t^3-2t^2+t)M0 + (-2t^3+3t^2)P1 + (t^3-t^2)M1."""
    t2 = t * t
    t3 = t2 * t
    return (
        (2 * t3 - 3 * t2 + 1) * p0
        + (t3 - 2 * t2 + t) * m0
        + (-2 * t3 + 3 * t2) * p1
        + (t3 - t2) * m1
    )


def shortest_angle_delta(a: float, b: float) -> float:
    """Signed smallest delta from angle a to b in degrees."""
    return (b - a + 180.0) % 360.0 - 180.0


@dataclass(slots=True)
class PlaybackSample:
    t: float
    pos: np.ndarray
    rot_y: float
    pitch: float
    actions: Actions
    finished: bool = False


class TrajectoryReplayer:
    """Interpolates 20Hz keyframes into continuous 60+FPS motion.

    Tangents are Catmull-Rom finite differences, which reduce to smooth
    cubic Hermite segments while passing exactly through every keyframe.
    """

    def __init__(self, frames: list[TelemetryFrame], loop: bool = False, time_scale: float = 1.0) -> None:
        self.frames = [f for f in frames]
        self.loop = loop
        self.time_scale = time_scale
        self.playhead = 0.0
        self._index = 0
        self._positions = np.array([f.pos for f in self.frames], dtype=float) if self.frames else np.zeros((0, 3))
        self._times = np.array([f.t for f in self.frames], dtype=float) if self.frames else np.zeros(0)
        self._tangents = self._compute_tangents()
        self.fired_edges: list[float] = [f.t for f in self.frames if f.actions.fire]

    @property
    def duration(self) -> float:
        return float(self._times[-1]) if len(self._times) else 0.0

    @property
    def is_empty(self) -> bool:
        return len(self.frames) < 2

    def _compute_tangents(self) -> np.ndarray:
        n = len(self._positions)
        if n == 0:
            return np.zeros((0, 3))
        tangents = np.zeros_like(self._positions)
        if n == 1:
            return tangents
        tangents[0] = self._positions[1] - self._positions[0]
        tangents[-1] = self._positions[-1] - self._positions[-2]
        if n > 2:
            tangents[1:-1] = 0.5 * (self._positions[2:] - self._positions[:-2])
        return tangents

    def reset(self) -> None:
        self.playhead = 0.0
        self._index = 0

    def advance(self, dt: float) -> PlaybackSample | None:
        if self.is_empty:
            return None
        self.playhead += dt * self.time_scale
        finished = False
        if self.playhead >= self.duration:
            if self.loop:
                self.playhead = self.playhead % self.duration
                self._index = 0
            else:
                self.playhead = self.duration
                finished = True
        return self.sample_at(self.playhead, finished)

    def sample_at(self, t: float, finished: bool = False) -> PlaybackSample:
        i = int(np.searchsorted(self._times, t, side="right") - 1)
        i = max(0, min(i, len(self.frames) - 2))
        self._index = i
        t0, t1 = self._times[i], self._times[i + 1]
        span = max(1e-6, t1 - t0)
        u = float(min(1.0, max(0.0, (t - t0) / span)))

        pos = hermite(
            self._positions[i],
            self._tangents[i] * span,
            self._positions[i + 1],
            self._tangents[i + 1] * span,
            u,
        )
        f0, f1 = self.frames[i], self.frames[i + 1]
        rot_y = f0.rot_y + shortest_angle_delta(f0.rot_y, f1.rot_y) * u
        pitch = f0.pitch + (f1.pitch - f0.pitch) * u
        return PlaybackSample(t=t, pos=pos, rot_y=rot_y, pitch=pitch, actions=f0.actions, finished=finished)

    def actions_between(self, start: float, end: float) -> list[TelemetryFrame]:
        """Keyframes whose timestamp falls in (start, end] - used to fire weapons."""
        return [f for f in self.frames if start < f.t <= end]

    def path_points(self, stride: int = 1) -> np.ndarray:
        return self._positions[::stride]
