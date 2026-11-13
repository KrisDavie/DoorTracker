"""The door tracker's map, with no user interface attached.

Rooms (supertiles) live at world positions. Links between doors either snap two rooms together into
a rigid stack or pull on them as springs, and rooms push each other apart. Whatever draws the map
only reads positions from here; nothing in this file knows about windows, zoom or pixels.

The data (tiles / door_links / lobby_doors / special_doors) and the YAML format are the same as the
original grid tracker, so existing tracker files load unchanged.
"""

import math
import random
from collections import defaultdict, deque
from pathlib import Path

from PIL import ImageColor

from data.doors_data import (
    complex_tiles,
    dark_tiles,
    door_coordinates,
    door_coordinates_key,
    doors_data,
    doors_to_regions,
    dungeon_abv_to_name,
    dungeon_lobbies,
    dungeon_warps,
    falldown_pits,
    interior_doors,
    logical_connections,
    mandatory_tiles,
    regions_to_doors,
    simple_tiles,
    vanilla_logical_connections,
)
from data.room_bounds import room_bounds
from data.worlds_data import dungeon_worlds

ITEM_SHEET_PATH = Path(__file__).parent.parent.parent / "data" / "Doors_Sheet.png"

# Geometry, in world units (canvas pixels at zoom 1.0)
THUMB = 128  # supertile thumbnail edge
COMPACT_W = 104  # pass-through tiles collapse to a pill
COMPACT_H = 26
DOOR_RADIUS = 5.5  # an unexplored door; linked and interior doors are drawn smaller
LINK_GAP = 46  # preferred door-to-door distance of a link
MIN_GAP = 14  # blocks are never packed closer than this when searching for an arrangement
CONTACT_RANGE = 44  # inside this distance blocks push back hard, so links cannot press them together
CONTACT_STRENGTH = 0.5
HARD_GAP = 4  # last resort while settling: rooms that actually touch are moved apart outright
REPEL_RANGE = 60  # default reach of the repulsion between blocks; the toolbar slider changes it per tab
REPEL_STRENGTH = 0.12  # share of the missing distance two blocks are pushed apart each step
LINK_PULL_MAX = 10  # a link never pulls harder than one stretched this far, so repulsion can hold it off
STACK_GAP = 4  # space left between the walls of two stacked rooms, where the doorway bar sits
SNAP = THUMB / 8  # stacked rooms line up on this grid along the shared wall

DIRECTIONS = {"No": (0, -1), "So": (0, 1), "We": (-1, 0), "Ea": (1, 0)}
VALID_AUTO_LINKS = [{"So", "No"}, {"Ea", "We"}, {"Up", "Dn"}, {"Up"}, {"Dn"}]

INTERIOR_DOORS = set()
for _pair in interior_doors:
    INTERIOR_DOORS.update(_pair)

# Doors that only exist as a way into the dungeon, drawn as entrances rather than ports
ENTRANCE_ONLY_DOORS = ("Sanctuary Mirror Route", "Sewer Drop")

MANUAL_REGIONS_ADDED = {
    "Eastern Hint Tile WN": "Eastern Hint Tile Blocked Path",
    "Ice Dead End WS": "Ice Big Key",
}

MANUAL_DROPS = {
    "Ice Bomb Drop Hole": "Ice Stalfos Hint Drop Entrance",
    "Ice Crystal Block Hole": "Ice Switch Room Drop Entrance",
    "Ice Falling Square Hole": "Ice Tall Hint Drop Entrance",
    "Ice Freezors Hole": "Ice Big Chest View Drop Entrance",
    "Ice Antechamber Hole": "Ice Boss Drop Entrance",
    "PoD Pit Room Bomb Hole": "PoD Basement Ledge Drop Entrance",
    "PoD Pit Room Freefall": "PoD Stalfos Basement Drop Entrance",
    "Swamp Attic Left Pit": "Swamp West Ledge Drop Entrance",
    "Swamp Attic Right Pit": "Swamp Barrier Ledge Drop Entrance",
    "Skull Final Drop Hole": "Skull Boss Drop Entrance",
    "Mire Torches Bottom Holes": "Mire Warping Pool Drop Entrance",
    "Mire Torches Top Holes": "Mire Conveyor Barrier Drop Entrance",
    "Mire Attic Hint Hole": "Mire BK Chest Ledge Drop Entrance",
    "GT Bob's Room Hole": "GT Ice Armos Drop Entrance",
    "GT Falling Torches Hole": "GT Staredown Drop Entrance",
    "GT Moldorm Hole": "GT Moldorm Pit Drop Entrance",
}

DEFAULT_DOORS = {}
for _door_set in [logical_connections, interior_doors, falldown_pits, dungeon_warps, vanilla_logical_connections]:
    DEFAULT_DOORS.update(_door_set)
DEFAULT_DOORS.update(MANUAL_DROPS)

DUNGEON_COLOURS = {
    "Hyrule_Castle": "#566573",
    "Eastern_Palace": "#2e8b57",
    "Desert_Palace": "#b9892b",
    "Tower_of_Hera": "#b4532a",
    "Castle_Tower": "#8e5bb5",
    "Palace_of_Darkness": "#5b3f96",
    "Swamp_Palace": "#2878b5",
    "Skull_Woods": "#6b8e23",
    "Thieves_Town": "#8b5a2b",
    "Ice_Palace": "#3aa6c9",
    "Misery_Mire": "#8f8f2a",
    "Turtle_Rock": "#c0392b",
    "Ganons_Tower": "#2c2c34",
}
UNKNOWN_DUNGEON_COLOUR = "#666666"

BACKGROUND = "#eef0f3"
DOOR_OPEN = "#1fd655"
DOOR_LINKED = "#9aa0a6"
DOOR_INTERIOR = "#1b2a8a"
DOOR_SELECTED = "#ff9800"
PLAYER = "#e60000"
EDGE_FADED = "#c9cdd4"
WARP_COLOUR = "#7b4fc4"  # warp tiles: fixed, drawn dashed
DROP_COLOUR = "#4a4f57"  # fixed pit drops: drawn like links, but not one of the tracked colours

# Rooms with no doors at all: you fall in and warp out. Everything else about a supertile is worked
# out from its doors, so these are spelled out. region: (supertile, dungeon, where in the picture 0..1)
DOORLESS_ROOMS = {
    "Ice Fairy": ((15, 4), "Ice_Palace", (0.75, 0.25)),
    "Eastern Fairies": ((9, 8), "Eastern_Palace", (0.5, 0.31)),
    "Hera Fairies": ((7, 10), "Tower_of_Hera", (0.27, 0.25)),
}
DOORLESS_TILES = {tile: (region, dungeon) for region, (tile, dungeon, place) in DOORLESS_ROOMS.items()}

# Where a warp tile and its landing are in their supertile pictures (0..1), for the ones that are far
# from any door. warp: (tile, landing)
WARP_SPOTS = {
    # Under one of the moving spikes on the far side of the barrier; lands at the far right of the
    # Firesnake room
    "GT Spike Crystals Warp": ((0.885, 0.26), (0.89, 0.265)),
}


def _build_room_links():
    """Connections the game data only gives room to room: warp tiles, and holes without a marked pit.

    Neither end is a door, so each gets a made-up port in the middle of the part of the supertile
    its region occupies. Links whose rooms cannot be placed on the map are left out.
    """
    home = {}
    for region, doors in regions_to_doors.items():
        for name in doors:
            home.setdefault(name, []).append(region)

    def spot(regions):
        """(tile, x, y) for a region: the average position of its real doors."""
        points, names = {}, {}
        for region in regions:
            if region in DOORLESS_ROOMS:
                tile, dungeon, place = DOORLESS_ROOMS[region]
                return tile, place[0], place[1], None
            for name in regions_to_doors.get(region, []):
                if name in door_coordinates_key:
                    tile, list_pos = door_coordinates_key[name]
                    coords = door_coordinates[tile][list_pos]
                    points.setdefault(tile, []).append((coords["x"] / 512, coords["y"] / 512))
                    names.setdefault(tile, name)
        if len(points) != 1:
            return None
        tile, found = next(iter(points.items()))
        return tile, sum(p[0] for p in found) / len(found), sum(p[1] for p in found) / len(found), names[tile]

    def block(place):
        """The block a spot is in: its supertile and which part of it."""
        return place[0], DOOR_PART.get(place[3], 0)

    # Regions you can walk between inside a room, and where each region's warp tiles lead
    beside, onward = {}, {}
    for name, target in logical_connections:
        for region in home.get(name, []):
            beside.setdefault(region, set()).add(target)
            beside.setdefault(target, set()).add(region)
    for name, target in dungeon_warps:
        for region in home.get(name, []):
            onward.setdefault(region, []).append(target)

    def place_of(region):
        """A spot on the map for a region.

        A corner of a room behind a barrier has no door of its own (the far side of GT Spike
        Crystals, where its warp tile is): it is placed with the part of the room that has one.
        """
        seen, queue = {region}, [region]
        while queue:
            current = queue.pop(0)
            place = spot([current])
            if place is not None:
                return place
            for other in sorted(beside.get(current, ())):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        return None

    def landings(target):
        """Where a warp or hole ends up, as spots on the map.

        Some of GT's warp maze is pockets with no door, only more warp tiles. They have no place on
        the map, so the trip is followed through them to the rooms that do.
        """
        seen, queue, out = {target}, [target], []
        while queue:
            region = queue.pop()
            place = place_of(region)
            if place is not None:
                out.append(place)
                continue
            for further in onward.get(region, []):
                if further not in seen:
                    seen.add(further)
                    queue.append(further)
        return out

    ports, found = {}, {}
    for kind, pairs in (("warp", dungeon_warps), ("hole", falldown_pits)):
        for name, target in pairs:
            if name in MANUAL_DROPS or name in door_coordinates_key:
                continue  # has a real pit and landing point, handled as a door-to-door drop
            start = next((p for p in map(place_of, home.get(name, [])) if p is not None), None)
            if start is None:
                continue
            for end in landings(target):
                if start[0] == end[0]:
                    continue  # within one supertile: that is what makes it one block, not a link
                # Told apart by part, not supertile: GT Compass Room warps to Conveyor Star Pits and GT
                # Hidden Star warps to Invisible Bridges, the same two supertiles but four different rooms
                found.setdefault((block(start), block(end), kind), (name, start, end))
    links = []
    for (ta, tb, kind), (name, start, end) in found.items():
        both_ways = (tb, ta, kind) in found
        if both_ways and (tb, ta) < (ta, tb):
            continue  # a pair of warps that lead to each other is one two-way connection
        a, b = name, f"{name} landing"
        # A warp is drawn from the middle of its room's doors unless it is known where the tile is
        if name in WARP_SPOTS:
            (sx, sy), (ex, ey) = WARP_SPOTS[name]
            start, end = (start[0], sx, sy, start[3]), (end[0], ex, ey, end[3])
        ports[a], ports[b] = start, end
        links.append({"a": a, "b": b, "kind": kind, "both_ways": both_ways})
    return ports, links


ROOM_PORTS, ROOM_LINKS = {}, []


SPLIT_ROOMS = True  # follows the "Split Partitioned Rooms" setting


# Supertiles the region data would split but which are one place when you look at them: the arms of
# Ice Cross are only separated by push blocks, the sewer drop lands in the room it is drawn in, and
# the Ice Freezors ledge can be bomb-jumped to.
ONE_PLACE = {(14, 1), (1, 1), (14, 7)}


def _build_parts():
    """Split each supertile into parts that cannot be walked between without leaving it.

    TR Main Lobby's compass room, or the bridge in Mire that passes over two corridors, are in the
    same supertile as their neighbours but are separate places as far as the map is concerned. Two
    doors are in the same part when their regions are connected by the game's own in-room
    connections, an interior door, or a warp tile inside the supertile; drops do not count.
    """
    home = {}
    for region, names in regions_to_doors.items():
        for name in names:
            home.setdefault(name, []).append(region)

    def region_tile(region):
        tiles = {door_coordinates_key[d][0] for d in regions_to_doors.get(region, []) if d in door_coordinates_key}
        if not tiles:
            return None  # a region with no doors of its own: part of whatever it connects
        return next(iter(tiles)) if len(tiles) == 1 else "several"

    neighbours = {}

    def connect(a, b):
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)

    for exit_name, region in list(logical_connections) + list(vanilla_logical_connections):
        if region in regions_to_doors:
            for start in home.get(exit_name, []):
                connect(start, region)
    for a, b in interior_doors:
        for ra in home.get(a, []):
            for rb in home.get(b, []):
                connect(ra, rb)
    # A warp tile that lands in the same supertile is a way through it: the pockets of GT's warp
    # maze are one block. A warp to another supertile joins nothing here, because a part never
    # reaches into a region that belongs to a different supertile.
    for exit_name, region in dungeon_warps:
        for start in home.get(exit_name, []):
            connect(start, region)

    parts, door_part = {}, {}
    for tile, entries in door_coordinates.items():
        group_of = {}

        def flood(start):
            stack = [start]
            while stack:
                region = stack.pop()
                if region in group_of:
                    continue
                group_of[region] = start
                for other in neighbours.get(region, ()):
                    if other not in group_of and region_tile(other) in (tile, None):
                        stack.append(other)

        groups = {}
        for entry in entries:
            name = entry["name"]
            regions = home.get(name, [])
            if not regions:
                groups.setdefault(("alone", name), []).append(name)
                continue
            for region in regions:
                if region not in group_of:
                    flood(region)
            groups.setdefault(group_of[regions[0]], []).append(name)
        parts[tile] = list(groups.values())
        if tile in ONE_PLACE:
            parts[tile] = [[name for names in parts[tile] for name in names]]
        for k, names in enumerate(parts[tile]):
            for name in names:
                door_part[name] = k
    return parts, door_part


PARTS, DOOR_PART = _build_parts()


def part_areas(tile):
    """For a partitioned supertile, the share of the picture each part gets, as boxes in picture pixels.

    Measured from the picture by tools/find_rooms.py and stored in data/room_bounds.py. Without that
    data a part simply gets the drawn rooms its doors are in.
    """
    entry = room_bounds.get(tile, {})
    parts = PARTS.get(tile, [[]])
    areas = entry.get("areas")
    if areas and len(areas) == len(parts):
        return areas
    live = entry.get("live") or [(0, 0, 512, 512)]
    shares = []
    for names in parts:
        mine = set()
        for name in names:
            spot = door_coordinates[tile][door_coordinates_key[name][1]]
            mine.add(
                min(
                    range(len(live)),
                    key=lambda i: max(live[i][0] - spot["x"], 0, spot["x"] - live[i][2])
                    + max(live[i][1] - spot["y"], 0, spot["y"] - live[i][3]),
                )
            )
        shares.append([live[i] for i in sorted(mine)])
    return shares


def part_count(tile):
    """How many separate blocks a supertile is drawn as."""
    return len(PARTS.get(tile[:2], [0])) if SPLIT_ROOMS else 1


def door_tile(door):
    """The block a door belongs to, as (x, y, part): its supertile on the EG map and which part of it.

    None for regions and unknown names. Supertiles that are not partitioned only have part 0.
    """
    if door in ROOM_PORTS:
        x, y = ROOM_PORTS[door][0]
        return (x, y, DOOR_PART.get(ROOM_PORTS[door][3], 0) if SPLIT_ROOMS else 0)
    if door in door_coordinates_key:
        x, y = door_coordinates_key[door][0]
        return (x, y, DOOR_PART.get(door, 0) if SPLIT_ROOMS else 0)
    if door in doors_data:
        room = int(doors_data[door][0])
        return (room % 16, room // 16, 0)
    return None


def door_direction(door):
    try:
        return doors_data[door][1]
    except (KeyError, IndexError):
        return None


def door_fraction(door):
    """Position of a door inside its supertile as 0..1 fractions."""
    if door in ROOM_PORTS:
        return ROOM_PORTS[door][1], ROOM_PORTS[door][2]
    if door in door_coordinates_key:
        tile, list_pos = door_coordinates_key[door]
        coords = door_coordinates[tile][list_pos]
        return coords["x"] / 512, coords["y"] / 512
    return 0.5, 0.5


def tile_door_names(tile):
    """Doors of a supertile (x, y), or of one part of it (x, y, part)."""
    base = tile[:2]
    # door_coordinates is a defaultdict; [] would insert the key
    names = [d["name"] for d in door_coordinates.get(base) or []]
    parts = PARTS.get(base, [])
    if len(tile) == 3 and SPLIT_ROOMS and len(parts) > 1:
        mine = set(parts[tile[2]]) if tile[2] < len(parts) else set()
        return [name for name in names if name in mine]
    return names


def tile_regions(tile):
    regions = []
    for door in tile_door_names(tile):
        found = doors_to_regions.get(door)
        if found is None:
            continue
        for region in found if isinstance(found, list) else [found]:
            if region not in regions:
                regions.append(region)
    return regions


def tile_dungeon(tile):
    for door in tile_door_names(tile[:2]):
        prefix = door.split(" ")[0]
        if prefix in dungeon_abv_to_name:
            return dungeon_abv_to_name[prefix]
        if prefix == "Sanctuary":
            return "Hyrule_Castle"
    if tile[:2] in DOORLESS_TILES:
        return DOORLESS_TILES[tile[:2]][1]
    return None


def tile_title(tile):
    regions = tile_regions(tile)
    if regions:
        return regions[0]
    if tile[:2] in DOORLESS_TILES:
        return DOORLESS_TILES[tile[:2]][0]
    doors = tile_door_names(tile)
    if doors:
        return " ".join(doors[0].split(" ")[:-1]) or doors[0]
    return f"Tile {tile[0]},{tile[1]}"


ROOM_PORTS, ROOM_LINKS = _build_room_links()


def _dungeon_backgrounds():
    """Each dungeon's own background: the colour between the rooms in its supertile pictures.

    A dungeon can have more than one (Hyrule Castle has the castle and the sewers); the one most of
    its supertiles use wins.
    """
    counts = {}
    for tile, entry in room_bounds.items():
        colour = "#%02x%02x%02x" % tuple(entry["background"])
        tally = counts.setdefault(tile_dungeon(tile), {})
        tally[colour] = tally.get(colour, 0) + 1
    return {dungeon: max(tally, key=tally.get) for dungeon, tally in counts.items() if dungeon}


DUNGEON_BACKGROUNDS = _dungeon_backgrounds()


def enclosing_circle(points):
    """Smallest circle containing every point, as (x, y, radius)."""

    def from_two(a, b):
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, math.dist(a, b) / 2

    def from_three(a, b, c):
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-9:
            return None
        ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1]) + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
        uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0]) + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
        return ux, uy, math.dist((ux, uy), a)

    def holds(circle, point):
        return circle is not None and math.dist(circle[:2], point) <= circle[2] + 1e-6

    # Few points per block, so the simple incremental construction is plenty
    points = list(dict.fromkeys(points))
    circle = None
    for i, p in enumerate(points):
        if holds(circle, p):
            continue
        circle = (p[0], p[1], 0.0)
        for j, q in enumerate(points[:i]):
            if holds(circle, q):
                continue
            circle = from_two(p, q)
            for r in points[:j]:
                if not holds(circle, r):
                    circle = from_three(p, q, r) or circle
    return circle


def lighten(colour, amount):
    r, g, b = ImageColor.getrgb(colour)
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def link_colours(n):
    """n distinct hues, dark enough to read on the light background."""
    colours = []
    for i in range(n):
        # Golden angle stepping keeps neighbouring links far apart in hue
        hue = (i * 137.508) % 360
        r, g, b = ImageColor.getrgb(f"hsl({hue:.0f}, 78%, {38 + (i % 3) * 6}%)")
        colours.append(f"#{r:02x}{g:02x}{b:02x}")
    return colours


def convex_hull(points):
    points = sorted(set(points))
    if len(points) <= 2:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class GraphModel:
    """One dungeon tab's map: what has been tracked, how it is stacked, and where everything sits."""

    def __init__(self, tab_world, experimental_flags):
        self.tab_world = tab_world
        self.dungeon_name = [k for k, v in dungeon_worlds.items() if v == tab_world][0]
        self.experimental_flags = experimental_flags
        self.show_all_doors = False
        self.auto_stack = True
        self.group_by_dungeon = False
        self.spacing = float(REPEL_RANGE)  # blocks closer than this push each other away
        self.leaf_pull = 2.5  # how much harder a block's links pull when they all lead to one other block
        self.circle_repulsion = False  # experiment: a block repels as one circle around all its rooms
        self.reset()

    def reset(self):
        self.tiles = {}
        self.door_links = []
        self.lobby_doors = []
        self.special_doors = {}
        self.pinned_eg_tiles = set()  # kept expanded when single-route rooms are collapsed
        self.sanc_dungeon = False

        self.pos = {}  # tile -> [x, y] centre of the room, world units
        self.fixed = set()  # pinned rooms: neither the layout nor the simulation moves them
        self.unsettled = set()  # freshly added tiles, free to move until they are linked
        self.compact = set()
        self.stack_root = {}
        self.stack_off = {}
        self.stack_members = {}
        self.joined = set()
        self.doors_available = set()
        self.player = None  # (block, x, y): where in its supertile, 0..512
        self.visited = set()  # blocks the player has stood in this session
        self._whole = set()  # split supertiles shown whole; see nodes()
        self.provisional = {}  # supertile -> the part the player seemed to be in when it was added
        self.located = None  # the block the player is known to be in
        self._sighted = None  # the supertile the player was last seen in
        self._layout_signature = None
        self._stack_rank = {}
        self._held = set()  # rooms being dragged right now
        self._damping = {}
        self._last_step = 0.0
        self._seam_doors = set()
        self._linked_doors = set()
        self._piece_cache = {}
        for tile in mandatory_tiles[self.tab_world]:
            self._ensure_tile(tile)
        self.update()

    # ------------------------------------------------------------------ changes

    def update(self):
        """Bring stacks and positions in line with the data after any change to it."""
        self._sync_model()
        self._layout()
        self._refresh_door_sets()

    def relayout(self):
        """Lay everything out again from scratch, around the pinned rooms. Returns True if there was no map before."""
        self._sync_model()
        self._optimise_stack_order()
        before = self._bounds() if self.pos else None
        self._layout(full=True)
        if before is not None:
            self._keep_centre(before)
        self._refresh_door_sets()
        return before is None

    def settle(self, iterations):
        """Run the forces for a few steps from where everything is now."""
        if not self.pos:
            return
        edges = [(a, b) for a, b, kind, n in self._layout_edges()]
        self._relax(iterations=iterations, old_mobility=1.0, edges=edges, cold=True)

    def _refresh_door_sets(self):
        self._seam_doors = set()
        for n in self.joined:
            self._seam_doors.add(self.door_links[n]["door"])
            self._seam_doors.add(self.door_links[n]["linked_door"])
        self._linked_doors = set()
        for link in self.door_links:
            self._linked_doors.add(link["door"])
            self._linked_doors.add(link["linked_door"])
        for a, b, kind, n in self._edges():
            if kind == "drop":
                # Nothing left to explore through a pit whose landing is already on the map
                self._linked_doors.add(a)
                self._linked_doors.add(b)

    def add_link(self, door, linked_door):
        self.door_links.append({"door": door, "linked_door": linked_door})
        self.update()

    def remove_link(self, n):
        del self.door_links[n]
        self.update()

    def toggle_stack(self, a, b, n):
        """Split two rooms stacked on a doorway, or stack the rooms at either end of a link.

        Returns a message when it cannot be done, otherwise None.
        """
        link = self.door_links[n]
        if n in self.joined:
            link["stack"] = False
            self.update()
            return None
        if self._join_offset(a, b) is None:
            return "These two doors cannot be stacked: only north/south and east/west doorways fit together"
        link["stack"] = True
        self._sync_model()
        if n not in self.joined:
            link.pop("stack")
            self._sync_model()
            return "Cannot stack here: the rooms would land on top of rooms already in the stack"
        self.update()
        return None

    def set_pinned(self, tile, pinned):
        """Pin or release a room, together with everything stacked on it."""
        members = self._stack_of(tile)
        if pinned:
            self.fixed.update(members)
        else:
            self.fixed.difference_update(members)

    def nodes(self):
        """Every block on the map: one per supertile, or one per reached part where it is partitioned.

        Knowing a supertile is knowing the part of it you walked into, not the parts you cannot get to
        from there. A part is on the map once something leads to it: a link, an entrance, an icon, the
        player, or a fixed drop or warp from a block that is on the map. Until anything is known about
        a supertile all of it is shown, and "keep expanded" shows all of it too.
        """
        split = [tile for tile in self.tiles if part_count(tile) > 1]
        shown = {(tile[0], tile[1], 0) for tile in self.tiles if part_count(tile) == 1}
        # Supertiles shown whole because nothing says which part is which yet: their parts stay together
        self._whole = set()
        if split:
            used = set(self.special_doors)
            for link in self.door_links:
                used.update((link["door"], link["linked_door"]))
            used.update(entry["door"] for entry in self.lobby_doors)
            for door in used:
                if door in door_coordinates_key and door_coordinates_key[door][0] in self.tiles:
                    shown.add(door_tile(door))
            shown.update(node for node in self.visited if node[:2] in self.tiles)
            shown.update(node for tile, node in self.provisional.items() if tile in self.tiles)
            shown.update(node for node in self.pinned_eg_tiles if node[:2] in self.tiles)
            # Fixed ways from one block to another, each in the direction it can be taken
            fixed = []
            for link in ROOM_LINKS:
                if link["kind"] != "hole" or self.experimental_flags.get("vanilla_drops"):
                    fixed.append((link["a"], link["b"]))
                    if link["both_ways"]:
                        fixed.append((link["b"], link["a"]))
            if self.experimental_flags.get("vanilla_drops"):
                fixed += list(MANUAL_DROPS.items())
            # Warp tiles and unmarked holes are named after their room, not a door: door_tile knows both
            fixed = [(door_tile(a), door_tile(b)) for a, b in fixed]
            fixed = [(a, b) for a, b in fixed if a and b and a[:2] in self.tiles and b[:2] in self.tiles]
            grew = True
            while grew:
                grew = False
                for a, b in fixed:
                    if a in shown and b not in shown:
                        shown.add(b)
                        grew = True
            for tile in split:
                parts = [(tile[0], tile[1], k) for k in range(part_count(tile))]
                if any(node in self.pinned_eg_tiles for node in parts):
                    shown.update(parts)
                elif not any(node in shown for node in parts):
                    # A dark room nobody has seen is one question mark, whatever is inside it
                    shown.update(parts[:1] if self._is_hidden_dark(tile) else parts)
                    self._whole.add(tile)
        return [(tile[0], tile[1], k) for tile in self.tiles for k in range(part_count(tile)) if (tile[0], tile[1], k) in shown]

    def player_node(self, tile, x, y):
        """Which part of a supertile the player is standing in."""
        if part_count(tile) == 1:
            return (tile[0], tile[1], 0)
        # Shares can sit inside one another (a nook inside its lobby): the smallest one around the
        # player is the one they are in. This is a guess; the door they came in by is not, see arrive().
        best = None
        for k, boxes in enumerate(part_areas(tile)):
            for left, top, right, bottom in boxes:
                if left <= x <= right and top <= y <= bottom:
                    area = (right - left) * (bottom - top)
                    if best is None or area < best[0]:
                        best = (area, k)
        return (tile[0], tile[1], best[1] if best else 0)

    def arrive(self, door):
        """The player came in through this door, so which part of the supertile they are in is known."""
        if door not in door_coordinates_key:
            return
        node = door_tile(door)
        self.located = node
        self.visited.add(node)
        self.provisional.pop(node[:2], None)  # the door settles what the position only suggested
        if self.player is not None and self.player[0][:2] == node[:2]:
            self.player = (node, self.player[1], self.player[2])

    def locate(self, tile, x, y):
        """The block the player is in, or None while that is not settled yet.

        Parts of a supertile cannot be walked between, so whatever part the player came into they are
        still in. Where they are standing is only used when no door said so (a fall, or the tracker
        starting mid-dungeon), and not on the first sighting in a supertile: the door they came in by
        is reported just after it.
        """
        if self.located is not None and self.located[:2] == tile:
            return self.located
        self.located = None
        if part_count(tile) > 1 and self._sighted != tile:
            self._sighted = tile
            return None
        self._sighted = tile
        self.located = self.player_node(tile, x, y)
        self.visited.add(self.located)
        self.provisional.pop(tile, None)
        return self.located

    def move_stack(self, tile, dx, dy):
        for member in self._stack_of(tile):
            self.pos[member][0] += dx
            self.pos[member][1] += dy

    def add_tile(self, tile, has_been_lit=False, at=None, player=None):
        """Put a supertile on the map.

        Added by hand it is the whole supertile. Added because the player (x, y) walked into it, it is
        only the part they are standing in, until the door they came through says otherwise.
        """
        tile = tile[:2]
        if tile in self.tiles:
            return False
        self._ensure_tile(tile, has_been_lit=has_been_lit)
        if player is not None and part_count(tile) > 1:
            self.provisional[tile] = self.player_node(tile, *player)
        if at is not None:
            self.pos[(tile[0], tile[1], 0)] = [at[0], at[1]]
        self.update()
        return True

    def remove_tile(self, tile):
        """Remove a whole supertile, every part of it."""
        tile = tile[:2]
        if tile in mandatory_tiles[self.tab_world] or tile not in self.tiles:
            return False
        doors = set(tile_door_names(tile))
        doors.discard("Sanctuary Mirror Route")
        self.door_links = [x for x in self.door_links if x["door"] not in doors and x["linked_door"] not in doors]
        self.lobby_doors = [x for x in self.lobby_doors if x["door"] not in doors]
        for door in doors:
            self.special_doors.pop(door, None)
        del self.tiles[tile]
        for node in [n for n in self.pos if n[:2] == tile]:
            del self.pos[node]
        self.pinned_eg_tiles = {n for n in self.pinned_eg_tiles if n[:2] != tile}
        self.fixed = {n for n in self.fixed if n[:2] != tile}
        self.visited = {n for n in self.visited if n[:2] != tile}
        self.provisional.pop(tile, None)
        if self.located is not None and self.located[:2] == tile:
            self.located = None
        if self.player and self.player[0][:2] == tile:
            self.player = None
        self.update()
        return True

    def annotate(self, door, icon, lobbies):
        """Put an icon on a door. Lobby icons also make the door an entrance."""
        if icon in lobbies or icon == "Drop":
            self.add_lobby_door(door, icon)
            if "Drop" in door:
                self.special_doors[door] = "Drop"
        else:
            self.special_doors[door] = icon
        self.update()

    def remove_annotation(self, door):
        if door == "Sanctuary Mirror Route":
            return
        self.lobby_doors = [x for x in self.lobby_doors if x["door"] != door]
        self.special_doors.pop(door, None)
        self.update()

    # ------------------------------------------------------- auto tracking entry

    def auto_add_door_link(self, door, linked_door):
        for d in [door, linked_door] if not self._decoupled() else [door]:
            if d is None or self.has_target(d) or d in INTERIOR_DOORS or d in self._lobby_door_names():
                return False
        if door is None or linked_door is None:
            return False
        directions = {door_direction(door), door_direction(linked_door)}
        if directions not in VALID_AUTO_LINKS:
            return False
        self.add_link(door, linked_door)
        return True

    def auto_add_lobby(self, door):
        current_lobbies = [x["lobby"] for x in self.lobby_doors]
        if (
            door is None
            or door in self._lobby_door_names()
            or "Boss" in door
            or door in ["Tower Agahnim 1 SW", "GT Agahnim 2 SW"]
            or door in INTERIOR_DOORS
            or door_direction(door) in ["No", "We", "Ea", "Up", "Dn"]
        ):
            return False
        lobby = None
        for possible_lobby in dungeon_lobbies[self.tab_world]:
            if possible_lobby not in current_lobbies:
                lobby = possible_lobby
                break
        if lobby is None:
            return False
        self.add_lobby_door(door, lobby)
        self.update()
        return True

    # ---------------------------------------------------------------- save / load

    def load(self, data):
        """Load one dungeon's section of a tracker file. Returns True when it carried saved positions."""
        self.door_links = []
        for x in data.get("door_links", []):
            link = {"door": x["door"], "linked_door": x["linked_door"]}
            if x.get("stack") is not None:
                link["stack"] = bool(x["stack"])
            self.door_links.append(link)
        self._stack_rank = {}
        for rank, n in enumerate(data.get("stacked_links") or []):
            if 0 <= n < len(self.door_links):
                self._stack_rank[(self.door_links[n]["door"], self.door_links[n]["linked_door"])] = rank
        self.lobby_doors = [{"door": x["door"], "lobby": x["lobby"]} for x in data.get("lobby_doors", [])]
        self.special_doors = dict(data.get("special_doors", {}))
        self.tiles = {}
        self.pos = {}
        self.fixed = set()
        self.unsettled = set()
        self.player = None
        self._layout_signature = None
        self._damping = {}
        for key, lit in data.get("tiles", {}).items():
            tile = tuple(int(x) for x in str(key).split("__"))
            self._ensure_tile(tile, has_been_lit=bool(lit))
        self.visited, self.provisional, self.located, self._sighted = set(), {}, None, None
        for key in data.get("reached_parts") or []:
            node = tuple(int(x) for x in str(key).split("__"))
            if len(node) == 3 and node[:2] in self.tiles and node[2] < part_count(node):
                self.visited.add(node)
        for key, value in (data.get("graph_layout") or {}).items():
            # "x__y" is the supertile (its first part); further parts are saved as "x__y__part"
            numbers = [int(x) for x in str(key).split("__")]
            node = (numbers[0], numbers[1], numbers[2] if len(numbers) > 2 else 0)
            if node[:2] in self.tiles and node[2] < part_count(node):
                self.pos[node] = [float(value[0]), float(value[1])]
                if len(value) > 2 and value[2]:
                    self.fixed.add(node)
        if data.get("satellite_pull"):
            self.leaf_pull = max(1.0, min(4.0, float(data["satellite_pull"])))
        if data.get("spacing"):
            self.spacing = max(10.0, min(200.0, float(data["spacing"])))
        had_positions = bool(self.pos)
        self._sync_model()
        if self.pos and "stacked_links" not in data:
            # A file from before stacked doorways were saved: read them back off the saved positions,
            # so rooms that were sitting together stay one block instead of being regrouped
            rank = 0
            for link in self.door_links:
                a, b = link["door"], link["linked_door"]
                rel = self._join_offset(a, b)
                ta, tb = door_tile(a), door_tile(b)
                if rel is None or ta not in self.pos or tb not in self.pos:
                    continue
                if (
                    abs(self.pos[tb][0] - self.pos[ta][0] - rel[0]) < 2
                    and abs(self.pos[tb][1] - self.pos[ta][1] - rel[1]) < 2
                ):
                    self._stack_rank[(a, b)] = rank
                    rank += 1
            self._build_stacks()
        if self.pos and all(t in self.pos for t in self.nodes()):
            # A saved arrangement is shown as it was left. Stacked rooms are set against each other
            # again, in case the file predates a change to how closely they sit.
            for root, members in self.stack_members.items():
                anchor = next((m for m in members if m in self.fixed), root)
                self._place_stack(anchor, *self.pos[anchor])
            self._layout_signature = self._signature()
        else:
            self._optimise_stack_order()
        self._layout(full=not self.pos)
        self._refresh_door_sets()
        return had_positions

    def save(self):
        door_links = []
        for x in self.door_links:
            link = {"door": x["door"], "linked_door": x["linked_door"]}
            if x.get("stack") is not None:
                # Only present when a doorway was split or stacked by hand
                link["stack"] = x["stack"]
            door_links.append(link)
        return {
            "door_links": door_links,
            # Which doorways are stacked, in the order they claimed their place, so the same blocks
            # come back on load instead of being worked out afresh
            "stacked_links": [n for n in self._stack_order() if n in self.joined],
            "lobby_doors": [{"door": x["door"], "lobby": x["lobby"]} for x in self.lobby_doors],
            "tiles": {f"{t[0]}__{t[1]}": data["has_been_lit"] for t, data in self.tiles.items()},
            # Parts of split supertiles the player has stood in. A link shows its own part; this is
            # for the ones reached by a fall or a warp, which leave nothing else behind.
            "reached_parts": sorted(
                f"{n[0]}__{n[1]}__{n[2]}"
                for n in self.visited | set(self.provisional.values())
                if n[:2] in self.tiles and part_count(n) > 1
            ),
            "special_doors": dict(self.special_doors),
            "graph_layout": {
                (f"{t[0]}__{t[1]}" if t[2] == 0 else f"{t[0]}__{t[1]}__{t[2]}"): [
                    round(p[0], 1),
                    round(p[1], 1),
                    t in self.fixed,
                ]
                for t, p in self.pos.items()
            },
            "spacing": round(self.spacing, 1),
            "satellite_pull": self.leaf_pull,
        }

    # ------------------------------------------------- data, stacks, layout, forces

    def _ensure_tile(self, tile, has_been_lit=False):
        if tile is None:
            return
        tile = tile[:2]
        if tile in self.tiles:
            return
        self.tiles[tile] = {
            "is_dark": tile in dark_tiles,
            "has_been_lit": has_been_lit,
            # Kept for the EG tile picker, which counts tiles with a map position as "in use"
            "map_tile": tile,
        }

    def _decoupled(self):
        return self.experimental_flags["decoupled_doors"]

    def _is_hidden_dark(self, tile):
        data = self.tiles.get(tile[:2])
        return bool(data and data["is_dark"] and not data["has_been_lit"])

    def _link_map(self):
        """door -> linked door, both directions unless doors are decoupled."""
        links = {}
        for link in self.door_links:
            links[link["door"]] = link["linked_door"]
            if not self._decoupled():
                links.setdefault(link["linked_door"], link["door"])
        return links

    def has_target(self, door):
        for link in self.door_links:
            if link["door"] == door:
                return True
            if not self._decoupled() and link["linked_door"] == door:
                return True
        return False

    def _lobby_door_names(self):
        return [x["door"] for x in self.lobby_doors]

    def add_lobby_door(self, door, lobby):
        if door not in self._lobby_door_names():
            self.lobby_doors.append({"door": door, "lobby": lobby})
        self.special_doors[door] = lobby

    def _sync_model(self):
        """Make sure every supertile mentioned by a link, lobby or fixed connection exists."""
        for link in self.door_links:
            self._ensure_tile(door_tile(link["door"]))
            self._ensure_tile(door_tile(link["linked_door"]))
        for lobby in self.lobby_doors:
            self._ensure_tile(door_tile(lobby["door"]))

        # Drop entrances and the sanctuary mirror route are entrances by definition
        lobby_doors = self._lobby_door_names()
        for tile in list(self.tiles):
            for door in tile_door_names(tile):
                if door.startswith("Sanctuary") and not self.sanc_dungeon:
                    self.sanc_dungeon = True
                    if "Sanctuary Mirror Route" in door_coordinates_key:
                        self.add_lobby_door("Sanctuary Mirror Route", "Sanctuary_Mirror")
                if "Drop" in door and door in dungeon_lobbies[self.tab_world] and door not in lobby_doors:
                    self.add_lobby_door(door, door)

        self.doors_available = self._reachable_doors()
        for door in self.doors_available:
            tile = door_tile(door)
            if tile is not None and door in door_coordinates_key:
                self._ensure_tile(tile)

        self._piece_cache = {}
        self.compact = self._compact_tiles()
        self._piece_cache = {}
        self._build_stacks()

    def _reachable_doors(self):
        """Everything reachable from the lobbies through regions, fixed connections and tracked links."""
        adjacency = defaultdict(set)
        for a, b in DEFAULT_DOORS.items():
            adjacency[a].add(b)
            adjacency[b].add(a)
        for link in self.door_links:
            adjacency[link["door"]].add(link["linked_door"])
            if not self._decoupled():
                adjacency[link["linked_door"]].add(link["door"])

        seen = set()
        queue = deque()

        def push(name):
            if name not in seen:
                seen.add(name)
                queue.append(name)

        def drain():
            while queue:
                name = queue.popleft()
                if name in regions_to_doors:
                    for member in regions_to_doors[name]:
                        push(member)
                regions = doors_to_regions.get(name)
                if regions is not None:
                    for region in regions if isinstance(regions, list) else [regions]:
                        push(region)
                if name in MANUAL_REGIONS_ADDED:
                    push(MANUAL_REGIONS_ADDED[name])
                for other in adjacency.get(name, ()):
                    push(other)

        for lobby in self.lobby_doors:
            push(lobby["door"])
        drain()

        # Supertiles the lobbies do not reach yet (added by hand or by the auto tracker) show all their doors
        for tile in list(self.tiles):
            names = tile_door_names(tile)
            if not any(name in seen for name in names):
                for name in names:
                    push(name)
                drain()
        return seen

    def _compact_tiles(self):
        """Pass-through supertiles: every exit is linked and there is only one way through."""
        if not self.experimental_flags["hide_single_route_tiles"]:
            return set()
        links = self._link_map()
        lobbies = set(self._lobby_door_names())
        compact = set()
        for tile in self.tiles:
            if tile not in simple_tiles and tile not in complex_tiles:
                continue
            if any(node[:2] == tile for node in self.pinned_eg_tiles) or self._is_hidden_dark(tile):
                continue
            exits = [d for d in tile_door_names(tile) if d not in INTERIOR_DOORS]
            if any(d in lobbies for d in exits):
                continue
            linked = {d for d in exits if d in links}
            if tile in complex_tiles:
                paths = complex_tiles[tile]["paths"]
                all_paths = set().union(*paths)
                if linked in paths or linked == all_paths:
                    compact.add(tile)
            elif exits and len(linked) == len(exits):
                compact.add(tile)
        return {(tile[0], tile[1], k) for tile in compact for k in range(part_count(tile))}

    def _pieces(self, tile):
        """What is drawn of a block; see _work_out_pieces. Remembered until the map next changes."""
        pieces = self._piece_cache.get(tile)
        if pieces is None:
            pieces = self._piece_cache[tile] = self._work_out_pieces(tile)
        return pieces

    def _work_out_pieces(self, tile):
        """The parts of a supertile that are drawn, each as (left, top, right, bottom) around the tile's centre.

        Positions always refer to the centre of the whole 512x512 supertile, so doors and stacking do
        not care about this. Normally it is one piece, the whole square. With dead rooms hidden there
        is one piece per room that has a door, and whatever lies between them is free for other rooms.
        """
        if tile in self.compact:
            return [(-COMPACT_W / 2, -COMPACT_H / 2, COMPACT_W / 2, COMPACT_H / 2)]
        half = THUMB / 2
        live = room_bounds.get(tile[:2], {}).get("live")
        if not live or not self.experimental_flags.get("hide_dead_rooms") or self._is_hidden_dark(tile):
            return [(-half, -half, half, half)]
        # Rooms found in the picture are found on a coarse grid, so they get a margin to be sure of
        # their outer wall. A share of a room was cut to measure and is drawn as it is.
        found = {tuple(b) for b in live}
        if part_count(tile) > 1:
            # One part of a partitioned supertile: only its own share of the picture
            live = part_areas(tile[:2])[tile[2]] or live
        scale = THUMB / 512
        pieces = []
        for b in live:
            pad = 6 if tuple(b) in found else 0
            pieces.append(
                (
                    max(0, b[0] - pad) * scale - half,
                    max(0, b[1] - pad) * scale - half,
                    min(512, b[2] + pad) * scale - half,
                    min(512, b[3] + pad) * scale - half,
                )
            )
        return pieces

    def _box(self, tile):
        """The box around everything drawn of a supertile."""
        pieces = self._pieces(tile)
        return (
            min(p[0] for p in pieces),
            min(p[1] for p in pieces),
            max(p[2] for p in pieces),
            max(p[3] for p in pieces),
        )

    def _size(self, tile):
        left, top, right, bottom = self._box(tile)
        return right - left, bottom - top

    def _port_offset(self, door):
        """Offset of a door port from the centre of its card, world units."""
        tile = door_tile(door)
        fx, fy = door_fraction(door)
        w, h = self._size(tile)
        if tile in self.compact:
            direction = door_direction(door)
            if direction == "No":
                return (fx - 0.5) * w * 0.8, -h / 2
            if direction == "So":
                return (fx - 0.5) * w * 0.8, h / 2
            if direction == "We":
                return -w / 2, (fy - 0.5) * h * 0.6
            if direction == "Ea":
                return w / 2, (fy - 0.5) * h * 0.6
            return (fx - 0.5) * w * 0.8, (fy - 0.5) * h * 0.6
        if self._is_hidden_dark(tile):
            fx = fy = 0.5
        return (fx - 0.5) * THUMB, (fy - 0.5) * THUMB

    def _stackable(self, tile):
        return tile[:2] in self.tiles and tile not in self.compact and not self._is_hidden_dark(tile)

    def _join_offset(self, a, b):
        """Where the room of door b sits relative to the room of door a when the two doorways meet.

        Only doorways that face each other fit: north onto south, east onto west.
        """
        da, db = DIRECTIONS.get(door_direction(a)), DIRECTIONS.get(door_direction(b))
        if da is None or db is None or (da[0] + db[0], da[1] + db[1]) != (0, 0):
            return None
        ta, tb = door_tile(a), door_tile(b)
        if ta == tb or not self._stackable(ta) or not self._stackable(tb):
            return None
        if a not in door_coordinates_key or b not in door_coordinates_key:
            return None
        fax, fay = door_fraction(a)
        fbx, fby = door_fraction(b)
        # Along the doorway the two rooms meet wall to wall. That is the walls of the rooms the doors
        # are in, not the edges of the supertile squares: a room can sit well inside its square when
        # the rest of it is dead.
        pa, pb = self._piece_at(a), self._piece_at(b)
        gap = STACK_GAP if self.experimental_flags.get("hide_dead_rooms") else 0.0
        if da[0] == 0:
            across = round((fax - fbx) * THUMB / SNAP) * SNAP
            return across, (pa[1] - pb[3] - gap) if da[1] < 0 else (pa[3] - pb[1] + gap)
        across = round((fay - fby) * THUMB / SNAP) * SNAP
        return ((pa[0] - pb[2] - gap) if da[0] < 0 else (pa[2] - pb[0] + gap)), across

    def _piece_at(self, door):
        """The drawn piece of a supertile that a door belongs to."""
        ox, oy = self._port_offset(door)
        return min(
            self._pieces(door_tile(door)),
            key=lambda p: max(p[0] - ox, 0, ox - p[2]) + max(p[1] - oy, 0, oy - p[3]),
        )

    def _stack_order(self, rank=None):
        """Links in the order they get to claim a doorway: stacked by hand first, then by rank, then by age."""
        rank = self._stack_rank if rank is None else rank
        big = len(rank) + len(self.door_links)

        def key(n):
            link = self.door_links[n]
            return (link.get("stack") is not True, rank.get((link["door"], link["linked_door"]), big + n), n)

        return sorted(range(len(self.door_links)), key=key)

    def _compute_stacks(self, order):
        """Snap linked doorways together, taking links in the given order.

        A link is left as a normal edge when its rooms would land on top of rooms already in the stack.
        """
        nodes = self.nodes()
        root = {t: t for t in nodes}
        off = {t: (0.0, 0.0) for t in nodes}
        members = {t: [t] for t in nodes}
        boxes = {t: self._pieces(t) for t in nodes}
        # A supertile nothing is known about is drawn as it is in the game: its parts in one stack, in
        # place. It only comes apart once a link or the player says which part is which.
        for tile in self._whole:
            parts = [t for t in nodes if t[:2] == tile]
            for part in parts[1:]:
                root[part] = parts[0]
                members[parts[0]] += members.pop(part)
        joined = set()
        auto = self.auto_stack
        for n in order:
            link = self.door_links[n]
            wanted = link.get("stack")
            if wanted is False or (wanted is None and not auto):
                continue
            a, b = link["door"], link["linked_door"]
            rel = self._join_offset(a, b)
            if rel is None:
                continue
            ta, tb = door_tile(a), door_tile(b)
            ra, rb = root[ta], root[tb]
            # Shift that takes everything in b's stack into a's frame
            sx = off[ta][0] + rel[0] - off[tb][0]
            sy = off[ta][1] + rel[1] - off[tb][1]
            if ra == rb:
                if abs(sx) < 1 and abs(sy) < 1:
                    joined.add(n)
                continue
            clash = False
            for m in members[rb]:
                mx, my = off[m][0] + sx, off[m][1] + sy
                for k in members[ra]:
                    kx, ky = off[k]
                    clash = any(
                        mx + ml < kx + kr - 1 and kx + kl < mx + mr - 1 and my + mt < ky + kb - 1 and ky + kt < my + mb - 1
                        for ml, mt, mr, mb in boxes[m]
                        for kl, kt, kr, kb in boxes[k]
                    )
                    if clash:
                        break
                if clash:
                    break
            if clash:
                continue
            if len(members[rb]) > len(members[ra]):
                # Keep the bigger stack's frame so it is the small one that moves
                ra, rb, sx, sy = rb, ra, -sx, -sy
            for m in members[rb]:
                off[m] = (off[m][0] + sx, off[m][1] + sy)
                root[m] = ra
            members[ra] += members.pop(rb)
            joined.add(n)
        return root, off, members, joined

    def _build_stacks(self):
        self.stack_root, self.stack_off, self.stack_members, self.joined = self._compute_stacks(self._stack_order())

    def _optimise_stack_order(self):
        """Look for the order of claiming doorways that stacks the most links.

        Only done on a full re-layout: while tracking, stacks must not reshuffle under the player.
        """
        keys = [(x["door"], x["linked_door"]) for x in self.door_links]
        candidates = [n for n, x in enumerate(self.door_links) if self._join_offset(*keys[n]) is not None]
        if len(candidates) < 3:
            return
        rng = random.Random(len(self.door_links))
        best_rank = {keys[n]: i for i, n in enumerate(self._stack_order())}
        best_score = len(self._compute_stacks(self._stack_order(best_rank))[3])
        for _ in range(60):
            shuffled = candidates[:]
            rng.shuffle(shuffled)
            rank = {keys[n]: i for i, n in enumerate(shuffled)}
            score = len(self._compute_stacks(self._stack_order(rank))[3])
            if score > best_score:
                best_score, best_rank = score, rank
        self._stack_rank = best_rank
        self._build_stacks()

    def _stack_of(self, tile):
        return self.stack_members.get(self.stack_root.get(tile, tile), [tile])

    def _place_stack(self, anchor, x, y):
        """Position a whole stack so that the given member's centre lands on (x, y)."""
        ax, ay = self.stack_off[anchor]
        for m in self._stack_of(anchor):
            mx, my = self.stack_off[m]
            self.pos[m] = [x + mx - ax, y + my - ay]

    def _port(self, door):
        tile = door_tile(door)
        ox, oy = self._port_offset(door)
        x, y = self.pos[tile]
        return x + ox, y + oy

    def _edges(self, known=None):
        """All drawable edges as (door, linked_door, kind, link_index)."""
        known = self.pos if known is None else known
        edges = []
        seen = set()
        for n, link in enumerate(self.door_links):
            a, b = link["door"], link["linked_door"]
            if door_tile(a) not in known or door_tile(b) not in known:
                continue
            if a not in door_coordinates_key or b not in door_coordinates_key:
                continue
            kind = "interior" if a in INTERIOR_DOORS else "link"
            edges.append((a, b, kind, n))
            seen.add(frozenset((a, b)))
        # Fixed interior connections between two supertiles that are both on the map
        for a, b in interior_doors:
            if frozenset((a, b)) in seen:
                continue
            if a not in door_coordinates_key or b not in door_coordinates_key:
                continue
            if door_tile(a) not in known or door_tile(b) not in known:
                continue
            if not self._door_visible(a) or not self._door_visible(b):
                continue
            edges.append((a, b, "interior", None))
        # Where a pit lands can be shuffled, so a drop is only a connection once it has been tracked like
        # any other link. Only when the seed is known to keep drops vanilla (an opt-in setting) are they
        # filled in from the game's own layout.
        vanilla_drops = MANUAL_DROPS if self.experimental_flags.get("vanilla_drops") else {}
        for a, b in vanilla_drops.items():
            if frozenset((a, b)) in seen or self.has_target(a):
                continue
            if door_tile(a) not in known or door_tile(b) not in known:
                continue
            if not self._door_visible(a) or not self._door_visible(b):
                continue
            edges.append((a, b, "drop", None))
        # Warp tiles always lead to the same room. Holes without a marked pit follow the same rule as pits.
        for link in ROOM_LINKS:
            if link["kind"] == "hole" and not self.experimental_flags.get("vanilla_drops"):
                continue
            ta, tb = door_tile(link["a"]), door_tile(link["b"])
            if ta not in known or tb not in known or self._is_hidden_dark(ta) or self._is_hidden_dark(tb):
                continue
            edges.append((link["a"], link["b"], link["kind"] + ("_both" if link["both_ways"] else ""), None))
        return edges

    def _door_visible(self, door):
        if self.show_all_doors or not self.lobby_doors:
            return True
        return door in self.doors_available

    def _signature(self):
        """Everything the arrangement depends on; the layout only runs again when this changes."""
        return (
            tuple(sorted(self.nodes())),
            tuple(sorted(self.joined)),
            tuple(sorted(self.compact)),
            len(self.door_links),
            tuple(sorted(tuple(sorted(m)) for m in self.stack_members.values())),
        )

    def _layout(self, full=False):
        gap = LINK_GAP
        tiles = self.nodes()
        if not tiles:
            return
        present = set(tiles)
        for tile in list(self.pos):
            if tile not in present:
                del self.pos[tile]
        self.fixed &= set(tiles)
        self.unsettled &= set(tiles)

        signature = self._signature()
        if not full and signature == self._layout_signature and all(t in self.pos for t in tiles):
            return
        self._layout_signature = signature

        if full:
            # Start from a clean slate so the same map always lays out the same way
            self._damping = {}
            for tile in tiles:
                if tile not in self.fixed:
                    self.pos.pop(tile, None)

        # Rooms that joined a stack snap onto the part of it that is already on the map
        for root, members in self.stack_members.items():
            placed = [m for m in members if m in self.pos]
            if not placed:
                continue
            anchor = next((m for m in placed if m in self.fixed), root if root in self.pos else placed[0])
            self.unsettled -= set(members)
            self._place_stack(anchor, *self.pos[anchor])

        edges = [(a, b) for a, b, kind, n in self._layout_edges()]
        pending = {root for root in self.stack_members if root not in self.pos}
        new_tiles = [m for root in pending for m in self.stack_members[root]]

        def place_from(anchor_door, new_door):
            anchor = door_tile(anchor_door)
            new = door_tile(new_door)
            ax, ay = self.pos[anchor]
            aox, aoy = self._port_offset(anchor_door)
            nox, noy = self._port_offset(new_door)
            direction = DIRECTIONS.get(door_direction(anchor_door))
            if direction is None:
                opposite = DIRECTIONS.get(door_direction(new_door))
                direction = (-opposite[0], -opposite[1]) if opposite else (1, 0.35)
            self._place_stack(new, ax + aox + direction[0] * gap - nox, ay + aoy + direction[1] * gap - noy)

        def place_loose(root):
            placed = list(self.pos.values())
            if not placed:
                self._place_stack(root, 0.0, 0.0)
            elif self.player and self.player[0] in self.pos and self.player[0] not in self._stack_of(root):
                px, py = self.pos[self.player[0]]
                self._place_stack(root, px + THUMB + LINK_GAP * 2, py + 20.0)
            else:
                max_x = max(p[0] for p in placed)
                min_y = min(p[1] for p in placed)
                self._place_stack(
                    root, max_x + THUMB + LINK_GAP * 3, min_y + (len(placed) % 5) * (THUMB + LINK_GAP)
                )

        # Seed with lobbies first so the entrances anchor the picture
        lobby_roots = [self.stack_root.get(door_tile(x["door"])) for x in self.lobby_doors]
        order = [r for r in lobby_roots if r in pending] + sorted(pending, key=lambda r: -len(self.stack_members[r]))
        while pending:
            progressed = True
            while progressed:
                progressed = False
                for a, b in edges:
                    ra, rb = self.stack_root[door_tile(a)], self.stack_root[door_tile(b)]
                    if ra in pending and rb not in pending:
                        place_from(b, a)
                        pending.discard(ra)
                        progressed = True
                    elif rb in pending and ra not in pending:
                        place_from(a, b)
                        pending.discard(rb)
                        progressed = True
            if pending:
                root = next(r for r in order if r in pending)
                place_loose(root)
                pending.discard(root)

        self.unsettled |= set(new_tiles)
        if not full:
            # Fitting something new in must not rearrange what is already there. Only the new
            # blocks are moved to where their links want them...
            self._relax(iterations=90, old_mobility=0.0, edges=edges, cold=True)
            # ...and then anything left physically overlapping is nudged apart, and nothing else.
            self._relax(iterations=0, old_mobility=1.0, edges=edges, cold=True)
        elif self.experimental_flags.get("stress_layout"):
            # Stress gets the overall shape right but knows distances, not shapes: the forces then
            # pull each link short and move apart whatever overlaps
            self._stress_layout(edges)
            self._relax(iterations=180, old_mobility=1.0, edges=edges, improve=True)
            self._relax(iterations=150, old_mobility=1.0, edges=edges, cold=True)
            self._park_unlinked(edges)
        else:
            # The result depends a lot on where things start: try a few shaken starts and keep the best
            rng = random.Random(len(tiles) * 1000 + len(edges))
            start = {t: list(p) for t, p in self.pos.items()}
            best = None
            blocks = len(self.stack_members)
            attempts = 5 if blocks <= 20 else 3 if blocks <= 35 else 2
            steps = 260 if blocks <= 35 else 180
            for attempt in range(attempts):
                self.pos = {t: list(p) for t, p in start.items()}
                if attempt:
                    for root, members in self.stack_members.items():
                        if not any(m in self.fixed for m in members):
                            x, y = self.pos[root]
                            self._place_stack(root, x + rng.uniform(-260, 260), y + rng.uniform(-260, 260))
                self._relax(iterations=steps, old_mobility=1.0, edges=edges, improve=True)
                cost = self._relax(iterations=80, old_mobility=0.5, edges=edges, improve=True)
                if best is None or cost < best[0]:
                    best = (cost, {t: list(p) for t, p in self.pos.items()})
            self.pos = best[1]
            self._relax(iterations=150, old_mobility=1.0, edges=edges, cold=True)
            self._park_unlinked(edges)
        self._laid_spacing = self.spacing

        linked = set()
        for a, b in edges:
            linked.update(self._stack_of(door_tile(a)))
            linked.update(self._stack_of(door_tile(b)))
        self.unsettled -= linked

    def _stress_layout(self, edges):
        """Arrange the stacks by stress majorization (Gansner, Koren and North 2004).

        Every pair of stacks gets an ideal distance, the length of the shortest chain of links between
        them, and the arrangement is the one where drawn distances are closest to the ideal ones. A
        link through a door in a wall also says which way its neighbour should lie: beyond that wall.
        Each stack is moved in turn to the weighted average of where the others want it, which only
        ever lowers the stress, so there is nothing to damp. Overlaps are removed afterwards.
        """
        roots = list(self.stack_members)
        index = {r: i for i, r in enumerate(roots)}
        n = len(roots)
        gap = LINK_GAP + self.spacing * 0.5
        # Each stack as a box around a centre; "origin" is where its stack offsets are measured from
        centre, half, movable = [], [], []
        for r in roots:
            boxes = []
            for m in self.stack_members[r]:
                left, top, right, bottom = self._box(m)
                ox, oy = self.stack_off[m]
                boxes.append((ox + left, oy + top, ox + right, oy + bottom))
            left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
            right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
            centre.append(((left + right) / 2, (top + bottom) / 2))
            half.append(((right - left) / 2, (bottom - top) / 2))
            movable.append(not any(m in self.fixed for m in self.stack_members[r]))
        size = [(w + h) / 2 for w, h in half]

        def origin(r):
            return self.pos[r][0] - self.stack_off[r][0], self.pos[r][1] - self.stack_off[r][1]

        # What each link asks for: the offset from one stack's centre to the other's
        wants = {}  # (i, j), i < j -> [vectors from i to j]
        loose = {}  # (i, j) -> a link with no direction (stairs, drops, warps)
        ends = []
        for a, b in edges:
            i, j = index[self.stack_root[door_tile(a)]], index[self.stack_root[door_tile(b)]]
            if i > j:
                a, b, i, j = b, a, j, i
            port = []
            for door, k in ((a, i), (b, j)):
                ox, oy = self.stack_off[door_tile(door)]
                px, py = self._port_offset(door)
                port.append((ox + px - centre[k][0], oy + py - centre[k][1]))
            ends.append((i, j, port[0], port[1]))
            da, db = DIRECTIONS.get(door_direction(a)), DIRECTIONS.get(door_direction(b))
            nx = (da[0] if da else 0) - (db[0] if db else 0)
            ny = (da[1] if da else 0) - (db[1] if db else 0)
            length = math.hypot(nx, ny)
            if length < 0.5:
                loose[(i, j)] = True
                continue
            nx, ny = nx / length, ny / length
            wants.setdefault((i, j), []).append((port[0][0] + nx * gap - port[1][0], port[0][1] + ny * gap - port[1][1]))
        target = {}
        for (i, j), vectors in wants.items():
            tx, ty = sum(v[0] for v in vectors) / len(vectors), sum(v[1] for v in vectors) / len(vectors)
            # Doors that disagree average out to nothing: keep the two stacks apart at least
            least = size[i] + size[j] + gap * 0.5
            length = math.hypot(tx, ty)
            if length < least:
                tx, ty = (tx / length * least, ty / length * least) if length > 1 else (least, 0.0)
            target[(i, j)] = (tx, ty)
            target[(j, i)] = (-tx, -ty)

        # Ideal distances: shortest chain of links, never less than the two stacks side by side
        far = float("inf")
        dist = [[far] * n for _ in range(n)]
        for i in range(n):
            dist[i][i] = 0.0
        for (i, j), (tx, ty) in target.items():
            dist[i][j] = min(dist[i][j], math.hypot(tx, ty))
        for i, j in loose:
            if (i, j) not in target:
                dist[i][j] = dist[j][i] = min(dist[i][j], size[i] + size[j] + gap)
        for k in range(n):
            row_k = dist[k]
            for i in range(n):
                through = dist[i][k]
                if through == far:
                    continue
                row_i = dist[i]
                for j in range(n):
                    if through + row_k[j] < row_i[j]:
                        row_i[j] = through + row_k[j]
        group = list(range(n))
        for i in range(n):
            for j in range(i):
                if dist[i][j] < far:
                    group[i] = group[j]
                    break
        pairs = [[] for _ in range(n)]  # per stack: (other, weight, ideal distance, target or None)
        for i in range(n):
            for j in range(n):
                if i == j or dist[i][j] == far:
                    continue
                want = target.get((i, j))
                ideal = max(dist[i][j], size[i] + size[j] + gap * 0.5)
                # A door's say counts for more than a distance: it is what makes the map read like a map
                pairs[i].append((j, (3.0 if want else 1.0) / (ideal * ideal), ideal, want))

        def crossings(xs, ys):
            lines = [(xs[i] + pa[0], ys[i] + pa[1], xs[j] + pb[0], ys[j] + pb[1], i, j) for i, j, pa, pb in ends]
            count = 0
            for p, (ax, ay, bx, by, ai, aj) in enumerate(lines):
                for cx, cy, dx, dy, ci, cj in lines[p + 1 :]:
                    if ai in (ci, cj) or aj in (ci, cj):
                        continue
                    d1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                    d2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
                    d3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
                    d4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
                    if d1 * d2 < 0 and d3 * d4 < 0:
                        count += 1
            return count

        def solve(xs, ys):
            for sweep in range(200):
                moved = 0.0
                for i in range(n):
                    if not movable[i] or not pairs[i]:
                        continue
                    x, y = xs[i], ys[i]
                    sx = sy = sw = 0.0
                    for j, weight, ideal, want in pairs[i]:
                        if want:
                            sx += weight * (xs[j] - want[0])
                            sy += weight * (ys[j] - want[1])
                        else:
                            dx, dy = x - xs[j], y - ys[j]
                            apart = math.hypot(dx, dy)
                            if apart < 1e-6:
                                dx, dy, apart = 1.0, 0.0, 1.0
                            sx += weight * (xs[j] + ideal * dx / apart)
                            sy += weight * (ys[j] + ideal * dy / apart)
                        sw += weight
                    xs[i], ys[i] = sx / sw, sy / sw
                    moved = max(moved, abs(xs[i] - x), abs(ys[i] - y))
                if moved < 0.3:
                    break
            stress = 0.0
            for i in range(n):
                for j, weight, ideal, want in pairs[i]:
                    if want:
                        stress += weight * ((xs[j] - xs[i] - want[0]) ** 2 + (ys[j] - ys[i] - want[1]) ** 2)
                    else:
                        stress += weight * (math.hypot(xs[i] - xs[j], ys[i] - ys[j]) - ideal) ** 2
            return stress

        start_x = [origin(r)[0] + centre[i][0] for i, r in enumerate(roots)]
        start_y = [origin(r)[1] + centre[i][1] for i, r in enumerate(roots)]
        rng = random.Random(n * 1000 + len(edges))
        spread = (sum(size) / max(n, 1) * 2 + gap) * math.sqrt(n)
        best = None
        for attempt in range(8 if n <= 40 else 5 if n <= 80 else 3):
            xs, ys = start_x[:], start_y[:]
            if attempt:
                for i in range(n):
                    if movable[i]:
                        xs[i], ys[i] = rng.uniform(-spread, spread), rng.uniform(-spread, spread)
            stress = solve(xs, ys)
            score = (crossings(xs, ys), stress)
            if best is None or score < best[0]:
                best = (score, xs, ys)
        xs, ys = best[1], best[2]

        # Separate groups of stacks have nothing holding them in place: set them out in rows
        groups = {}
        for i in range(n):
            groups.setdefault(group[i], []).append(i)
        free = [g for g in groups.values() if all(movable[i] for i in g)]
        held = [i for g in groups.values() if g not in free for i in g]
        free.sort(key=lambda g: -len(g))
        boxes = []
        for g in free:
            boxes.append(
                (
                    min(xs[i] - half[i][0] for i in g),
                    min(ys[i] - half[i][1] for i in g),
                    max(xs[i] + half[i][0] for i in g),
                    max(ys[i] + half[i][1] for i in g),
                )
            )
        if free:
            area = sum((b[2] - b[0] + gap) * (b[3] - b[1] + gap) for b in boxes)
            row_width = max(math.sqrt(area) * 1.5, boxes[0][2] - boxes[0][0])
            left = max((xs[i] + half[i][0] for i in held), default=0.0) + (gap * 2 if held else 0.0)
            top = min((ys[i] - half[i][1] for i in held), default=0.0)
            x, y, row_height = left, top, 0.0
            for g, box in zip(free, boxes):
                width, height = box[2] - box[0], box[3] - box[1]
                if x > left and x + width > left + row_width:
                    x, y, row_height = left, y + row_height + gap * 2, 0.0
                for i in g:
                    xs[i] += x - box[0]
                    ys[i] += y - box[1]
                x += width + gap * 2
                row_height = max(row_height, height)

        for i, r in enumerate(roots):
            if movable[i]:
                self._place_stack(r, xs[i] - centre[i][0] + self.stack_off[r][0], ys[i] - centre[i][1] + self.stack_off[r][1])

    def repulsion_shapes(self):
        """What each stack repels as, in world units: (circle or None, room boxes, reach).

        Two stacks push each other when their shapes are closer than the reach. With circle repulsion
        the shape is one circle around the whole stack; without it, the stack's own rooms, measured
        wall to wall. Either way rooms nearly touching are also told apart wall to wall.
        """
        shapes = []
        for root, members in self.stack_members.items():
            if any(m not in self.pos for m in members):
                continue
            boxes = []
            for m in members:
                x, y = self.pos[m]
                boxes.extend((x + left, y + top, x + right, y + bottom) for left, top, right, bottom in self._pieces(m))
            circle = None
            if self.circle_repulsion:
                corners = [(bx, by) for left, top, right, bottom in boxes for bx in (left, right) for by in (top, bottom)]
                circle = enclosing_circle(corners)
            shapes.append((circle, boxes, self.spacing if circle else max(self.spacing, CONTACT_RANGE)))
        return shapes

    def _park_unlinked(self, edges):
        """Line blocks that have no links to anything up beside the map.

        Nothing pulls on them, so without this they would be left wherever the search happened to drop them.
        """
        linked = set()
        for a, b in edges:
            linked.add(self.stack_root[door_tile(a)])
            linked.add(self.stack_root[door_tile(b)])
        loose = [
            r
            for r, members in self.stack_members.items()
            if r not in linked and not any(m in self.fixed for m in members)
        ]
        rest = [t for r in self.stack_members if r not in loose for t in self.stack_members[r]]
        if not loose or not rest:
            return
        right = max(self.pos[t][0] + self._box(t)[2] for t in rest)
        y = min(self.pos[t][1] + self._box(t)[1] for t in rest)
        gap = max(self.spacing, LINK_GAP)
        for r in sorted(loose):
            members = self.stack_members[r]
            left = min(self.stack_off[m][0] + self._box(m)[0] for m in members)
            top = min(self.stack_off[m][1] + self._box(m)[1] for m in members)
            bottom = max(self.stack_off[m][1] + self._box(m)[3] for m in members)
            self._place_stack(r, right + gap * 2 - left, y - top)
            y += bottom - top + gap

    def _layout_edges(self):
        """Links that still pull two different stacks towards each other."""
        return [
            e
            for e in self._edges(known=set(self.nodes()))
            if e[3] not in self.joined and self.stack_root[door_tile(e[0])] != self.stack_root[door_tile(e[1])]
        ]

    def _relax(self, iterations, old_mobility, edges, improve=False, cold=False):
        """Force layout over stacks: each stack is one rigid body made of its rooms.

        Returns the total length of the links between stacks, lower is better.
        """
        gap = LINK_GAP
        roots = list(self.stack_members)
        index = {r: i for i, r in enumerate(roots)}
        n = len(roots)
        xs = [self.pos[r][0] for r in roots]
        ys = [self.pos[r][1] for r in roots]
        start_x, start_y = xs[:], ys[:]
        # Per block: how freely it may move, and which way it last went (kept between simulation frames)
        damping = [self._damping.setdefault(r, [1.0, 0.0, 0.0]) for r in roots]
        # Rooms of each stack as (dx, dy, half width, half height) around the stack origin
        rects = []
        centres = []
        extents = []
        mobility = []
        for r in roots:
            members = self.stack_members[r]
            boxes = []
            for m in members:
                for left, top, right, bottom in self._pieces(m):
                    boxes.append(
                        (
                            self.stack_off[m][0] + (left + right) / 2,
                            self.stack_off[m][1] + (top + bottom) / 2,
                            (right - left) / 2,
                            (bottom - top) / 2,
                        )
                    )
            rects.append(boxes)
            centres.append((sum(b[0] for b in boxes) / len(boxes), sum(b[1] for b in boxes) / len(boxes)))
            extents.append(
                (
                    min(b[0] - b[2] for b in boxes),
                    max(b[0] + b[2] for b in boxes),
                    min(b[1] - b[3] for b in boxes),
                    max(b[1] + b[3] for b in boxes),
                )
            )
            if any(m in self.fixed or m in self._held for m in members):
                mobility.append(0.0)
            elif all(m in self.unsettled for m in members):
                mobility.append(1.0)
            else:
                mobility.append(old_mobility)

        # A circle around each block, for a cheap "nowhere near each other" test before the exact one
        mid_x = [(e[0] + e[1]) / 2 for e in extents]
        mid_y = [(e[2] + e[3]) / 2 for e in extents]
        radius = [math.hypot(e[1] - e[0], e[3] - e[2]) / 2 for e in extents]

        springs = []
        for a, b in edges:
            ta, tb = door_tile(a), door_tile(b)
            ia, ib = index[self.stack_root[ta]], index[self.stack_root[tb]]
            aox, aoy = self._port_offset(a)
            box, boy = self._port_offset(b)
            da, db = DIRECTIONS.get(door_direction(a)), DIRECTIONS.get(door_direction(b))
            # Where the far port should sit relative to the near one; None for stairs and drops
            if da is not None and db is not None:
                want = ((da[0] - db[0]) / 2 * gap, (da[1] - db[1]) / 2 * gap)
            elif da is not None:
                want = (da[0] * gap, da[1] * gap)
            elif db is not None:
                want = (-db[0] * gap, -db[1] * gap)
            else:
                want = None
            springs.append(
                (
                    ia,
                    aox + self.stack_off[ta][0],
                    aoy + self.stack_off[ta][1],
                    ib,
                    box + self.stack_off[tb][0],
                    boy + self.stack_off[tb][1],
                    want,
                )
            )
        incident = [[] for _ in range(n)]
        for spring in springs:
            incident[spring[0]].append(spring)
            incident[spring[3]].append(spring)

        groups = []
        if self.group_by_dungeon:
            by_dungeon = defaultdict(list)
            for r in roots:
                by_dungeon[tile_dungeon(r)].append(index[r])
            groups = [members for members in by_dungeon.values() if len(members) > 1]

        # The arrangement depends only on the links and the repulsion, never on the window looking at it
        margin_x = margin_y = HARD_GAP if cold else MIN_GAP
        reach = self.spacing
        far = max(reach, CONTACT_RANGE)

        # One circle per block, just big enough to hold all of its rooms
        circles = []
        if self.circle_repulsion:
            for boxes in rects:
                corners = [(bx + sx * hw, by + sy * hh) for bx, by, hw, hh in boxes for sx in (-1, 1) for sy in (-1, 1)]
                circles.append(enclosing_circle(corners))

        def repulsion():
            """Blocks closer than the reach push each other apart, harder the closer they are."""
            # As circles, a block repels as a whole and the same in every direction. Rooms pressing
            # right up against each other are still told apart wall to wall, whatever the shape.
            near = CONTACT_RANGE if circles else far
            for a in range(n):
                ea = extents[a]
                for b in range(a + 1, n):
                    ma, mb = mobility[a], mobility[b]
                    if ma + mb == 0:
                        continue
                    if not circles:
                        dx = xs[b] + mid_x[b] - xs[a] - mid_x[a]
                        dy = ys[b] + mid_y[b] - ys[a] - mid_y[a]
                        limit = radius[a] + radius[b] + near
                        if dx * dx + dy * dy > limit * limit:
                            continue
                    # Heavier blocks give way less: a block's share falls with the number of rooms in it
                    ease_a, ease_b = ma / weight[a], mb / weight[b]
                    share_a, share_b = ease_a / (ease_a + ease_b), ease_b / (ease_a + ease_b)
                    if circles:
                        ca, cb = circles[a], circles[b]
                        cx = xs[b] + cb[0] - xs[a] - ca[0]
                        cy = ys[b] + cb[1] - ys[a] - ca[1]
                        apart = math.hypot(cx, cy)
                        gap = apart - ca[2] - cb[2]
                        if gap < reach:
                            if apart < 1e-6:
                                cx, cy, apart = 1.0, 0.0, 1.0
                            push = REPEL_STRENGTH * (reach - max(0.0, gap))
                            xs[a] -= cx / apart * push * share_a
                            ys[a] -= cy / apart * push * share_a
                            xs[b] += cx / apart * push * share_b
                            ys[b] += cy / apart * push * share_b
                    eb = extents[b]
                    sx, sy = xs[b] - xs[a], ys[b] - ys[a]
                    if (
                        sx + eb[0] - near >= ea[1]
                        or sx + eb[1] + near <= ea[0]
                        or sy + eb[2] - near >= ea[3]
                        or sy + eb[3] + near <= ea[2]
                    ):
                        continue
                    # Measured wall to wall between the two closest rooms
                    nearest = near
                    ux = uy = 0.0
                    for ax, ay, ahw, ahh in rects[a]:
                        for bx, by, bhw, bhh in rects[b]:
                            dx = sx + bx - ax
                            dy = sy + by - ay
                            gap_x = max(0.0, abs(dx) - ahw - bhw)
                            gap_y = max(0.0, abs(dy) - ahh - bhh)
                            distance = math.hypot(gap_x, gap_y)
                            if distance < nearest:
                                nearest = distance
                                if distance > 1e-6:
                                    ux, uy = (gap_x if dx >= 0 else -gap_x), (gap_y if dy >= 0 else -gap_y)
                                else:
                                    ux, uy = dx, dy
                    if nearest >= near:
                        continue
                    norm = math.hypot(ux, uy) or 1.0
                    # Applied straight away, pair by pair, which keeps a crowd of blocks from overshooting
                    push = CONTACT_STRENGTH * max(0.0, CONTACT_RANGE - nearest)
                    if not circles:
                        push += REPEL_STRENGTH * max(0.0, reach - nearest)
                    xs[a] -= ux / norm * push * share_a
                    ys[a] -= uy / norm * push * share_a
                    xs[b] += ux / norm * push * share_b
                    ys[b] += uy / norm * push * share_b

        def overlap(a, b):
            """How far stack b has to move to clear stack a, as (x, y); (0, 0) when they are apart."""
            ea, eb = extents[a], extents[b]
            sx, sy = xs[b] - xs[a], ys[b] - ys[a]
            if (
                sx + eb[0] - margin_x >= ea[1]
                or sx + eb[1] + margin_x <= ea[0]
                or sy + eb[2] - margin_y >= ea[3]
                or sy + eb[3] + margin_y <= ea[2]
            ):
                return 0.0, 0.0
            # Blocks are not simple boxes: one can sit in a notch of another, where pushing two rooms
            # apart only drives it into a third. So look for one straight move that clears every room:
            # right, left, down or up, whichever is shortest.
            right = left = down = up = 0.0
            touching = False
            for ax, ay, ahw, ahh in rects[a]:
                for bx, by, bhw, bhh in rects[b]:
                    dx = sx + bx - ax
                    dy = sy + by - ay
                    wsum = ahw + bhw + margin_x
                    hsum = ahh + bhh + margin_y
                    in_row = -hsum < dy < hsum
                    in_column = -wsum < dx < wsum
                    if not in_row and not in_column:
                        continue
                    if in_row:
                        right = max(right, wsum - dx)
                        left = max(left, wsum + dx)
                    if in_column:
                        down = max(down, hsum - dy)
                        up = max(up, hsum + dy)
                    if in_row and in_column:
                        touching = True
            if not touching:
                return 0.0, 0.0
            shortest = min(right, left, down, up)
            if shortest == right:
                return right, 0.0
            if shortest == left:
                return -left, 0.0
            if shortest == down:
                return 0.0, down
            return 0.0, -up

        def separate(strength):
            moved = False
            for a in range(n):
                for b in range(a + 1, n):
                    ma, mb = mobility[a], mobility[b]
                    if ma + mb == 0:
                        continue
                    dx = xs[b] + mid_x[b] - xs[a] - mid_x[a]
                    dy = ys[b] + mid_y[b] - ys[a] - mid_y[a]
                    limit = radius[a] + radius[b] + margin_x
                    if dx * dx + dy * dy > limit * limit:
                        continue
                    push_x, push_y = overlap(a, b)
                    if not push_x and not push_y:
                        continue
                    moved = True
                    # Heavier blocks give way less: a block's share falls with the number of rooms in it
                    ease_a, ease_b = ma / weight[a], mb / weight[b]
                    share_a, share_b = ease_a / (ease_a + ease_b), ease_b / (ease_a + ease_b)
                    xs[a] -= push_x * strength * share_a
                    xs[b] += push_x * strength * share_b
                    ys[a] -= push_y * strength * share_a
                    ys[b] += push_y * strength * share_b
            return moved

        def cost(i):
            total = 0.0
            for ia, aox, aoy, ib, box, boy, want in incident[i]:
                dx = xs[ib] + box - xs[ia] - aox
                dy = ys[ib] + boy - ys[ia] - aoy
                if want is not None:
                    dx -= want[0]
                    dy -= want[1]
                total += math.hypot(dx, dy)
            return total

        degree = [len(x) for x in incident]
        # Experiment: a block whose links all lead to one other block is a satellite of it, and its
        # links are allowed to pull harder so it tucks in next to that block instead of floating off.
        # The slider is cubed: 1 is no boost, 4 lets those links pull 64 times as hard, which in
        # practice means nothing short of another block in the way keeps the satellite off.
        neighbours = [set() for _ in range(n)]
        for spring in springs:
            neighbours[spring[0]].add(spring[3])
            neighbours[spring[3]].add(spring[0])
        pull_limit = [
            LINK_PULL_MAX * (self.leaf_pull**3 if len(neighbours[sp[0]]) == 1 or len(neighbours[sp[3]]) == 1 else 1.0)
            for sp in springs
        ]
        weight = [len(self.stack_members[r]) for r in roots]
        total_weight = sum(weight)

        for it in range(iterations):
            cooling = 1 - it / iterations
            # A cold run only settles what is already there, it never throws blocks around
            temperature = 10 if cold else 80 * cooling + 4
            if cold:
                prev_x, prev_y = xs[:], ys[:]
            tx = [0.0] * n
            ty = [0.0] * n
            for k, (ia, aox, aoy, ib, box, boy, want) in enumerate(springs):
                pax, pay = xs[ia] + aox, ys[ia] + aoy
                pbx, pby = xs[ib] + box, ys[ib] + boy
                if want is None:
                    # No heading: keep them a card apart, any direction
                    dx, dy = pbx - pax, pby - pay
                    dist = math.hypot(dx, dy) or 0.01
                    vx, vy = dx / dist * gap * 2, dy / dist * gap * 2
                else:
                    vx, vy = want
                # How far each end is from where this link wants it
                ex, ey = pax + vx - pbx, pay + vy - pby
                if cold:
                    stretch = math.hypot(ex, ey)
                    if stretch > pull_limit[k]:
                        # Past the limit the pull keeps growing with the stretch, but as its square root:
                        # a long link does try harder than a short one, without a handful of long links
                        # being able to flatten the repulsion the way a plain spring would.
                        pull = math.sqrt(stretch * pull_limit[k])
                        ex, ey = ex / stretch * pull, ey / stretch * pull
                # Both ends get the same pull in opposite directions. Sharing it unevenly made any pair
                # held apart by repulsion creep across the map for ever.
                # ...and split by mass, so a single room comes to a big block rather than towing it along.
                # Everything that moves blocks uses the same masses, which keeps the map from creeping.
                share = 2 / max(degree[ia], degree[ib]) / (weight[ia] + weight[ib])
                tx[ib] += ex * share * weight[ia]
                ty[ib] += ey * share * weight[ia]
                tx[ia] -= ex * share * weight[ib]
                ty[ia] -= ey * share * weight[ib]

            # There is no pull towards the middle of the map: links are what hold it together, and a
            # block with no links simply stays where it is. Only "Group by original dungeon" adds a pull,
            # towards the middle of each dungeon's rooms.
            gx = [None] * n
            gy = [None] * n
            for members in groups:
                mx = sum(xs[i] + centres[i][0] for i in members) / len(members)
                my = sum(ys[i] + centres[i][1] for i in members) / len(members)
                for i in members:
                    gx[i], gy[i] = mx, my

            moves = []
            fastest = 0.0
            for i in range(n):
                if mobility[i] == 0:
                    moves.append((0.0, 0.0))
                    continue
                dx = dy = 0.0
                if gx[i] is not None:
                    dx = (gx[i] - xs[i] - centres[i][0]) * 0.25
                    dy = (gy[i] - ys[i] - centres[i][1]) * 0.25
                # Part of the way towards where its links want this stack to be
                dx += tx[i] * 0.45
                dy += ty[i] * 0.45
                dx *= mobility[i]
                dy *= mobility[i]
                moves.append((dx, dy))
                fastest = max(fastest, math.hypot(dx, dy))
            # While settling, the speed limit slows everything down together. Capping blocks one by one
            # held a fast one back while its partner moved freely, and the pair then drifted off for good.
            together = min(1.0, temperature / fastest) if cold and fastest else 1.0
            for i, (dx, dy) in enumerate(moves):
                step = math.hypot(dx, dy)
                if cold:
                    dx, dy = dx * together, dy * together
                elif step > temperature:
                    dx, dy = dx / step * temperature, dy / step * temperature
                xs[i] += dx
                ys[i] += dy
            repulsion()
            separate(1.0 if cold else 0.3 + 0.5 * (1 - cooling))
            if cold:
                # Go only half way to where this step wanted everything. The resting places are the
                # same, but two blocks can no longer swap back and forth on alternate steps.
                # A block that reverses direction is hunting around its resting place: each reversal
                # halves how far it may move, and steady movement lets it speed up again.
                for i in range(n):
                    dx = (xs[i] - prev_x[i]) / 2
                    dy = (ys[i] - prev_y[i]) / 2
                    state = damping[i]
                    if dx * state[1] + dy * state[2] < 0:
                        state[0] = max(0.02, state[0] * 0.5)
                    else:
                        state[0] = min(1.0, state[0] * 1.15)
                    state[1], state[2] = dx, dy
                    xs[i] = prev_x[i] + dx * state[0]
                    ys[i] = prev_y[i] + dy * state[0]

        for _ in range(80):
            if not separate(1.0):
                break

        if improve:
            # Forces alone leave stacks stranded on the wrong side of their neighbours. Lift each one out,
            # drop it where one of its links wants it, slide it clear of the others, and keep it if shorter.
            def settle(i):
                for _ in range(40):
                    clear = True
                    for other in range(n):
                        if other == i:
                            continue
                        dx = xs[i] + mid_x[i] - xs[other] - mid_x[other]
                        dy = ys[i] + mid_y[i] - ys[other] - mid_y[other]
                        limit = radius[i] + radius[other] + margin_x
                        if dx * dx + dy * dy > limit * limit:
                            continue
                        push_x, push_y = overlap(other, i)
                        if push_x or push_y:
                            clear = False
                            xs[i] += push_x
                            ys[i] += push_y
                    if clear:
                        return True
                return False

            movable = [i for i in range(n) if mobility[i] > 0 and degree[i]]
            for _ in range(5 if n <= 35 else 3):
                improved = False
                for i in sorted(movable, key=cost, reverse=True):
                    before = cost(i)
                    best = (before - 1, xs[i], ys[i])
                    home = (xs[i], ys[i])
                    spots = []
                    sum_x = sum_y = 0.0
                    for ia, aox, aoy, ib, box, boy, want in incident[i]:
                        vx, vy = want if want is not None else (0.0, gap * 2)
                        if ib == i and ia != i:
                            spot = (xs[ia] + aox + vx - box, ys[ia] + aoy + vy - boy)
                        elif ia == i and ib != i:
                            spot = (xs[ib] + box - vx - aox, ys[ib] + boy - vy - aoy)
                        else:
                            continue
                        spots.append(spot)
                        sum_x += spot[0]
                        sum_y += spot[1]
                    if not spots:
                        continue
                    spots.append((sum_x / len(spots), sum_y / len(spots)))
                    for spot_x, spot_y in spots:
                        xs[i], ys[i] = spot_x, spot_y
                        if settle(i):
                            value = cost(i)
                            if value < best[0]:
                                best = (value, xs[i], ys[i])
                    xs[i], ys[i] = best[1], best[2]
                    if (xs[i], ys[i]) != home:
                        improved = True
                if not improved:
                    break

        if cold and iterations and all(mobility):
            # Uneven pulls would otherwise make the whole map creep sideways while it settles
            shift_x = sum((xs[i] - start_x[i]) * weight[i] for i in range(n)) / total_weight
            shift_y = sum((ys[i] - start_y[i]) * weight[i] for i in range(n)) / total_weight
            xs = [x - shift_x for x in xs]
            ys = [y - shift_y for y in ys]
        # How fast things were still moving: the simulation stops by itself once this is tiny
        self._last_step = max(
            (math.hypot(xs[i] - start_x[i], ys[i] - start_y[i]) for i in range(n)), default=0.0
        ) / max(1, iterations)
        for i, r in enumerate(roots):
            self._place_stack(r, xs[i], ys[i])
        return sum(cost(i) for i in range(n)) / 2

    def _keep_centre(self, before):
        """Shift the map back to where it was, so a new arrangement does not jump out from under the view."""
        after = self._bounds()
        dx = (before[0] + before[2] - after[0] - after[2]) / 2
        dy = (before[1] + before[3] - after[1] - after[3]) / 2
        for position in self.pos.values():
            position[0] += dx
            position[1] += dy

    def _bounds(self):
        if not self.pos:
            return 0, 0, 1, 1
        x0 = min(self.pos[t][0] + self._box(t)[0] for t in self.pos)
        y0 = min(self.pos[t][1] + self._box(t)[1] for t in self.pos)
        x1 = max(self.pos[t][0] + self._box(t)[2] for t in self.pos)
        y1 = max(self.pos[t][1] + self._box(t)[3] for t in self.pos)
        return x0, y0, x1, y1

    def _door_dots(self, tile):
        """Every door drawn on a card as (door, x, y, radius, fill, outline), offsets in world units from its centre."""
        lobby_doors = set(self._lobby_door_names())
        dots = []
        for door in tile_door_names(tile):
            if door in ENTRANCE_ONLY_DOORS or door.startswith("Skull Drop Entrance"):
                continue
            if door in self._seam_doors or not self._door_visible(door):
                continue
            interior = door in INTERIOR_DOORS
            if interior and tile in self.compact:
                continue
            linked = door in self._linked_doors or door in lobby_doors
            if interior:
                fill = DOOR_INTERIOR
            elif linked:
                fill = DOOR_LINKED
            else:
                fill = DOOR_OPEN
            ox, oy = self._port_offset(door)
            small = interior or linked
            dots.append((door, ox, oy, DOOR_RADIUS * (0.7 if small else 1.0), fill, 1 if small else 1.5))
        return dots

    def _is_linked(self, door):
        if door in self._lobby_door_names():
            return True
        for link in self.door_links:
            if link["door"] == door or link["linked_door"] == door:
                return True
        return False
