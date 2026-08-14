"""Decoupled pub/sub messaging between gameplay systems (STEP_07)."""
from __future__ import annotations

import collections
from typing import Any, Callable

Callback = Callable[..., Any]


class EventBus:
    """Minimal synchronous pub/sub with deferred emission support.

    Deferred events are queued and flushed once per frame so subscribers never
    mutate the subscriber table while it is being iterated.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = collections.defaultdict(list)
        self._queue: collections.deque[tuple[str, dict[str, Any]]] = collections.deque()

    def subscribe(self, topic: str, callback: Callback) -> Callback:
        if callback not in self._subscribers[topic]:
            self._subscribers[topic].append(callback)
        return callback

    def unsubscribe(self, topic: str, callback: Callback) -> None:
        if callback in self._subscribers.get(topic, []):
            self._subscribers[topic].remove(callback)

    def emit(self, topic: str, **kwargs: Any) -> None:
        for callback in list(self._subscribers.get(topic, ())):
            callback(**kwargs)

    def post(self, topic: str, **kwargs: Any) -> None:
        """Queue an event for the next flush instead of dispatching inline."""
        self._queue.append((topic, kwargs))

    def flush(self) -> int:
        dispatched = 0
        while self._queue:
            topic, kwargs = self._queue.popleft()
            self.emit(topic, **kwargs)
            dispatched += 1
        return dispatched

    def clear(self) -> None:
        self._subscribers.clear()
        self._queue.clear()


class Topics:
    """Canonical topic names; string literals stay out of gameplay code."""

    WEAPON_FIRED = "weapon.fired"
    WEAPON_RELOADED = "weapon.reloaded"
    ENTITY_DAMAGED = "entity.damaged"
    ECHO_DESTROYED = "echo.destroyed"
    PLAYER_DIED = "player.died"
    PLAYER_JUMPED = "player.jumped"
    PLAYER_SLID = "player.slid"
    TERMINAL_BREACHED = "terminal.breached"
    RUN_STARTED = "run.started"
    RUN_ENDED = "run.ended"
    STATE_CHANGED = "state.changed"


bus = EventBus()
