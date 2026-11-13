"""Static room data derived from the door tables: supertiles, their parts, doors, warps and holes."""

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import NamedTuple

from data.doors_data import (
    door_coordinates,
    doors_data,
    doors_to_regions,
    dungeon_abv_to_name,
    dungeon_warps,
    falldown_pits,
    interior_doors,
    logical_connections,
    regions_to_doors,
    vanilla_logical_connections,
)
from data.room_bounds import room_bounds


class Node(NamedTuple):
    """A room card on the map: a supertile, or one part of a split one."""

    x: int
    y: int
    part: int = 0

    @property
    def tile(self):
        return (self.x, self.y)


@dataclass(frozen=True)
class Door:
    """A door, or one end of a warp or hole (see ROOM_PORTS)."""

    tile: tuple  # supertile (x, y)
    x: float  # position in the supertile picture, 0..1
    y: float
    facing: str = None  # No, So, We, Ea, Up or Dn; None for a warp or hole end
    regions: tuple = ()
    part: int = 0  # index into its supertile's parts


@dataclass(frozen=True)
class DoorlessRoom:
    tile: tuple  # supertile (x, y)
    dungeon: str
    x: float  # position in the supertile picture, 0..1
    y: float


class EdgeKind(Enum):
    """How two doors are connected."""

    LINK = "link"  # tracked: found by the player or the tracker
    INTERIOR = "interior"  # two doors inside one supertile; never shuffled
    DROP = "drop"  # a fall from one door to another, as in vanilla
    WARP = "warp"  # a warp tile; never shuffled
    HOLE = "hole"  # a fall with no door at either end, as in vanilla


@dataclass(frozen=True)
class RoomLink:
    """A warp or unmarked hole between two supertiles."""

    a: str  # its ends, as names in ROOM_PORTS
    b: str
    kind: EdgeKind  # WARP or HOLE
    both_ways: bool


def _read_doors():
    doors = {}
    for tile, entries in door_coordinates.items():
        for entry in entries:
            name = entry["name"]
            found = doors_to_regions.get(name)
            regions = () if found is None else tuple(found) if isinstance(found, list) else (found,)
            doors[name] = Door(tile, entry["x"] / 512, entry["y"] / 512, doors_data[name][1], regions)
    return doors


DOORS = _read_doors()  # parts are filled in once the supertiles are built

DIRECTIONS ={"No": (0, -1), "So": (0, 1), "We": (-1, 0), "Ea": (1, 0)}
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

# Rooms with no doors, by region
DOORLESS_ROOMS = {
    "Ice Fairy": DoorlessRoom((15, 4), "Ice_Palace", 0.75, 0.25),
    "Eastern Fairies": DoorlessRoom((9, 8), "Eastern_Palace", 0.5, 0.31),
    "Hera Fairies": DoorlessRoom((7, 10), "Tower_of_Hera", 0.27, 0.25),
}

# Known warp tile positions. warp: (tile, landing), each 0..1 in its supertile picture
WARP_SPOTS = {
    # Under the moving spikes; lands at the right of the Firesnake room
    "GT Spike Crystals Warp": ((0.885, 0.26), (0.89, 0.265)),
}


def _build_room_links():
    """Warps and unmarked holes as (ports, links).

    Their ends are regions, not doors, so each end gets a port: a Door record with no facing.
    """
    home = {}
    for region, doors in regions_to_doors.items():
        for name in doors:
            home.setdefault(name, []).append(region)

    def spot(regions):
        """A port at the mean position of the regions' doors, in the part of the first one; None unless they share one supertile."""
        points, part = {}, {}
        for region in regions:
            if region in DOORLESS_ROOMS:
                room = DOORLESS_ROOMS[region]
                return Door(room.tile, room.x, room.y)
            for name in regions_to_doors.get(region, []):
                if name in DOORS:
                    door = DOORS[name]
                    points.setdefault(door.tile, []).append((door.x, door.y))
                    part.setdefault(door.tile, door.part)
        if len(points) != 1:
            return None
        tile, found = next(iter(points.items()))
        return Door(tile, sum(p[0] for p in found) / len(found), sum(p[1] for p in found) / len(found), part=part[tile])

    def part_of(place):
        """(supertile, part) of a port."""
        return place.tile, place.part

    # beside: regions joined in-room. onward: region -> warp targets
    beside, onward = {}, {}
    for name, target in logical_connections:
        for region in home.get(name, []):
            beside.setdefault(region, set()).add(target)
            beside.setdefault(target, set()).add(region)
    for name, target in dungeon_warps:
        for region in home.get(name, []):
            onward.setdefault(region, []).append(target)

    def place_of(region):
        """Spot for a region; a doorless region takes the spot of one it connects to in-room."""
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
        """Spots a warp or hole leads to, following warps through regions that have no spot."""
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
    for kind, pairs in ((EdgeKind.WARP, dungeon_warps), (EdgeKind.HOLE, falldown_pits)):
        for name, target in pairs:
            if name in MANUAL_DROPS or name in DOORS:
                continue  # door-to-door drop, handled elsewhere
            start = next((p for p in map(place_of, home.get(name, [])) if p is not None), None)
            if start is None:
                continue
            for end in landings(target):
                if start.tile == end.tile:
                    continue  # same supertile: see _build_parts
                # Keyed by part: two warps can join the same pair of supertiles
                found.setdefault((part_of(start), part_of(end), kind), (name, start, end))
    links = []
    for (ta, tb, kind), (name, start, end) in found.items():
        both_ways = (tb, ta, kind) in found
        if both_ways and (tb, ta) < (ta, tb):
            continue  # the reverse warp covers this pair
        a, b = name, f"{name} landing"
        if name in WARP_SPOTS:
            (sx, sy), (ex, ey) = WARP_SPOTS[name]
            start, end = replace(start, x=sx, y=sy), replace(end, x=ex, y=ey)
        ports[a], ports[b] = start, end
        links.append(RoomLink(a, b, kind, both_ways))
    return MappingProxyType(ports), tuple(links)


# Never split: Ice Cross (push blocks), Sewers Rat Path (drop landing), Ice Freezors (bomb jump)
ONE_PLACE = {(14, 1), (1, 1), (14, 7)}


def _build_parts():
    """Split each supertile into parts you cannot walk between.

    Doors share a part when their regions are joined by a logical connection, an interior door or
    an in-supertile warp. Drops do not join. Returns {supertile: [door names per part]}.
    """
    home = {}
    for region, names in regions_to_doors.items():
        for name in names:
            home.setdefault(name, []).append(region)

    def region_tile(region):
        tiles = {DOORS[d].tile for d in regions_to_doors.get(region, []) if d in DOORS}
        if not tiles:
            return None  # doorless region: belongs to whatever it connects
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
    # Warps count too; flood() stops at other supertiles, so only in-supertile warps join anything
    for exit_name, region in dungeon_warps:
        for start in home.get(exit_name, []):
            connect(start, region)

    by_tile = {}
    for name, door in DOORS.items():
        by_tile.setdefault(door.tile, []).append(name)

    parts = {}
    for tile, names in by_tile.items():
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
        for name in names:
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
    return parts


@dataclass(frozen=True)
class Supertile:
    """Static data for one supertile. Unknown supertiles get the empty record."""

    doors: tuple = ()  # door names, in door table order
    parts: tuple = ((),)  # door names per part; one part when not split
    areas: tuple = ()  # picture boxes per part; empty when not split
    live: tuple = ()  # picture boxes of rooms in use; empty when unknown
    background: tuple = None
    dungeon: str = None
    title: str = None  # doorless rooms only; others are titled by region


def _build_supertiles():
    parts_by_tile = _build_parts()
    doorless = {room.tile: (region, room.dungeon) for region, room in DOORLESS_ROOMS.items()}
    records = {}
    for tile in set(parts_by_tile) | set(doorless):
        parts = parts_by_tile.get(tile, [[]])
        doors = [name for name, door in DOORS.items() if door.tile == tile]
        bounds = room_bounds.get(tile, {})
        live = bounds.get("live") or []
        areas = []
        if len(parts) > 1:
            areas = bounds.get("areas")
            if not areas or len(areas) != len(parts):
                # No generated areas: each part gets the live rooms nearest its doors
                rooms = live or [(0, 0, 512, 512)]
                areas = []
                for names in parts:
                    mine = set()
                    for x, y in ((DOORS[name].x * 512, DOORS[name].y * 512) for name in names):
                        mine.add(
                            min(
                                range(len(rooms)),
                                key=lambda i: max(rooms[i][0] - x, 0, x - rooms[i][2]) + max(rooms[i][1] - y, 0, y - rooms[i][3]),
                            )
                        )
                    areas.append([rooms[i] for i in sorted(mine)])
        title, dungeon = doorless.get(tile, (None, None))
        for name in doors:
            prefix = name.split(" ")[0]
            if prefix in dungeon_abv_to_name or prefix == "Sanctuary":
                dungeon = dungeon_abv_to_name.get(prefix, "Hyrule_Castle")
                break
        records[tile] = Supertile(
            doors=tuple(doors),
            parts=tuple(tuple(names) for names in parts),
            areas=tuple(tuple(tuple(box) for box in boxes) for boxes in areas),
            live=tuple(tuple(box) for box in live),
            background=tuple(bounds["background"]) if "background" in bounds else None,
            dungeon=dungeon,
            title=title,
        )
    return MappingProxyType(records)


SUPERTILES = _build_supertiles()
_UNKNOWN = Supertile()
DOORS = MappingProxyType(
    {
        name: replace(DOORS[name], part=k)
        for st in SUPERTILES.values()
        for k, names in enumerate(st.parts)
        for name in names
    }
)
# Ends of warps and holes by name; kept apart from DOORS, which holds only real doors
ROOM_PORTS, ROOM_LINKS = _build_room_links()


def supertile(tile):
    """Record for a supertile (x, y)."""
    return SUPERTILES.get(tile, _UNKNOWN)


def find_door(name):
    """Record of a door or port; None if unknown."""
    return DOORS.get(name) or ROOM_PORTS.get(name)


def door_direction(name):
    door = find_door(name)
    return door.facing if door else None


def door_fraction(name):
    """Position of a door or port inside its supertile as 0..1 fractions."""
    door = find_door(name)
    return (door.x, door.y) if door else (0.5, 0.5)


class Rooms:
    """Lookups that depend on whether supertiles are split into parts."""

    def __init__(self, split):
        self.split = split

    def part_count(self, tile):
        return len(supertile(tile).parts) if self.split else 1

    def node(self, name):
        """Node of a door or port; None if unknown."""
        door = find_door(name)
        return Node(*door.tile, door.part if self.split else 0) if door else None

    def doors(self, node):
        st = supertile(node.tile)
        if self.split and len(st.parts) > 1:
            return list(st.parts[node.part]) if node.part < len(st.parts) else []
        return list(st.doors)

    def regions(self, node):
        regions = []
        for door in self.doors(node):
            for region in DOORS[door].regions:
                if region not in regions:
                    regions.append(region)
        return regions

    def title(self, node):
        regions = self.regions(node)
        if regions:
            return regions[0]
        if supertile(node.tile).title:
            return supertile(node.tile).title
        doors = self.doors(node)
        if doors:
            return " ".join(doors[0].split(" ")[:-1]) or doors[0]
        return f"Tile {node.x},{node.y}"


SPLIT, WHOLE = Rooms(True), Rooms(False)


def _dungeon_backgrounds():
    """Background colour per dungeon: the most common one among its supertile pictures."""
    counts = {}
    for st in SUPERTILES.values():
        if st.background is None:
            continue
        colour = "#%02x%02x%02x" % st.background
        tally = counts.setdefault(st.dungeon, {})
        tally[colour] = tally.get(colour, 0) + 1
    return {dungeon: max(tally, key=tally.get) for dungeon, tally in counts.items() if dungeon}


DUNGEON_BACKGROUNDS = _dungeon_backgrounds()
