"""Headless stress + desync validation for the Echo playback engine (STEP_49)."""
from __future__ import annotations

import math
import os
import sys
import time
import tracemalloc
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.telemetry.recorder import TelemetryRecorder  # noqa: E402
from src.telemetry.replayer import TrajectoryReplayer, hermite, shortest_angle_delta  # noqa: E402
from src.telemetry.serializer import Actions, TelemetryFrame  # noqa: E402

CONCURRENT_ECHOES = 10
SIM_SECONDS = 20.0
FRAME_DT = 1.0 / 60.0
MAX_POSITION_DRIFT = 0.05  # metres between keyframe time and interpolated sample


def synthetic_run(seconds: float = 30.0, radius: float = 8.0) -> list[TelemetryFrame]:
    """A smooth circular patrol sampled at 20Hz with periodic fire flags."""
    frames = []
    steps = int(seconds * 20)
    for i in range(steps):
        t = i * 0.05
        angle = t * 0.9
        frames.append(
            TelemetryFrame(
                t=t,
                pos=(math.cos(angle) * radius, 0.0, math.sin(angle) * radius),
                rot_y=(math.degrees(angle) % 360.0),
                pitch=math.sin(t) * 10.0,
                actions=Actions(fire=(i % 20 == 0), weapon_id="carbine"),
            )
        )
    return frames


class TestReplayerMath(unittest.TestCase):
    def test_hermite_endpoints_are_exact(self):
        import numpy as np

        p0, p1 = np.array([0.0, 0, 0]), np.array([1.0, 2, 3])
        m0, m1 = np.array([1.0, 0, 0]), np.array([0.0, 1, 0])
        self.assertTrue(np.allclose(hermite(p0, m0, p1, m1, 0.0), p0))
        self.assertTrue(np.allclose(hermite(p0, m0, p1, m1, 1.0), p1))

    def test_yaw_interpolation_takes_short_path(self):
        self.assertAlmostEqual(shortest_angle_delta(350.0, 10.0), 20.0)
        self.assertAlmostEqual(shortest_angle_delta(10.0, 350.0), -20.0)

    def test_playback_passes_through_keyframes(self):
        replayer = TrajectoryReplayer(synthetic_run(5.0))
        for frame in replayer.frames[1:-1]:
            sample = replayer.sample_at(frame.t)
            drift = max(abs(a - b) for a, b in zip(sample.pos, frame.pos))
            self.assertLess(drift, 1e-6, f"keyframe drift at t={frame.t}")

    def test_interpolated_path_tracks_ground_truth(self):
        frames = synthetic_run(10.0)
        replayer = TrajectoryReplayer(frames)
        t = 0.0
        worst = 0.0
        while t < replayer.duration:
            sample = replayer.sample_at(t)
            angle = t * 0.9
            truth = (math.cos(angle) * 8.0, 0.0, math.sin(angle) * 8.0)
            worst = max(worst, max(abs(a - b) for a, b in zip(sample.pos, truth)))
            t += FRAME_DT
        self.assertLess(worst, MAX_POSITION_DRIFT, f"spline drift {worst:.4f}m exceeds budget")


class TestRecorderCompression(unittest.TestCase):
    def test_idle_frames_are_dropped_and_motion_is_kept(self):
        recorder = TelemetryRecorder()
        recorder.start()
        idle = TelemetryFrame(t=0.0, pos=(0, 0, 0), rot_y=0.0, pitch=0.0)
        recorder.tick(1.0, lambda t: TelemetryFrame(t=t, pos=idle.pos, rot_y=0.0, pitch=0.0))
        self.assertEqual(len(recorder.frames), 1, "only the first idle frame should be retained")
        self.assertGreaterEqual(recorder.sampled_frames, 19)
        self.assertEqual(recorder.dropped_frames, recorder.sampled_frames - 1)

        idle_samples = recorder.sampled_frames
        recorder.tick(1.0, lambda t: TelemetryFrame(t=t, pos=(t, 0, 0), rot_y=0.0, pitch=0.0))
        moving_samples = recorder.sampled_frames - idle_samples
        self.assertEqual(len(recorder.frames), 1 + moving_samples, "moving frames must all be kept")

    def test_ring_buffer_is_bounded(self):
        recorder = TelemetryRecorder(maxlen=50)
        recorder.start()
        recorder.tick(30.0, lambda t: TelemetryFrame(t=t, pos=(t, 0, 0), rot_y=t, pitch=0.0))
        self.assertEqual(len(recorder.frames), 50)


class TestConcurrentEchoStress(unittest.TestCase):
    """10 concurrent Echoes replayed for 20s of simulated time at 60FPS."""

    def test_ten_echoes_stay_synced_and_bounded(self):
        replayers = [
            TrajectoryReplayer(synthetic_run(30.0, radius=6.0 + i * 0.4), loop=True)
            for i in range(CONCURRENT_ECHOES)
        ]
        tracemalloc.start()
        baseline = tracemalloc.get_traced_memory()[0]
        started = time.perf_counter()

        steps = int(SIM_SECONDS / FRAME_DT)
        for _ in range(steps):
            for replayer in replayers:
                sample = replayer.advance(FRAME_DT)
                self.assertIsNotNone(sample)

        wall = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()

        for replayer in replayers:
            expected = (SIM_SECONDS % replayer.duration)
            self.assertAlmostEqual(replayer.playhead, expected, places=3, msg="playhead desync")

        budget = steps * FRAME_DT
        self.assertLess(wall, budget, f"playback cost {wall:.2f}s of a {budget:.0f}s frame budget")
        self.assertLess(peak - baseline, 8 * 1024 * 1024, "playback allocated more than 8MB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
