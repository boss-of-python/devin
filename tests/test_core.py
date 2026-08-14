"""Unit coverage for the ursina-independent core systems."""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.event_bus import EventBus, Topics  # noqa: E402
from src.core.state_manager import (  # noqa: E402
    GameState,
    PerkTree,
    StateManager,
    threat_coefficient,
)
from src.procedural.grid_builder import (  # noqa: E402
    FLOOR,
    PILLAR,
    WALL,
    farthest_room_pair,
    generate_layout,
    spawn_points,
)
from src.telemetry.serializer import (  # noqa: E402
    Actions,
    RunMetadata,
    RunRecord,
    TelemetryFrame,
    load_ghost_runs,
    load_run,
    prune_runs,
    save_run,
)


class TestEventBus(unittest.TestCase):
    def test_emit_and_unsubscribe(self):
        bus = EventBus()
        received = []
        handler = bus.subscribe(Topics.WEAPON_FIRED, lambda **kw: received.append(kw))
        bus.emit(Topics.WEAPON_FIRED, weapon_id="carbine")
        bus.unsubscribe(Topics.WEAPON_FIRED, handler)
        bus.emit(Topics.WEAPON_FIRED, weapon_id="pistol")
        self.assertEqual(received, [{"weapon_id": "carbine"}])

    def test_posted_events_dispatch_on_flush(self):
        bus = EventBus()
        seen = []
        bus.subscribe("tick", lambda **kw: seen.append(kw["n"]))
        bus.post("tick", n=1)
        bus.post("tick", n=2)
        self.assertEqual(seen, [])
        self.assertEqual(bus.flush(), 2)
        self.assertEqual(seen, [1, 2])


class TestThreatScaling(unittest.TestCase):
    def test_matches_closed_form(self):
        expected = 100.0 * (1 + 0.35 * math.log(6)) + 0.5 * 0.5 * 100.0
        self.assertAlmostEqual(threat_coefficient(5, 0.5), expected)

    def test_monotonic_in_run_count_and_accuracy(self):
        self.assertGreater(threat_coefficient(4, 0.2), threat_coefficient(1, 0.2))
        self.assertGreater(threat_coefficient(1, 0.9), threat_coefficient(1, 0.1))


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = StateManager(profile_path=os.path.join(self.tmp.name, "profile.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_illegal_transitions_are_rejected(self):
        self.assertFalse(self.manager.transition(GameState.IN_RUN))
        self.assertTrue(self.manager.transition(GameState.HUB))
        self.assertTrue(self.manager.transition(GameState.IN_RUN))
        self.assertFalse(self.manager.transition(GameState.BOOT_MENU))

    def test_run_completion_persists_progression(self):
        self.manager.transition(GameState.HUB)
        self.manager.transition(GameState.IN_RUN)
        self.manager.stats.elapsed = 42.0
        self.manager.stats.shots_fired = 10
        self.manager.stats.shots_hit = 5
        self.manager.stats.shards = 7
        self.manager.transition(GameState.RUN_DEATH)
        self.manager.complete_run("death")

        reloaded = StateManager(profile_path=self.manager.profile_path)
        self.assertEqual(reloaded.profile.runs_completed, 1)
        self.assertAlmostEqual(reloaded.profile.best_duration, 42.0)
        self.assertAlmostEqual(reloaded.profile.lifetime_accuracy, 0.5)
        self.assertEqual(reloaded.profile.perks.shards, 7)

    def test_echo_health_grows_with_experience(self):
        base = self.manager.echo_health()
        self.manager.profile.runs_completed = 8
        self.assertGreater(self.manager.echo_health(), base)


class TestPerkTree(unittest.TestCase):
    def test_purchase_consumes_shards_and_caps_rank(self):
        perks = PerkTree(shards=3)
        self.assertTrue(perks.purchase("sprint"))
        self.assertEqual(perks.shards, 0)
        self.assertAlmostEqual(perks.sprint_multiplier, 1.06)
        self.assertFalse(perks.purchase("sprint"))

        perks.shards = 500
        for _ in range(10):
            perks.purchase("magazine")
        self.assertEqual(perks.magazine_rank, PerkTree.MAX_RANK)


class TestSerializer(unittest.TestCase):
    def _record(self, duration: float, run_id: str) -> RunRecord:
        frames = [
            TelemetryFrame(t=i * 0.05, pos=(i * 0.1, 1.0, 0.0), rot_y=i * 2.0, pitch=1.0, actions=Actions(fire=bool(i % 5 == 0)))
            for i in range(20)
        ]
        return RunRecord(meta=RunMetadata(run_id=run_id, duration=duration, shots_fired=4, shots_hit=2), frames=frames)

    def test_roundtrip_preserves_frames_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_run(self._record(30.0, "abc123"), save_dir=tmp)
            loaded = load_run(path)
            self.assertEqual(len(loaded.frames), 20)
            self.assertAlmostEqual(loaded.meta.duration, 30.0)
            self.assertAlmostEqual(loaded.meta.accuracy, 0.5)
            self.assertTrue(loaded.frames[0].actions.fire)

    def test_ghost_selector_ranks_by_survival(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, duration in enumerate([12.0, 55.0, 31.0, 7.0]):
                save_run(self._record(duration, f"run{i}"), save_dir=tmp)
            top = load_ghost_runs(3, save_dir=tmp)
            self.assertEqual([r.meta.duration for r in top], [55.0, 31.0, 12.0])

    def test_prune_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(6):
                save_run(self._record(float(i), f"r{i}"), save_dir=tmp)
            self.assertEqual(prune_runs(keep=4, save_dir=tmp), 2)
            self.assertEqual(len(load_ghost_runs(10, save_dir=tmp)), 4)


class TestProceduralLayout(unittest.TestCase):
    def test_layout_is_deterministic_for_a_seed(self):
        a = generate_layout(seed=1234)
        b = generate_layout(seed=1234)
        self.assertTrue((a.grid == b.grid).all())
        self.assertEqual([r.center for r in a.rooms], [r.center for r in b.rooms])

    def test_rooms_do_not_overlap_and_are_walled(self):
        layout = generate_layout(seed=7)
        self.assertGreaterEqual(len(layout.rooms), 4)
        floors = [c for c in layout.floor_cells()]
        self.assertGreater(len(floors), 200)
        self.assertIn(WALL, layout.grid)
        self.assertIn(FLOOR, layout.grid)
        self.assertIn(PILLAR, layout.grid)
        # every floor cell sits inside the grid interior, never on the border
        for x, z in floors:
            self.assertTrue(0 < x < layout.size - 1 and 0 < z < layout.size - 1)

    def test_spawns_are_spread_apart(self):
        layout = generate_layout(seed=99)
        room_a, room_b = farthest_room_pair(layout.rooms)
        distance = math.dist(room_a.center, room_b.center)
        self.assertGreater(distance, layout.size * 0.4)
        spawns = spawn_points(layout, 3)
        self.assertEqual(len(spawns), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
