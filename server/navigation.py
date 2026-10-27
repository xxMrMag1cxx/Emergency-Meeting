"""
Kartor och vägar för bots.

Varje karta finns i mappen kartdata/ som en JSON-fil med:
  - väggar (linjer som man inte kan gå igenom)
  - var uppdragen finns ("konsolerna" man går fram till)
  - rummens mittpunkter, ventiler och var spelarna börjar

För att hitta en väg delar vi kartan i små rutor (0,25 x 0,25 enheter).
Rutor nära en vägg är "blockerade". Sedan letar A* (ett vanligt sätt att
hitta kortaste vägen) en väg genom de fria rutorna, och till sist rätar vi
ut vägen så att boten går i raka linjer mellan hörnen, som en människa.

Alla positioner här är *fötternas* position. Spelet skickar positionen för
mitten av gubben, som är FEET_OFFSET högre upp.
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

DATA_DIR = Path(__file__).parent / "kartdata"

CELL = 0.2  # rutornas storlek
CLEARANCE = 0.25  # så nära en vägg fötterna får komma
FEET_OFFSET = 0.3636  # gubbens mitt ligger så här högt över fötterna
OPEN_MAP_RADIUS = 4.5  # på kartor med många öppna ytor: håll dig nära kända platser
MIN_AREA_CELLS = 100  # mindre områden än så (4 m²) är fickor inuti möbler

# Kartans nummer i spelinställningarna -> filnamn
MAP_FILES = {0: "skeld", 1: "mira", 2: "polus", 3: "dleks", 4: "airship", 5: "fungle"}

SQRT2 = math.sqrt(2.0)
NEIGHBOURS = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2),
)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    """Avståndet från punkten p till sträckan a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


class NavMap:
    """En karta som bots kan hitta vägar på."""

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

        # Platser där man säkert kan stå: rummens mitt och startplatserna.
        rooms: List[Point] = list(self.rooms.values()) + self.spawn_points
        for name in ("initial", "meeting", "meeting2"):
            point = self.spawn.get(name)
            if point and tuple(point) != (0, 0) and abs(point[1]) < 35:  # Airships start är utanför kartan
                rooms.append(tuple(point))
        if not rooms:  # lobbyn: mitten av väggarna
            xs = [p[0] for line in lines for p in line]
            ys = [p[1] for line in lines for p in line]
            rooms.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
        # Platser som är nära något man kan gå på (konsoler sitter ofta på väggen).
        landmarks: List[Point] = rooms + vents + doors
        for task in self.tasks.values():
            landmarks.extend(task["consoles"])

        self._build_grid(lines, rooms, landmarks)

    # --- Rutnätet ---------------------------------------------------------

    def _build_grid(self, lines: List[List[Point]], rooms: List[Point], landmarks: List[Point]) -> None:
        xs = [p[0] for line in lines for p in line] + [p[0] for p in landmarks]
        ys = [p[1] for line in lines for p in line] + [p[1] for p in landmarks]
        self.min_x = min(xs) - 2.0
        self.min_y = min(ys) - 2.0
        self.w = int((max(xs) + 2.0 - self.min_x) / CELL) + 1
        self.h = int((max(ys) + 2.0 - self.min_y) / CELL) + 1
        w, h = self.w, self.h

        # 1. Blockera rutor vars mitt är närmare en vägg än CLEARANCE.
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

        # 2. På öppna kartor (utomhus) finns inte alla väggar med i datan.
        #    Där får boten bara gå i närheten av kända platser.
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

        # Kanten på rutnätet är alltid blockerad.
        for x in range(w):
            blocked[x] = blocked[(h - 1) * w + x] = 1
        for y in range(h):
            blocked[y * w] = blocked[y * w + w - 1] = 1

        # 3. Fyll från rummen: allt man kan nå därifrån går att gå på.
        #    (Konsoler och ventiler sitter i väggar, därför fyller vi inte från dem.)
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
                # Läcker ut utanför kartan (det är inte insidan), eller en liten
                # ficka inuti ett bord eller en maskin: där kan man inte gå.
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
        """Närmaste ruta där grid[ruta] == want, högst max_dist bort."""
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

    # --- Frågor från bots -------------------------------------------------

    def is_walkable(self, point: Point) -> bool:
        index = self._index(point)
        return index is not None and bool(self.walk[index])

    def nearest_walkable(self, point: Point, max_dist: float = 1.5) -> Optional[Point]:
        """Närmaste punkt man kan stå på, eller None om ingen finns i närheten."""
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
        En väg från start till goal som en lista med hörn (utan start).
        None om det inte finns någon väg.
        """
        # Står boten lite snett (t.ex. vid mötesbordet)? Gå först till närmaste fria ruta.
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
                    continue  # skär inte genom hörn
                new_cost = cost + step
                if new_cost < best.get(n, math.inf):
                    best[n] = new_cost
                    came[n] = current
                    hx, hy = abs(nx - gx), abs(ny - gy)
                    estimate = hx + hy + (SQRT2 - 2.0) * min(hx, hy)
                    heapq.heappush(heap, (new_cost + estimate, new_cost, n))
        return None

    def _straighten(self, points: List[Point]) -> List[Point]:
        """Tar bort onödiga hörn: gå rakt så länge ingen vägg är i vägen."""
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
        """En slumpad plats inom `radius` från center som går att gå till."""
        for _ in range(tries):
            angle = random.uniform(0, 2 * math.pi)
            d = random.uniform(0.3, radius)
            point = (center[0] + math.cos(angle) * d, center[1] + math.sin(angle) * d)
            if self.is_walkable(point) and self.reachable(center, point):
                return point
        return None

    def room_spots(self, near: Point) -> List[Point]:
        """Platser i rummen som man kan gå till härifrån."""
        here = self.nearest_walkable(near, 3.0) or near
        spots = []
        for center in self.rooms.values():
            spot = self.nearest_walkable(center, 2.5)
            if spot is not None and self.reachable(here, spot):
                spots.append(spot)
        return spots

    def console_spot(self, console: Point) -> Optional[Point]:
        """Var boten ska stå för att använda en konsol (inom en enhet)."""
        return self.nearest_walkable(console, 0.95)

    # --- Startplatser -----------------------------------------------------

    def spawn_position(self, player_id: int, player_count: int, initial: bool) -> Point:
        """Där spelet ställer spelaren i början av rundan eller på ett möte."""
        count = max(1, player_count)
        if not initial and self.key == "polus":
            # Polus: två rader vid bordet i kontoret
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
        # Vector2.up roterad: (−sin, cos)
        return (cx - math.sin(angle) * radius, cy + math.cos(angle) * radius)


_cache: Dict[str, NavMap] = {}
_lock = threading.Lock()


def load(key: str) -> Optional[NavMap]:
    """Läser en karta (första gången tar det en liten stund)."""
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
