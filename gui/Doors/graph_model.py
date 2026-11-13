"""Map model for one dungeon tab: tracked rooms and links, blocks, positions. No UI code.

Rooms linked through facing doorways are joined wall to wall into a block, which moves as one piece.

Static room data is in rooms.py and the solvers are in layout.py.
Save format is compatible with the original grid tracker.
"""

import random
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from enum import Enum

from data.doors_data import (
    complex_tiles,
    dark_tiles,
    doors_to_regions,
    dungeon_lobbies,
    interior_doors,
    mandatory_tiles,
    regions_to_doors,
    simple_tiles,
)
from data.worlds_data import dungeon_worlds
from gui.Doors import layout, rooms
from gui.Doors.layout import CONTACT_RANGE, LINK_GAP, REPEL_RANGE, enclosing_circle
from gui.Doors.rooms import (
    DEFAULT_DOORS,
    DIRECTIONS,
    DOORS,
    ENTRANCE_ONLY_DOORS,
    EdgeKind,
    Node,
    INTERIOR_DOORS,
    MANUAL_DROPS,
    MANUAL_REGIONS_ADDED,
    ONE_WAY,
    ROOM_LINKS,
    VALID_AUTO_LINKS,
    door_direction,
    door_fraction,
    supertile,
)

# Geometry, in world units (canvas pixels at zoom 1.0)
THUMB = 128  # supertile thumbnail edge
COMPACT_W = 104  # pass-through tiles collapse to a pill
COMPACT_H = 26
JOIN_GAP = 4  # gap between joined rooms
SNAP = THUMB / 8  # grid for joined rooms along the shared wall


@dataclass(eq=False)
class Link:
    """A tracked connection between two doors. Compared by identity, not by its doors."""

    door: str
    linked_door: str
    join: bool = None  # True or False once joined or split by hand


@dataclass(frozen=True)
class LobbyDoor:
    """A door that is a way into the dungeon."""

    door: str
    lobby: str  # which entrance; also the icon drawn


@dataclass
class TileState:
    is_dark: bool
    has_been_lit: bool


@dataclass(frozen=True)
class Edge:
    """A line on the map between two doors or ports."""

    a: str
    b: str
    kind: EdgeKind
    link: Link = None  # the tracked link, if it is one
    both_ways: bool = False  # warps and holes only


@dataclass(frozen=True)
class Player:
    node: Node
    x: float  # position in the supertile, 0..512
    y: float


class DoorState(Enum):
    OPEN = "open"  # not linked yet
    LINKED = "linked"  # linked, or an entrance
    INTERIOR = "interior"


@dataclass(frozen=True)
class DoorDot:
    door: str
    x: float  # relative to the node's centre, world units
    y: float
    state: DoorState


@dataclass(frozen=True)
class RepulsionShape:
    """What one block repels with, in world units."""

    circle: tuple  # (x, y, radius); None when repelling wall to wall
    boxes: list  # rooms as (left, top, right, bottom)
    reach: float


@dataclass
class Blocks:
    """Nodes grouped into blocks by the joined links. A node on its own is a block of one."""

    root: dict = field(default_factory=dict)  # node -> the node its block is named after
    offset: dict = field(default_factory=dict)  # node -> (x, y) from its root
    members: dict = field(default_factory=dict)  # root -> its nodes
    joined: set = field(default_factory=set)  # links whose two rooms are joined at the doorway

    def of(self, node):
        """Every node in the block this node is in."""
        return self.members.get(self.root.get(node, node), [node])


class GraphModel:
    """One dungeon tab: tracked data, blocks and positions."""

    def __init__(self, tab_world, experimental_flags):
        self.tab_world = tab_world
        self.dungeon_name = [k for k, v in dungeon_worlds.items() if v == tab_world][0]
        self.experimental_flags = experimental_flags
        self.show_all_doors = False
        self.auto_join = True
        self.group_by_dungeon = False
        self.spacing = float(REPEL_RANGE)  # repulsion reach
        self.leaf_pull = 2.5  # pull boost for blocks linked to a single other block
        self.circle_repulsion = False  # repel as one enclosing circle per block
        self._shown_rooms = rooms.Rooms(True, whole=self.is_hidden_dark)
        self.reset()

    @property
    def rooms(self):
        """Room lookups as shown on the map: an unlit dark supertile is one card, whatever its parts."""
        return self._shown_rooms if self.experimental_flags.get("split_rooms", True) else rooms.WHOLE

    @property
    def real_rooms(self):
        """Room lookups by the supertiles' real parts, for recording where the player has been."""
        return rooms.SPLIT if self.experimental_flags.get("split_rooms", True) else rooms.WHOLE

    def reset(self):
        self.tiles = {}  # supertile -> TileState
        self.door_links = []  # Link
        self.lobby_doors = []  # LobbyDoor
        self.special_doors = {}
        self.kept_expanded = set()  # nodes; see toggle_expanded
        self.sanc_dungeon = False

        self.pos = {}  # node -> [x, y] supertile centre, world units
        self.fixed = set()  # pinned nodes
        self.unsettled = set()  # new nodes, movable by the incremental layout
        self.compact = set()
        self.blocks = Blocks()
        self.doors_available = set()
        self.player = None  # Player
        self.visited = set()  # nodes the player has been in; saved as reached_parts
        self._whole = set()  # split supertiles shown whole; see nodes()
        self.provisional = {}  # supertile -> node guessed from position when it was added
        self.located = None  # node the player is in, once known
        self._sighted = None  # supertile of the last position report
        self._layout_signature = None
        self._join_rank = {}  # link -> join priority, lowest first
        self.held = set()  # nodes being dragged
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
        """Rebuild blocks and lay out new nodes. Call after any data change."""
        self._sync_model()
        self._layout()
        self._refresh_door_sets()

    def relayout(self):
        """Full layout; pinned nodes stay. Returns True if nothing was placed before."""
        self._sync_model()
        self._optimise_join_order()
        before = self.bounds() if self.pos else None
        self._layout(full=True)
        if before is not None and not self.fixed:
            # Pinned nodes already hold the map in place; recentring would move them
            self._keep_centre(before)
        self._refresh_door_sets()
        return before is None

    def settle(self, iterations):
        """Run the solver in place for some iterations."""
        if not self.pos:
            return
        self._relax(iterations=iterations, old_mobility=1.0, edges=self._layout_edges(), cold=True)

    def _refresh_door_sets(self):
        self._seam_doors = set()
        for link in self.blocks.joined:
            self._seam_doors.add(link.door)
            self._seam_doors.add(link.linked_door)
        self._linked_doors = set()
        for link in self.door_links:
            self._linked_doors.add(link.door)
            self._linked_doors.add(link.linked_door)
        for edge in self.edges():
            if edge.kind is EdgeKind.DROP:
                # Vanilla drop with its landing on the map counts as linked
                self._linked_doors.add(edge.a)
                self._linked_doors.add(edge.b)

    def add_link(self, door, linked_door):
        self.door_links.append(Link(door, linked_door))
        self.update()

    def remove_link(self, link):
        self.door_links.remove(link)
        self.update()

    def toggle_join(self, link):
        """Join or split the rooms on a link. Returns an error message or None."""
        if link in self.blocks.joined:
            link.join = False
            self.update()
            return None
        if self.join_offset(link.door, link.linked_door) is None:
            return "These two doors cannot be joined: only north/south and east/west doorways fit together"
        link.join = True
        self._sync_model()
        if link not in self.blocks.joined:
            link.join = None
            self._sync_model()
            return "Cannot join here: the rooms would land on top of rooms already in the block"
        self.update()
        return None

    def set_pinned(self, node, pinned):
        """Pin or unpin a node's whole block."""
        members = self.blocks.of(node)
        if pinned:
            self.fixed.update(members)
        else:
            self.fixed.difference_update(members)

    def nodes(self):
        """Nodes on the map.

        A part of a split supertile is included when it has a link, entrance or icon, the player has
        been in it, or a fixed drop/warp leads to it from another node. If no part qualifies, or the
        supertile is kept expanded, all parts are included.
        """
        split = [tile for tile in self.tiles if self.rooms.part_count(tile) > 1]
        shown = {Node(*tile) for tile in self.tiles if self.rooms.part_count(tile) == 1}
        self._whole = set()
        if split:
            used = set(self.special_doors)
            for link in self.door_links:
                used.update((link.door, link.linked_door))
            used.update(entry.door for entry in self.lobby_doors)
            for door in used:
                if door in DOORS and DOORS[door].tile in self.tiles:
                    shown.add(self.rooms.node(door))
            shown.update(node for node in self.visited if node.tile in self.tiles)
            shown.update(node for tile, node in self.provisional.items() if tile in self.tiles)
            shown.update(node for node in self.kept_expanded if node.tile in self.tiles)
            # Fixed drops and warps, as directed (from, to)
            fixed = []
            for link in ROOM_LINKS:
                if link.kind is not EdgeKind.HOLE or self.experimental_flags.get("vanilla_drops"):
                    fixed.append((link.a, link.b))
                    if link.both_ways:
                        fixed.append((link.b, link.a))
            if self.experimental_flags.get("vanilla_drops"):
                fixed += list(MANUAL_DROPS.items())
            fixed = [(self.rooms.node(a), self.rooms.node(b)) for a, b in fixed]
            fixed = [(a, b) for a, b in fixed if a and b and a.tile in self.tiles and b.tile in self.tiles]
            grew = True
            while grew:
                grew = False
                for a, b in fixed:
                    if a in shown and b not in shown:
                        shown.add(b)
                        grew = True
            for tile in split:
                parts = [Node(*tile, k) for k in range(self.rooms.part_count(tile))]
                if any(node in self.kept_expanded for node in parts):
                    shown.update(parts)
                elif not any(node in shown for node in parts):
                    # Unlit dark room: one placeholder node
                    shown.update(parts[:1] if self.is_hidden_dark(tile) else parts)
                    self._whole.add(tile)
        return [Node(*tile, k) for tile in self.tiles for k in range(self.rooms.part_count(tile)) if (*tile, k) in shown]

    def player_node(self, tile, x, y):
        """Node for a position in a supertile. A guess: areas of different parts can overlap."""
        if self.real_rooms.part_count(tile) == 1:
            return Node(*tile)
        # Smallest containing area wins (a nook inside its lobby)
        best = None
        for k, boxes in enumerate(supertile(tile).areas):
            for left, top, right, bottom in boxes:
                if left <= x <= right and top <= y <= bottom:
                    area = (right - left) * (bottom - top)
                    if best is None or area < best[0]:
                        best = (area, k)
        return Node(*tile, best[1] if best else 0)

    def arrive(self, door):
        """Record that the player entered by this door; overrides any position guess."""
        if door not in DOORS:
            return
        node = self.real_rooms.node(door)
        self.located = node
        self.visited.add(node)
        self.provisional.pop(node.tile, None)
        if self.player is not None and self.player.node.tile == node.tile:
            self.player = replace(self.player, node=node)

    def locate(self, tile, x, y):
        """Node the player is in, or None if not yet known.

        Uses the node set by arrive() while the player stays in that supertile. Otherwise guesses from
        position, but not on the first report in a split supertile: the tracker reports position
        before the door, so the guess waits one report.
        """
        if self.located is not None and self.located.tile == tile:
            return self.located
        self.located = None
        if self.real_rooms.part_count(tile) > 1 and self._sighted != tile:
            self._sighted = tile
            return None
        self._sighted = tile
        self.located = self.player_node(tile, x, y)
        self.visited.add(self.located)
        self.provisional.pop(tile, None)
        return self.located

    def move_player(self, tile, x, y):
        """Put the player at a position in a supertile. Returns the node, or None while locate() does not know it."""
        node = self.locate(tile, x, y)
        if node is not None:
            self.player = Player(node, x, y)
        return node

    def clear_player(self):
        self.player = None

    def drag(self, node, dx, dy):
        """Move a node's block, and hold it against the solver until drop()."""
        self.held = set(self.blocks.of(node))
        for member in self.held:
            self.pos[member][0] += dx
            self.pos[member][1] += dy

    def drop(self):
        """End a drag. The block stays where it was put, without being pinned."""
        self.unsettled -= self.held
        self.held = set()

    def unpin_all(self):
        self.fixed = set()

    def toggle_expanded(self, node):
        """Keep a node expanded, or stop: it is never collapsed and its supertile shows every part."""
        self.kept_expanded ^= {node}
        self.update()

    def light(self, tile):
        """Record that a dark supertile has been seen lit. Returns True if that is new."""
        state = self.tiles[tile]
        if state.has_been_lit:
            return False
        state.has_been_lit = True
        # The parts take the place of the single card the supertile was while unlit
        card = Node(*tile)
        for part in range(1, self.rooms.part_count(tile)):
            if card in self.pos:
                self.pos[Node(*tile, part)] = list(self.pos[card])
            if card in self.fixed:
                self.fixed.add(Node(*tile, part))
        self.update()
        return True

    def add_tile(self, tile, has_been_lit=False, at=None, player=None):
        """Add a supertile. With player=(x, y), only the part at that position is shown at first."""
        if tile in self.tiles:
            return False
        self._ensure_tile(tile, has_been_lit=has_been_lit)
        if player is not None and self.real_rooms.part_count(tile) > 1:
            self.provisional[tile] = self.player_node(tile, *player)
        if at is not None:
            self.pos[Node(*tile)] = [at[0], at[1]]
        self.update()
        return True

    def remove_tile(self, tile):
        """Remove a supertile and everything attached to it."""
        if tile in mandatory_tiles[self.tab_world] or tile not in self.tiles:
            return False
        doors = set(supertile(tile).doors)
        doors.discard("Sanctuary Mirror Route")
        self.door_links = [x for x in self.door_links if x.door not in doors and x.linked_door not in doors]
        self.lobby_doors = [x for x in self.lobby_doors if x.door not in doors]
        for door in doors:
            self.special_doors.pop(door, None)
        del self.tiles[tile]
        for node in [n for n in self.pos if n.tile == tile]:
            del self.pos[node]
        self.kept_expanded = {n for n in self.kept_expanded if n.tile != tile}
        self.fixed = {n for n in self.fixed if n.tile != tile}
        self.visited = {n for n in self.visited if n.tile != tile}
        self.provisional.pop(tile, None)
        if self.located is not None and self.located.tile == tile:
            self.located = None
        if self.player and self.player.node.tile == tile:
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
        self.lobby_doors = [x for x in self.lobby_doors if x.door != door]
        self.special_doors.pop(door, None)
        self.update()

    # ------------------------------------------------------- auto tracking entry

    def auto_add_door_link(self, door, linked_door):
        for d in [door, linked_door] if not self.decoupled() else [door]:
            if d is None or self.has_target(d) or d in INTERIOR_DOORS or d in self.lobby_door_names():
                return False
        if door is None or linked_door is None:
            return False
        directions = {door_direction(door), door_direction(linked_door)}
        if directions not in VALID_AUTO_LINKS:
            return False
        self.add_link(door, linked_door)
        return True

    def auto_add_lobby(self, door):
        current_lobbies = [x.lobby for x in self.lobby_doors]
        if (
            door is None
            or door in self.lobby_door_names()
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
        """Load one tab's section of a tracker file. Returns True if it had saved positions."""
        # Older files say "stack" and "stacked_links" for "join" and "joined_links"
        self.door_links = []
        for x in data.get("door_links", []):
            join = x.get("join", x.get("stack"))
            self.door_links.append(Link(x["door"], x["linked_door"], None if join is None else bool(join)))
        joins_saved = "joined_links" in data or "stacked_links" in data
        # joined_links holds positions in door_links
        self._join_rank = {}
        for rank, n in enumerate(data.get("joined_links", data.get("stacked_links")) or []):
            if 0 <= n < len(self.door_links):
                self._join_rank[self.door_links[n]] = rank
        self.lobby_doors = [LobbyDoor(x["door"], x["lobby"]) for x in data.get("lobby_doors", [])]
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
            node = Node(*(int(x) for x in str(key).split("__")))
            if node.tile in self.tiles and node.part < self.real_rooms.part_count(node.tile):
                self.visited.add(node)
        for key, value in (data.get("graph_layout") or {}).items():
            # Keys: "x__y" for part 0, "x__y__part" otherwise
            node = Node(*(int(x) for x in str(key).split("__")))
            if node.tile in self.tiles and node.part < self.rooms.part_count(node.tile):
                self.pos[node] = [float(value[0]), float(value[1])]
                if len(value) > 2 and value[2]:
                    self.fixed.add(node)
        if data.get("satellite_pull"):
            self.leaf_pull = max(1.0, min(4.0, float(data["satellite_pull"])))
        if data.get("spacing"):
            self.spacing = max(10.0, min(200.0, float(data["spacing"])))
        had_positions = bool(self.pos)
        self._sync_model()
        if self.pos and not joins_saved:
            # File from before joins were saved: infer them from saved positions
            rank = 0
            for link in self.door_links:
                a, b = link.door, link.linked_door
                rel = self.join_offset(a, b)
                na, nb = self.rooms.node(a), self.rooms.node(b)
                if rel is None or na not in self.pos or nb not in self.pos:
                    continue
                if (
                    abs(self.pos[nb][0] - self.pos[na][0] - rel[0]) < 2
                    and abs(self.pos[nb][1] - self.pos[na][1] - rel[1]) < 2
                ):
                    self._join_rank[link] = rank
                    rank += 1
            self._build_blocks()
        if self.pos and all(n in self.pos for n in self.nodes()):
            # Keep saved positions, but re-seat blocks in case join offsets changed since the save
            for root, members in self.blocks.members.items():
                anchor = next((m for m in members if m in self.fixed), root)
                self._place_block(anchor, *self.pos[anchor])
            self._layout_signature = self._signature()
        else:
            self._optimise_join_order()
        self._layout(full=not self.pos)
        self._refresh_door_sets()
        return had_positions

    def save(self):
        door_links = []
        for link in self.door_links:
            entry = {"door": link.door, "linked_door": link.linked_door}
            if link.join is not None:
                entry["join"] = link.join
            door_links.append(entry)
        position = {link: n for n, link in enumerate(self.door_links)}
        return {
            "door_links": door_links,
            # Joined links as positions in door_links, in claim order, so load rebuilds the same blocks
            "joined_links": [position[link] for link in self._join_order() if link in self.blocks.joined],
            "lobby_doors": [{"door": x.door, "lobby": x.lobby} for x in self.lobby_doors],
            "tiles": {f"{t[0]}__{t[1]}": state.has_been_lit for t, state in self.tiles.items()},
            # Parts reached without a link (falls, warps) would otherwise be lost on reload
            "reached_parts": sorted(
                f"{n.x}__{n.y}__{n.part}"
                for n in self.visited | set(self.provisional.values())
                if n.tile in self.tiles and self.real_rooms.part_count(n.tile) > 1
            ),
            "special_doors": dict(self.special_doors),
            "graph_layout": {
                (f"{n.x}__{n.y}" if n.part == 0 else f"{n.x}__{n.y}__{n.part}"): [
                    round(p[0], 1),
                    round(p[1], 1),
                    n in self.fixed,
                ]
                for n, p in self.pos.items()
            },
            "spacing": round(self.spacing, 1),
            "satellite_pull": self.leaf_pull,
        }

    # ------------------------------------------------- data, blocks, layout, forces

    def _ensure_tile(self, tile, has_been_lit=False):
        if tile in self.tiles:
            return
        self.tiles[tile] = TileState(tile in dark_tiles, has_been_lit)

    def decoupled(self):
        return self.experimental_flags["decoupled_doors"]

    def is_hidden_dark(self, tile):
        state = self.tiles.get(tile)
        return bool(state and state.is_dark and not state.has_been_lit)

    def link_map(self):
        """door -> linked door, both directions unless doors are decoupled."""
        links = {}
        for link in self.door_links:
            links[link.door] = link.linked_door
            if not self.decoupled():
                links.setdefault(link.linked_door, link.door)
        return links

    def has_target(self, door):
        for link in self.door_links:
            if link.door == door:
                return True
            if not self.decoupled() and link.linked_door == door:
                return True
        return False

    def lobby_door_names(self):
        return [x.door for x in self.lobby_doors]

    def add_lobby_door(self, door, lobby):
        if door not in self.lobby_door_names():
            self.lobby_doors.append(LobbyDoor(door, lobby))
        self.special_doors[door] = lobby

    def _sync_model(self):
        """Add any supertile referenced by a link or lobby; refresh derived state."""
        used = [door for link in self.door_links for door in (link.door, link.linked_door)]
        used += [lobby.door for lobby in self.lobby_doors]
        for door in used:
            if door in DOORS:
                self._ensure_tile(DOORS[door].tile)

        # Drop entrances and the sanctuary mirror route are always entrances
        lobby_doors = self.lobby_door_names()
        for tile in list(self.tiles):
            for door in supertile(tile).doors:
                if door.startswith("Sanctuary") and not self.sanc_dungeon:
                    self.sanc_dungeon = True
                    if "Sanctuary Mirror Route" in DOORS:
                        self.add_lobby_door("Sanctuary Mirror Route", "Sanctuary_Mirror")
                if "Drop" in door and door in dungeon_lobbies[self.tab_world] and door not in lobby_doors:
                    self.add_lobby_door(door, door)

        # Add the supertiles that fixed connections lead to. That can show more parts, which lead further.
        while True:
            doors = self._reachable_doors(both_ways=False)
            led_to = {DOORS[door].tile for door in doors if door in DOORS} - set(self.tiles)
            if not led_to:
                break
            for tile in sorted(led_to):
                self._ensure_tile(tile)
        self.doors_available = self._reachable_doors()

        self._piece_cache = {}
        self.compact = self._compact_nodes()
        self._piece_cache = {}
        self._build_blocks()

    def _reachable_doors(self, both_ways=True):
        """Doors reachable from the lobbies via regions, fixed connections and links.

        With both_ways=False, warps and drops are followed only the way they go. Which door dots are
        shown uses both ways; which supertiles are added to the map does not.
        """
        adjacency = defaultdict(set)
        for a, b in DEFAULT_DOORS.items():
            adjacency[a].add(b)
            if both_ways or a not in ONE_WAY:
                adjacency[b].add(a)
        for link in self.door_links:
            adjacency[link.door].add(link.linked_door)
            if not self.decoupled():
                adjacency[link.linked_door].add(link.door)

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
            push(lobby.door)
        drain()

        # Nodes not reached from a lobby show all their doors
        for node in self.nodes():
            names = self.rooms.doors(node)
            if not any(name in seen for name in names):
                for name in names:
                    push(name)
                drain()
        return seen

    def _compact_nodes(self):
        """Nodes to collapse: fully linked, single-route supertiles."""
        if not self.experimental_flags["hide_single_route_tiles"]:
            return set()
        links = self.link_map()
        lobbies = set(self.lobby_door_names())
        compact = set()
        for tile in self.tiles:
            if tile not in simple_tiles and tile not in complex_tiles:
                continue
            if any(node.tile == tile for node in self.kept_expanded) or self.is_hidden_dark(tile):
                continue
            exits = [d for d in supertile(tile).doors if d not in INTERIOR_DOORS]
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
        return {Node(*tile, k) for tile in compact for k in range(self.rooms.part_count(tile))}

    def pieces(self, node):
        """Cached _work_out_pieces."""
        pieces = self._piece_cache.get(node)
        if pieces is None:
            pieces = self._piece_cache[node] = self._work_out_pieces(node)
        return pieces

    def _work_out_pieces(self, node):
        """Drawn rectangles of a node as (left, top, right, bottom), relative to the supertile centre."""
        if node in self.compact:
            return [(-COMPACT_W / 2, -COMPACT_H / 2, COMPACT_W / 2, COMPACT_H / 2)]
        half = THUMB / 2
        live = supertile(node.tile).live
        if not live or not self.experimental_flags.get("hide_dead_rooms") or self.is_hidden_dark(node.tile):
            return [(-half, -half, half, half)]
        # Auto-detected rooms are on an 8px grid and get a margin; hand-set areas are exact
        found = {tuple(b) for b in live}
        if self.rooms.part_count(node.tile) > 1:
            live = supertile(node.tile).areas[node.part] or live
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

    def box(self, node):
        """Bounding box of a node's pieces."""
        pieces = self.pieces(node)
        return (
            min(p[0] for p in pieces),
            min(p[1] for p in pieces),
            max(p[2] for p in pieces),
            max(p[3] for p in pieces),
        )

    def size(self, node):
        left, top, right, bottom = self.box(node)
        return right - left, bottom - top

    def port_offset(self, door):
        """Door position relative to its node's centre, world units."""
        node = self.rooms.node(door)
        fx, fy = door_fraction(door)
        w, h = self.size(node)
        if node in self.compact:
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
        if self.is_hidden_dark(node.tile):
            fx = fy = 0.5
        return (fx - 0.5) * THUMB, (fy - 0.5) * THUMB

    def _joinable(self, node):
        return node.tile in self.tiles and node not in self.compact and not self.is_hidden_dark(node.tile)

    def join_offset(self, a, b):
        """Offset of b's node from a's when the two are joined at these doorways; None unless they face each other."""
        da, db = DIRECTIONS.get(door_direction(a)), DIRECTIONS.get(door_direction(b))
        if da is None or db is None or (da[0] + db[0], da[1] + db[1]) != (0, 0):
            return None
        na, nb = self.rooms.node(a), self.rooms.node(b)
        if na == nb or not self._joinable(na) or not self._joinable(nb):
            return None
        if a not in DOORS or b not in DOORS:
            return None
        fax, fay = door_fraction(a)
        fbx, fby = door_fraction(b)
        # Walls of the pieces the doors are on, not the supertile edges
        pa, pb = self._piece_at(a), self._piece_at(b)
        gap = JOIN_GAP if self.experimental_flags.get("hide_dead_rooms") else 0.0
        if da[0] == 0:
            across = round((fax - fbx) * THUMB / SNAP) * SNAP
            return across, (pa[1] - pb[3] - gap) if da[1] < 0 else (pa[3] - pb[1] + gap)
        across = round((fay - fby) * THUMB / SNAP) * SNAP
        return ((pa[0] - pb[2] - gap) if da[0] < 0 else (pa[2] - pb[0] + gap)), across

    def _piece_at(self, door):
        """The piece of its node nearest to a door."""
        ox, oy = self.port_offset(door)
        return min(
            self.pieces(self.rooms.node(door)),
            key=lambda p: max(p[0] - ox, 0, ox - p[2]) + max(p[1] - oy, 0, oy - p[3]),
        )

    def _join_order(self, rank=None):
        """Links in the order they get to join: manual first, then rank, then age."""
        rank = self._join_rank if rank is None else rank
        big = len(rank) + len(self.door_links)
        age = {link: n for n, link in enumerate(self.door_links)}
        return sorted(self.door_links, key=lambda link: (link.join is not True, rank.get(link, big + age[link]), age[link]))

    def _compute_blocks(self, order):
        """Join facing doorways in the given order, skipping joins that would overlap.

        Returns the Blocks.
        """
        nodes = self.nodes()
        root = {n: n for n in nodes}
        off = {n: (0.0, 0.0) for n in nodes}
        members = {n: [n] for n in nodes}
        boxes = {n: self.pieces(n) for n in nodes}
        # Parts of a supertile shown whole stay in one block at zero offset
        for tile in self._whole:
            parts = [n for n in nodes if n.tile == tile]
            for part in parts[1:]:
                root[part] = parts[0]
                members[parts[0]] += members.pop(part)
        joined = set()
        auto = self.auto_join
        for link in order:
            if link.join is False or (link.join is None and not auto):
                continue
            a, b = link.door, link.linked_door
            rel = self.join_offset(a, b)
            if rel is None:
                continue
            na, nb = self.rooms.node(a), self.rooms.node(b)
            ra, rb = root[na], root[nb]
            # Shift from b's block frame to a's
            sx = off[na][0] + rel[0] - off[nb][0]
            sy = off[na][1] + rel[1] - off[nb][1]
            if ra == rb:
                if abs(sx) < 1 and abs(sy) < 1:
                    joined.add(link)
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
                # Merge the smaller block into the bigger
                ra, rb, sx, sy = rb, ra, -sx, -sy
            for m in members[rb]:
                off[m] = (off[m][0] + sx, off[m][1] + sy)
                root[m] = ra
            members[ra] += members.pop(rb)
            joined.add(link)
        return Blocks(root, off, members, joined)

    def _build_blocks(self):
        self.blocks = self._compute_blocks(self._join_order())

    def _optimise_join_order(self):
        """Random search for the order that joins the most links. Full re-layout only."""
        candidates = [x for x in self.door_links if self.join_offset(x.door, x.linked_door) is not None]
        if len(candidates) < 3:
            return

        def joins(rank):
            return len(self._compute_blocks(self._join_order(rank)).joined)

        rng = random.Random(len(self.door_links))
        best_rank = {link: i for i, link in enumerate(self._join_order())}
        best_score = joins(best_rank)
        for _ in range(60):
            shuffled = candidates[:]
            rng.shuffle(shuffled)
            rank = {link: i for i, link in enumerate(shuffled)}
            score = joins(rank)
            if score > best_score:
                best_score, best_rank = score, rank
        self._join_rank = best_rank
        self._build_blocks()

    def _place_block(self, anchor, x, y):
        """Move a block so that `anchor` is at (x, y)."""
        ax, ay = self.blocks.offset[anchor]
        for m in self.blocks.of(anchor):
            mx, my = self.blocks.offset[m]
            self.pos[m] = [x + mx - ax, y + my - ay]

    def port(self, door):
        ox, oy = self.port_offset(door)
        x, y = self.pos[self.rooms.node(door)]
        return x + ox, y + oy

    def edges(self, known=None):
        """Everything drawn between doors, as Edges."""
        known = self.pos if known is None else known
        edges = []
        seen = set()
        for link in self.door_links:
            a, b = link.door, link.linked_door
            if self.rooms.node(a) not in known or self.rooms.node(b) not in known:
                continue
            if a not in DOORS or b not in DOORS:
                continue
            edges.append(Edge(a, b, EdgeKind.INTERIOR if a in INTERIOR_DOORS else EdgeKind.LINK, link))
            seen.add(frozenset((a, b)))
        # Interior doors not already tracked as links
        for a, b in interior_doors:
            if frozenset((a, b)) in seen:
                continue
            if a not in DOORS or b not in DOORS:
                continue
            if self.rooms.node(a) not in known or self.rooms.node(b) not in known:
                continue
            if not self._door_visible(a) or not self._door_visible(b):
                continue
            edges.append(Edge(a, b, EdgeKind.INTERIOR))
        # Drops can be shuffled: only assumed when the vanilla_drops setting is on
        vanilla_drops = MANUAL_DROPS if self.experimental_flags.get("vanilla_drops") else {}
        for a, b in vanilla_drops.items():
            if frozenset((a, b)) in seen or self.has_target(a):
                continue
            if self.rooms.node(a) not in known or self.rooms.node(b) not in known:
                continue
            if not self._door_visible(a) or not self._door_visible(b):
                continue
            edges.append(Edge(a, b, EdgeKind.DROP))
        # Warps are never shuffled; unmarked holes follow vanilla_drops
        for link in ROOM_LINKS:
            if link.kind is EdgeKind.HOLE and not self.experimental_flags.get("vanilla_drops"):
                continue
            na, nb = self.rooms.node(link.a), self.rooms.node(link.b)
            if na not in known or nb not in known or self.is_hidden_dark(na.tile) or self.is_hidden_dark(nb.tile):
                continue
            edges.append(Edge(link.a, link.b, link.kind, both_ways=link.both_ways))
        return edges

    def _door_visible(self, door):
        if self.show_all_doors or not self.lobby_doors:
            return True
        return door in self.doors_available

    def _signature(self):
        """Layout inputs; the layout reruns only when this changes."""
        return (
            tuple(sorted(self.nodes())),
            frozenset(self.blocks.joined),
            tuple(sorted(self.compact)),
            len(self.door_links),
            tuple(sorted(tuple(sorted(m)) for m in self.blocks.members.values())),
        )

    def _layout(self, full=False):
        gap = LINK_GAP
        nodes = self.nodes()
        if not nodes:
            return
        present = set(nodes)
        for node in list(self.pos):
            if node not in present:
                del self.pos[node]
        self.fixed &= present
        self.unsettled &= present

        signature = self._signature()
        if not full and signature == self._layout_signature and all(n in self.pos for n in nodes):
            return
        self._layout_signature = signature

        if full:
            # Deterministic: drop previous positions
            self._damping = {}
            for node in nodes:
                if node not in self.fixed:
                    self.pos.pop(node, None)

        # Seat each block on a member that already has a position
        for root, members in self.blocks.members.items():
            placed = [m for m in members if m in self.pos]
            if not placed:
                continue
            anchor = next((m for m in placed if m in self.fixed), root if root in self.pos else placed[0])
            self.unsettled -= set(members)
            self._place_block(anchor, *self.pos[anchor])

        edges = self._layout_edges()
        pending = {root for root in self.blocks.members if root not in self.pos}
        new_nodes = [m for root in pending for m in self.blocks.members[root]]

        def place_from(anchor_door, new_door):
            anchor = self.rooms.node(anchor_door)
            new = self.rooms.node(new_door)
            ax, ay = self.pos[anchor]
            aox, aoy = self.port_offset(anchor_door)
            nox, noy = self.port_offset(new_door)
            direction = DIRECTIONS.get(door_direction(anchor_door))
            if direction is None:
                opposite = DIRECTIONS.get(door_direction(new_door))
                direction = (-opposite[0], -opposite[1]) if opposite else (1, 0.35)
            self._place_block(new, ax + aox + direction[0] * gap - nox, ay + aoy + direction[1] * gap - noy)

        def place_loose(root):
            placed = list(self.pos.values())
            if not placed:
                self._place_block(root, 0.0, 0.0)
            elif self.player and self.player.node in self.pos and self.player.node not in self.blocks.of(root):
                px, py = self.pos[self.player.node]
                self._place_block(root, px + THUMB + LINK_GAP * 2, py + 20.0)
            else:
                max_x = max(p[0] for p in placed)
                min_y = min(p[1] for p in placed)
                self._place_block(
                    root, max_x + THUMB + LINK_GAP * 3, min_y + (len(placed) % 5) * (THUMB + LINK_GAP)
                )

        # Place lobby blocks first
        lobby_roots = [self.blocks.root.get(self.rooms.node(x.door)) for x in self.lobby_doors]
        order = [r for r in lobby_roots if r in pending] + sorted(pending, key=lambda r: -len(self.blocks.members[r]))
        while pending:
            progressed = True
            while progressed:
                progressed = False
                for edge in edges:
                    ra, rb = self.blocks.root[self.rooms.node(edge.a)], self.blocks.root[self.rooms.node(edge.b)]
                    if ra in pending and rb not in pending:
                        place_from(edge.b, edge.a)
                        pending.discard(ra)
                        progressed = True
                    elif rb in pending and ra not in pending:
                        place_from(edge.a, edge.b)
                        pending.discard(rb)
                        progressed = True
            if pending:
                root = next(r for r in order if r in pending)
                place_loose(root)
                pending.discard(root)

        self.unsettled |= set(new_nodes)
        if not full:
            # Incremental: move only the new blocks
            self._relax(iterations=90, old_mobility=0.0, edges=edges, cold=True)
            # then separate overlaps
            self._relax(iterations=0, old_mobility=1.0, edges=edges, cold=True)
        else:
            # Stress for the global shape, then forces to shorten links and separate overlaps
            self._stress_layout(edges)
            self._relax(iterations=180, old_mobility=1.0, edges=edges, improve=True)
            self._relax(iterations=150, old_mobility=1.0, edges=edges, cold=True)
            self._park_unlinked(edges)
        self._laid_spacing = self.spacing

        linked = set()
        for edge in edges:
            linked.update(self.blocks.of(self.rooms.node(edge.a)))
            linked.update(self.blocks.of(self.rooms.node(edge.b)))
        self.unsettled -= linked

    def repulsion_shapes(self):
        """A RepulsionShape per block, for the debug overlay."""
        shapes = []
        for root, members in self.blocks.members.items():
            if any(m not in self.pos for m in members):
                continue
            boxes = []
            for m in members:
                x, y = self.pos[m]
                boxes.extend((x + left, y + top, x + right, y + bottom) for left, top, right, bottom in self.pieces(m))
            circle = None
            if self.circle_repulsion:
                corners = [(bx, by) for left, top, right, bottom in boxes for bx in (left, right) for by in (top, bottom)]
                circle = enclosing_circle(corners)
            shapes.append(RepulsionShape(circle, boxes, self.spacing if circle else max(self.spacing, CONTACT_RANGE)))
        return shapes

    def _park_unlinked(self, edges):
        """Line up unlinked blocks beside the map."""
        linked = set()
        for edge in edges:
            linked.add(self.blocks.root[self.rooms.node(edge.a)])
            linked.add(self.blocks.root[self.rooms.node(edge.b)])
        loose = [
            r
            for r, members in self.blocks.members.items()
            if r not in linked and not any(m in self.fixed for m in members)
        ]
        rest = [n for r in self.blocks.members if r not in loose for n in self.blocks.members[r]]
        if not loose or not rest:
            return
        right = max(self.pos[n][0] + self.box(n)[2] for n in rest)
        y = min(self.pos[n][1] + self.box(n)[1] for n in rest)
        gap = max(self.spacing, LINK_GAP)
        for r in sorted(loose):
            members = self.blocks.members[r]
            left = min(self.blocks.offset[m][0] + self.box(m)[0] for m in members)
            top = min(self.blocks.offset[m][1] + self.box(m)[1] for m in members)
            bottom = max(self.blocks.offset[m][1] + self.box(m)[3] for m in members)
            self._place_block(r, right + gap * 2 - left, y - top)
            y += bottom - top + gap

    def _layout_edges(self):
        """Edges between different blocks."""
        return [
            e
            for e in self.edges(known=set(self.nodes()))
            if e.link not in self.blocks.joined and self.blocks.root[self.rooms.node(e.a)] != self.blocks.root[self.rooms.node(e.b)]
        ]

    def _bodies(self, old_mobility):
        """Blocks as layout.Body, in blocks.members order. Unsettled blocks are free; the rest get old_mobility."""
        bodies = []
        for root, members in self.blocks.members.items():
            rects = []
            for m in members:
                ox, oy = self.blocks.offset[m]
                for left, top, right, bottom in self.pieces(m):
                    rects.append((ox + (left + right) / 2, oy + (top + bottom) / 2, (right - left) / 2, (bottom - top) / 2))
            if any(m in self.fixed or m in self.held for m in members):
                mobility = 0.0
            elif all(m in self.unsettled for m in members):
                mobility = 1.0
            else:
                mobility = old_mobility
            bodies.append(
                layout.Body(rects, mobility, len(members), self._damping.setdefault(root, layout.Damping()), supertile(root.tile).dungeon)
            )
        return bodies

    def _springs(self, edges):
        """Edges as layout.Spring, with bodies numbered in blocks.members order."""
        index = {root: i for i, root in enumerate(self.blocks.members)}
        springs = []
        for edge in edges:
            na, nb = self.rooms.node(edge.a), self.rooms.node(edge.b)
            ax, ay = self.port_offset(edge.a)
            bx, by = self.port_offset(edge.b)
            springs.append(
                layout.Spring(
                    a=index[self.blocks.root[na]],
                    ax=ax + self.blocks.offset[na][0],
                    ay=ay + self.blocks.offset[na][1],
                    b=index[self.blocks.root[nb]],
                    bx=bx + self.blocks.offset[nb][0],
                    by=by + self.blocks.offset[nb][1],
                    facing_a=DIRECTIONS.get(door_direction(edge.a)),
                    facing_b=DIRECTIONS.get(door_direction(edge.b)),
                )
            )
        return springs

    def _stress_layout(self, edges):
        """Place every unpinned block with the stress solver."""
        roots = list(self.blocks.members)
        boxes, movable = [], []
        for root in roots:
            members = self.blocks.members[root]
            parts = [(self.blocks.offset[m], self.box(m)) for m in members]
            boxes.append(
                (
                    min(off[0] + box[0] for off, box in parts),
                    min(off[1] + box[1] for off, box in parts),
                    max(off[0] + box[2] for off, box in parts),
                    max(off[1] + box[3] for off, box in parts),
                )
            )
            movable.append(not any(m in self.fixed for m in members))
        xs, ys = layout.stress(
            boxes,
            movable,
            [self.pos[r][0] - self.blocks.offset[r][0] for r in roots],
            [self.pos[r][1] - self.blocks.offset[r][1] for r in roots],
            self._springs(edges),
            spacing=self.spacing,
        )
        for root, x, y, free in zip(roots, xs, ys, movable):
            if free:
                self._place_block(root, x + self.blocks.offset[root][0], y + self.blocks.offset[root][1])

    def _relax(self, iterations, old_mobility, edges, improve=False, cold=False):
        """Run the force solver on the current positions. Returns total link length."""
        roots = list(self.blocks.members)
        xs, ys, cost, self._last_step = layout.relax(
            self._bodies(old_mobility),
            [self.pos[r][0] for r in roots],
            [self.pos[r][1] for r in roots],
            self._springs(edges),
            iterations=iterations,
            spacing=self.spacing,
            leaf_pull=self.leaf_pull,
            improve=improve,
            cold=cold,
            circles=self.circle_repulsion,
            grouped=self.group_by_dungeon,
        )
        for root, x, y in zip(roots, xs, ys):
            self._place_block(root, x, y)
        return cost

    def _keep_centre(self, before):
        """Translate the map so its bounds centre matches `before`."""
        after = self.bounds()
        dx = (before[0] + before[2] - after[0] - after[2]) / 2
        dy = (before[1] + before[3] - after[1] - after[3]) / 2
        for position in self.pos.values():
            position[0] += dx
            position[1] += dy

    def bounds(self):
        if not self.pos:
            return 0, 0, 1, 1
        x0 = min(self.pos[n][0] + self.box(n)[0] for n in self.pos)
        y0 = min(self.pos[n][1] + self.box(n)[1] for n in self.pos)
        x1 = max(self.pos[n][0] + self.box(n)[2] for n in self.pos)
        y1 = max(self.pos[n][1] + self.box(n)[3] for n in self.pos)
        return x0, y0, x1, y1

    def door_dots(self, node):
        """The door dots drawn on a node."""
        lobby_doors = set(self.lobby_door_names())
        dots = []
        for door in self.rooms.doors(node):
            if door in ENTRANCE_ONLY_DOORS or door.startswith("Skull Drop Entrance"):
                continue
            if door in self._seam_doors or not self._door_visible(door):
                continue
            interior = door in INTERIOR_DOORS
            if interior and node in self.compact:
                continue
            linked = door in self._linked_doors or door in lobby_doors
            ox, oy = self.port_offset(door)
            state = DoorState.INTERIOR if interior else DoorState.LINKED if linked else DoorState.OPEN
            dots.append(DoorDot(door, ox, oy, state))
        return dots
