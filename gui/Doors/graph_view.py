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
from collections import defaultdict, deque
from pathlib import Path
from tkinter import BOTH, LAST, LEFT, NW, RIGHT, X, BooleanVar, Canvas, Menu, StringVar, ttk

from PIL import Image, ImageColor, ImageOps, ImageTk

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
LINK_GAP = 46  # preferred port-to-port distance of a link
CARD_MARGIN = 34  # minimum space kept between cards
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
        self._thumb_cache = {}
        self._sprite_cache = {}
        self._items = {}  # canvas item id -> (kind, payload)
        self._door_items = {}
        self._images = []  # keep PhotoImage references alive
        self._press = None
        self._needs_fit = True
        self._auto_view = True

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
        self.status = StringVar(value="")
        ttk.Label(toolbar, textvariable=self.status, anchor="w").pack(side=LEFT, padx=8, fill=X, expand=True)
        self.summary = StringVar(value="")
        ttk.Label(toolbar, textvariable=self.summary, anchor="e").pack(side=RIGHT, padx=8)

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
        c.bind("<Control-Button-3>", self._on_ctrl_right_click)
        c.bind("<Button-2>", self._on_middle_click)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        c.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))
        c.bind("<Motion>", self._on_motion)
        c.bind("<Escape>", lambda e: self._cancel_selection())
        c.bind("<Configure>", self._on_configure)

    # -------------------------------------------------------------------- model

    def init_page(self):
        self.tiles = {}
        self.door_links = []
        self.lobby_doors = []
        self.special_doors = {}
        self.pinned_eg_tiles = set()
        self.sanc_dungeon = False

        self.pos = {}  # tile -> [x, y] centre of the card, world units
        self.fixed = set()  # tiles the user dragged; the layout never moves them
        self.unsettled = set()  # freshly added tiles, free to move until they are linked
        self.compact = set()
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
        return THUMB, THUMB + TITLE_H

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
        return (fx - 0.5) * THUMB, -h / 2 + TITLE_H + fy * THUMB

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
        return edges

    def _door_visible(self, door):
        if self.show_all_doors or not self.lobby_doors:
            return True
        return door in self.doors_available

    # ------------------------------------------------------------------- layout

    def _layout(self, full=False):
        tiles = list(self.tiles)
        if not tiles:
            return
        for tile in list(self.pos):
            if tile not in self.tiles:
                del self.pos[tile]
        self.fixed &= set(tiles)
        self.unsettled &= set(tiles)

        if full:
            for tile in tiles:
                if tile not in self.fixed:
                    self.pos.pop(tile, None)

        new_tiles = [t for t in tiles if t not in self.pos]
        if not new_tiles and not full and not self.unsettled:
            return

        # Temporary positions so port offsets can be computed for unplaced tiles
        pending = set(new_tiles)
        edges = []
        for a, b, kind, _ in self._all_layout_edges():
            edges.append((a, b))

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
            self.pos[new] = [
                ax + aox + direction[0] * LINK_GAP - nox,
                ay + aoy + direction[1] * LINK_GAP - noy,
            ]

        def place_loose(tile):
            placed = [self.pos[t] for t in self.pos]
            w, h = self._size(tile)
            if not placed:
                self.pos[tile] = [0.0, 0.0]
            elif self.player and self.player[0] in self.pos and self.player[0] != tile:
                px, py = self.pos[self.player[0]]
                self.pos[tile] = [px + THUMB + CARD_MARGIN * 2, py + 20.0]
            else:
                max_x = max(p[0] for p in placed)
                min_y = min(p[1] for p in placed)
                self.pos[tile] = [max_x + THUMB + CARD_MARGIN * 3, min_y + (len(placed) % 5) * (h + CARD_MARGIN)]

        # Seed with lobbies first so the entrances anchor the picture
        lobby_tiles = [door_tile(x["door"]) for x in self.lobby_doors]
        order = [t for t in lobby_tiles if t in pending] + [t for t in new_tiles if t not in lobby_tiles]
        while pending:
            progressed = True
            while progressed:
                progressed = False
                for a, b in edges:
                    ta, tb = door_tile(a), door_tile(b)
                    if ta in pending and tb in self.pos and tb not in pending:
                        place_from(b, a)
                        pending.discard(ta)
                        progressed = True
                    elif tb in pending and ta in self.pos and ta not in pending:
                        place_from(a, b)
                        pending.discard(tb)
                        progressed = True
            if pending:
                tile = next(t for t in order if t in pending)
                place_loose(tile)
                pending.discard(tile)

        self.unsettled |= set(new_tiles)
        self._relax(iterations=320 if full else 90, old_mobility=1.0 if full else 0.12, edges=edges, swap=full)
        if full:
            # Settle again around the improved arrangement
            self._relax(iterations=120, old_mobility=0.5, edges=edges, swap=True)

        linked = set()
        for a, b in edges:
            linked.add(door_tile(a))
            linked.add(door_tile(b))
        self.unsettled -= linked

    def _all_layout_edges(self):
        return [e for e in self._edges(known=self.tiles) if door_tile(e[0]) != door_tile(e[1])]

    def _relax(self, iterations, old_mobility, edges, swap=False):
        tiles = list(self.tiles)
        index = {t: i for i, t in enumerate(tiles)}
        n = len(tiles)
        xs = [self.pos[t][0] for t in tiles]
        ys = [self.pos[t][1] for t in tiles]
        sizes = [self._size(t) for t in tiles]
        mobility = [0.0 if t in self.fixed else (1.0 if t in self.unsettled else old_mobility) for t in tiles]

        springs = []
        for a, b in edges:
            ia, ib = index[door_tile(a)], index[door_tile(b)]
            aox, aoy = self._port_offset(a)
            box, boy = self._port_offset(b)
            springs.append((ia, aox, aoy, DIRECTIONS.get(door_direction(a)), ib, box, boy, DIRECTIONS.get(door_direction(b))))

        groups = []
        if self.group_by_dungeon.get():
            by_dungeon = defaultdict(list)
            for t in tiles:
                by_dungeon[tile_dungeon(t)].append(index[t])
            groups = [members for members in by_dungeon.values() if len(members) > 1]

        # A wide window has room to spare sideways: use it as routing space between cards
        vw, vh = self._viewport()
        margin_x = CARD_MARGIN * max(1.0, min(1.5, vw / vh))

        def separate(strength):
            moved = False
            for a in range(n):
                wa, ha = sizes[a]
                for b in range(a + 1, n):
                    wb, hb = sizes[b]
                    dx = xs[b] - xs[a]
                    dy = ys[b] - ys[a]
                    ox = (wa + wb) / 2 + margin_x - abs(dx)
                    oy = (ha + hb) / 2 + CARD_MARGIN - abs(dy)
                    if ox <= 0 or oy <= 0:
                        continue
                    ma, mb = mobility[a], mobility[b]
                    if ma + mb == 0:
                        continue
                    share_a, share_b = ma / (ma + mb), mb / (ma + mb)
                    moved = True
                    # Split along the axis the two cards are already most apart on
                    if abs(dx) * (ha + hb) >= abs(dy) * (wa + wb):
                        push = ox * strength * (1 if dx >= 0 else -1)
                        xs[a] -= push * share_a
                        xs[b] += push * share_b
                    else:
                        push = oy * strength * (1 if dy >= 0 else -1)
                        ys[a] -= push * share_a
                        ys[b] += push * share_b
            return moved

        # Aspect of the window: pull harder along the short axis so the map fills the view
        gravity_x = 0.02
        gravity_y = gravity_x * max(1.0, min(6.0, (vw / vh) ** 2.5))
        degree = [0] * n
        for spring in springs:
            degree[spring[0]] += 1
            degree[spring[4]] += 1

        for it in range(iterations):
            cooling = 1 - it / iterations
            temperature = 80 * cooling + 4
            tx = [0.0] * n
            ty = [0.0] * n
            for ia, aox, aoy, da, ib, box, boy, db in springs:
                pax, pay = xs[ia] + aox, ys[ia] + aoy
                pbx, pby = xs[ib] + box, ys[ib] + boy
                # Where the far port should sit relative to the near one
                if da is not None and db is not None:
                    vx, vy = (da[0] - db[0]) / 2 * LINK_GAP, (da[1] - db[1]) / 2 * LINK_GAP
                elif da is not None:
                    vx, vy = da[0] * LINK_GAP, da[1] * LINK_GAP
                elif db is not None:
                    vx, vy = -db[0] * LINK_GAP, -db[1] * LINK_GAP
                else:
                    # Stairs and drops have no heading: keep them a card apart, any direction
                    dx, dy = pbx - pax, pby - pay
                    dist = math.hypot(dx, dy) or 0.01
                    vx, vy = dx / dist * LINK_GAP * 2, dy / dist * LINK_GAP * 2
                tx[ib] += pax + vx - box
                ty[ib] += pay + vy - boy
                tx[ia] += pbx - vx - aox
                ty[ia] += pby - vy - aoy

            cx = sum(xs) / n
            cy = sum(ys) / n
            gx = [cx] * n
            gy = [cy] * n
            for members in groups:
                mx = sum(xs[i] for i in members) / len(members)
                my = sum(ys[i] for i in members) / len(members)
                for i in members:
                    gx[i], gy[i] = mx, my
            group_pull = 0.25 if groups else 0.0

            for i in range(n):
                if mobility[i] == 0:
                    continue
                dx = (cx - xs[i]) * gravity_x + (gx[i] - xs[i]) * group_pull
                dy = (cy - ys[i]) * gravity_y + (gy[i] - ys[i]) * group_pull
                if degree[i]:
                    # Move towards the average of where each link wants this card to be
                    dx += (tx[i] / degree[i] - xs[i]) * 0.45
                    dy += (ty[i] / degree[i] - ys[i]) * 0.45
                dx *= mobility[i]
                dy *= mobility[i]
                step = math.hypot(dx, dy)
                if step > temperature:
                    dx, dy = dx / step * temperature, dy / step * temperature
                xs[i] += dx
                ys[i] += dy
            separate(0.3 + 0.5 * (1 - cooling))

        for _ in range(60):
            if not separate(1.0):
                break

        if swap:
            # Cards end up packed, so trading places is the cheap way out of a bad local arrangement
            def cost(i):
                total = 0.0
                for ia, aox, aoy, da, ib, box, boy, db in incident[i]:
                    dx = xs[ib] + box - xs[ia] - aox
                    dy = ys[ib] + boy - ys[ia] - aoy
                    if da is not None:
                        dx -= da[0] * LINK_GAP
                        dy -= da[1] * LINK_GAP
                    elif db is not None:
                        dx += db[0] * LINK_GAP
                        dy += db[1] * LINK_GAP
                    total += math.hypot(dx, dy)
                return total

            incident = [[] for _ in range(n)]
            for spring in springs:
                incident[spring[0]].append(spring)
                incident[spring[4]].append(spring)
            movable = [i for i in range(n) if mobility[i] > 0 and sizes[i] == (THUMB, THUMB + TITLE_H)]
            for _ in range(6):
                improved = False
                for ai, a in enumerate(movable):
                    for b in movable[ai + 1 :]:
                        before = cost(a) + cost(b)
                        xs[a], xs[b], ys[a], ys[b] = xs[b], xs[a], ys[b], ys[a]
                        if cost(a) + cost(b) < before - 1:
                            improved = True
                        else:
                            xs[a], xs[b], ys[a], ys[b] = xs[b], xs[a], ys[b], ys[a]
                if not improved:
                    break

        for i, t in enumerate(tiles):
            self.pos[t] = [xs[i], ys[i]]

    def relayout(self):
        self._sync_model()
        self._layout(full=True)
        self._needs_fit = True
        self._render()

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

    def _scroll_to(self, left, top):
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
        x0, y0, x1, y1 = self._bounds()
        pad = 70
        vw, vh = self._viewport()
        zoom = min(vw / (x1 - x0 + pad * 2), vh / (y1 - y0 + pad * 2))
        self.zoom = max(0.15, min(1.6, zoom))
        self._needs_fit = False
        self._auto_view = True
        self._fit_job = None
        self._render()
        cx, cy = (x0 + x1) / 2 * self.zoom, (y0 + y1) / 2 * self.zoom
        self._scroll_to(cx - vw / 2, cy - vh / 2)

    def _thumbnail(self, tile, size):
        key = (tile, size)
        if key not in self._thumb_cache:
            x, y = tile
            if self.eg_img is None:
                img = Image.new("RGB", (size, size), "#444")
            else:
                img = self.eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).resize(
                    (size, size), Image.LANCZOS
                )
            self._thumb_cache[key] = ImageTk.PhotoImage(img)
        return self._thumb_cache[key]

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
            vw, vh = self._viewport()
            self._scroll_to(-vw / 2, -vh / 2)
            c.create_text(0, 0, text="Double-click to add a supertile", fill="#888", font=("TkDefaultFont", 12))

        open_doors = sum(1 for d, item in self._door_items.items() if d not in INTERIOR_DOORS and not self._is_linked(d))
        self.summary.set(
            f"{self.dungeon_name.replace('_', ' ')}   {len(self.tiles)} supertiles · "
            f"{len(self.door_links)} links · {open_doors} open doors"
        )

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
        z = self.zoom
        x, y = self.pos[tile]
        w, h = self._size(tile)
        left, top = self._w2c(x - w / 2, y - h / 2)
        right, bottom = self._w2c(x + w / 2, y + h / 2)
        colour = DUNGEON_COLOURS.get(tile_dungeon(tile), UNKNOWN_DUNGEON_COLOUR)
        hidden = self._is_hidden_dark(tile)
        is_player = self.player is not None and self.player[0] == tile
        tag = f"tile_{tile[0]}_{tile[1]}"
        title = "Dark room" if hidden else tile_title(tile)
        max_chars = max(3, int((right - left) / (font_size * 0.72)))
        if len(title) > max_chars:
            title = title[: max_chars - 1] + "…"

        if tile in self.pinned_eg_tiles:
            c.create_rectangle(left - 4, top - 4, right + 4, bottom + 4, fill="#18c418", outline="", tags=[tag, "card"])

        if tile in self.compact:
            item = c.create_rectangle(
                left, top, right, bottom, fill=lighten(colour, 0.7), outline=colour, width=2, tags=[tag, "card"]
            )
            self._track(item, "card", tile)
            if show_text:
                text = c.create_text(
                    (left + right) / 2,
                    (top + bottom) / 2,
                    text=title,
                    fill="#111",
                    font=("TkDefaultFont", font_size),
                    tags=[tag, "card"],
                )
                self._track(text, "card", tile)
        else:
            title_bottom = top + TITLE_H * z
            bar = c.create_rectangle(left, top, right, title_bottom, fill=colour, outline=colour, tags=[tag, "card"])
            self._track(bar, "card", tile)
            if show_text:
                text = c.create_text(
                    left + 4 * z,
                    (top + title_bottom) / 2,
                    text=title,
                    anchor="w",
                    fill="white",
                    font=("TkDefaultFont", font_size, "bold"),
                    tags=[tag, "card"],
                )
                self._track(text, "card", tile)
            size = max(8, int(round(THUMB * z)))
            if hidden:
                body = c.create_rectangle(left, title_bottom, right, bottom, fill="#000", outline="", tags=[tag, "card"])
                c.create_text(
                    (left + right) / 2,
                    (title_bottom + bottom) / 2,
                    text="?",
                    fill="#555",
                    font=("TkDefaultFont", max(8, int(28 * z)), "bold"),
                    tags=[tag, "card"],
                    state="disabled",
                )
            else:
                img = self._thumbnail(tile, size)
                self._images.append(img)
                body = c.create_image(left, title_bottom, image=img, anchor=NW, tags=[tag, "card"])
            self._track(body, "card", tile)
            c.create_rectangle(left, top, right, bottom, outline=colour, width=2, tags=[tag, "card"], state="disabled")

        if tile in self.fixed:
            r = max(2, 3 * z)
            c.create_oval(
                right - 3 * r, top + r, right - r, top + 3 * r, fill="#ffd54a", outline="#333", tags=[tag, "card"],
                state="disabled",
            )
        if is_player:
            c.create_rectangle(
                left - 3, top - 3, right + 3, bottom + 3, outline=PLAYER, width=3, tags=["player"], state="disabled"
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
        width = max(1.5, 3 * z)
        for a, b, kind, n in self._edges():
            points = self._edge_points(a, b)
            if kind == "interior":
                item = c.create_line(
                    *points, smooth=True, fill="#222", width=max(1, width * 0.5), dash=(3, 3), tags=["edge"]
                )
                self._track(item, "edge", (a, b, n))
                continue
            one_way = self._decoupled() or door_direction(a) not in DIRECTIONS and "Stairs" not in a and "Ladder" not in a
            item = c.create_line(
                *points,
                smooth=True,
                fill=colours[n],
                width=width,
                activefill=PLAYER,
                activewidth=width + 2,
                arrow=LAST if one_way else None,
                arrowshape=(12 * z + 4, 15 * z + 5, 5 * z + 2),
                tags=["edge"],
            )
            self._track(item, "edge", (a, b, n))

    def _draw_doors(self):
        c = self.canvas
        z = self.zoom
        lobby_doors = set(self._lobby_door_names())
        radius = max(2.5, 5.5 * z)
        for tile in self.tiles:
            for door in tile_door_names(tile):
                if door in ENTRANCE_ONLY_DOORS or door.startswith("Skull Drop Entrance"):
                    continue
                if not self._door_visible(door):
                    continue
                interior = door in INTERIOR_DOORS
                if interior and tile in self.compact:
                    continue
                x, y = self._w2c(*self._port(door))
                linked = self._is_linked(door) or door in lobby_doors
                r = radius * (0.7 if interior or linked else 1.0)
                if door == self.selected_door:
                    fill = DOOR_SELECTED
                elif interior:
                    fill = DOOR_INTERIOR
                elif linked:
                    fill = DOOR_LINKED
                else:
                    fill = DOOR_OPEN
                item = c.create_oval(
                    x - r,
                    y - r,
                    x + r,
                    y + r,
                    fill=fill,
                    outline="#111",
                    width=1 if linked or interior else 2,
                    activefill=PLAYER,
                    tags=["door", f"tile_{tile[0]}_{tile[1]}"],
                )
                self._track(item, "door", door)
                self._door_items[door] = item

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
        w, h = self._size(tile)
        wx = x - w / 2 + (px / 512) * THUMB
        wy = y - h / 2 + TITLE_H + (py / 512) * THUMB
        cx, cy = self._w2c(wx, wy)
        s = max(4, 7 * self.zoom)
        width = max(2, 3 * self.zoom)
        c.create_line(cx - s, cy - s, cx + s, cy + s, fill=PLAYER, width=width, tags=["player"], state="disabled")
        c.create_line(cx + s, cy - s, cx - s, cy + s, fill=PLAYER, width=width, tags=["player"], state="disabled")

    # ------------------------------------------------------------- interactions

    def _hit(self):
        current = self.canvas.find_withtag("current")
        if not current:
            return None, None
        return self._items.get(current[0], (None, None))

    def _event_world(self, event):
        return self.canvas.canvasx(event.x) / self.zoom, self.canvas.canvasy(event.y) / self.zoom

    def _on_configure(self, event):
        # Keep the whole map in view while the window changes size, until the user takes over the camera
        size = (event.width, event.height)
        if size == getattr(self, "_last_size", None):
            return
        self._last_size = size
        if self._auto_view and self.pos:
            if getattr(self, "_fit_job", None):
                self.after_cancel(self._fit_job)
            self._fit_job = self.after(60, self.fit_view)

    def _on_press(self, event):
        self.canvas.focus_set()
        kind, payload = self._hit()
        self._press = {"kind": kind, "payload": payload, "x": event.x, "y": event.y, "moved": False}
        if kind is None or kind == "edge":
            self._press["kind"] = "pan"
            self.canvas.scan_mark(event.x, event.y)
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
            self._auto_view = False
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        tile = press["payload"] if press["kind"] == "card" else door_tile(press["payload"])
        if tile not in self.pos:
            return
        self.pos[tile][0] += dx / self.zoom
        self.pos[tile][1] += dy / self.zoom
        press["x"], press["y"] = event.x, event.y
        press["dragged_tile"] = tile
        self.canvas.move(f"tile_{tile[0]}_{tile[1]}", dx, dy)
        self.canvas.delete("edge")
        self._items = {k: v for k, v in self._items.items() if v[0] != "edge"}
        self._draw_edges()
        self.canvas.tag_raise("door")
        self.canvas.tag_raise("icon")
        self.canvas.tag_raise("player")

    def _on_release(self, event):
        press, self._press = self._press, None
        if not press:
            return
        if press["moved"]:
            tile = press.get("dragged_tile")
            if tile is not None:
                self.fixed.add(tile)
                self.unsettled.discard(tile)
                self._render()
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
            self.canvas.itemconfigure(self._door_items[door], fill=DOOR_SELECTED)
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

    def _on_motion(self, event):
        kind, payload = self._hit()
        if kind == "door":
            links = self._link_map()
            target = links.get(payload)
            text = payload + (f"  →  {target}" if target else "")
            if payload in self.special_doors:
                text += f"   [{self.special_doors[payload]}]"
        elif kind == "edge":
            text = f"{payload[0]}  ↔  {payload[1]}"
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
            self.canvas.tag_lower("rubber", "door")
        if text != self.status.get():
            self.status.set(text)

    def _on_wheel(self, event):
        self._zoom_at(event.x, event.y, 1.15 if event.delta > 0 else 1 / 1.15)

    def _zoom_at(self, sx, sy, factor):
        new_zoom = max(0.15, min(2.5, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        wx, wy = self.canvas.canvasx(sx) / self.zoom, self.canvas.canvasy(sy) / self.zoom
        self.zoom = new_zoom
        self._auto_view = False
        self._render()
        self._scroll_to(wx * new_zoom - sx, wy * new_zoom - sy)

    def _on_double_click(self, event):
        kind, payload = self._hit()
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
        kind, payload = self._hit()
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
        elif kind is None:
            menu = Menu(self, tearoff=0)
            menu.add_command(label="Fit to window", command=self.fit_view)
            menu.add_command(label="Re-layout", command=self.relayout)
            menu.add_command(label="Unfix all dragged tiles", command=self._unfix_all)
            wx, wy = self._event_world(event)
            menu.add_command(label="Add supertile here…", command=lambda: self._add_tile_from_picker(wx, wy))
            menu.tk_popup(event.x_root, event.y_root)

    def _unfix_all(self):
        self.fixed.clear()
        self.relayout()

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

    def _on_ctrl_right_click(self, event):
        kind, tile = self._hit()
        if kind != "card" or tile in mandatory_tiles[self.tab_world]:
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
        if self.player and self.player[0] == tile:
            self.player = None
        self.redraw_canvas()

    def _on_middle_click(self, event):
        kind, tile = self._hit()
        if kind != "card":
            return
        if tile in self.fixed:
            # Middle click on a dragged tile hands it back to the layout
            self.fixed.discard(tile)
        elif tile in self.pinned_eg_tiles:
            self.pinned_eg_tiles.discard(tile)
        else:
            self.pinned_eg_tiles.add(tile)
        self.redraw_canvas()

    # --------------------------------------------------------- save / load / api

    def load_yaml(self, yaml_data):
        self.door_links = [
            {"door": x["door"], "linked_door": x["linked_door"]} for x in yaml_data.get("door_links", [])
        ]
        self.lobby_doors = [{"door": x["door"], "lobby": x["lobby"]} for x in yaml_data.get("lobby_doors", [])]
        self.special_doors = dict(yaml_data.get("special_doors", {}))
        self.tiles = {}
        self.pos = {}
        self.fixed = set()
        self.unsettled = set()
        self.player = None
        self.selected_door = None
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
        self._sync_model()
        self._layout(full=not self.pos)
        self._render()

    def return_connections(self):
        return {
            "door_links": [{"door": x["door"], "linked_door": x["linked_door"]} for x in self.door_links],
            "lobby_doors": [{"door": x["door"], "lobby": x["lobby"]} for x in self.lobby_doors],
            "tiles": {f"{t[0]}__{t[1]}": data["has_been_lit"] for t, data in self.tiles.items()},
            "special_doors": dict(self.special_doors),
            "graph_layout": {
                f"{t[0]}__{t[1]}": [round(p[0], 1), round(p[1], 1), t in self.fixed] for t, p in self.pos.items()
            },
        }

    def update_size(self, size):
        self.cwidth, self.cheight = size
        self.canvas.config(width=self.cwidth + 50, height=self.cheight + 50 - TOOLBAR_HEIGHT)
        self._needs_fit = True
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
            self._follow_player()
        else:
            self._draw_player()

    def clear_player(self):
        if self.player is not None:
            self.player = None
            self.canvas.delete("player")

    def _follow_player(self):
        """Scroll just enough to keep the card the player is in on screen."""
        tile = self.player[0]
        if tile not in self.pos:
            return
        x, y = self._w2c(*self.pos[tile])
        vw, vh = self._viewport()
        left, top = self.canvas.canvasx(0), self.canvas.canvasy(0)
        margin = (THUMB / 2 + 20) * self.zoom
        if left + margin <= x <= left + vw - margin and top + margin <= y <= top + vh - margin:
            return
        self._scroll_to(x - vw / 2, y - vh / 2)

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
