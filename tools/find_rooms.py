"""Generate data/room_bounds.py from data/maps/egmap.png.

Per supertile: the drawn rooms (live = has a door, dead = none), the background colour, and for
split supertiles the picture boxes of each part.

    uv run tools/find_rooms.py
"""

import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from data.doors_data import door_coordinates, doors_data  # noqa: E402

CELL = 8  # grid cell, pixels
N = 512 // CELL
SPECK = 40  # components smaller than this many cells are ignored
INWARD = {"No": (0, 1), "So": (0, -1), "We": (1, 0), "Ea": (-1, 0)}


# Hand-set part areas, overriding the measured ones. {supertile: {any door of the part: boxes}}
HAND_AREAS = {
    # Catwalk: raised corner. Abyss: whole room
    (2, 8): {
        "Hyrule Dungeon South Abyss Catwalk North Edge": [(0, 0, 76, 150)],
        "Hyrule Dungeon South Abyss North Edge": [(0, 0, 448, 472)],
    },
    # Top room is the BK door room; the minibridge crosses over it
    (2, 11): {
        "Mire BK Door Room N": [(16, 32, 496, 240)],
        "Mire Minibridge NE": [(355, 32, 412, 240), (16, 288, 240, 496), (272, 288, 496, 496)],
    },
    # Ledge: side pockets and bottom. Courtyard: middle
    (9, 10): {
        "Eastern Courtyard N": [(16, 32, 496, 250), (130, 250, 382, 330)],
        "Eastern Courtyard Ledge S": [(16, 250, 130, 330), (382, 250, 496, 330), (16, 330, 496, 496)],
    },
    # Alley: fenced middle strip and end platform
    (10, 6): {
        "PoD Dark Alley NE": [(350, 37, 416, 380), (332, 370, 436, 452)],
        "PoD Dark Basement W Up Stairs": [(272, 32, 350, 496), (416, 32, 496, 496), (350, 452, 416, 496)],
    },
    # Valley: low floor (west corner, the five holes, south exit)
    (10, 10): {
        # Upstairs: walkways between the holes, plus the other two rooms
        "Eastern East Wing W": [
            (116, 100, 240, 138),
            (16, 172, 120, 186),
            (16, 186, 240, 200),
            (16, 246, 240, 263),
            (16, 310, 240, 338),
            (16, 172, 74, 338),
            (120, 100, 146, 338),
            (192, 100, 240, 410),
            (272, 32, 496, 240),
            (272, 288, 496, 496),
        ],
        "Eastern Map Valley WN": [
            (44, 84, 116, 170),
            (116, 84, 188, 104),
            (152, 144, 186, 180),
            (80, 206, 114, 240),
            (152, 206, 186, 240),
            (80, 269, 114, 304),
            (152, 269, 186, 304),
            (64, 338, 174, 390),
            (110, 390, 148, 492),
        ],
    },
    # Nook: sunken chest room
    (11, 13): {
        "Thieves Big Chest Nook ES Edge": [(336, 280, 476, 436)],
        "Thieves Lobby S": [(16, 32, 496, 496)],
    },
    # Each door pair with its pipes
    (4, 1): {
        "TR Lava Island WS": [(20, 127, 493, 437)],
        "TR Lava Escape NW": [(100, 34, 413, 493)],
    },
    # Ledges with their chest and walls
    (7, 3): {
        "Swamp Map Ledge EN": [(304, 80, 496, 192)],
        "Swamp Trench 1 Approach ES": [(16, 32, 304, 240), (16, 288, 496, 496)],
    },
    (5, 3): {
        "Swamp Big Key Ledge WN": [(16, 80, 208, 192)],
        "Swamp Crystal Switch EN": [(208, 32, 496, 240), (16, 288, 496, 496)],
    },
    (7, 12): {"TR Torches Ledge WS": [(16, 330, 100, 496)]},
    (10, 1): {"PoD Big Chest Balcony W": [(16, 238, 96, 312)]},
    # Ledge: walkway ring over the room
    (9, 11): {
        "Eastern Cannonball Ledge WN": [(16, 104, 496, 236)],
        "Eastern Cannonball S": [(16, 32, 496, 104), (16, 236, 496, 496)],
    },
    # Landing: middle column down to its railing
    (10, 3): {"PoD Big Key Landing Down Stairs": [(216, 32, 296, 190)]},
    # The fenced square in the petting zoo's room is a warp maze pocket
    (13, 7): {
        "GT Firesnake Room SW": [(80, 64, 496, 240), (16, 288, 240, 496), (400, 310, 456, 358)],
        "GT Petting Zoo SE": [(272, 288, 400, 496), (400, 358, 496, 496), (456, 288, 496, 358), (400, 288, 456, 310)],
    },
}


def find_rooms(picture):
    """(room boxes, background colour). Rooms are connected non-background regions."""
    px = picture.load()
    background = px[1, 1]

    def is_background(cx, cy):
        hits = 0
        for dx in range(0, CELL, 2):
            for dy in range(0, CELL, 2):
                p = px[cx * CELL + dx, cy * CELL + dy]
                if abs(p[0] - background[0]) + abs(p[1] - background[1]) + abs(p[2] - background[2]) < 24:
                    hits += 1
        return hits >= 12  # of the 16 pixels sampled

    solid = [[not is_background(cx, cy) for cx in range(N)] for cy in range(N)]
    seen = [[False] * N for _ in range(N)]
    rooms = []
    for cy in range(N):
        for cx in range(N):
            if not solid[cy][cx] or seen[cy][cx]:
                continue
            cells = []
            queue = deque([(cx, cy)])
            seen[cy][cx] = True
            while queue:
                ax, ay = queue.popleft()
                cells.append((ax, ay))
                for bx, by in ((ax + 1, ay), (ax - 1, ay), (ax, ay + 1), (ax, ay - 1)):
                    if 0 <= bx < N and 0 <= by < N and solid[by][bx] and not seen[by][bx]:
                        seen[by][bx] = True
                        queue.append((bx, by))
            if len(cells) >= SPECK:
                xs = [c[0] for c in cells]
                ys = [c[1] for c in cells]
                rooms.append((min(xs) * CELL, min(ys) * CELL, (max(xs) + 1) * CELL, (max(ys) + 1) * CELL))
    return rooms, background


def distance_to(box, x, y):
    dx = max(box[0] - x, 0, x - box[2])
    dy = max(box[1] - y, 0, y - box[3])
    return (dx * dx + dy * dy) ** 0.5


def floor_patch(px, room, x, y, facing):
    """Box around the floor inside a door, or None.

    Flood fill over the colours sampled just inside the door, tried at several distances from it;
    the smallest plausible result wins.
    """
    left, top, right, bottom = room
    step = INWARD.get(facing, (0, 0))
    room_area = (right - left) * (bottom - top)
    best = None
    for reach in (20, 30, 42, 56):
        sx = int(min(right - 2, max(left + 1, x + step[0] * reach)))
        sy = int(min(bottom - 2, max(top + 1, y + step[1] * reach)))
        palette = set()
        for dx in range(-6, 7):
            for dy in range(-6, 7):
                qx, qy = sx + dx, sy + dy
                if left <= qx < right and top <= qy < bottom:
                    colour = px[qx, qy]
                    if max(colour) >= 28:  # exclude black (pits)
                        palette.add(colour)
        if px[sx, sy] not in palette:
            continue
        seen = {(sx, sy)}
        queue = deque([(sx, sy)])
        x0 = x1 = sx
        y0 = y1 = sy
        while queue:
            ax, ay = queue.popleft()
            x0, x1, y0, y1 = min(x0, ax), max(x1, ax), min(y0, ay), max(y1, ay)
            for bx, by in ((ax + 1, ay), (ax - 1, ay), (ax, ay + 1), (ax, ay - 1)):
                if left <= bx < right and top <= by < bottom and (bx, by) not in seen and px[bx, by] in palette:
                    seen.add((bx, by))
                    queue.append((bx, by))
        width, height = x1 - x0 + 1, y1 - y0 + 1
        if width < 24 or height < 24 or len(seen) < 400:
            continue  # too small to be a floor
        if width * height > room_area * 0.85:
            continue  # fill leaked into the whole room
        if best is None or width * height < best[0]:
            best = (width * height, (x0, y0, x1 + 1, y1 + 1))
    return best[1] if best else None


def share_out(px, live, parts, tile):
    """Picture boxes for each part of a split supertile."""
    entries = {entry["name"]: entry for entry in door_coordinates[tile]}

    def room_of(name):
        x, y = entries[name]["x"], entries[name]["y"]
        return min(range(len(live)), key=lambda i: distance_to(live[i], x, y))

    areas = [[] for _ in parts]
    for index, room in enumerate(live):
        inside = {k: [d for d in names if room_of(d) == index] for k, names in enumerate(parts)}
        inside = {k: doors for k, doors in inside.items() if doors}
        if not inside:
            continue
        if len(inside) == 1:
            areas[next(iter(inside))].append(room)
            continue
        left, top, right, bottom = room
        main = max(inside, key=lambda k: (len(inside[k]), -k))
        across, down = [], []
        for k, doors in inside.items():
            if k == main:
                continue
            boxes = []
            for name in doors:
                x, y = entries[name]["x"], entries[name]["y"]
                patch = floor_patch(px, room, x, y, doors_data[name][1])
                if patch is None:
                    # Fallback: small box around the door
                    patch = (x - 40, y - 40, x + 40, y + 40)
                # Pad to include the surrounding wall and the door
                pad = 12
                box = (
                    max(left, min(patch[0] - pad, x - 14)),
                    max(top, min(patch[1] - pad, y - 14)),
                    min(right, max(patch[2] + pad, x + 14)),
                    min(bottom, max(patch[3] + pad, y + 14)),
                )
                boxes.append(box)
            # Merge overlapping boxes
            merged = []
            for box in boxes:
                for i, other in enumerate(merged):
                    if box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]:
                        merged[i] = (min(box[0], other[0]), min(box[1], other[1]), max(box[2], other[2]), max(box[3], other[3]))
                        break
                else:
                    merged.append(box)
            areas[k].extend(merged)
            for box in merged:
                # A wall-to-wall walkway is cut out of the main part's area
                if box[2] - box[0] >= (right - left) * 0.85:
                    across.append((box[1], box[3]))
                elif box[3] - box[1] >= (bottom - top) * 0.85:
                    down.append((box[0], box[2]))
        rows = [(top, bottom)]
        for start, end in sorted(across):
            rows = [piece for a, b in rows for piece in ((a, min(b, start)), (max(a, end), b)) if piece[1] - piece[0] > 24]
        columns = [(left, right)]
        for start, end in sorted(down):
            columns = [piece for a, b in columns for piece in ((a, min(b, start)), (max(a, end), b)) if piece[1] - piece[0] > 24]
        for y0, y1 in rows:
            for x0, x1 in columns:
                areas[main].append((x0, y0, x1, y1))
    return [[tuple(int(round(v)) for v in box) for box in boxes] for boxes in areas]


def main():
    from gui.Doors.rooms import DOORLESS_ROOMS, supertile

    # Points that mark a room live: door positions, plus the spot of each doorless room
    marks = {tile: [(door["x"], door["y"]) for door in doors] for tile, doors in door_coordinates.items()}
    for room in DOORLESS_ROOMS.values():
        marks.setdefault(room.tile, []).append((room.x * 512, room.y * 512))

    eg_map = Image.open(ROOT / "data" / "maps" / "egmap.png").convert("RGB")
    out = {}
    for tile in sorted(marks):
        x, y = tile
        picture = eg_map.crop((x * 512, y * 512, x * 512 + 512, y * 512 + 512))
        rooms, background = find_rooms(picture)
        live = set()
        for mark_x, mark_y in marks[tile]:
            if not rooms:
                break
            # Nearest room
            nearest = min(range(len(rooms)), key=lambda i: distance_to(rooms[i], mark_x, mark_y))
            live.add(nearest)
        entry = {
            "live": [rooms[i] for i in sorted(live)],
            "dead": [room for i, room in enumerate(rooms) if i not in live],
            "background": background,
        }
        parts = supertile(tile).parts
        if len(parts) > 1 and entry["live"]:
            entry["areas"] = share_out(picture.load(), entry["live"], parts, tile)
            for door, boxes in HAND_AREAS.get(tile, {}).items():
                entry["areas"][next(k for k, names in enumerate(parts) if door in names)] = boxes
        out[tile] = entry

    lines = [
        '"""What is drawn where inside each supertile picture. Generated by tools/find_rooms.py; do not edit.',
        "",
        "Boxes are (left, top, right, bottom) in pixels of the 512x512 supertile picture. A room is live when",
        'it has at least one door, dead when it has none. "background" is the colour between rooms. Supertiles',
        'that are partitioned also have "areas": for each part in turn, the boxes of the picture that are its.',
        '"""',
        "",
        "room_bounds = {",
    ]
    for tile, entry in out.items():
        lines.append(f"    {tile}: {{")
        lines.append(f'        "live": {entry["live"]},')
        lines.append(f'        "dead": {entry["dead"]},')
        lines.append(f'        "background": {tuple(entry["background"])},')
        if "areas" in entry:
            lines.append(f'        "areas": {entry["areas"]},')
        lines.append("    },")
    lines.append("}")
    (ROOT / "data" / "room_bounds.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with_dead = sum(1 for e in out.values() if e["dead"])
    print(f"{len(out)} supertiles written; {with_dead} have at least one dead room, {sum(len(e['dead']) for e in out.values())} dead rooms in all")
    print(f"{sum(1 for e in out.values() if 'areas' in e)} partitioned supertiles have their picture shared out")
    empty = [t for t, e in out.items() if not e["live"]]
    if empty:
        print("no live room found in:", empty)


if __name__ == "__main__":
    main()
