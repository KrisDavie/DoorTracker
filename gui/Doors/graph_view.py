"""Cluster + graph renderer for the door tracker.

Every supertile is a *cluster* (a card holding its doors at their real positions),
every door link is a graph *edge* between two door ports. Cards are placed by a
direction-aware force layout: a link leaving through a north door pulls the linked
supertile above the card, an east door pulls it to the right, and so on. Positions
are kept between redraws so the map stays stable while it grows.

The model (tiles / door_links / lobby_doors / special_doors) and the YAML format are
the same as the old grid renderer, so existing tracker files load unchanged.
"""

import math
import random
from collections import defaultdict, deque
from pathlib import Path
from tkinter import messagebox
from tkinter import BOTH, FIRST, LAST, LEFT, NW, RIGHT, X, BooleanVar, Canvas, DoubleVar, Menu, StringVar, ttk

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, ImageTk

import data.doors_sprite_data as doors_sprite_data
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
from data.worlds_data import dungeon_worlds

ITEM_SHEET_PATH = Path(__file__).parent.parent.parent / "data" / "Doors_Sheet.png"

# Geometry, in world units (canvas pixels at zoom 1.0)
THUMB = 128  # supertile thumbnail edge
TITLE_H = 18  # card title bar
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
SNAP = THUMB / 8  # stacked rooms line up on this grid along the shared wall  # minimum space kept between cards
SCROLL_EXTENT = 200000
TOOLBAR_HEIGHT = 30

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
DROP_COLOUR = "#4a4f57"  # fixed pit drops: drawn like links, but not one of the tracked colours


def door_tile(door):
    """Supertile (x, y) on the EG map a door belongs to, or None for regions and unknown names."""
    if door in door_coordinates_key:
        return door_coordinates_key[door][0]
    if door in doors_data:
        room = int(doors_data[door][0])
        return (room % 16, room // 16)
    return None


def door_direction(door):
    try:
        return doors_data[door][1]
    except (KeyError, IndexError):
        return None


def door_fraction(door):
    """Position of a door inside its supertile as 0..1 fractions."""
    if door in door_coordinates_key:
        tile, list_pos = door_coordinates_key[door]
        coords = door_coordinates[tile][list_pos]
        return coords["x"] / 512, coords["y"] / 512
    return 0.5, 0.5


def tile_door_names(tile):
    if tile not in door_coordinates:
        return []
    return [d["name"] for d in door_coordinates[tile]]


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
    for door in tile_door_names(tile):
        prefix = door.split(" ")[0]
        if prefix in dungeon_abv_to_name:
            return dungeon_abv_to_name[prefix]
        if prefix == "Sanctuary":
            return "Hyrule_Castle"
    return None


def tile_title(tile):
    regions = tile_regions(tile)
    if regions:
        return regions[0]
    doors = tile_door_names(tile)
    if doors:
        return " ".join(doors[0].split(" ")[:-1]) or doors[0]
    return f"Tile {tile[0]},{tile[1]}"


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


class GraphDoorPage(ttk.Frame):
    def __init__(self, top, parent, tab_world, eg_img=None, cdims=(1548, 768), aspect_ratio=(1, 2)):
        super().__init__(parent)
        self.top = top
        self.tab_world = tab_world
        self.eg_img = eg_img
        self.dungeon_name = [k for k, v in dungeon_worlds.items() if v == tab_world][0]
        self.dungeon = self.dungeon_name

        self.aspect_ratio = aspect_ratio
        self.cheight = cdims[1]
        self.cwidth = int(cdims[1] * aspect_ratio[1] / aspect_ratio[0])
        self.show_all_doors = False
        self.experimental_flags = top.experimental_flags
        self.eg_selection_mode = False

        self.zoom = 1.0
        self._drawn_zoom = 1.0
        self._thumb_cache = {}
        self._card_cache = {}
        self._dots_by_tile = {}
        self._seam_doors = set()
        self._linked_doors = set()
        self._hot_door = None
        self._drawn_zoom = 1.0
        self._sprite_cache = {}
        self._items = {}  # canvas item id -> (kind, payload)
        self._door_items = {}
        self._images = []  # keep PhotoImage references alive
        self._press = None
        self._needs_fit = True
        self._fit_provisional = False
        self.spacing = float(REPEL_RANGE)  # blocks closer than this push each other away
        self._laid_spacing = None
        self.leaf_pull = 2.5  # how much harder a block's links pull when they all lead to one other block
        self._held = set()  # rooms being dragged right now
        self._damping = {}
        self._tick_job = None
        self._last_step = 0.0
        self._spacing_job = None
        self.camera = [0.0, 0.0]  # world point shown at the centre of the window

        self._build_widgets()
        self.init_page()
        self.redraw_canvas()

    # ------------------------------------------------------------------ widgets

    def _build_widgets(self):
        toolbar = ttk.Frame(self, height=TOOLBAR_HEIGHT)
        toolbar.pack(fill=X)
        ttk.Button(toolbar, text="Fit", width=5, command=self.fit_view).pack(side=LEFT, padx=(4, 2), pady=2)
        ttk.Button(toolbar, text="Re-layout", command=self.relayout).pack(side=LEFT, padx=2, pady=2)
        self.group_by_dungeon = BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar, text="Group by original dungeon", variable=self.group_by_dungeon, command=self.relayout
        ).pack(side=LEFT, padx=8)
        self.auto_stack = BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Stack fitting rooms", variable=self.auto_stack, command=self.relayout).pack(
            side=LEFT, padx=8
        )
        ttk.Label(toolbar, text="Spacing").pack(side=LEFT, padx=(8, 2))
        self.spacing_var = DoubleVar(value=self.spacing)
        ttk.Scale(
            toolbar, from_=10, to=200, length=120, variable=self.spacing_var, command=self._on_spacing
        ).pack(side=LEFT)
        ttk.Label(toolbar, text="Satellite pull").pack(side=LEFT, padx=(8, 2))
        self.leaf_pull_var = DoubleVar(value=self.leaf_pull)
        ttk.Scale(
            toolbar, from_=1, to=4, length=80, variable=self.leaf_pull_var, command=self._on_leaf_pull
        ).pack(side=LEFT)
        self.simulate = BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Simulate", variable=self.simulate, command=self._on_simulate).pack(side=LEFT, padx=8)
        self.follow_player = BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Follow player", variable=self.follow_player).pack(side=LEFT, padx=8)
        self.status = StringVar(value="")
        ttk.Label(toolbar, textvariable=self.status, anchor="w").pack(side=LEFT, padx=8, fill=X, expand=True)

        self.canvas = Canvas(
            self,
            width=self.cwidth + 50,
            height=self.cheight + 50 - TOOLBAR_HEIGHT,
            background=BACKGROUND,
            highlightthickness=0,
            confine=False,
            scrollregion=(-SCROLL_EXTENT, -SCROLL_EXTENT, SCROLL_EXTENT, SCROLL_EXTENT),
        )
        self.canvas.pack(fill=BOTH, expand=True)

        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Double-Button-1>", self._on_double_click)
        c.bind("<Button-3>", self._on_right_click)
        c.bind("<Control-ButtonPress-1>", self._on_ctrl_click)
        c.bind("<Button-2>", self._on_middle_click)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        c.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))
        c.bind("<Motion>", self._on_motion)
        c.bind("<Escape>", lambda e: self._cancel_selection())
        c.bind("<Configure>", self._on_configure)
        c.bind("<Map>", self._on_configure)

    # -------------------------------------------------------------------- model

    def init_page(self):
        self.tiles = {}
        self.door_links = []
        self.lobby_doors = []
        self.special_doors = {}
        self.pinned_eg_tiles = set()
        self.sanc_dungeon = False

        self.pos = {}  # tile -> [x, y] centre of the card, world units
        self.fixed = set()  # pinned rooms: neither the layout nor the simulation moves them
        self.unsettled = set()  # freshly added tiles, free to move until they are linked
        self.compact = set()
        self.stack_root = {}
        self.stack_off = {}
        self.stack_members = {}
        self.joined = set()
        self._layout_signature = None
        self._stack_rank = {}
        self._focus = None
        self._edge_fill = {}
        self._door_style = {}
        self._hot_door = None
        self._zoom_job = None
        self.doors_available = set()
        self.player = None
        self.selected_door = None
        self._needs_fit = True

        for tile in mandatory_tiles[self.tab_world]:
            self._ensure_tile(tile)

    def _ensure_tile(self, tile, has_been_lit=False):
        if tile is None or tile in self.tiles:
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
        data = self.tiles.get(tile)
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

        self.compact = self._compact_tiles()
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
            if tile in self.pinned_eg_tiles or self._is_hidden_dark(tile):
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
        return compact

    # ----------------------------------------------------------------- geometry

    def _size(self, tile):
        if tile in self.compact:
            return COMPACT_W, COMPACT_H
        return THUMB, THUMB

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

    # ------------------------------------------------------------------- stacks

    def _stackable(self, tile):
        return tile in self.tiles and tile not in self.compact and not self._is_hidden_dark(tile)

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
        if da[0] == 0:
            return round((fax - fbx) * THUMB / SNAP) * SNAP, da[1] * THUMB
        return da[0] * THUMB, round((fay - fby) * THUMB / SNAP) * SNAP

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
        root = {t: t for t in self.tiles}
        off = {t: (0.0, 0.0) for t in self.tiles}
        members = {t: [t] for t in self.tiles}
        joined = set()
        auto = self.auto_stack.get()
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
            clash = any(
                abs(off[m][0] + sx - off[k][0]) < THUMB - 1 and abs(off[m][1] + sy - off[k][1]) < THUMB - 1
                for m in members[rb]
                for k in members[ra]
            )
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
        return edges

    def _door_visible(self, door):
        if self.show_all_doors or not self.lobby_doors:
            return True
        return door in self.doors_available

    # ------------------------------------------------------------------- layout

    def _signature(self):
        """Everything the arrangement depends on; the layout only runs again when this changes."""
        return (
            tuple(sorted(self.tiles)),
            tuple(sorted(self.joined)),
            tuple(sorted(self.compact)),
            len(self.door_links),
            tuple(sorted(tuple(sorted(m)) for m in self.stack_members.values())),
        )

    def _layout(self, full=False):
        gap = LINK_GAP
        tiles = list(self.tiles)
        if not tiles:
            return
        for tile in list(self.pos):
            if tile not in self.tiles:
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
        else:
            # The result depends a lot on where things start: try a few shaken starts and keep the best
            rng = random.Random(len(tiles) * 1000 + len(edges))
            start = {t: list(p) for t, p in self.pos.items()}
            best = None
            for attempt in range(5):
                self.pos = {t: list(p) for t, p in start.items()}
                if attempt:
                    for root, members in self.stack_members.items():
                        if not any(m in self.fixed for m in members):
                            x, y = self.pos[root]
                            self._place_stack(root, x + rng.uniform(-260, 260), y + rng.uniform(-260, 260))
                self._relax(iterations=260, old_mobility=1.0, edges=edges, improve=True)
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
        right = max(self.pos[t][0] + self._size(t)[0] / 2 for t in rest)
        y = min(self.pos[t][1] - self._size(t)[1] / 2 for t in rest)
        gap = max(self.spacing, LINK_GAP)
        for r in sorted(loose):
            members = self.stack_members[r]
            left = min(self.stack_off[m][0] - self._size(m)[0] / 2 for m in members)
            top = min(self.stack_off[m][1] - self._size(m)[1] / 2 for m in members)
            bottom = max(self.stack_off[m][1] + self._size(m)[1] / 2 for m in members)
            self._place_stack(r, right + gap * 2 - left, y - top)
            y += bottom - top + gap

    def _layout_edges(self):
        """Links that still pull two different stacks towards each other."""
        return [
            e
            for e in self._edges(known=self.tiles)
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
                w, h = self._size(m)
                boxes.append((self.stack_off[m][0], self.stack_off[m][1], w / 2, h / 2))
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
        if self.group_by_dungeon.get():
            by_dungeon = defaultdict(list)
            for r in roots:
                by_dungeon[tile_dungeon(r)].append(index[r])
            groups = [members for members in by_dungeon.values() if len(members) > 1]

        # The arrangement depends only on the links and the repulsion, never on the window looking at it
        margin_x = margin_y = HARD_GAP if cold else MIN_GAP
        reach = self.spacing
        far = max(reach, CONTACT_RANGE)

        def repulsion():
            """Blocks closer than the reach push each other apart, harder the closer they are."""
            for a in range(n):
                ea = extents[a]
                for b in range(a + 1, n):
                    ma, mb = mobility[a], mobility[b]
                    if ma + mb == 0:
                        continue
                    eb = extents[b]
                    sx, sy = xs[b] - xs[a], ys[b] - ys[a]
                    if (
                        sx + eb[0] - far >= ea[1]
                        or sx + eb[1] + far <= ea[0]
                        or sy + eb[2] - far >= ea[3]
                        or sy + eb[3] + far <= ea[2]
                    ):
                        continue
                    # Measured wall to wall between the two closest rooms
                    nearest = far
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
                    if nearest >= far:
                        continue
                    norm = math.hypot(ux, uy) or 1.0
                    # Applied straight away, pair by pair, which keeps a crowd of blocks from overshooting
                    push = REPEL_STRENGTH * max(0.0, reach - nearest) + CONTACT_STRENGTH * max(
                        0.0, CONTACT_RANGE - nearest
                    )
                    # Heavier blocks give way less: a block's share falls with the number of rooms in it
                    ease_a, ease_b = ma / weight[a], mb / weight[b]
                    share_a, share_b = ease_a / (ease_a + ease_b), ease_b / (ease_a + ease_b)
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
                    in_row = abs(dy) < hsum
                    in_column = abs(dx) < wsum
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
        weight = [len(r) for r in rects]
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
                        ex, ey = ex / stretch * pull_limit[k], ey / stretch * pull_limit[k]
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
                        push_x, push_y = overlap(other, i)
                        if push_x or push_y:
                            clear = False
                            xs[i] += push_x
                            ys[i] += push_y
                    if clear:
                        return True
                return False

            movable = [i for i in range(n) if mobility[i] > 0 and degree[i]]
            for _ in range(5):
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

    def relayout(self):
        self._sync_model()
        self._optimise_stack_order()
        before = self._bounds() if self.pos else None
        self._layout(full=True)
        if before is None:
            self._needs_fit = True
        else:
            self._keep_centre(before)
        self._render()

    def _on_spacing(self, value):
        self.spacing = float(round(float(value)))
        if self.spacing != self._laid_spacing:
            self._laid_spacing = self.spacing
            self._kick()

    def _on_leaf_pull(self, value):
        value = round(float(value), 1)
        if value != self.leaf_pull:
            self.leaf_pull = value
            self._kick()

    def _on_simulate(self):
        if self.simulate.get() and self._tick_job is None:
            self._tick_job = self.after(1, self._tick)

    def _kick(self):
        """Something changed the forces (slider, a dropped block, a pin).

        With Simulate ticked the running simulation picks it up. Without it the map is moved to its
        new resting place in one go, and then nothing moves again until the next change.
        """
        if self.simulate.get():
            if self._tick_job is None:
                self._tick_job = self.after(1, self._tick)
            return
        if not self.pos:
            return
        before = {t: (p[0], p[1]) for t, p in self.pos.items()}
        edges = [(a, b) for a, b, kind, n in self._layout_edges()]
        self._relax(iterations=150, old_mobility=1.0, edges=edges, cold=True)
        self._slide(before)

    def _tick(self):
        """One frame of the simulation: a few solver steps, then slide the drawn rooms to match."""
        self._tick_job = None
        if not self.simulate.get() or not self.winfo_exists():
            # Unticked: stop here. Nothing moves on its own while Simulate is off.
            return
        if self.pos and self._zoom_job is None and self.canvas.winfo_viewable():
            before = {t: (p[0], p[1]) for t, p in self.pos.items()}
            edges = [(a, b) for a, b, kind, n in self._layout_edges()]
            self._relax(iterations=3, old_mobility=1.0, edges=edges, cold=True)
            self._slide(before)
        self._tick_job = self.after(15, self._tick)

    def _slide(self, before):
        """Move what is already drawn instead of drawing everything again."""
        if self._drawn_zoom != self.zoom or self.group_by_dungeon.get():
            self._render()
            return
        z = self.zoom
        moved = False
        for tile, (old_x, old_y) in before.items():
            if tile not in self.pos:
                continue
            dx, dy = (self.pos[tile][0] - old_x) * z, (self.pos[tile][1] - old_y) * z
            if abs(dx) > 0.01 or abs(dy) > 0.01:
                self.canvas.move(f"tile_{tile[0]}_{tile[1]}", dx, dy)
                moved = True
        if moved:
            self._redraw_edges()

    def _redraw_edges(self):
        self.canvas.delete("edge")
        self._items = {k: v for k, v in self._items.items() if v[0] != "edge" or self.canvas.type(k) == "rectangle"}
        focus = self._focus
        self._draw_edges()
        self._set_focus(focus)
        self.canvas.tag_raise("door")
        self.canvas.tag_raise("icon")
        self.canvas.tag_raise("player")
        self._draw_door_marks()

    # ---------------------------------------------------------------- rendering

    def redraw_canvas(self):
        self._sync_model()
        self._layout()
        self._render()

    def _w2c(self, x, y):
        return x * self.zoom, y * self.zoom

    def _viewport(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            w, h = self.cwidth + 50, self.cheight + 50 - TOOLBAR_HEIGHT
        return w, h

    def _apply_camera(self):
        """Point the window at the camera. The camera is the only thing that decides what is on screen."""
        vw, vh = self._viewport()
        left = self.camera[0] * self._drawn_zoom - vw / 2
        top = self.camera[1] * self._drawn_zoom - vh / 2
        span = SCROLL_EXTENT * 2
        self.canvas.xview_moveto((left + SCROLL_EXTENT) / span)
        self.canvas.yview_moveto((top + SCROLL_EXTENT) / span)

    def _bounds(self):
        if not self.pos:
            return 0, 0, 1, 1
        x0 = min(self.pos[t][0] - self._size(t)[0] / 2 for t in self.pos)
        x1 = max(self.pos[t][0] + self._size(t)[0] / 2 for t in self.pos)
        y0 = min(self.pos[t][1] - self._size(t)[1] / 2 for t in self.pos)
        y1 = max(self.pos[t][1] + self._size(t)[1] / 2 for t in self.pos)
        return x0, y0, x1, y1

    def fit_view(self):
        """Move the camera so the whole map is in view. Only run when asked for, or for a freshly loaded map."""
        x0, y0, x1, y1 = self._bounds()
        pad = 70
        vw, vh = self._viewport()
        zoom = min(vw / (x1 - x0 + pad * 2), vh / (y1 - y0 + pad * 2))
        self.zoom = max(0.15, min(1.0, zoom))
        self.camera = [(x0 + x1) / 2, (y0 + y1) / 2]
        self._needs_fit = False
        # A tab that has never been shown does not know its real size yet
        self._fit_provisional = not self.canvas.winfo_viewable()
        self._render()

    _mips = {}  # supertile -> (512px, 256px) opaque copies, shared by every dungeon tab
    _fonts = {}
    _dot_sprites = {}

    def _thumbnail(self, tile, size):
        """The supertile picture at the given pixel size, as a PIL image."""
        key = (tile, size)
        if key not in self._thumb_cache:
            if len(self._thumb_cache) > 400:
                self._thumb_cache.clear()
            if self.eg_img is None:
                img = Image.new("RGB", (size, size), "#444")
            else:
                if tile not in GraphDoorPage._mips:
                    x, y = tile
                    crop = self.eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).convert("RGB")
                    GraphDoorPage._mips[tile] = (crop, crop.resize((256, 256), Image.LANCZOS))
                full, half = GraphDoorPage._mips[tile]
                img = (half if size <= 256 else full).resize((size, size), Image.BILINEAR)
            self._thumb_cache[key] = img
        return self._thumb_cache[key]

    def _font(self, px):
        px = max(7, int(round(px)))
        if px not in GraphDoorPage._fonts:
            font = None
            for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
                try:
                    font = ImageFont.truetype(name, px)
                    break
                except OSError:
                    continue
            if font is None:
                try:
                    font = ImageFont.load_default(px)
                except TypeError:
                    font = ImageFont.load_default()
            GraphDoorPage._fonts[px] = font
        return GraphDoorPage._fonts[px]

    def _dot_sprite(self, fill, size, width):
        """An anti-aliased door dot, pasted into card images."""
        key = (fill, size, width)
        if key not in GraphDoorPage._dot_sprites:
            scale = 4
            img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse(
                (0, 0, size * scale - 1, size * scale - 1),
                fill=fill,
                outline="#111111",
                width=max(1, int(round(width * scale))),
            )
            GraphDoorPage._dot_sprites[key] = img.resize((size, size), Image.LANCZOS)
        return GraphDoorPage._dot_sprites[key]

    _pin_sprites = {}

    def _pin_sprite(self, size):
        """A pushpin, drawn in the corner of a pinned room."""
        if size not in GraphDoorPage._pin_sprites:
            scale = 4
            n = size * scale
            img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # White backing so it reads on any room, then needle, then the red head on top
            draw.ellipse((0, 0, n - 1, n - 1), fill=(255, 255, 255, 235), outline="#222222", width=scale)
            draw.line((n * 0.46, n * 0.54, n * 0.2, n * 0.8), fill="#222222", width=max(2, int(n * 0.08)))
            head = (n * 0.36, n * 0.16, n * 0.84, n * 0.64)
            draw.ellipse(head, fill="#e53935", outline="#7a1512", width=max(2, int(n * 0.05)))
            draw.ellipse((n * 0.52, n * 0.24, n * 0.66, n * 0.38), fill="#ff8a80")
            GraphDoorPage._pin_sprites[size] = img.resize((size, size), Image.LANCZOS)
        return GraphDoorPage._pin_sprites[size]

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

    def _card_image(self, tile, show_text):
        """One supertile baked into a single image: picture, border, name and door dots.

        Tk repaints the whole canvas on every pan and drag step, and hundreds of small items on top of
        the pictures made that slow. One opaque image per room keeps a frame cheap.
        """
        z = self.zoom
        w, h = self._size(tile)
        pw, ph = max(8, int(round(w * z))), max(6, int(round(h * z)))
        colour = DUNGEON_COLOURS.get(tile_dungeon(tile), UNKNOWN_DUNGEON_COLOUR)
        hidden = self._is_hidden_dark(tile)
        compact = tile in self.compact
        title = ("Dark room" if hidden else tile_title(tile)) if show_text else None
        dots = self._door_dots(tile)
        self._dots_by_tile[tile] = dots
        key = (
            tile,
            pw,
            ph,
            colour,
            hidden,
            compact,
            title,
            tile in self.pinned_eg_tiles,
            tile in self.fixed,
            tuple(d[1:] for d in dots),
        )
        photo = self._card_cache.get(key)
        if photo is not None:
            return photo
        if len(self._card_cache) > 500:
            self._card_cache.clear()

        if compact:
            img = Image.new("RGB", (pw, ph), lighten(colour, 0.7))
        elif hidden:
            img = Image.new("RGB", (pw, ph), "#000000")
        else:
            img = self._thumbnail(tile, pw).copy()
        draw = ImageDraw.Draw(img)
        border = max(2, int(round(2 * z)))
        if tile in self.pinned_eg_tiles:
            draw.rectangle((0, 0, pw - 1, ph - 1), outline="#18c418", width=border + max(2, int(round(3 * z))))
        draw.rectangle((0, 0, pw - 1, ph - 1), outline=colour, width=border)

        if hidden and not compact:
            draw.text((pw / 2, ph / 2), "?", fill="#555555", font=self._font(40 * z), anchor="mm")
        if title:
            font = self._font(11 * z)
            room = pw - 2 * border - 4
            while len(title) > 3 and draw.textlength(title, font=font) > room:
                title = title[:-2].rstrip() + "…"
            if compact:
                draw.text((pw / 2, ph / 2), title, fill="#111111", font=font, anchor="mm")
            else:
                # The name is a tag in the top left corner; doors are drawn after it so it never hides one
                left, top, right, bottom = draw.textbbox((border + 2, border), title, font=font)
                draw.rectangle((0, 0, right + 3, bottom + 2), fill=colour)
                draw.text((border + 2, border), title, fill="#ffffff", font=font)
        if tile in self.fixed:
            pin = self._pin_sprite(max(11, int(round(20 * z))))
            img.paste(pin, (pw - border - pin.width - 1, border + 1), pin)

        for door, ox, oy, radius, fill, outline in dots:
            size = max(5, int(round(radius * 2 * z)) | 1)
            sprite = self._dot_sprite(fill, size, outline)
            cx, cy = (ox + w / 2) * z, (oy + h / 2) * z
            img.paste(sprite, (int(round(cx - size / 2)), int(round(cy - size / 2))), sprite)

        photo = ImageTk.PhotoImage(img)
        self._card_cache[key] = photo
        return photo

    def _sprite(self, icon, scale):
        key = (icon, scale)
        if key not in self._sprite_cache:
            if icon not in doors_sprite_data.all_icons:
                return None
            if not hasattr(GraphDoorPage, "_sheet"):
                GraphDoorPage._sheet = Image.open(ITEM_SHEET_PATH)
            sprite_y, sprite_x = doors_sprite_data.all_icons[icon]
            img = GraphDoorPage._sheet.crop((sprite_x * 16, sprite_y * 16, sprite_x * 16 + 16, sprite_y * 16 + 16))
            if scale != 1:
                img = img.resize((16 * scale, 16 * scale), Image.NEAREST)
            self._sprite_cache[key] = ImageTk.PhotoImage(ImageOps.expand(img, 1, "#fff"))
        return self._sprite_cache[key]

    def _track(self, item, kind, payload):
        self._items[item] = (kind, payload)
        return item

    def _render(self):
        if self._needs_fit and self.pos:
            # fit_view renders once the zoom is known
            self.fit_view()
            return

        c = self.canvas
        c.delete("all")
        self._drawn_zoom = self.zoom
        self._dots_by_tile = {}
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
                self._linked_doors.add(a)
                self._linked_doors.add(b)
        self._items = {}
        self._door_items = {}
        self._images = []
        z = self.zoom
        font_size = max(6, int(round(8 * z)))
        show_text = z >= 0.45

        if self.group_by_dungeon.get():
            self._draw_hulls(font_size)

        for tile in self.tiles:
            self._draw_card(tile, font_size, show_text)

        self._draw_edges()
        self._draw_doors()
        self._draw_annotations(font_size, show_text)
        self._draw_player()

        if not self.tiles:
            c.create_text(0, 0, text="Double-click to add a supertile", fill="#888", font=("TkDefaultFont", 12))
        self._apply_camera()

    def _is_linked(self, door):
        if door in self._lobby_door_names():
            return True
        for link in self.door_links:
            if link["door"] == door or link["linked_door"] == door:
                return True
        return False

    def _draw_hulls(self, font_size):
        by_dungeon = defaultdict(list)
        for tile in self.tiles:
            by_dungeon[tile_dungeon(tile)].append(tile)
        pad = 16
        for dungeon, members in by_dungeon.items():
            colour = DUNGEON_COLOURS.get(dungeon, UNKNOWN_DUNGEON_COLOUR)
            points = []
            for tile in members:
                x, y = self.pos[tile]
                w, h = self._size(tile)
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        points.append((x + sx * (w / 2 + pad), y + sy * (h / 2 + pad)))
            hull = convex_hull(points)
            flat = [coord for p in hull for coord in self._w2c(*p)]
            self.canvas.create_polygon(flat, fill=lighten(colour, 0.82), outline=lighten(colour, 0.35), width=2)
            top_point = min(hull, key=lambda p: p[1])
            tx, ty = self._w2c(top_point[0], top_point[1])
            self.canvas.create_text(
                tx,
                ty - 2,
                text=(dungeon or "Unknown").replace("_", " "),
                anchor="s",
                fill=colour,
                font=("TkDefaultFont", font_size + 1, "bold"),
            )

    def _draw_card(self, tile, font_size, show_text):
        c = self.canvas
        x, y = self.pos[tile]
        w, h = self._size(tile)
        left, top = self._w2c(x - w / 2, y - h / 2)
        tag = f"tile_{tile[0]}_{tile[1]}"
        photo = self._card_image(tile, show_text)
        self._images.append(photo)
        item = c.create_image(round(left), round(top), image=photo, anchor=NW, tags=[tag, "card"])
        self._track(item, "card", tile)
        if self.player is not None and self.player[0] == tile:
            right, bottom = self._w2c(x + w / 2, y + h / 2)
            c.create_rectangle(
                left - 3, top - 3, right + 3, bottom + 3, outline=PLAYER, width=3, tags=["player", tag], state="disabled"
            )

    def _edge_points(self, a, b):
        ax, ay = self._w2c(*self._port(a))
        bx, by = self._w2c(*self._port(b))
        dist = math.hypot(bx - ax, by - ay)
        reach = min(60 * self.zoom, dist / 2.2)
        da = DIRECTIONS.get(door_direction(a))
        db = DIRECTIONS.get(door_direction(b))
        if door_tile(a) == door_tile(b):
            reach = max(reach, 30 * self.zoom)
        points = [ax, ay]
        if da and not self._is_hidden_dark(door_tile(a)):
            points += [ax + da[0] * reach, ay + da[1] * reach]
        if db and not self._is_hidden_dark(door_tile(b)):
            points += [bx + db[0] * reach, by + db[1] * reach]
        points += [bx, by]
        return points

    def _draw_edges(self):
        c = self.canvas
        z = self.zoom
        colours = link_colours(len(self.door_links))
        self._edge_fill = {}
        width = max(1.5, 3 * z)
        for a, b, kind, n in self._edges():
            if n in self.joined:
                # The two rooms are stacked on this doorway: there is no line to draw
                continue
            points = self._edge_points(a, b)
            if kind == "interior":
                item = c.create_line(
                    *points, smooth=True, fill="#222", width=max(1, width * 0.5), dash=(3, 3), tags=["edge"]
                )
                self._track(item, "edge", (a, b, n))
                continue
            one_way = self._decoupled() or (
                door_direction(a) not in DIRECTIONS and "Stairs" not in a and "Ladder" not in a
            )
            colour = DROP_COLOUR if kind == "drop" else colours[n]
            # You fall from the pit (facing down) to the drop entrance (facing up), whichever was stored first
            backwards = not self._decoupled() and door_direction(a) == "Up" and door_direction(b) == "Dn"
            item = c.create_line(
                *points,
                smooth=True,
                fill=colour,
                width=width,
                activefill=PLAYER,
                activewidth=width + 2,
                arrow=(FIRST if backwards else LAST) if one_way else None,
                arrowshape=(12 * z + 4, 15 * z + 5, 5 * z + 2),
                tags=["edge"],
            )
            self._track(item, "edge", (a, b, n))
            self._edge_fill[item] = colour
        self._focus = None

    def _set_focus(self, tile):
        """Fade every link that does not touch the room under the mouse."""
        if tile == self._focus:
            return
        self._focus = tile
        c = self.canvas
        width = max(1.5, 3 * self.zoom)
        for item, colour in self._edge_fill.items():
            a, b, n = self._items[item][1]
            touches = tile is None or door_tile(a) == tile or door_tile(b) == tile
            c.itemconfigure(item, fill=colour if touches else EDGE_FADED, width=width + 1 if touches and tile else width)
            if touches and tile is not None:
                c.tag_raise(item)
        c.tag_raise("door")
        c.tag_raise("icon")
        c.tag_raise("player")

    def _draw_doors(self):
        """Doorways shared by two stacked rooms: one opening across the wall instead of two dots and a line."""
        c = self.canvas
        z = self.zoom
        long_side, short_side = max(4, 11 * z), max(2.5, 5 * z)
        for n in sorted(self.joined):
            a, b = self.door_links[n]["door"], self.door_links[n]["linked_door"]
            ax, ay = self._w2c(*self._port(a))
            bx, by = self._w2c(*self._port(b))
            x, y = (ax + bx) / 2, (ay + by) / 2
            vertical = DIRECTIONS[door_direction(a)][0] == 0
            hw, hh = (long_side, short_side) if vertical else (short_side, long_side)
            ta = door_tile(a)
            item = c.create_rectangle(
                x - hw,
                y - hh,
                x + hw,
                y + hh,
                fill="#fffbe0",
                outline="#111",
                width=max(1, 2 * z),
                activefill=PLAYER,
                tags=["door", "seam", f"tile_{ta[0]}_{ta[1]}"],
            )
            self._track(item, "edge", (a, b, n))
        self._draw_door_marks()

    def _draw_door_marks(self):
        """The only doors that are canvas items: the one being linked from and the one under the mouse."""
        c = self.canvas
        c.delete("mark")
        for door, colour in ((self.selected_door, DOOR_SELECTED), (self._hot_door, PLAYER)):
            if door is None or door_tile(door) not in self.pos or door not in door_coordinates_key:
                continue
            x, y = self._w2c(*self._port(door))
            r = max(3.5, (DOOR_RADIUS + 1) * self.zoom)
            c.create_oval(
                x - r, y - r, x + r, y + r, fill=colour, outline="#111", width=2, tags=["mark"], state="disabled"
            )

    def _door_at(self, event):
        """The door dot under the mouse, found by geometry since dots are part of the card images."""
        wx, wy = self._event_world(event)
        best = None
        for tile, dots in self._dots_by_tile.items():
            if tile not in self.pos:
                continue
            x, y = self.pos[tile]
            w, h = self._size(tile)
            if abs(wx - x) > w / 2 + 10 or abs(wy - y) > h / 2 + 10:
                continue
            for door, ox, oy, radius, fill, outline in dots:
                distance = math.hypot(wx - x - ox, wy - y - oy)
                if distance <= max(radius, 6 / self._drawn_zoom) + 1 and (best is None or distance < best[0]):
                    best = (distance, door)
        return best[1] if best else None

    def _draw_annotations(self, font_size, show_text):
        c = self.canvas
        z = self.zoom
        scale = 2 if z >= 1.3 else 1
        lobby_doors = {x["door"]: x["lobby"] for x in self.lobby_doors}
        for door, icon in self.special_doors.items():
            tile = door_tile(door)
            if tile not in self.pos or door not in door_coordinates_key:
                continue
            x, y = self._w2c(*self._port(door))
            tag = f"tile_{tile[0]}_{tile[1]}"
            if door in lobby_doors:
                self._draw_entrance(door, lobby_doors[door], x, y, tag, font_size, show_text, scale)
                continue
            sprite = self._sprite(icon, scale)
            if sprite is None:
                continue
            self._images.append(sprite)
            item = c.create_image(x, y, image=sprite, tags=["icon", tag])
            self._track(item, "icon", door)

    def _draw_entrance(self, door, lobby, x, y, tag, font_size, show_text, scale):
        """Lobbies are drawn as entry nodes hanging off the door they lead to."""
        c = self.canvas
        z = self.zoom
        direction = DIRECTIONS.get(door_direction(door)) or (0, 1)
        if door in ENTRANCE_ONLY_DOORS or "Drop" in door:
            direction = (0, -1)
        if self._is_hidden_dark(door_tile(door)):
            direction = (0, 1)
        ex, ey = x + direction[0] * 30 * z, y + direction[1] * 30 * z
        c.create_line(x, y, ex, ey, fill="#111", width=max(1.5, 2.5 * z), dash=(4, 2), tags=["icon", tag], state="disabled")
        if "Drop" in lobby or "Drop" in door:
            icon = "Drop"
        else:
            icon = lobby
        sprite = self._sprite(icon, scale)
        half = 9 * scale
        box = c.create_rectangle(
            ex - half - 2, ey - half - 2, ex + half + 2, ey + half + 2, fill="white", outline="#111", width=2, tags=["icon", tag]
        )
        self._track(box, "icon", door)
        if sprite is not None:
            self._images.append(sprite)
            item = c.create_image(ex, ey, image=sprite, tags=["icon", tag])
            self._track(item, "icon", door)
        if show_text:
            label = c.create_text(
                ex,
                ey + (half + 3) * (1 if direction[1] >= 0 else -1),
                text=lobby.replace("_", " "),
                anchor="n" if direction[1] >= 0 else "s",
                fill="#111",
                font=("TkDefaultFont", font_size, "bold"),
                tags=["icon", tag],
            )
            self._track(label, "icon", door)

    def _draw_player(self):
        c = self.canvas
        if self.player is None:
            return
        tile, px, py = self.player
        if tile not in self.pos or tile in self.compact:
            return
        x, y = self.pos[tile]
        cx, cy = self._w2c(x + (px / 512 - 0.5) * THUMB, y + (py / 512 - 0.5) * THUMB)
        s = max(4, 7 * self.zoom)
        width = max(2, 3 * self.zoom)
        tags = ["player", f"tile_{tile[0]}_{tile[1]}"]
        c.create_line(cx - s, cy - s, cx + s, cy + s, fill=PLAYER, width=width, tags=tags, state="disabled")
        c.create_line(cx + s, cy - s, cx - s, cy + s, fill=PLAYER, width=width, tags=tags, state="disabled")

    # ------------------------------------------------------------- interactions

    def _hit(self, event):
        """What is under the mouse, as (kind, payload)."""
        current = self.canvas.find_withtag("current")
        kind, payload = self._items.get(current[0], (None, None)) if current else (None, None)
        if kind != "icon":
            # Doors are small targets: one under a link line or a doorway bar still wins the click
            door = self._door_at(event)
            if door is not None:
                return "door", door
        return kind, payload

    def _event_world(self, event):
        zoom = self._drawn_zoom
        return self.canvas.canvasx(event.x) / zoom, self.canvas.canvasy(event.y) / zoom

    def _on_configure(self, event):
        # A resized window shows more or less of the world around the same camera; it never zooms.
        # The one exception is a fit that had to guess the window size because this tab was never shown.
        if self._fit_provisional and self.pos and self.canvas.winfo_viewable():
            self.after_idle(self.fit_view)
        else:
            self._apply_camera()

    def _room_at(self, event):
        """The room whose card is under the mouse, whatever is drawn on top of it."""
        wx, wy = self._event_world(event)
        for tile, (x, y) in self.pos.items():
            w, h = self._size(tile)
            if abs(wx - x) <= w / 2 and abs(wy - y) <= h / 2:
                return tile
        return None

    def _on_press(self, event):
        self.canvas.focus_set()
        kind, payload = self._hit(event)
        self._press = {"kind": kind, "payload": payload, "x": event.x, "y": event.y, "moved": False}
        if kind == "edge" and (
            payload[2] in self.joined or door_tile(payload[0]) == door_tile(payload[1])
        ):
            # Lines and doorways that live inside a card or a stack drag it like the card itself
            self._press["kind"] = "card"
            self._press["payload"] = door_tile(payload[0])
        elif kind == "edge" and self._room_at(event) is not None:
            # A link passing over a room does not get in the way of dragging that room
            self._press["kind"] = "card"
            self._press["payload"] = self._room_at(event)
        elif kind is None or kind == "edge":
            self._press["kind"] = "pan"
        elif kind == "icon":
            tile = door_tile(payload)
            self._press["kind"] = "card"
            self._press["payload"] = tile

    def _on_drag(self, event):
        press = self._press
        if not press:
            return
        dx, dy = event.x - press["x"], event.y - press["y"]
        if not press["moved"] and abs(dx) + abs(dy) < 4:
            return
        press["moved"] = True
        if press["kind"] == "pan":
            self._fit_provisional = False
            self.camera[0] -= dx / self._drawn_zoom
            self.camera[1] -= dy / self._drawn_zoom
            press["x"], press["y"] = event.x, event.y
            self._apply_camera()
            return
        tile = press["payload"] if press["kind"] == "card" else door_tile(press["payload"])
        if tile not in self.pos:
            return
        press["x"], press["y"] = event.x, event.y
        press["dragged_tile"] = tile
        # A stack moves as one piece
        self._held = set(self._stack_of(tile))
        for member in self._held:
            self.pos[member][0] += dx / self.zoom
            self.pos[member][1] += dy / self.zoom
            self.canvas.move(f"tile_{member[0]}_{member[1]}", dx, dy)
        self._redraw_edges()
        if self.simulate.get():
            self._kick()

    def _on_release(self, event):
        press, self._press = self._press, None
        self._held = set()
        if not press:
            return
        if press["moved"]:
            tile = press.get("dragged_tile")
            if tile is not None:
                # A dropped block stays exactly where it was put and nothing else moves. It is not
                # pinned though: a running simulation or a later layout is free to move it.
                self.unsettled.difference_update(self._stack_of(tile))
            return
        if press["kind"] == "door":
            self._door_clicked(press["payload"])
        elif press["kind"] == "pan" and self.selected_door:
            self._cancel_selection()

    def _cancel_selection(self):
        self.selected_door = None
        self.canvas.delete("rubber")
        self._render()

    def _door_clicked(self, door):
        if door in INTERIOR_DOORS or door in self._lobby_door_names():
            return
        if self.selected_door is None:
            if self.has_target(door):
                return
            self.selected_door = door
            self._draw_door_marks()
            return
        if door == self.selected_door:
            self._cancel_selection()
            return
        if self.has_target(door) and not self._decoupled():
            return
        source, self.selected_door = self.selected_door, None
        self.canvas.delete("rubber")
        self.door_links.append({"door": source, "linked_door": door})
        self.redraw_canvas()

    def _highlight_door(self, door):
        if door != self._hot_door:
            self._hot_door = door
            self._draw_door_marks()

    def _on_motion(self, event):
        kind, payload = self._hit(event)
        self._highlight_door(payload if kind == "door" else None)
        if not self._press:
            if kind == "card":
                self._set_focus(payload)
            elif kind == "door":
                self._set_focus(door_tile(payload))
            elif kind != "edge":
                self._set_focus(None)
        if kind == "door":
            links = self._link_map()
            target = links.get(payload)
            text = payload + (f"  →  {target}" if target else "")
            if payload in self.special_doors:
                text += f"   [{self.special_doors[payload]}]"
        elif kind == "edge":
            text = f"{payload[0]}  ↔  {payload[1]}"
            if payload[2] in self.joined:
                text += "   (stacked — middle click to split)"
            elif payload[2] is not None and self._join_offset(payload[0], payload[1]) is not None:
                text += "   (middle click to stack)"
        elif kind == "card":
            text = f"{', '.join(tile_regions(payload)[:4]) or tile_title(payload)}   (EG {payload[0]},{payload[1]})"
        elif kind == "icon":
            text = f"{payload}: {self.special_doors.get(payload, '')}"
        else:
            text = ""
        if self.selected_door:
            text = f"Linking {self.selected_door} — click another door (Esc to cancel)   {text}"
            self.canvas.delete("rubber")
            sx, sy = self._w2c(*self._port(self.selected_door))
            self.canvas.create_line(
                sx,
                sy,
                self.canvas.canvasx(event.x),
                self.canvas.canvasy(event.y),
                fill=DOOR_SELECTED,
                width=2,
                dash=(4, 3),
                tags=["rubber"],
                state="disabled",
            )
            self.canvas.tag_raise("mark")
        if text != self.status.get():
            self.status.set(text)

    def _on_wheel(self, event):
        self._zoom_at(event.x, event.y, 1.15 if event.delta > 0 else 1 / 1.15)

    def _zoom_at(self, sx, sy, factor):
        new_zoom = max(0.15, min(2.5, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        vw, vh = self._viewport()
        # Keep the world point under the mouse where it is on screen
        wx = self.camera[0] + (sx - vw / 2) / self.zoom
        wy = self.camera[1] + (sy - vh / 2) / self.zoom
        self.zoom = new_zoom
        self.camera = [wx - (sx - vw / 2) / new_zoom, wy - (sy - vh / 2) / new_zoom]
        self._fit_provisional = False
        if self._zoom_job is None:
            self._zoom_job = self.after_idle(self._apply_zoom)

    def _apply_zoom(self):
        """Redraw once for however many wheel ticks arrived since the last frame."""
        self._zoom_job = None
        self._render()

    def _on_double_click(self, event):
        kind, payload = self._hit(event)
        self._press = None
        if kind == "door":
            if self.has_target(payload) or payload in INTERIOR_DOORS:
                return
            self.selected_door = None
            ox, oy = self._port(payload)
            direction = DIRECTIONS.get(door_direction(payload)) or (1, 0)
            reach = THUMB / 2 + LINK_GAP
            self._add_tile_from_picker(ox + direction[0] * reach, oy + direction[1] * reach)
        elif kind is None:
            self._add_tile_from_picker(*self._event_world(event))

    def _add_tile_from_picker(self, wx, wy):
        """Ask the EG map window for a supertile and drop it at the given world position."""
        top = self.top
        notebook = top.notebook
        notebook.setvar("selected_eg_tile", BooleanVar(value=False))  # type: ignore
        for page in top.eg_tile_window.pages.values():
            page.content.deactivate_tiles(
                page.content,
                top.eg_tile_multiuse,
                top.disabled_eg_tiles,
                temp_disabled_eg_tiles=list(self.tiles),
            )
        top.eg_tile_window.deiconify()
        top.eg_tile_window.focus_set()
        top.eg_tile_window.grab_set()
        notebook.wait_variable("selected_eg_tile")
        if not hasattr(notebook, "selected_eg_tile"):
            return
        tile = notebook.selected_eg_tile
        delattr(notebook, "selected_eg_tile")
        if tile in self.tiles:
            return
        # Picked by hand, so the player knows what it is: never obscure it
        self._ensure_tile(tile, has_been_lit=True)
        self.pos[tile] = [wx, wy]
        self.redraw_canvas()

    def _on_right_click(self, event):
        kind, payload = self._hit(event)
        if kind == "door":
            self._annotate_door(payload, event)
        elif kind == "edge":
            a, b, n = payload
            if n is None:
                return
            del self.door_links[n]
            self.redraw_canvas()
        elif kind == "icon":
            self._remove_annotation(payload)
        elif kind == "card":
            tile = payload
            menu = Menu(self, tearoff=0)
            if tile in self.fixed:
                menu.add_command(label="Unpin", command=lambda: self._set_pinned(tile, False))
            else:
                menu.add_command(label="Pin in place", command=lambda: self._set_pinned(tile, True))
            if tile not in mandatory_tiles[self.tab_world]:
                menu.add_separator()
                menu.add_command(label="Remove supertile…", command=lambda: self._remove_tile(tile))
            menu.tk_popup(event.x_root, event.y_root)
        elif kind is None:
            menu = Menu(self, tearoff=0)
            menu.add_command(label="Fit to window", command=self.fit_view)
            menu.add_command(label="Re-layout", command=self.relayout)
            menu.add_command(label="Unpin all", command=self._unfix_all)
            wx, wy = self._event_world(event)
            menu.add_command(label="Add supertile here…", command=lambda: self._add_tile_from_picker(wx, wy))
            menu.tk_popup(event.x_root, event.y_root)

    def _unfix_all(self):
        self.fixed.clear()
        self._render()

    def _on_ctrl_click(self, event):
        self._press = None
        kind, payload = self._hit(event)
        # Anywhere on the room counts, including on one of its doors
        if kind in ("door", "icon"):
            kind, payload = "card", door_tile(payload)
        elif kind == "edge" and (door_tile(payload[0]) == door_tile(payload[1]) or payload[2] in self.joined):
            kind, payload = "card", door_tile(payload[0])
        if kind == "card" and payload in self.pos:
            self._set_pinned(payload, payload not in self.fixed)

    def _set_pinned(self, tile, pinned):
        """Pin or release a room, together with everything stacked on it."""
        members = self._stack_of(tile)
        if pinned:
            self.fixed.update(members)
        else:
            self.fixed.difference_update(members)
        self._render()

    def _annotate_door(self, door, event):
        selected = doors_sprite_data.show_sprites(self, self.top, event, self.tab_world)
        if selected is None:
            return
        if selected in doors_sprite_data.all_dungeon_lobbies or selected == "Drop":
            self.add_lobby_door(door, selected)
            if "Drop" in door:
                self.special_doors[door] = "Drop"
        else:
            self.special_doors[door] = selected
        self.redraw_canvas()

    def _remove_annotation(self, door):
        if door == "Sanctuary Mirror Route":
            return
        self.lobby_doors = [x for x in self.lobby_doors if x["door"] != door]
        self.special_doors.pop(door, None)
        self.redraw_canvas()

    def _remove_tile(self, tile):
        if tile in mandatory_tiles[self.tab_world] or tile not in self.tiles:
            return
        # Takes the room's links, lobbies and annotations with it, so never without asking
        if not messagebox.askyesno(
            "Remove supertile",
            f"Remove {tile_title(tile)} and every link, lobby and annotation on it?",
            icon="warning",
            default="no",
            parent=self,
        ):
            return
        doors = set(tile_door_names(tile))
        doors.discard("Sanctuary Mirror Route")
        self.door_links = [x for x in self.door_links if x["door"] not in doors and x["linked_door"] not in doors]
        self.lobby_doors = [x for x in self.lobby_doors if x["door"] not in doors]
        for door in doors:
            self.special_doors.pop(door, None)
        del self.tiles[tile]
        self.pos.pop(tile, None)
        self.pinned_eg_tiles.discard(tile)
        self.fixed.discard(tile)
        if self.player and self.player[0] == tile:
            self.player = None
        self.redraw_canvas()

    def _on_middle_click(self, event):
        kind, payload = self._hit(event)
        if kind == "edge":
            self._toggle_stack(payload)
            return
        if kind != "card":
            return
        tile = payload
        if tile in self.pinned_eg_tiles:
            self.pinned_eg_tiles.discard(tile)
        else:
            self.pinned_eg_tiles.add(tile)
        self.redraw_canvas()

    def _toggle_stack(self, payload):
        """Split two rooms stacked on a doorway, or stack the rooms at either end of a link."""
        a, b, n = payload
        if n is None:
            return
        link = self.door_links[n]
        if n in self.joined:
            link["stack"] = False
            self.redraw_canvas()
            return
        if self._join_offset(a, b) is None:
            self.status.set("These two doors cannot be stacked: only north/south and east/west doorways fit together")
            return
        link["stack"] = True
        self._sync_model()
        if n not in self.joined:
            link.pop("stack")
            self._sync_model()
            self.status.set("Cannot stack here: the rooms would land on top of rooms already in the stack")
            return
        self.redraw_canvas()

    # --------------------------------------------------------- save / load / api

    def load_yaml(self, yaml_data):
        self.door_links = []
        for x in yaml_data.get("door_links", []):
            link = {"door": x["door"], "linked_door": x["linked_door"]}
            if x.get("stack") is not None:
                link["stack"] = bool(x["stack"])
            self.door_links.append(link)
        self._stack_rank = {}
        for rank, n in enumerate(yaml_data.get("stacked_links") or []):
            if 0 <= n < len(self.door_links):
                self._stack_rank[(self.door_links[n]["door"], self.door_links[n]["linked_door"])] = rank
        self.lobby_doors = [{"door": x["door"], "lobby": x["lobby"]} for x in yaml_data.get("lobby_doors", [])]
        self.special_doors = dict(yaml_data.get("special_doors", {}))
        self.tiles = {}
        self.pos = {}
        self.fixed = set()
        self.unsettled = set()
        self.player = None
        self.selected_door = None
        self._layout_signature = None
        self._damping = {}
        for key, lit in yaml_data.get("tiles", {}).items():
            tile = tuple(int(x) for x in str(key).split("__"))
            self._ensure_tile(tile, has_been_lit=bool(lit))
        for key, value in (yaml_data.get("graph_layout") or {}).items():
            tile = tuple(int(x) for x in str(key).split("__"))
            if tile in self.tiles:
                self.pos[tile] = [float(value[0]), float(value[1])]
                if len(value) > 2 and value[2]:
                    self.fixed.add(tile)
        self._needs_fit = True
        if yaml_data.get("satellite_pull"):
            self.leaf_pull = max(1.0, min(4.0, float(yaml_data["satellite_pull"])))
            self.leaf_pull_var.set(self.leaf_pull)
        if yaml_data.get("spacing"):
            self.spacing = max(10.0, min(200.0, float(yaml_data["spacing"])))
            self.spacing_var.set(self.spacing)
        saved_camera = yaml_data.get("camera")
        if saved_camera and self.pos:
            # Come back to the same view the map was saved with
            self.camera = [float(saved_camera[0]), float(saved_camera[1])]
            self.zoom = max(0.15, min(2.5, float(saved_camera[2])))
            self._needs_fit = False
        self._sync_model()
        if self.pos and "stacked_links" not in yaml_data:
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
        if self.pos and all(t in self.pos for t in self.tiles):
            # A saved arrangement is shown exactly as it was left
            self._layout_signature = self._signature()
        else:
            self._optimise_stack_order()
        self._layout(full=not self.pos)
        self._render()

    def return_connections(self):
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
            "special_doors": dict(self.special_doors),
            "graph_layout": {
                f"{t[0]}__{t[1]}": [round(p[0], 1), round(p[1], 1), t in self.fixed] for t, p in self.pos.items()
            },
            "camera": [round(self.camera[0], 1), round(self.camera[1], 1), round(self.zoom, 4)],
            "spacing": round(self.spacing, 1),
            "satellite_pull": self.leaf_pull,
        }

    def update_size(self, size):
        self.cwidth, self.cheight = size
        self.canvas.config(width=self.cwidth + 50, height=self.cheight + 50 - TOOLBAR_HEIGHT)
        self.redraw_canvas()

    def auto_add_tile(self, tile, was_lit=False):
        if tile in self.tiles:
            return
        self._ensure_tile(tile, has_been_lit=was_lit)
        self.redraw_canvas()

    def auto_draw_player(self, x, y, current_tile):
        if current_tile not in self.tiles:
            return
        changed_tile = self.player is None or self.player[0] != current_tile
        self.player = (current_tile, x, y)
        self.canvas.delete("player")
        if changed_tile:
            self._render()
            if self.follow_player.get():
                self._follow_player()
        else:
            self._draw_player()

    def clear_player(self):
        if self.player is not None:
            self.player = None
            self.canvas.delete("player")

    def _follow_player(self):
        """Optional: centre the camera on the player's room when it is not fully on screen."""
        tile = self.player[0]
        if tile not in self.pos:
            return
        x, y = self.pos[tile]
        vw, vh = self._viewport()
        half_w = vw / 2 / self.zoom - THUMB / 2 - 20
        half_h = vh / 2 / self.zoom - THUMB / 2 - 20
        if abs(x - self.camera[0]) <= half_w and abs(y - self.camera[1]) <= half_h:
            return
        self.camera = [x, y]
        self._apply_camera()

    def auto_add_door_link(self, door, linked_door):
        for d in [door, linked_door] if not self._decoupled() else [door]:
            if d is None or self.has_target(d) or d in INTERIOR_DOORS or d in self._lobby_door_names():
                return
        if door is None or linked_door is None:
            return
        directions = {door_direction(door), door_direction(linked_door)}
        if directions not in VALID_AUTO_LINKS:
            return
        self.door_links.append({"door": door, "linked_door": linked_door})
        self.redraw_canvas()

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
            return
        lobby = None
        for possible_lobby in dungeon_lobbies[self.tab_world]:
            if possible_lobby not in current_lobbies:
                lobby = possible_lobby
                break
        if lobby is None:
            return
        self.add_lobby_door(door, lobby)
        self.redraw_canvas()

    def auto_add_lamp_icon(self, door, icon="Lamp"):
        if door is None or door in INTERIOR_DOORS:
            return
        self.special_doors[door] = icon
        self.redraw_canvas()
