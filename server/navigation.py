"""
Maps and paths for bots.

Every map is in the mapdata/ folder as a JSON file with:
  - walls (lines you can't walk through)
  - where the tasks are (the "consoles" you walk up to)
  - the rooms' center points, vents and where the players start

To find a path we split the map into small cells (0.2 x 0.2 units).
Cells near a wall are "blocked". Then A* (a common way of finding the
shortest path) looks for a path through the free cells, and finally we
straighten the path so that the bot walks in straight lines between the
corners, like a human.

All positions here are the position of the *feet*. The game sends the
position of the middle of the character, which is FEET_OFFSET higher up.
"""

from __future__ import annotations

import heapq
import json
import math
import random
import threading
from array import array
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

DATA_DIR = Path(__file__).parent / "mapdata"

CELL = 0.2  # the size of the cells
CLEARANCE = 0.25  # how close to a wall the feet may come
FEET_OFFSET = 0.3636  # the middle of the character is this high above the feet
OPEN_MAP_RADIUS = 4.5  # on maps with many open areas: stay near known places
MIN_AREA_CELLS = 100  # areas smaller than that (4 m²) are pockets inside furniture

# The map's number in the game settings -> file name
MAP_FILES = {0: "skeld", 1: "mira", 2: "polus", 3: "dleks", 4: "airship", 5: "fungle"}

SQRT2 = math.sqrt(2.0)
NEIGHBOURS = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2),
)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    """The distance from the point p to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


class NavMap:
    """A map that bots can find paths on."""

    def __init__(self, key: str):
        data = json.loads((DATA_DIR / f"{key}.json").read_text("utf-8"))
        self.key = key
        self.name: str = data.get("name", key)
        self.is_open: bool = data.get("open", False)
        self.spawn: Dict = data.get("spawn", {})
        self.rooms: Dict[str, Point] = {k: tuple(v) for k, v in data.get("rooms", {}).items()}
        self.spawn_points: List[Point] = [tuple(p) for p in data.get("spawn_points", [])]
        self.tasks: Dict[int, Dict] = {
            int(task_id): {
                "type": task["type"],
                "length": task["length"],
                "consoles": [tuple(c) for c in task["consoles"]],
            }
            for task_id, task in data.get("tasks", {}).items()
        }
        vents = [tuple(p) for p in data.get("vents", [])]
        doors = [tuple(p) for p in data.get("doors", [])]
        lines = [list(zip(flat[0::2], flat[1::2])) for flat in data.get("colliders", [])]

        # Places where you can surely stand: the middle of the rooms and the start places.
        rooms: List[Point] = list(self.rooms.values()) + self.spawn_points
        for name in ("initial", "meeting", "meeting2"):
            point = self.spawn.get(name)
            if point and tuple(point) != (0, 0) and abs(point[1]) < 35:  # the Airship's start is outside the map
                rooms.append(tuple(point))
        if not rooms:  # the lobby: the middle of the walls
            xs = [p[0] for line in lines for p in line]
            ys = [p[1] for line in lines for p in line]
            rooms.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
        # Places that are near something you can walk on (consoles are often on the wall).
        landmarks: List[Point] = rooms + vents + doors
        for task in self.tasks.values():
            landmarks.extend(task["consoles"])

        self._build_grid(lines, rooms, landmarks)

    # --- The grid ---------------------------------------------------------

    def _build_grid(self, lines: List[List[Point]], rooms: List[Point], landmarks: List[Point]) -> None:
        xs = [p[0] for line in lines for p in line] + [p[0] for p in landmarks]
        ys = [p[1] for line in lines for p in line] + [p[1] for p in landmarks]
        self.min_x = min(xs) - 2.0
        self.min_y = min(ys) - 2.0
        self.w = int((max(xs) + 2.0 - self.min_x) / CELL) + 1
        self.h = int((max(ys) + 2.0 - self.min_y) / CELL) + 1
        w, h = self.w, self.h

        # 1. Block cells whose middle is closer to a wall than CLEARANCE.
        blocked = bytearray(w * h)
        for line in lines:
            for a, b in zip(line, line[1:]):
                x_lo, y_lo = self._cell(min(a[0], b[0]) - CLEARANCE, min(a[1], b[1]) - CLEARANCE)
                x_hi, y_hi = self._cell(max(a[0], b[0]) + CLEARANCE, max(a[1], b[1]) + CLEARANCE)
                for cy in range(max(0, y_lo), min(h, y_hi + 1)):
                    for cx in range(max(0, x_lo), min(w, x_hi + 1)):
                        index = cy * w + cx
                        if not blocked[index] and _segment_distance(self._center(index), a, b) < CLEARANCE:
                            blocked[index] = 1

        # 2. On open maps (outdoors) not all walls are in the data.
        #    There the bot may only walk near known places.
        if self.is_open:
            allowed = bytearray(w * h)
            r = int(OPEN_MAP_RADIUS / CELL)
            near = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if dx * dx + dy * dy <= r * r]
            for sx, sy in landmarks:
                cx, cy = self._cell(sx, sy)
                for dx, dy in near:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        allowed[ny * w + nx] = 1
            for i in range(w * h):
                if not allowed[i]:
                    blocked[i] = 1

        # The edge of the grid is always blocked.
        for x in range(w):
            blocked[x] = blocked[(h - 1) * w + x] = 1
        for y in range(h):
            blocked[y * w] = blocked[y * w + w - 1] = 1

        # 3. Fill from the rooms: everything you can reach from there is walkable.
        #    (Consoles and vents are in walls, that's why we don't fill from them.)
        walk = bytearray(w * h)
        self.comp = array("i", [-1]) * (w * h)
        self.walk = walk
        self._blocked = blocked
        component = 0
        for point in rooms:
            start = self._nearest_free(point, blocked, 1.0)
            if start is None or walk[start]:
                continue
            walk[start] = 1
            self.comp[start] = component
            queue = [start]
            cells = [start]
            touches_edge = False
            while queue:
                current = queue.pop()
                cx, cy = current % w, current // w
                if cx <= 1 or cy <= 1 or cx >= w - 2 or cy >= h - 2:
                    touches_edge = True
                for dx, dy, _ in NEIGHBOURS[:4]:
                    n = (cy + dy) * w + (cx + dx)
                    if not blocked[n] and not walk[n]:
                        walk[n] = 1
                        self.comp[n] = component
                        queue.append(n)
                        cells.append(n)
            if (touches_edge and not self.is_open) or len(cells) < MIN_AREA_CELLS:
                # Leaks out outside the map (it's not the inside), or a little
                # pocket inside a table or a machine: you can't walk there.
                for index in cells:
                    walk[index] = 0
                    self.comp[index] = -1
            component += 1

    def _cell(self, x: float, y: float) -> Tuple[int, int]:
        return int((x - self.min_x) / CELL), int((y - self.min_y) / CELL)

    def _index(self, point: Point) -> Optional[int]:
        cx, cy = self._cell(*point)
        if 0 <= cx < self.w and 0 <= cy < self.h:
            return cy * self.w + cx
        return None

    def _center(self, index: int) -> Point:
        return (
            self.min_x + (index % self.w + 0.5) * CELL,
            self.min_y + (index // self.w + 0.5) * CELL,
        )

    def _nearest_free(self, point: Point, grid: bytearray, max_dist: float, want: int = 0) -> Optional[int]:
        """The nearest cell where grid[cell] == want, at most max_dist away."""
        cx, cy = self._cell(*point)
        best, best_d = None, None
        r = int(max_dist / CELL) + 1
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < self.w and 0 <= ny < self.h):
                    continue
                index = ny * self.w + nx
                if grid[index] != want:
                    continue
                d = distance(point, self._center(index))
                if d <= max_dist and (best_d is None or d < best_d):
                    best, best_d = index, d
        return best

    # --- Questions from bots -------------------------------------------------

    def is_walkable(self, point: Point) -> bool:
        index = self._index(point)
        return index is not None and bool(self.walk[index])

    def nearest_walkable(self, point: Point, max_dist: float = 1.5) -> Optional[Point]:
        """The nearest point you can stand on, or None if there is none nearby."""
        if self.is_walkable(point):
            return point
        index = self._nearest_free(point, self.walk, max_dist, want=1)
        return self._center(index) if index is not None else None

    def reachable(self, a: Point, b: Point) -> bool:
        ia, ib = self._index(a), self._index(b)
        if ia is None or ib is None or not self.walk[ia] or not self.walk[ib]:
            return False
        return self.comp[ia] == self.comp[ib]

    def line_is_clear(self, a: Point, b: Point) -> bool:
        steps = max(1, int(distance(a, b) / (CELL * 0.4)))
        for i in range(steps + 1):
            t = i / steps
            if not self.is_walkable((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)):
                return False
        return True

    def find_path(self, start: Point, goal: Point) -> Optional[List[Point]]:
        """
        A path from start to goal as a list of corners (without start).
        None if there is no path.
        """
        # Is the bot standing a bit off (for example at the meeting table)? First walk to the nearest free cell.
        begin = self.nearest_walkable(start, 3.0)
        goal_point = self.nearest_walkable(goal, 1.5)
        if begin is None or goal_point is None or not self.reachable(begin, goal_point):
            return None
        first = [] if begin == start else [begin]
        if self.line_is_clear(begin, goal_point):
            return first + [goal_point]

        cells = self._astar(self._index(begin), self._index(goal_point))
        if cells is None:
            return None
        points = [begin] + [self._center(c) for c in cells[1:-1]] + [goal_point]
        return first + self._straighten(points)

    def _astar(self, s: int, g: int) -> Optional[List[int]]:
        w, h, walk = self.w, self.h, self.walk
        gx, gy = g % w, g // w
        best: Dict[int, float] = {s: 0.0}
        came: Dict[int, int] = {}
        heap = [(0.0, 0.0, s)]
        while heap:
            _, cost, current = heapq.heappop(heap)
            if current == g:
                path = [g]
                while path[-1] != s:
                    path.append(came[path[-1]])
                path.reverse()
                return path
            if cost > best.get(current, math.inf):
                continue
            cx, cy = current % w, current // w
            for dx, dy, step in NEIGHBOURS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                n = ny * w + nx
                if not walk[n]:
                    continue
                if dx and dy and not (walk[cy * w + nx] and walk[ny * w + cx]):
                    continue  # don't cut through corners
                new_cost = cost + step
                if new_cost < best.get(n, math.inf):
                    best[n] = new_cost
                    came[n] = current
                    hx, hy = abs(nx - gx), abs(ny - gy)
                    estimate = hx + hy + (SQRT2 - 2.0) * min(hx, hy)
                    heapq.heappush(heap, (new_cost + estimate, new_cost, n))
        return None

    def _straighten(self, points: List[Point]) -> List[Point]:
        """Removes unnecessary corners: walk straight as long as no wall is in the way."""
        result: List[Point] = []
        anchor = 0
        i = 1
        while i < len(points):
            if not self.line_is_clear(points[anchor], points[i]):
                result.append(points[i - 1])
                anchor = i - 1
            i += 1
        result.append(points[-1])
        return result

    def random_point_near(self, center: Point, radius: float, tries: int = 30) -> Optional[Point]:
        """A random place within `radius` from center that you can walk to."""
        for _ in range(tries):
            angle = random.uniform(0, 2 * math.pi)
            d = random.uniform(0.3, radius)
            point = (center[0] + math.cos(angle) * d, center[1] + math.sin(angle) * d)
            if self.is_walkable(point) and self.reachable(center, point):
                return point
        return None

    def room_spots(self, near: Point) -> List[Point]:
        """Places in the rooms that you can walk to from here."""
        here = self.nearest_walkable(near, 3.0) or near
        spots = []
        for center in self.rooms.values():
            spot = self.nearest_walkable(center, 2.5)
            if spot is not None and self.reachable(here, spot):
                spots.append(spot)
        return spots

    def console_spot(self, console: Point) -> Optional[Point]:
        """Where the bot should stand to use a console (within one unit)."""
        return self.nearest_walkable(console, 0.95)

    # --- Start places -----------------------------------------------------

    def spawn_position(self, player_id: int, player_count: int, initial: bool) -> Point:
        """Where the game puts the player at the start of the round or in a meeting."""
        count = max(1, player_count)
        if not initial and self.key == "polus":
            # Polus: two rows at the table in the office
            half = count // 2
            slot = player_id % 15
            if slot < half:
                x, y = self.spawn["meeting"]
                return (x + 0.6 * slot, y)
            x, y = self.spawn["meeting2"]
            return (x + 0.6 * (slot - half), y)
        cx, cy = self.spawn["initial" if initial else "meeting"]
        angle = math.radians((player_id - 1) * (360.0 / count))
        radius = float(self.spawn.get("radius", 1.55))
        # Vector2.up rotated: (-sin, cos)
        return (cx - math.sin(angle) * radius, cy + math.cos(angle) * radius)


_cache: Dict[str, NavMap] = {}
_lock = threading.Lock()


def load(key: str) -> Optional[NavMap]:
    """Reads a map (the first time it takes a little while)."""
    with _lock:
        nav = _cache.get(key)
        if nav is None:
            if not (DATA_DIR / f"{key}.json").exists():
                return None
            nav = NavMap(key)
            _cache[key] = nav
        return nav


def for_map(map_id: int) -> Optional[NavMap]:
    key = MAP_FILES.get(map_id)
    return load(key) if key else None


def path_length(start: Point, path: Sequence[Point]) -> float:
    total, previous = 0.0, start
    for point in path:
        total += distance(previous, point)
        previous = point
    return total
