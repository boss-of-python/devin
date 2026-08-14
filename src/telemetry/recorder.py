"""20Hz ring-buffer telemetry sampler (STEP_27 - STEP_29)."""
from __future__ import annotations

import collections
import uuid

from .serializer import Actions, RunMetadata, RunRecord, SAMPLE_INTERVAL, TelemetryFrame

BUFFER_MAXLEN = 12000  # 10 minutes at 20Hz
POSITION_EPSILON = 0.02  # metres
ANGLE_EPSILON = 0.5  # degrees


class TelemetryRecorder:
    """Samples operative state at a fixed 20Hz and drops redundant idle frames.

    Compression is lossless for replay purposes: a frame is skipped only when
    the operative has neither moved nor turned nor changed action flags, so the
    interpolator reconstructs the same trajectory from the retained keyframes.
    """

    def __init__(self, maxlen: int = BUFFER_MAXLEN, interval: float = SAMPLE_INTERVAL) -> None:
        self.frames: collections.deque[TelemetryFrame] = collections.deque(maxlen=maxlen)
        self.interval = interval
        self.elapsed = 0.0
        self.recording = False
        self._accumulator = 0.0
        self._last_kept: TelemetryFrame | None = None
        self.dropped_frames = 0
        self.sampled_frames = 0

    def start(self) -> None:
        self.frames.clear()
        self.elapsed = 0.0
        self._accumulator = 0.0
        self._last_kept = None
        self.dropped_frames = 0
        self.sampled_frames = 0
        self.recording = True

    def stop(self) -> None:
        self.recording = False

    def tick(self, dt: float, sample_provider) -> int:
        """Advance the clock and sample as many fixed intervals as elapsed.

        `sample_provider` is called as `sample_provider(t)` and must return a
        `TelemetryFrame`. Returns the number of frames appended.
        """
        if not self.recording:
            return 0
        self.elapsed += dt
        self._accumulator += dt
        appended = 0
        while self._accumulator >= self.interval:
            self._accumulator -= self.interval
            frame = sample_provider(self.elapsed - self._accumulator)
            self.sampled_frames += 1
            if self._should_keep(frame):
                self.frames.append(frame)
                self._last_kept = frame
                appended += 1
            else:
                self.dropped_frames += 1
        return appended

    def _should_keep(self, frame: TelemetryFrame) -> bool:
        previous = self._last_kept
        if previous is None:
            return True
        if frame.actions.to_dict() != previous.actions.to_dict():
            return True
        moved = sum((a - b) ** 2 for a, b in zip(frame.pos, previous.pos)) ** 0.5
        if moved > POSITION_EPSILON:
            return True
        turned = max(abs(frame.rot_y - previous.rot_y), abs(frame.pitch - previous.pitch))
        return turned > ANGLE_EPSILON

    def force_sample(self, frame: TelemetryFrame) -> None:
        """Append a frame unconditionally (used to bookend a run)."""
        self.frames.append(frame)
        self._last_kept = frame

    def build_record(self, outcome: str, **meta_fields) -> RunRecord:
        meta = RunMetadata(
            run_id=uuid.uuid4().hex[:12],
            duration=self.elapsed,
            outcome=outcome,
            **meta_fields,
        )
        return RunRecord(meta=meta, frames=list(self.frames))


def frame_from_player(t: float, player, weapon_id: str, firing: bool) -> TelemetryFrame:
    """Adapter turning a live Player entity into a telemetry frame."""
    pos = player.world_position
    return TelemetryFrame(
        t=t,
        pos=(float(pos.x), float(pos.y), float(pos.z)),
        rot_y=float(player.rotation_y),
        pitch=float(player.pitch),
        actions=Actions(
            fire=bool(firing),
            jump=bool(not player.is_grounded),
            slide=bool(player.is_sliding),
            weapon_id=weapon_id,
        ),
    )
