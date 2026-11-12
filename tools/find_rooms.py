"""Work out what is drawn where inside each supertile picture, and write data/room_bounds.py.

A supertile picture is a 512x512 square that can hold several separate rooms.

* Some rooms are blank placeholders the game never uses (the right half of GT Gauntlet 4). The
  picture is split into rooms wherever the background colour shows through; a room is "live" when
  at least one door sits in it and "dead" otherwise.
* Some supertiles hold places that cannot be walked between (see _build_parts in graph_model). When
  two such parts share one drawn room, a bridge over a corridor say, each part's share of the
  picture is measured from the picture: the patch of floor its doors stand on.

Run it again after changing data/maps/egmap.png or the door coordinates:

    uv run tools/find_rooms.py
"""

import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from data.doors_data import door_coordinates, doors_data  # noqa: E402

CELL = 8  # the picture is examined in 8x8 pixel cells
N = 512 // CELL
SPECK = 40  # groups of fewer cells than this are decoration, not rooms
INWARD = {"No": (0, 1), "So": (0, -1), "We": (1, 0), "Ea": (-1, 0)}


# Shares of the picture set by eye, where measuring gets it wrong: two floors on top of each other,
# or a floor that is not one colour. {supertile: {a door of the part: its boxes}}
HAND_AREAS = {
    # The catwalk is the raised corner; the abyss is everything
    (2, 8): {
        "Hyrule Dungeon South Abyss Catwalk North Edge": [(0, 0, 76, 150)],
        "Hyrule Dungeon South Abyss North Edge": [(0, 0, 448, 472)],
    },
    # The top room is the BK door room's floor, with the minibridge crossing over it
    (2, 11): {
        "Mire BK Door Room N": [(16, 32, 496, 240)],
        "Mire Minibridge NE": [(355, 32, 412, 240), (16, 288, 240, 496), (272, 288, 496, 496)],
    },
    # The ledge is the two side pockets and the bottom; the courtyard is the middle
    (9, 10): {
        "Eastern Courtyard N": [(16, 32, 496, 250), (130, 250, 382, 330)],
        "Eastern Courtyard Ledge S": [(16, 250, 130, 330), (382, 250, 496, 330), (16, 330, 496, 496)],
    },
    # The alley is the fenced strip down the middle and the platform at its end
    (10, 6): {
        "PoD Dark Alley NE": [(350, 37, 416, 380), (332, 370, 436, 452)],
        "PoD Dark Basement W Up Stairs": [(272, 32, 350, 496), (416, 32, 496, 496), (350, 452, 416, 496)],
    },
    # The valley is the low floor: the corner at its west door, each fenced hole, and the way out south
    (10, 10): {
        # Upstairs is the walkways between the holes; the other two rooms are all its own
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
    # The nook is the sunken chest room in the corner
    (11, 13): {
        "Thieves Big Chest Nook ES Edge": [(336, 280, 476, 436)],
        "Thieves Lobby S": [(16, 32, 496, 496)],
    },
    # Each set of doors with the pipes that join them
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
    # The walkway ring that crosses over the room
    (9, 11): {
        "Eastern Cannonball Ledge WN": [(16, 104, 496, 236)],
        "Eastern Cannonball S": [(16, 32, 496, 104), (16, 236, 496, 496)],
    },
    # The middle column, down to its railing
    (10, 3): {"PoD Big Key Landing Down Stairs": [(216, 32, 296, 190)]},
}


def find_rooms(picture):
    """Rooms as (x0, y0, x1, y1) boxes in picture pixels, plus the background colour."""
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
    """The box around the floor a door stands on, or None when it cannot be told from the picture.

    Floors are drawn from a handful of repeating tiles, so the colours just inside the door are the
    floor's colours. Spreading out from there over pixels of those colours covers the floor and
    stops at walls, railings, pits and stairs. Several starting distances are tried, since how far
    the door frame reaches into the room varies; the tightest sensible result wins.
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
                    if max(colour) >= 28:  # pits are black; they are never floor
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
            continue  # landed on a door frame or a decoration, not a floor
        if width * height > room_area * 0.85:
            continue  # leaked along the walls and swallowed the room
        if best is None or width * height < best[0]:
            best = (width * height, (x0, y0, x1 + 1, y1 + 1))
    return best[1] if best else None


def share_out(px, live, parts, tile):
    """Each part's share of the picture, as boxes in picture pixels (see the module docstring)."""
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
                    # Nothing readable: a small box around the door is the honest fallback
                    patch = (x - 40, y - 40, x + 40, y + 40)
                # Room for the railing or wall around the floor, and for the door itself
                pad = 12
                box = (
                    max(left, min(patch[0] - pad, x - 14)),
                    max(top, min(patch[1] - pad, y - 14)),
                    min(right, max(patch[2] + pad, x + 14)),
                    min(bottom, max(patch[3] + pad, y + 14)),
                )
                boxes.append(box)
            # Doors standing on the same floor give the same box: keep one, merged
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
                # A walkway from wall to wall divides the room for whoever is underneath it
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
    # PARTS: which doors can be walked between. DOORLESS_ROOMS: rooms with no doors. Neither needs a picture
    from gui.Doors.graph_model import DOORLESS_ROOMS, PARTS

    # What marks a room as used: its doors, or for a room without doors the spot it was given
    marks = {tile: [(door["x"], door["y"]) for door in doors] for tile, doors in door_coordinates.items()}
    for tile, dungeon, place in DOORLESS_ROOMS.values():
        marks.setdefault(tile, []).append((place[0] * 512, place[1] * 512))

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
            # A door belongs to the room it is in, or failing that the nearest one
            nearest = min(range(len(rooms)), key=lambda i: distance_to(rooms[i], mark_x, mark_y))
            live.add(nearest)
        entry = {
            "live": [rooms[i] for i in sorted(live)],
            "dead": [room for i, room in enumerate(rooms) if i not in live],
            "background": background,
        }
        parts = PARTS.get(tile, [])
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
