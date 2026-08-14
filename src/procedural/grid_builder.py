"""2D Binary Space Partitioning and mesh primitives (STEP_12, STEP_37).

Pure python/numpy so the layout can be generated and asserted headlessly.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

GRID_SIZE = 50
MIN_ROOM = 7
MAX_DEPTH = 4

EMPTY = 0
FLOOR = 1
WALL = 2
PILLAR = 3


@dataclass(slots=True)
class Rect:
    x: int
    z: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.z + self.h // 2

    @property
    def area(self) -> int:
        return self.w * self.h

    def inset(self, margin: int) -> Rect:
        return Rect(self.x + margin, self.z + margin, max(1, self.w - margin * 2), max(1, self.h - margin * 2))

    def contains(self, x: int, z: int) -> bool:
        return self.x <= x < self.x + self.w and self.z <= z < self.z + self.h


class BSPNode:
    def __init__(self, rect: Rect, depth: int = 0) -> None:
        self.rect = rect
        self.depth = depth
        self.left: BSPNode | None = None
        self.right: BSPNode | None = None
        self.room: Rect | None = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    def leaves(self) -> list[BSPNode]:
        if self.is_leaf:
            return [self]
        return (self.left.leaves() if self.left else []) + (self.right.leaves() if self.right else [])


def split_node(node: BSPNode, rng: random.Random, min_room: int = MIN_ROOM, max_depth: int = MAX_DEPTH) -> bool:
    if node.depth >= max_depth:
        return False
    rect = node.rect
    can_h = rect.h >= min_room * 2 + 1
    can_v = rect.w >= min_room * 2 + 1
    if not can_h and not can_v:
        return False
    horizontal = can_h if not can_v else (rng.random() < 0.5 if can_h else False)

    if horizontal:
        cut = rng.randint(min_room, rect.h - min_room - 1)
        node.left = BSPNode(Rect(rect.x, rect.z, rect.w, cut), node.depth + 1)
        node.right = BSPNode(Rect(rect.x, rect.z + cut, rect.w, rect.h - cut), node.depth + 1)
    else:
        cut = rng.randint(min_room, rect.w - min_room - 1)
        node.left = BSPNode(Rect(rect.x, rect.z, cut, rect.h), node.depth + 1)
        node.right = BSPNode(Rect(rect.x + cut, rect.z, rect.w - cut, rect.h), node.depth + 1)
    split_node(node.left, rng, min_room, max_depth)
    split_node(node.right, rng, min_room, max_depth)
    return True


@dataclass
class Layout:
    """Carved tile matrix plus the rooms and corridors used to build geometry."""

    grid: np.ndarray
    rooms: list[Rect]
    corridors: list[tuple[tuple[int, int], tuple[int, int]]]
    seed: int

    @property
    def size(self) -> int:
        return int(self.grid.shape[0])

    def is_floor(self, x: int, z: int) -> bool:
        return 0 <= x < self.grid.shape[0] and 0 <= z < self.grid.shape[1] and self.grid[x, z] in (FLOOR, PILLAR)

    def floor_cells(self) -> list[tuple[int, int]]:
        xs, zs = np.nonzero((self.grid == FLOOR) | (self.grid == PILLAR))
        return list(zip(xs.tolist(), zs.tolist()))

    def wall_cells(self) -> list[tuple[int, int]]:
        xs, zs = np.nonzero(self.grid == WALL)
        return list(zip(xs.tolist(), zs.tolist()))

    def pillar_cells(self) -> list[tuple[int, int]]:
        xs, zs = np.nonzero(self.grid == PILLAR)
        return list(zip(xs.tolist(), zs.tolist()))


def _carve_room(grid: np.ndarray, room: Rect) -> None:
    grid[room.x : room.x + room.w, room.z : room.z + room.h] = FLOOR


def _carve_corridor(grid: np.ndarray, a: tuple[int, int], b: tuple[int, int], width: int = 2) -> None:
    (ax, az), (bx, bz) = a, b
    half = max(0, width // 2)
    for x in range(min(ax, bx), max(ax, bx) + 1):
        grid[x, max(0, az - half) : az + half + 1] = FLOOR
    for z in range(min(az, bz), max(az, bz) + 1):
        grid[max(0, bx - half) : bx + half + 1, z] = FLOOR


def _add_walls(grid: np.ndarray) -> None:
    floors = grid == FLOOR
    padded = np.zeros((grid.shape[0] + 2, grid.shape[1] + 2), dtype=bool)
    padded[1:-1, 1:-1] = floors
    neighbours = (
        padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
        | padded[:-2, :-2] | padded[2:, 2:] | padded[:-2, 2:] | padded[2:, :-2]
    )
    grid[(~floors) & neighbours] = WALL


def _scatter_pillars(grid: np.ndarray, rooms: list[Rect], rng: random.Random) -> None:
    for room in rooms:
        inner = room.inset(2)
        if inner.w < 3 or inner.h < 3:
            continue
        for _ in range(rng.randint(2, 4)):
            x = rng.randint(inner.x, inner.x + inner.w - 1)
            z = rng.randint(inner.z, inner.z + inner.h - 1)
            if grid[x, z] == FLOOR:
                grid[x, z] = PILLAR


def generate_layout(size: int = GRID_SIZE, seed: int | None = None, min_room: int = MIN_ROOM, max_depth: int = MAX_DEPTH) -> Layout:
    """Recursively partition a size x size grid into rooms joined by corridors."""
    seed = random.randrange(1 << 30) if seed is None else seed
    rng = random.Random(seed)
    grid = np.zeros((size, size), dtype=np.int8)

    root = BSPNode(Rect(1, 1, size - 2, size - 2))
    split_node(root, rng, min_room, max_depth)

    leaves = root.leaves()
    rooms: list[Rect] = []
    for leaf in leaves:
        r = leaf.rect
        w = rng.randint(max(3, int(r.w * 0.55)), max(4, r.w - 2))
        h = rng.randint(max(3, int(r.h * 0.55)), max(4, r.h - 2))
        x = rng.randint(r.x + 1, max(r.x + 1, r.x + r.w - w - 1))
        z = rng.randint(r.z + 1, max(r.z + 1, r.z + r.h - h - 1))
        leaf.room = Rect(x, z, min(w, size - x - 1), min(h, size - z - 1))
        rooms.append(leaf.room)
        _carve_room(grid, leaf.room)

    corridors: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for a, b in zip(rooms, rooms[1:]):
        corridors.append((a.center, b.center))
        _carve_corridor(grid, a.center, b.center)

    _add_walls(grid)
    _scatter_pillars(grid, rooms, rng)
    return Layout(grid=grid, rooms=rooms, corridors=corridors, seed=seed)


def farthest_room_pair(rooms: list[Rect]) -> tuple[Rect, Rect]:
    """Room pair with maximal Euclidean centre distance (scipy when available)."""
    if len(rooms) < 2:
        raise ValueError("need at least two rooms")
    centers = np.array([r.center for r in rooms], dtype=float)
    try:
        from scipy.spatial.distance import cdist

        distances = cdist(centers, centers)
    except ImportError:
        diff = centers[:, None, :] - centers[None, :, :]
        distances = np.sqrt((diff ** 2).sum(-1))
    i, j = np.unravel_index(int(np.argmax(distances)), distances.shape)
    return rooms[int(i)], rooms[int(j)]


def spawn_points(layout: Layout, count: int) -> list[tuple[int, int]]:
    """Spread `count` spawn cells across rooms furthest from the first room."""
    if not layout.rooms:
        return []
    start, _ = farthest_room_pair(layout.rooms) if len(layout.rooms) > 1 else (layout.rooms[0], layout.rooms[0])
    origin = np.array(start.center, dtype=float)
    ranked = sorted(
        layout.rooms,
        key=lambda r: -float(np.linalg.norm(np.array(r.center, dtype=float) - origin)),
    )
    return [ranked[i % len(ranked)].center for i in range(count)]
