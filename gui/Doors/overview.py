import math
from tkinter import BOTH, BooleanVar, Toplevel, ttk, NW, Canvas
from typing import List, Tuple, TypedDict, Union, Callable
import typing
from PIL import ImageTk, Image, ImageOps, ImageColor
from collections import deque, defaultdict, Counter
import data.doors_sprite_data as doors_sprite_data
from gui.Entrances.overview import SelectState
from data.worlds_data import dungeon_worlds
from data.doors_data import (
    doors_data,
    dark_tiles,
    dungeon_lobbies,
    door_coordinates,
    doors_to_regions,
    regions_to_doors,
    door_coordinates_key,
    mandatory_tiles,
    interior_doors,
    logical_connections,
    falldown_pits,
    vanilla_logical_connections,
    dungeon_warps,
)

from pathlib import Path


BORDER_SIZE = 25
TILE_BORDER_SIZE = 3
MANUAL_REGIONS_ADDED = {
    # "Sewers Secret Room Up Stairs": "Sewers Rat Path",  # Sewer Drop
    # "Skull Small Hall ES": "Skull Back Drop",  # Skull Back Drop
    # "Skull Pot Circle WN": "Skull Pot Circle",  # Skull Pot Circle
    # "Skull Left Drop ES": "Skull Left Drop",  # Skull Left Drop
    # "Skull Pinball NE": "Skull Pinball",  # Skull Pinball
    "Eastern Hint Tile WN": "Eastern Hint Tile Blocked Path",  # Eastern Hint Tile
    "Ice Dead End WS": "Ice Big Key",  # Icebreaker
}

INTERIOR_DOORS = set()
for door_pair in interior_doors:
    INTERIOR_DOORS.add(door_pair[0])
    INTERIOR_DOORS.add(door_pair[1])

item_sheet_path = Path(__file__).parent.parent.parent / "data" / "Doors_Sheet.png"


class DoorData(TypedDict):
    door: str
    source_tile: tuple
    source_coords: tuple
    button: int


class DoorLink(DoorData):
    linked_door: str
    linked_tile: tuple
    linked_coords: tuple


class LobbyData(DoorData):
    lobby: str
    lobby_tile: tuple
    lobby_coords: tuple


class EGTileData(TypedDict):
    # Key =    eg_tile: Tuple[int, int]
    map_tile: Tuple[int, int] | None
    img_obj: ImageTk.PhotoImage | None
    button: int | None  # TKinter button number
    origin: Tuple[int, int] | None
    is_dark: bool
    has_been_lit: bool


def distinct_colours(n):
    """Generate n distinct colours, each with a different hue."""
    hues = [i * 2 * (180 / n) for i in range(n)]
    rgbs = [ImageColor.getrgb(f"hsl({h}, 100%, 50%)") for h in hues]
    hexs = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in rgbs]  # type: ignore
    return hexs


# These data structures drastically need to be cleaned up, but I'm not sure how to do it yet
class DoorPage(ttk.Frame):
    canvas: Canvas
    cwidth: int
    cheight: int
    tile_size: int
    map_dims: tuple[int, int]
    dungeon_name: str

    eg_tile_window: Union[Toplevel, None]
    eg_tile_window_notebook: Union[ttk.Notebook, None]
    eg_tile_multiuse: dict

    eg_selection_mode: bool
    select_state: SelectState
    redraw: bool

    doors: dict[str, str]

    tile_map: list
    disabled_tiles: dict
    door_links: List[DoorLink]
    lobby_doors: list[LobbyData]
    special_doors: dict
    placed_icons: dict
    unlinked_doors: set
    door_buttons: dict
    sanc_dungeon: bool
    x_center_align: int
    old_tiles: dict
    tiles: dict[Tuple[int, int], EGTileData]
    unused_map_tiles: dict
    eg_tile: Union[str, None]
    eg_tile_data: Union[dict, None]
    load_yaml: typing.Callable
    return_connections: typing.Callable
    y_offset: int
    x_offset: int
    source_location: tuple
    show_all_doors: bool
    doors_available: set
    aspect_ratio: tuple[int, int]
    spotsize: int
    linewidth: int
    init_page: Callable
    deactivate_tiles: Callable
    redraw_canvas: Callable
    auto_add_tile: Callable
    auto_draw_player: Callable
    auto_add_door_link: Callable
    auto_add_lobby: Callable
    auto_add_lamp_icon: Callable


def get_tile_data_by_map_tile(
    tiles: dict[Tuple[int, int], EGTileData], map_tile: Tuple[int, int]
) -> Union[Tuple[int, int], None]:
    for eg_tile in tiles:
        if tiles[eg_tile]["map_tile"] == map_tile:
            return eg_tile
    return None


def get_tile_data_by_button(tiles: dict[Tuple[int, int], EGTileData], button: int) -> Union[Tuple[int, int], None]:
    for eg_tile in tiles:
        if "button" in tiles[eg_tile] and tiles[eg_tile]["button"] == button:
            return eg_tile
    return None


disabled_tiles = {}


def door_customizer_page(
    top,
    parent,
    tab_world,
    eg_img=None,
    eg_selection_mode=False,
    vanilla_data=None,
    plando_window=None,
    cdims=(2048, 1024),
    aspect_ratio=(1, 2),
) -> DoorPage:
    def init_page(self: DoorPage, redraw=False) -> None:
        self.select_state = SelectState.NoneSelected
        self.canvas = Canvas(
            self,
            width=self.cwidth + (BORDER_SIZE * 2),
            height=self.cheight + (BORDER_SIZE * 2),
            background="white",
        )
        self.canvas.pack()

        # Draw dungeon name on the map
        dungeon_name = [k for k, v in dungeon_worlds.items() if v == tab_world][0]

        self.canvas.create_text(
            ((self.cwidth + (BORDER_SIZE * 2)) // 2),
            12,
            text=dungeon_name.replace("_", " "),
            anchor="center",
            font=("TkDefaultFont", 12, "bold"),
            tags=["dungeon_name"],
        )

        # Only for EG Map
        self.disabled_tiles = {}

        # Initialise the variables we need
        self.door_links = []
        self.doors = {}
        self.default_doors = {}
        self.lobby_doors = []
        self.special_doors = {}
        self.placed_icons = defaultdict(dict)
        self.unlinked_doors = set()
        self.door_buttons = {}
        self.sanc_dungeon = False
        self.x_center_align = 0
        self.dungeon_name = dungeon_name
        self.tiles = {}

        #  If we're redrawing, we need to keep tiles with no current connections, we store them temporarily in old_tiles
        if redraw:
            self.old_tiles = self.tiles.copy()
            self.redraw = True
        else:
            self.old_tiles = {}
            self.redraw = False

        # Are we plotting the vanilla map? If so, we need leave the vanilla data in place (added when the page is created)
        if self.eg_selection_mode:
            self.tiles = {
                tile: EGTileData(
                    is_dark=tile in dark_tiles,
                    has_been_lit=True,
                    map_tile=tile_data["map_tile"],
                    img_obj=None,
                    button=None,
                    origin=None,
                )
                for tile, tile_data in vanilla_data["tiles"].items()
            }
            # defaultdict(dict, )  # type: ignore

        self.unused_map_tiles = {}

        self.interior_doors_dict = dict(interior_doors)
        self.interior_doors_dict.update(dict([(x[1], x[0]) for x in interior_doors]))

        for door_set in [
            logical_connections,
            interior_doors,
            falldown_pits,
            dungeon_warps,
            vanilla_logical_connections,
        ]:
            self.default_doors.update(door_set)

        # Manual connections go here
        self.default_doors["Ice Bomb Drop Hole"] = "Ice Stalfos Hint Drop Entrance"
        self.default_doors["Ice Crystal Block Hole"] = "Ice Switch Room Drop Entrance"
        self.default_doors["Ice Falling Square Hole"] = "Ice Tall Hint Drop Entrance"
        self.default_doors["Ice Freezors Hole"] = "Ice Big Chest View Drop Entrance"
        self.default_doors["Ice Antechamber Hole"] = "Ice Boss Drop Entrance"
        self.default_doors["PoD Pit Room Bomb Hole"] = "PoD Basement Ledge Drop Entrance"
        self.default_doors["PoD Pit Room Freefall"] = "PoD Stalfos Basement Drop Entrance"
        self.default_doors["Swamp Attic Left Pit"] = "Swamp West Ledge Drop Entrance"
        self.default_doors["Swamp Attic Right Pit"] = "Swamp Barrier Ledge Drop Entrance"
        self.default_doors["Skull Final Drop Hole"] = "Skull Boss Drop Entrance"
        self.default_doors["Mire Torches Bottom Holes"] = "Mire Warping Pool Drop Entrance"
        self.default_doors["Mire Torches Top Holes"] = "Mire Conveyor Barrier Drop Entrance"
        self.default_doors["Mire Attic Hint Hole"] = "Mire BK Chest Ledge Drop Entrance"
        self.default_doors["GT Bob's Room Hole"] = "GT Ice Armos Drop Entrance"
        self.default_doors["GT Falling Torches Hole"] = "GT Staredown Drop Entrance"
        self.default_doors["GT Moldorm Hole"] = "GT Moldorm Pit Drop Entrance"

        self.doors = self.default_doors.copy()

        if self.eg_selection_mode:
            return

        for tile in mandatory_tiles[tab_world]:
            create_eg_tile_data(self, tile)

    # def redraw_canvas(self: DoorPage) -> None:
    #     # yaml = return_connections(self.door_links, self.lobby_doors, self.special_doors)
    #     reload_page(self, self.doors, self.lobby_doors, self. redraw=True)

    def load_yaml(self: DoorPage, yaml_doors: dict, yaml_lobbies):
        for k, v in yaml_doors.items():
            if type(v) == str:
                self.doors[k] = v
                self.doors[v] = k
            elif type(v) == dict:
                source = k
                if "dest" in v:
                    dest = v["dest"]
                else:
                    try:
                        dest = self.interior_doors_dict[source]
                    except KeyError:
                        print("Could not find interior door for " + source)
                        dest = None
                if not dest and "type" in v:
                    self.special_doors[source] = v["type"]
                    continue

                self.doors[source] = dest  # type: ignore
                self.doors[dest] = source  # type: ignore
                if "type" in v:
                    if "type" == "Trap Door":
                        self.special_doors[dest] = v["type"]
                    else:
                        self.special_doors[source] = v["type"]
                        self.special_doors[dest] = v["type"]
                if "one-way" in v:
                    self.special_doors[dest] = "Trap Door"
        for k, v in yaml_lobbies.items():
            self.lobby_doors.append(
                {
                    "door": k,
                    "lobby": v,
                }
            )

    def clean_canvas(self: DoorPage) -> None:
        for tag in [
            "tile_image",
            "door",
            "door_link",
            "background_select",
            "door_icon",
            "hidden_tile",
            "dungeon_name",
            "player",
        ]:
            for item in self.canvas.find_withtag(tag):
                self.canvas.delete(item)

    def redraw_canvas(self: DoorPage):
        doors_processed = set()
        door_links_to_make = set()
        doors_to_process: deque = deque()
        regions_processed = set()
        self.map_dims = (16, 16)

        #  Sort door_links by the "door" key of each dict
        old_door_links = sorted(self.door_links, key=lambda x: x["door"])
        old_lobby_doors = sorted(self.lobby_doors, key=lambda x: x["lobby"])
        old_tiles = dict(sorted(self.tiles.items()))
        self.old_tiles = old_tiles

        clean_canvas(self)
        self.canvas.create_text(
            ((self.cwidth + (BORDER_SIZE * 2)) // 2),
            12,
            text=dungeon_name.replace("_", " "),
            anchor="center",
            font=("TkDefaultFont", 12, "bold"),
            tags=["dungeon_name"],
        )
        # Reset data - We have a copy in the function args
        self.doors = self.default_doors.copy()
        self.lobby_doors = []
        self.tiles = {}
        self.door_links = []

        # Carry over links from old data, might need to just not do this and keep the original in place
        for old_link in old_door_links:
            self.doors[old_link["door"]] = old_link["linked_door"]

        def queue_regions_doors(door: str, is_region=False):
            if not is_region:
                if door in doors_to_regions:
                    # Some doors are in multiple regions
                    if type(doors_to_regions[door]) == list:
                        for r in doors_to_regions[door]:
                            queue_regions_doors(r, is_region=True)
                        return
                    region = doors_to_regions[door]
                else:
                    # print("ERROR: Door not found in doors_to_regions", door)
                    return
            else:
                region = door

            if region in regions_processed:
                return

            region_doors = regions_to_doors[region]

            # Add doors to queue
            for future_door in region_doors:
                if not (
                    future_door == door
                    or future_door in doors_processed
                    or future_door in doors_to_process
                    or future_door in regions_to_doors
                ):
                    doors_to_process.append(future_door)
            regions_processed.add(region)

        while old_lobby_doors:
            lobby_data = old_lobby_doors.pop()
            add_lobby(self, lobby_data["door"], lobby_data["lobby"])
            x, y = get_doors_eg_tile(lobby_data["door"])
            if (x, y) in old_tiles:
                self.tiles[(x, y)]["has_been_lit"] = old_tiles[(x, y)]["has_been_lit"]
                del old_tiles[(x, y)]
            queue_regions_doors(lobby_data["door"])

        # if len(doors_to_process) == 0:
        #     for tile in mandatory_tiles[tab_world]:
        #         create_eg_tile_data(self, tile, old_tiles[tile]["has_been_lit"])
        #         del old_tiles[tile]
        #         for door in door_coordinates[tile]:
        #             doors_to_process.append(door["name"])

        processed_doors = set()
        while True:
            if len(doors_to_process) == 0 and len(old_tiles) == 0:
                break
            if len(doors_to_process) == 0:
                while old_tiles:
                    tile, old_tile = old_tiles.popitem()
                    create_eg_tile_data(self, tile, old_tile["has_been_lit"])
                    for door in door_coordinates[tile]:
                        if door["name"] in doors_processed:
                            print("ERROR 001: This should never have happened!")
                            continue
                        doors_to_process.append(door["name"])
            # I think we can remove this loop - to be testes
            while doors_to_process:
                next_door = doors_to_process.pop()
                print(f"Processing {next_door}")
                processed_doors.add(next_door)

                # We've done all the linked doors from lobbies - do we have any tiles left?

                # We add some manual links here, typically for one way regions
                if next_door in MANUAL_REGIONS_ADDED:
                    queue_regions_doors(MANUAL_REGIONS_ADDED[next_door], is_region=True)

                doors_processed.add(next_door)
                door_eg_tile = get_doors_eg_tile(next_door)

                if door_eg_tile != (None, None):
                    queue_regions_doors(next_door)
                    door_links_to_make.add(next_door)
                else:
                    if next_door not in self.doors:
                        continue
                    _region = self.doors[next_door]
                    if _region not in regions_to_doors:
                        queue_regions_doors(self.doors[next_door])
                    else:
                        queue_regions_doors(self.doors[next_door], is_region=True)

                # Find the door that this door is linked to
                linked_door = None
                for d in [self.doors, {v: k for k, v in self.doors.items()}]:
                    if next_door in d:
                        linked_door = d[next_door]
                        if linked_door not in doors_processed and linked_door not in regions_to_doors:
                            doors_to_process.append(linked_door)

                linked_door_x, linked_door_y = get_doors_eg_tile(linked_door)

                # (Is this a door) or (have we already added the tile)?
                if door_eg_tile == (None, None) or (
                    door_eg_tile in self.tiles and self.tiles[door_eg_tile]["map_tile"] != None
                ):
                    current_lobby_doors = [x["door"] for x in self.lobby_doors]
                    if next_door in dungeon_lobbies[tab_world] and next_door not in current_lobby_doors:
                        # I don't think we ever get here after the first draw is added

                        add_lobby_door(self, next_door, next_door)
                    continue

                # PoD warp tile (Never seen but still linked, start from 0,0)
                if (linked_door_x, linked_door_y) != (None, None) and (
                    (linked_door_x, linked_door_y) in self.tiles
                    and self.tiles[(linked_door_x, linked_door_y)]["map_tile"] != None
                ):
                    new_tile_x, new_tile_y = self.tiles[(linked_door_x, linked_door_y)]["map_tile"]
                else:
                    new_tile_x = new_tile_y = 0

                direction = doors_data[next_door][1]
                last_cardinal = 0

                if door_eg_tile == (None, None):
                    continue

                # TODO: If (prefer_fill_map and map_usage <= 80%) then: find_closest_unused_tile_by_physical_distance() and use that

                # map_dims, x_offset, y_offset, len_x, len_y = calculate_map_dims(self)
                # num_placed_tiles = len([x for x in self.tiles.values() if x["map_tile"] != None])
                # map_usage = (num_placed_tiles / (map_dims[0] * map_dims[1])) * 100
                # prefer_fill_map = True
                # if prefer_fill_map and map_usage <= 80:
                #     current_unused_tiles = []
                #     for i in range(map_dims[0]):
                #         for j in range(map_dims[1]):
                #             if not get_tile_data_by_map_tile(self.tiles, (i, j)):
                #                 current_unused_tiles.append((i + x_offset, j + y_offset))
                #     dists = [
                #         math.sqrt((tile[0] - new_tile_x) ** 2 + (tile[1] - new_tile_y) ** 2)
                #         for tile in current_unused_tiles
                #     ]
                #     closest_idx = dists.index(min(dists))
                #     closest_tile = current_unused_tiles[closest_idx]
                #     while get_tile_data_by_map_tile(self.tiles, closest_tile):
                #         del current_unused_tiles[closest_idx]
                #         closest_idx = dists.index(min(dists))
                #         closest_tile = current_unused_tiles[closest_idx]
                #     new_tile_x, new_tile_y = closest_tile

                # else:
                # Complicated way of finding the nearest tile that isn't already used while respecting directionality
                print(f"Placing {door_eg_tile} ({next_door}), starting at ({new_tile_x}, {new_tile_y})")
                while get_tile_data_by_map_tile(self.tiles, (new_tile_x, new_tile_y)):
                    if (direction == "We" and last_cardinal == 0) or (
                        ((direction == "No" or direction == "Up") or (direction == "So" or direction == "Dn"))
                        and last_cardinal == -1
                    ):
                        new_tile_x += 1
                        print(f"Moving right to ({new_tile_x}, {new_tile_y})")
                    elif (direction == "Ea" and last_cardinal == 0) or (
                        ((direction == "No" or direction == "Up") or (direction == "So" or direction == "Dn"))
                        and last_cardinal == 1
                    ):
                        new_tile_x -= 1
                        print(f"Moving left to ({new_tile_x}, {new_tile_y})")
                    elif ((direction == "No" or direction == "Up") and last_cardinal == 0) or (
                        (direction == "We" or direction == "Ea") and last_cardinal == -1
                    ):
                        new_tile_y += 1
                        print(f"Moving down to ({new_tile_x}, {new_tile_y})")
                    elif ((direction == "So" or direction == "Dn") and last_cardinal == 0) or (
                        (direction == "We" or direction == "Ea") and last_cardinal == 1
                    ):
                        new_tile_y -= 1
                        print(f"Moving up to ({new_tile_x}, {new_tile_y})")
                    if last_cardinal == 0:
                        last_cardinal = -1
                    elif last_cardinal == -1:
                        last_cardinal = 1
                    elif last_cardinal == 1:
                        last_cardinal = 0

                if door_eg_tile in self.tiles:
                    self.tiles[door_eg_tile]["map_tile"] = (new_tile_x, new_tile_y)
                else:
                    print('Adding new EG tile to "tiles"')
                    create_eg_tile_data(
                        self,
                        door_eg_tile,
                        has_been_lit=old_tiles[door_eg_tile]["has_been_lit"] if door_eg_tile in old_tiles else False,
                    )
                    self.tiles[door_eg_tile]["map_tile"] = (
                        new_tile_x,
                        new_tile_y,
                    )
                    if door_eg_tile in old_tiles:
                        del old_tiles[door_eg_tile]

        links_made = set()

        for door in door_links_to_make:
            try:
                linked_door = self.doors[door] if door in self.doors else {v: k for k, v in self.doors.items()}[door]
                if linked_door in links_made or door in links_made:
                    continue
                add_door_link(self, door, linked_door)
                links_made.add(door)
                links_made.add(linked_door)
            except KeyError:
                # Couldn't make link for {door}, possibly a lobby or unlinked
                pass
        for tile in mandatory_tiles[tab_world]:
            if tile not in self.tiles:
                print("ERROR 002: This should never have happened!")
                self.tiles[tile]["map_tile"] = find_first_unused_tile()

        self.doors_available = doors_processed
        draw_map(self)

    def find_first_unused_tile():
        for row in range(self.map_dims[0]):
            for col in range(self.map_dims[1]):
                if not get_tile_data_by_map_tile(self.tiles, (col, row)):
                    return (col, row)
        raise Exception("No unused tiles left")

    def create_eg_tile_data(self: DoorPage, eg_tile: str, has_been_lit=False) -> None:
        if eg_tile in self.tiles:
            return
        self.tiles[eg_tile] = EGTileData(
            is_dark=eg_tile in dark_tiles,
            has_been_lit=has_been_lit,
            map_tile=None,
            img_obj=None,
            button=None,
            origin=None,
        )

    def get_doors_eg_tile(door):
        # Coords are x = left -> right, y = top -> bottom, 0,0 is top left
        if door in doors_data:
            # (found, x, y)
            return (
                int(doors_data[door][0]) % 16,
                int(doors_data[door][0]) // 16,
            )
        else:
            return (None, None)

    def find_map_tile(map_tile: Tuple[int, int]):
        for eg_tile, tile_data in self.tiles.items():
            if tile_data["map_tile"] == map_tile:
                return eg_tile
        return None

    def get_min_max_map_tiles():
        placed_tiles = [tile_data for tile, tile_data in self.tiles.items() if tile_data["map_tile"] != None]
        if len(placed_tiles) == 0:
            return (0, 0, 0, 0)
        min_x = min(placed_tiles, key=lambda x: x["map_tile"][0])["map_tile"][0]
        max_x = max(placed_tiles, key=lambda x: x["map_tile"][0])["map_tile"][0]
        min_y = min(placed_tiles, key=lambda x: x["map_tile"][1])["map_tile"][1]
        max_y = max(placed_tiles, key=lambda x: x["map_tile"][1])["map_tile"][1]
        return min_x, max_x, min_y, max_y

    def add_lobby(self: DoorPage, lobby_room: str, lobby: str):
        x, y = get_doors_eg_tile(lobby_room)
        if x == None or y == None:
            return

        if (x, y) in self.tiles:
            add_lobby_door(self, lobby_room, lobby)
            return
        else:
            self.tiles[(x, y)] = EGTileData(
                is_dark=(x, y) in dark_tiles,
                has_been_lit=self.old_tiles[(x, y)]["has_been_lit"] if (x, y) in self.old_tiles else False,
                map_tile=None,
                img_obj=None,
                button=None,
                origin=None,
            )

        # Have we placed any tiles yet? i.e. another lobby TODO: Add South/North here
        if find_map_tile((0, 0)):
            min_x, max_x, min_y, max_y = get_min_max_map_tiles()
            if "East" in lobby:
                tile_x = max_x + 1
            else:
                tile_x = min_x - 1
            self.tiles[(x, y)]["map_tile"] = (tile_x, 0)
        else:
            self.tiles[(x, y)] = EGTileData(
                is_dark=(x, y) in dark_tiles,
                has_been_lit=self.old_tiles[(x, y)]["has_been_lit"] if (x, y) in self.old_tiles else False,
                map_tile=(0, 0),
                img_obj=None,
                button=None,
                origin=None,
            )
        add_lobby_door(self, lobby_room, lobby)

    def remove_eg_tile(self: DoorPage, event):
        button = self.canvas.find_closest(event.x, event.y)[0]
        eg_tile = get_tile_data_by_button(self.tiles, button)
        if not eg_tile or eg_tile in mandatory_tiles[tab_world]:
            return
        self.canvas.delete(button)
        del self.tiles[eg_tile]
        for page in top.eg_tile_window.pages.values():
            if eg_tile in page.content.tiles:
                page.content.deactivate_tiles(page.content, top.eg_tile_multiuse, top.disabled_eg_tiles)

        # find doors in this tile:
        for door in door_coordinates[eg_tile]:
            if door["name"] == "Sanctuary Mirror Route":
                continue
            self.unlinked_doors.remove(door["name"])
            if door["name"] in self.special_doors:
                icon_idx = [k for k, v in self.placed_icons.items() if v["name"] == door["name"]][0]
                del self.placed_icons[icon_idx]
                del self.special_doors[door["name"]]
            _lobby_doors = [x["door"] for x in self.lobby_doors]
            if door["name"] in _lobby_doors:
                del self.lobby_doors[_lobby_doors.index(door["name"])]
            while True:
                _dl_idx, _door_link = get_link_by_door(door["name"])  # type: ignore
                if not _door_link or not _dl_idx:
                    if not door["name"] == "Sanctuary Mirror Route":
                        self.canvas.delete(self.door_buttons[door["name"]])
                    break
                self.canvas.delete(_door_link["button"])  # type: ignore
                # Set colors back to normal
                if _door_link["door"] == door["name"]:
                    self.canvas.itemconfigure(self.door_buttons[_door_link["linked_door"]], fill="#0f0")
                    self.canvas.delete(self.door_buttons[_door_link["door"]])
                else:
                    self.canvas.itemconfigure(self.door_buttons[_door_link["door"]], fill="#0f0")
                    self.canvas.delete(self.door_buttons[_door_link["linked_door"]])
                del self.door_links[_dl_idx]
                for _d in [_door_link["door"], _door_link["linked_door"]]:
                    if _d in self.special_doors:
                        del self.special_doors[_d]

    def disable_eg_tile(self: DoorPage, event):
        button = self.canvas.find_closest(event.x, event.y)[0]
        eg_tile = get_tile_data_by_button(self.tiles, button)
        if not eg_tile or eg_tile in mandatory_tiles[tab_world]:
            return
        disabled_tiles[eg_tile] = {}
        redraw_canvas(self)

    def reenable_eg_tile(self: DoorPage, event):
        button = self.canvas.find_closest(event.x, event.y)[0]
        for _tile, _data in disabled_tiles.items():
            if _data == button:
                del disabled_tiles[_tile]
                redraw_canvas(self)
                return

    def add_eg_tile_img(
        self: DoorPage,
        x: int,
        y: int,
        tile_x: int,
        tile_y: int,
        ci_kwargs={},
    ):
        x1 = (tile_x * self.tile_size) + BORDER_SIZE + (((2 * tile_x + 1) - 1) * TILE_BORDER_SIZE) + self.x_center_align
        y1 = (tile_y * self.tile_size) + BORDER_SIZE + (((2 * tile_y + 1) - 1) * TILE_BORDER_SIZE)

        if not eg_img:
            return

        img = ImageTk.PhotoImage(
            eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).resize(
                (self.tile_size, self.tile_size), Image.ANTIALIAS
            )
        )
        if self.tiles[(x, y)]["is_dark"] and self.eg_selection_mode:
            self.canvas.create_rectangle(
                x1 - TILE_BORDER_SIZE,
                y1 - TILE_BORDER_SIZE,
                x1 + self.tile_size + TILE_BORDER_SIZE,
                y1 + self.tile_size + TILE_BORDER_SIZE,
                fill="#f00",
                tags=["dark_tile"],
            )
        map = self.canvas.create_image(x1, y1, image=img, anchor=NW, tags=["tile_image"], **ci_kwargs)
        # TODO: Add the doors for a hidden tile and the code to unhide it. Tags should probably include tileid
        if self.tiles[(x, y)]["is_dark"] and not self.tiles[(x, y)]["has_been_lit"]:
            rect = self.canvas.create_rectangle(
                x1,
                y1,
                x1 + self.tile_size,
                y1 + self.tile_size,
                fill="#000",
                tags=["hidden_tile"],
            )
            self.tiles[(x, y)]["origin"] = (x1, y1)
            self.tiles[(x, y)]["button"] = rect
            return

        if (x, y) in disabled_tiles:
            rect = self.canvas.create_rectangle(
                x1,
                y1,
                x1 + self.tile_size,
                y1 + self.tile_size,
                fill="#888",
                stipple="gray25",
                tags=["disabled_tile"],
            )
            disabled_tiles[(x, y)] = rect
            self.canvas.tag_bind(rect, "<Button-2>", lambda event: reenable_eg_tile(self, event))
        if not self.eg_selection_mode:
            self.canvas.tag_bind(map, "<Control-Button-3>", lambda event: remove_eg_tile(self, event))
            self.canvas.tag_bind(map, "<Button-2>", lambda event: disable_eg_tile(self, event))
        else:
            self.canvas.tag_bind(
                map,
                "<Button-1>",
                lambda event: select_eg_tile(self, top, event, plando_window),
            )
        self.tiles[(x, y)]["img_obj"] = img
        self.tiles[(x, y)]["button"] = map
        self.tiles[(x, y)]["origin"] = (x1, y1)
        return

    def draw_vanilla_eg_map(self: DoorPage, top):
        for (eg_tile_x, eg_tile_y), tile_data in self.tiles.items():
            if tile_data["map_tile"] == None:
                continue
            x, y = tile_data["map_tile"]
            add_eg_tile_img(self, eg_tile_x, eg_tile_y, x + self.x_offset, y + self.y_offset)

    def get_door_coords(door):
        eg_tile, list_pos = door_coordinates_key[door]
        return door_coordinates[eg_tile][list_pos]

    def draw_empty_map(self: DoorPage):
        for row in range(self.map_dims[0]):
            for col in range(self.map_dims[1]):
                if get_tile_data_by_map_tile(self.tiles, (col - self.x_offset, row - self.y_offset)):
                    continue

                x1 = (
                    (col * self.tile_size)
                    + BORDER_SIZE
                    + (((2 * col + 1) - 1) * TILE_BORDER_SIZE)
                    + self.x_center_align
                )
                y1 = (row * self.tile_size) + BORDER_SIZE + (((2 * row + 1) - 1) * TILE_BORDER_SIZE)
                tile = self.canvas.create_rectangle(
                    x1,
                    y1,
                    x1 + self.tile_size,
                    y1 + self.tile_size,
                    outline="",
                    fill=f"#888",
                    activefill=f"#BBB",
                    tags=["background_select"],
                )
                # _ = self.canvas.create_text(
                #     x1 + self.tile_size / 2,
                #     y1 + self.tile_size / 2,
                #     text=f"{tile} - {col - self.x_offset}, {row - self.y_offset}",
                #     fill="white",
                #     font=("TkDefaultFont", 8),
                # )
                self.canvas.tag_bind(tile, "<Button-1>", lambda event: select_tile(self, event))
                self.canvas.tag_lower(tile)
                self.unused_map_tiles[(col, row)] = tile

    def calculate_map_dims(self: DoorPage):
        aspect_ratio = self.aspect_ratio
        if len(self.tiles) > 0:
            # Get the min x and y values
            min_x, max_x, min_y, max_y = get_min_max_map_tiles()
        else:
            # No tiles to plot, make an empty map
            min_x = min_y = 0
            max_x = aspect_ratio[1]
            max_y = aspect_ratio[0]

        len_x = max((max_x - min_x), aspect_ratio[1]) + 1
        len_y = max((max_y - min_y), aspect_ratio[0]) + 1
        x_offset = abs(min_x) if min_x < 0 else 0
        y_offset = abs(min_y) if min_y < 0 else 0

        #  dims = (rows, columns), (y, x)
        aspect_ratio_multiplier = aspect_ratio[1] / aspect_ratio[0]
        if len_x >= len_y * aspect_ratio_multiplier:
            map_dims = int((len_x // aspect_ratio_multiplier) + 1), int(
                ((len_x // aspect_ratio_multiplier) + 1) * aspect_ratio_multiplier
            )
        else:
            map_dims = (len_y, int(len_y * aspect_ratio_multiplier))

        return map_dims, x_offset, y_offset, len_x, len_y

    def draw_map(self: DoorPage):
        # Firstly are any tiles without a map_tile?
        if len([tile_data for tile, tile_data in self.tiles.items() if tile_data["map_tile"] == None]) > 0:
            print(
                "ERROR 003: We have a tile without a position. This should only happen when we have a tile with no doors (i.e. Eastern Fairies)"
            )
            for tile in self.tiles.keys():
                if self.tiles[tile]["map_tile"] == None:
                    self.tiles[tile]["map_tile"] = find_first_unused_tile()

        # Secondly, are there any overlapping tiles?
        if len(self.tiles) != len(set([tile_data["map_tile"] for tile, tile_data in self.tiles.items()])):
            print("ERROR 004: Multiple tiles have the same map_tile. This should never have happened!")
            c = Counter([tile_data["map_tile"] for tile, tile_data in self.tiles.items()])
            to_fix = [k for k, v in c.items() if v > 1]
            for map_tile in to_fix:
                tiles_to_fix = [tile for tile, tile_data in self.tiles.items() if tile_data["map_tile"] == map_tile]
                tiles_to_fix.pop(0)  # Leave the first one in place
                for tile in tiles_to_fix:
                    self.tiles[tile]["map_tile"] = find_first_unused_tile()

        self.x_center_align = 0
        # x is columns, y is rows
        icon_queue = []

        map_dims, x_offset, y_offset, len_x, len_y = calculate_map_dims(self)
        self.map_dims = map_dims

        y_offset += (self.map_dims[0] - len_y) // 2
        x_offset += (self.map_dims[1] - len_x) // 2
        self.y_offset = y_offset
        self.x_offset = x_offset

        self.tile_size = min((self.cwidth // (self.map_dims[1])), (self.cheight // (self.map_dims[0]))) - (
            TILE_BORDER_SIZE * 2
        )
        # recorrect x_offset to center map with unsual aspect ratios
        total_tile_width = (self.tile_size + (TILE_BORDER_SIZE * 2)) * self.map_dims[1] + x_offset
        if total_tile_width < self.cwidth:
            self.x_center_align += (self.cwidth - total_tile_width) // 2

        # This stores the x, y coords that we're plotting to and the eg x,y coords of the tile we're plotting
        self.tile_map = []

        #  Add any old tiles, with no connections to the tiles to be plotted. Put them in the first empty space
        # for tile, tile_data in self.old_tiles.items():
        #     if (tile in self.tiles and "map_tile" in self.tiles[tile]) or len(tile_data) == 0:
        #         continue
        #     self.tiles[tile]["map_tile"] = find_first_unused_tile()
        # self.old_tiles = {}

        for (eg_x, eg_y), tile_data in self.tiles.items():
            try:
                tile_x, tile_y = tile_data["map_tile"]
            except TypeError:
                print("ERROR 005: This should never have happened!")
                continue
            if eg_x == None or eg_y == None:
                continue

            tile_x += x_offset
            tile_y += y_offset
            add_eg_tile_img(self, eg_x, eg_y, tile_x, tile_y)

        for door, data in doors_data.items():
            if (
                hasattr(self, "doors_available")
                and door not in self.doors_available
                and len(self.lobby_doors) > 0
                and not self.show_all_doors
            ):
                continue

            d_eg_x = int(data[0]) % 16
            d_eg_y = int(data[0]) // 16
            if (d_eg_x, d_eg_y) not in self.tiles or "img_obj" not in self.tiles[(d_eg_x, d_eg_y)]:
                continue

            _data = create_door_dict(door)

            x1, y1 = get_final_door_coords(self, _data, "source", x_offset, y_offset)
            if door in self.special_doors:
                if "Drop" in door:
                    icon_queue.append(("Drop", x1, y1, door))
                else:
                    icon_queue.append((self.special_doors[door], x1, y1, door))
            if door == "Sanctuary Mirror Route" or door.startswith("Skull Drop Entrance") or door == "Sewer Drop":
                continue
            spotsize = self.spotsize * 0.75 if door in INTERIOR_DOORS else self.spotsize
            self.door_buttons[door] = self.canvas.create_oval(
                x1 - spotsize,
                y1 - spotsize,
                x1 + spotsize,
                y1 + spotsize,
                fill="#008" if door in INTERIOR_DOORS else "#0f0",
                width=2,
                activefill="red",
                tags=["door"],
            )
            self.unlinked_doors.add(door)
            if door not in INTERIOR_DOORS:
                self.canvas.tag_bind(
                    self.door_buttons[door],
                    "<Button-1>",
                    lambda event: select_location(self, event),
                )
            self.canvas.tag_bind(
                self.door_buttons[door],
                "<Button-3>",
                lambda event: show_door_icons(self, event),
            )

        # Display links between doors here
        doors_linked = set()
        link_colours = distinct_colours(len(self.door_links))
        for n, door_link in enumerate(self.door_links):
            x1, y1 = get_final_door_coords(self, door_link, "source", x_offset, y_offset)
            x2, y2 = get_final_door_coords(self, door_link, "linked", x_offset, y_offset)
            self.door_links[n]["button"] = self.canvas.create_line(
                x1,
                y1,
                x2,
                y2,
                fill="black" if door_link["door"] in INTERIOR_DOORS else link_colours[n],
                width=self.linewidth * 0.5 if door_link["door"] in INTERIOR_DOORS else self.linewidth,
                arrow=BOTH,
                activefill="red",
                dash=(2, 2) if door_link["door"] in INTERIOR_DOORS else (),
                tags=["door_link"],
            )
            if door_link["door"] not in INTERIOR_DOORS:
                self.canvas.tag_bind(
                    self.door_links[n]["button"],
                    "<Button-3>",
                    lambda event: remove_door_link(self, event),
                )

            # TODO: Refactor this
            doors_linked.add(door_link["door"])
            doors_linked.add(door_link["linked_door"])
            try:
                self.unlinked_doors.remove(door_link["door"])
                self.unlinked_doors.remove(door_link["linked_door"])
            except KeyError:
                pass

            try:
                self.canvas.itemconfigure(self.door_buttons[door_link["door"]], fill="grey")
            except KeyError:
                print(f"Error setting door {door_link['door']} to grey")

            try:
                self.canvas.itemconfigure(self.door_buttons[door_link["linked_door"]], fill="grey")
            except KeyError:
                print(f"Error setting door {door_link['linked_door']} to grey")

            if door_link["door"] in self.special_doors:
                icon_queue.append((self.special_doors[door_link["door"]], x1, y1, door_link["door"]))
            if door_link["linked_door"] in self.special_doors:
                icon_queue.append(
                    (
                        self.special_doors[door_link["linked_door"]],
                        x1,
                        y1,
                        door_link["linked_door"],
                    )
                )

        for n, lobby in enumerate(self.lobby_doors):
            x1, y1 = get_final_door_coords(self, lobby, "source", x_offset, y_offset)
            if "Drop" in lobby["lobby"]:
                lobby_icon = "Drop"
            else:
                lobby_icon = lobby["lobby"]
            icon_queue.append((lobby_icon, x1, y1, lobby["door"]))
            doors_linked.add(lobby["door"])
            doors_linked.add(lobby["lobby"])

        icon_queue = list(set(icon_queue))

        while icon_queue:
            icon, eg_x, eg_y, loc_name = icon_queue.pop()
            place_door_icon(self, icon, eg_x, eg_y, loc_name)

        # Draw the empty map
        draw_empty_map(self)

    def get_final_door_coords(self: DoorPage, door: DoorLink | LobbyData, door_type, min_x, min_y):
        tile = "source_tile"
        coords = "source_coords"
        door_key = "door"
        if door_type == "linked":
            tile = "linked_tile"
            coords = "linked_coords"
            door_key = "linked_door"

        door_eg = get_doors_eg_tile(door[door_key])
        door_tile_x = door[tile][0] + (min_x)
        door_tile_y = door[tile][1] + (min_y)
        if self.tiles[door_eg]["is_dark"] and not self.tiles[door_eg]["has_been_lit"]:
            _x = 0.5
            _y = 0.5
        else:
            _x = door[coords][0] / 512
            _y = door[coords][1] / 512

        x = (
            (_x * self.tile_size)
            + ((door_tile_x * self.tile_size) + BORDER_SIZE + (((2 * door_tile_x + 1) - 1) * TILE_BORDER_SIZE))
            + self.x_center_align
        )
        y = (_y * self.tile_size) + (
            (door_tile_y * self.tile_size) + BORDER_SIZE + (((2 * door_tile_y + 1) - 1) * TILE_BORDER_SIZE)
        )
        return x, y

    def add_door_link(self: DoorPage, door, linked_door):
        try:
            link_data = create_door_dict(door)
            link_data.update(create_door_dict(linked_door, linked=True))  # type: ignore
            self.door_links.append(link_data)
        except:
            print(f"Error adding door link for {door} and {linked_door}")

    def add_lobby_door(self: DoorPage, door, lobby):
        d_data = typing.cast(LobbyData, create_door_dict(door))
        d_data["lobby"] = lobby
        self.lobby_doors.append(d_data)
        self.special_doors[door] = lobby

    def get_loc_by_button(self: DoorPage, button) -> str:
        for name, loc in self.door_buttons.items():
            if loc == button[0]:
                return name
        return ""

    def show_door_icons(self: DoorPage, event):
        door = self.canvas.find_closest(event.x, event.y)
        loc_name = get_loc_by_button(self, door)
        selected_item = doors_sprite_data.show_sprites(self, top, event, tab_world)
        if selected_item in doors_sprite_data.all_dungeon_lobbies or selected_item == "Drop":
            lobby = selected_item
            add_lobby_door(self, loc_name, lobby)

            x_loc, y_loc = get_final_door_coords(self, self.lobby_doors[-1], "source", self.x_offset, self.y_offset)
            if "Drop" in loc_name:
                self.special_doors[loc_name] = "Drop"
            else:
                self.special_doors[loc_name] = lobby
        else:
            _data = create_door_dict(loc_name)
            x_loc, y_loc = get_final_door_coords(self, _data, "source", self.x_offset, self.y_offset)
            self.special_doors[loc_name] = selected_item
        place_door_icon(self, selected_item, x_loc, y_loc, loc_name)

    def place_door_icon(self: DoorPage, placed_icon, x_loc, y_loc, loc_name):
        # self.canvas.itemconfigure(item, state="hidden")

        # Place a new sprite
        if placed_icon == None:
            return
        sprite_y, sprite_x = doors_sprite_data.all_icons[placed_icon]
        self.placed_icons[(x_loc, y_loc)]["sprite"] = ImageTk.PhotoImage(
            ImageOps.expand(
                Image.open(item_sheet_path).crop(
                    (
                        sprite_x * 16,
                        sprite_y * 16,
                        sprite_x * 16 + 16,
                        sprite_y * 16 + 16,
                    )
                ),
                1,
                "#fff",
            )
        )
        self.placed_icons[(x_loc, y_loc)]["name"] = loc_name
        image = self.canvas.create_image(
            x_loc,
            y_loc,
            image=self.placed_icons[(x_loc, y_loc)]["sprite"],
            tags=["door_icon"],
        )
        self.placed_icons[(x_loc, y_loc)]["image"] = image
        if placed_icon == "Sanctuary_Mirror":
            return
        self.canvas.tag_bind(
            self.placed_icons[(x_loc, y_loc)]["image"],
            "<Button-3>",
            lambda event: remove_item(self, event, image, loc_name),
        )

    def remove_item(self: DoorPage, event, image, loc_name):
        self.canvas.delete(image)
        for loc, data in self.placed_icons.items():
            if data["name"] == loc_name:
                if self.special_doors[loc_name] in doors_sprite_data.all_dungeon_lobbies:
                    _lobby_doors = [x["door"] for x in self.lobby_doors]
                    del self.lobby_doors[_lobby_doors.index(loc_name)]
                del self.special_doors[loc_name]
                del self.placed_icons[loc]
                break

    def select_location(self: DoorPage, event):
        door = self.canvas.find_closest(event.x, event.y)

        # Catch when the user clicks on the world rather than a location
        if door[0] not in self.door_buttons.values():
            return

        # Get the location name from the button
        loc_name = get_loc_by_button(self, door)
        if loc_name in [x["door"] for x in self.door_links] + [x["linked_door"] for x in self.door_links] + [
            x["door"] for x in self.lobby_doors
        ]:
            return

        if self.select_state == SelectState.NoneSelected:
            self.canvas.itemconfigure(door, fill="orange")  # type: ignore
            self.select_state = SelectState.SourceSelected
            self.source_location = door
        elif self.select_state == SelectState.SourceSelected:
            if door == self.source_location:
                select_tile(self, event, find_unused=True)
            if has_target(self, loc_name) or self.source_location == door:
                return
            add_door_link(self, get_loc_by_button(self, self.source_location), loc_name)
            draw_latest_door_link(self, loc_name)

    def draw_latest_door_link(self: DoorPage, loc_name):
        last_link = self.door_links[-1]
        x1, y1 = get_final_door_coords(self, last_link, "source", self.x_offset, self.y_offset)
        x2, y2 = get_final_door_coords(self, last_link, "linked", self.x_offset, self.y_offset)
        last_link["button"] = self.canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill="black" if last_link["door"] in INTERIOR_DOORS else distinct_colours(1)[0],
            width=self.linewidth * 0.5 if last_link["door"] in INTERIOR_DOORS else self.linewidth,
            arrow=BOTH,
            activefill="red",
            dash=(2, 2) if last_link["door"] in INTERIOR_DOORS else (),
            tags=["door_link"],
        )
        if last_link["door"] not in INTERIOR_DOORS:
            self.canvas.tag_bind(
                last_link["button"],
                "<Button-3>",
                lambda event: remove_door_link(self, event),
            )
        self.select_state = SelectState.NoneSelected
        self.canvas.itemconfigure(self.door_buttons[last_link["door"]], fill="grey")
        self.canvas.itemconfigure(self.door_buttons[last_link["linked_door"]], fill="grey")  # type: ignore

    def auto_add_door_link(self: DoorPage, door, linked_door):
        for d in [door, linked_door]:
            if has_target(self, d) or d in INTERIOR_DOORS or d in [x["door"] for x in self.lobby_doors] or d == None:
                return

        _valid_links = [
            {"So", "No"},
            {"Ea", "We"},
            {"Up", "Dn"},
            {"Up", "Up"},
            {"Dn", "Dn"},
        ]
        directions = {doors_data[door][1], doors_data[linked_door][1]}

        if directions not in _valid_links:
            return

        add_door_link(self, door, linked_door)
        # draw_latest_door_link(self, linked_door)
        redraw_canvas(self)

    def auto_add_lobby(self: DoorPage, door):
        current_lobby_doors = [x["door"] for x in self.lobby_doors]
        current_lobbies = [x["lobby"] for x in self.lobby_doors]
        if (
            door in current_lobby_doors
            or door == None
            or door in INTERIOR_DOORS
            or doors_data[door][1] in ["No", "We", "Ea", "Up", "Dn"]
        ):
            return

        for possible_lobby in dungeon_lobbies[tab_world]:
            if possible_lobby not in current_lobbies:
                lobby = possible_lobby
                break
        if "Drop" in door:
            lobby_icon = "Drop"
        elif "Sanctuary Mirror Route" in door:
            lobby_icon = "Sanctuary_Mirror"
        else:
            lobby_icon = lobby
        add_lobby_door(self, door, lobby)
        x_loc, y_loc = get_final_door_coords(self, self.lobby_doors[-1], "source", self.x_offset, self.y_offset)
        # Find used lobbies

        place_door_icon(self, lobby_icon, x_loc, y_loc, lobby)

        redraw_canvas(self)

    def auto_add_lamp_icon(self: DoorPage, door, icon="Lamp"):
        if door in INTERIOR_DOORS or door == None:
            return
        if door in self.special_doors:
            icon_idx = [k for k, v in self.placed_icons.items() if v["name"] == door][0]
            del self.placed_icons[icon_idx]
            del self.special_doors[door]
        _data = create_door_dict(door)
        x_loc, y_loc = get_final_door_coords(self, _data, "source", self.x_offset, self.y_offset)
        self.special_doors[door] = icon
        place_door_icon(self, icon, x_loc, y_loc, door)

    def has_target(self: DoorPage, loc_name):
        linked_doors = set()
        for data in self.door_links:
            linked_doors.add(data["door"])
            if "linked_door" in data:
                linked_doors.add(data["linked_door"])
        return loc_name in linked_doors

    def return_connections(door_links, lobby_doors, special_doors):
        final_connections = {"doors": {}, "lobbies": {}, "dungeon": tab_world}
        special_doors_remaining = special_doors.copy()

        for data in door_links:
            door = data["door"]
            linked_door = data["linked_door"]
            if "Drop Entrance" in door or "Drop Entrance" in linked_door:
                continue
            final_connections["doors"][door] = linked_door
            if door in special_doors:
                door_type = special_doors[door]
                final_connections["doors"][door] = {
                    "dest": final_connections["doors"][door],
                    "type": door_type,
                }
                special_doors_remaining.pop(door)
            # Also checked linked doors
            elif linked_door in special_doors:
                door_type = special_doors[linked_door]
                final_connections["doors"][linked_door] = {
                    "dest": final_connections["doors"][linked_door],
                    "type": door_type,
                }
                special_doors_remaining.pop(linked_door)

        for lobby_data in lobby_doors:
            lobby = lobby_data["lobby"]
            if lobby == "Sanctuary_Mirror":
                lobby_door = "Sanctuary Mirror Route"
                final_connections["lobbies"][lobby] = {v: k for k, v in dungeon_worlds.items()}[
                    tab_world
                ]  # Add dungeon name instead of door name
            else:
                lobby_door = lobby_data["door"]
                final_connections["lobbies"][lobby] = lobby_door
                print(f"Added {lobby_door} to {self.dungeon_name} as {lobby}")
            try:
                special_doors_remaining.pop(lobby_door)
            except:
                print("We should never get here because nobody should link a door to a lobby")
                pass

        for door in special_doors_remaining:
            final_connections["doors"][door] = {"type": special_doors[door]}

        return final_connections

    def remove_door_link(self: DoorPage, event):
        link = self.canvas.find_closest(event.x, event.y)
        for data in self.door_links:
            if data["button"] == link[0]:
                self.door_links.remove(data)
                self.canvas.delete(link[0])  # type: ignore
                # Set colors back to normal
                self.canvas.itemconfigure(self.door_buttons[data["door"]], fill="#0f0")
                self.canvas.itemconfigure(self.door_buttons[data["linked_door"]], fill="#0f0")
                break

    def deactivate_tiles(self: DoorPage, eg_tile_multiuse, disabled_eg_tiles, temp_disabled_eg_tiles=[]):
        total_used_tiles = defaultdict(int)
        for page in top.pages.values():
            for tile, tile_data in page.content.tiles.items():
                if tile_data["map_tile"] != None:
                    total_used_tiles[tile] += 1
        for tile in self.tiles:
            if total_used_tiles[tile] < eg_tile_multiuse[tile] and tile not in temp_disabled_eg_tiles:
                if tile in disabled_eg_tiles:
                    self.canvas.delete(disabled_eg_tiles[tile])  # type: ignore
                    del disabled_eg_tiles[tile]
                continue
            elif tile in disabled_eg_tiles:
                continue
            tile_x, tile_y = self.tiles[tile]["map_tile"]
            tile_x += self.x_offset
            tile_y += self.y_offset

            x1 = (
                (tile_x * self.tile_size)
                + BORDER_SIZE
                + (((2 * tile_x + 1) - 1) * TILE_BORDER_SIZE)
                + self.x_center_align
            )
            y1 = (tile_y * self.tile_size) + BORDER_SIZE + (((2 * tile_y + 1) - 1) * TILE_BORDER_SIZE)
            x2 = x1 + self.tile_size
            y2 = y1 + self.tile_size
            rect = self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                fill="#888",
                stipple="gray25",
                state="disabled",
                tags=["disabled_tile"],
            )
            disabled_eg_tiles[tile] = rect

    def select_tile(self: DoorPage, event, find_unused=False):
        parent.setvar("selected_eg_tile", BooleanVar(value=False))  # type: ignore
        tiles_in_dungeon = [tile for tile in self.tiles if self.tiles[tile]["map_tile"] != None]
        for page in top.eg_tile_window.pages.values():
            page.content.deactivate_tiles(
                page.content,
                top.eg_tile_multiuse,
                top.disabled_eg_tiles,
                temp_disabled_eg_tiles=tiles_in_dungeon,
            )

        top.eg_tile_window.deiconify()
        top.eg_tile_window.focus_set()
        top.eg_tile_window.grab_set()
        # self.eg_tile_window.wait_visibility(self.eg_tile_window)
        parent.master.wait_variable("selected_eg_tile")
        if not hasattr(parent.master, "selected_eg_tile"):
            return
        selected_eg_tile = parent.master.selected_eg_tile

        bg_tiles = self.canvas.find_withtag("background_select")
        if not find_unused:
            empty_tile_button = self.canvas.find_closest(event.x, event.y)[0]
            if empty_tile_button not in bg_tiles:
                while empty_tile_button not in bg_tiles:
                    empty_tile_button = self.canvas.find_below(empty_tile_button)  # type: ignore
            (tile_x, tile_y) = [k for k, v in self.unused_map_tiles.items() if v == empty_tile_button][0]
        else:
            tile = find_first_unused_tile()
            if tile is None:
                print("No unused tiles left")
                return
            tile_x, tile_y = tile
            empty_tile_button = self.unused_map_tiles[tile]

        x, y = selected_eg_tile

        # We've selected the tile manually, it should not be dark
        self.tiles[selected_eg_tile] = EGTileData(
            is_dark=selected_eg_tile in dark_tiles,
            has_been_lit=True,
            map_tile=(tile_x, tile_y),
            img_obj=None,
            button=None,
            origin=None,
        )
        add_eg_tile_img(self, x, y, tile_x, tile_y)
        self.tiles[selected_eg_tile]["map_tile"] = (
            tile_x - self.x_offset,
            tile_y - self.y_offset,
        )

        parent.master.setvar("selected_eg_tile", BooleanVar(value=False))  # type: ignore
        delattr(parent.master, "selected_eg_tile")
        add_new_doors(self)

    def auto_add_tile(self, selected_eg_tile, was_lit=False):
        tile_x = tile_y = 0
        for tile in self.unused_map_tiles:
            if tile not in [
                self.tiles[tile]["map_tile"] for tile in self.tiles if self.tiles[tile]["map_tile"] != None
            ]:
                tile_x, tile_y = tile
                empty_tile_button = self.unused_map_tiles[tile]
                break

        x, y = selected_eg_tile
        self.canvas.delete(empty_tile_button)
        self.unused_map_tiles.pop((tile_x, tile_y))

        # Add clicked EG tile to clicked empty tile, this function IS needed
        self.tiles[selected_eg_tile] = EGTileData(
            is_dark=selected_eg_tile in dark_tiles,
            has_been_lit=was_lit,
            map_tile=None,
            img_obj=None,
            button=None,
            origin=None,
        )
        add_eg_tile_img(self, x, y, tile_x, tile_y)
        self.tiles[selected_eg_tile]["map_tile"] = (
            tile_x - self.x_offset,
            tile_y - self.y_offset,
        )
        add_new_doors(self)

    def add_new_doors(self: DoorPage):
        # Draw any _new_ unlinked doors
        for door, data in doors_data.items():
            if (
                door
                not in [dl["door"] for dl in self.door_links]
                + [dl["linked_door"] for dl in self.door_links]
                + [ld["door"] for ld in self.lobby_doors]
                and door not in self.unlinked_doors
            ):
                d_eg_x = int(data[0]) % 16
                d_eg_y = int(data[0]) // 16
                if (d_eg_x, d_eg_y) not in self.tiles or "img_obj" not in self.tiles[(d_eg_x, d_eg_y)]:
                    continue
                current_lobby_doors = [x["door"] for x in self.lobby_doors]
                if door.startswith("Sanctuary") and not self.sanc_dungeon:
                    self.sanc_dungeon = True
                    if door in current_lobby_doors:
                        continue
                    add_lobby_door(self, "Sanctuary Mirror Route", "Sanctuary_Mirror")
                    x1, y1 = get_final_door_coords(
                        self,
                        self.lobby_doors[-1],
                        "source",
                        self.x_offset,
                        self.y_offset,
                    )
                    place_door_icon(self, "Sanctuary_Mirror", x1, y1, "Sanctuary Mirror Route")
                    if door == "Sanctuary Mirror Route":
                        continue

                if "Drop" in door and door in dungeon_lobbies[tab_world] and door not in current_lobby_doors:
                    add_lobby_door(self, door, door)
                    x1, y1 = get_final_door_coords(
                        self,
                        self.lobby_doors[-1],
                        "source",
                        self.x_offset,
                        self.y_offset,
                    )
                    place_door_icon(self, "Drop", x1, y1, door)
                    continue

                _data = create_door_dict(door)

                x1, y1 = get_final_door_coords(self, _data, "source", self.x_offset, self.y_offset)
                spotsize = self.spotsize * 0.75 if door in INTERIOR_DOORS else self.spotsize
                self.door_buttons[door] = self.canvas.create_oval(
                    x1 - spotsize,
                    y1 - spotsize,
                    x1 + spotsize,
                    y1 + spotsize,
                    fill="#008" if door in INTERIOR_DOORS else "#0f0",
                    width=2,
                    activefill="red",
                    tags=["door"],
                )
                self.unlinked_doors.add(door)
                if door not in INTERIOR_DOORS:
                    self.canvas.tag_bind(
                        self.door_buttons[door],
                        "<Button-1>",
                        lambda event: select_location(self, event),
                    )
                self.canvas.tag_bind(
                    self.door_buttons[door],
                    "<Button-3>",
                    lambda event: show_door_icons(self, event),
                )

    def create_door_dict(door, linked=False) -> DoorLink:
        d_data = get_door_coords(door)
        d_eg_x, d_eg_y = door_coordinates_key[door][0]
        d_t_x, d_t_y = self.tiles[(d_eg_x, d_eg_y)]["map_tile"]
        data: DoorLink = {
            "linked_door" if linked else "door": door,  # type: ignore
            "linked_tile" if linked else "source_tile": (d_t_x, d_t_y),  # type: ignore
            "linked_coords" if linked else "source_coords": (d_data["x"], d_data["y"]),  # type: ignore
        }
        return data

    def get_link_by_door(door: str) -> Union[Tuple[int, DoorLink], Tuple[None, None]]:
        for n, link in enumerate(self.door_links):
            if link["door"] == door or link["linked_door"] == door:
                return n, link
        return None, None

    def select_eg_tile(self: DoorPage, top, event, parent):
        button = self.canvas.find_closest(event.x, event.y)[0]
        eg_tile = get_tile_data_by_button(self.tiles, button)
        if not eg_tile:
            return
        parent.selected_eg_tile = eg_tile
        parent.setvar("selected_eg_tile", BooleanVar(value=True))
        deactivate_tiles(self, top.eg_tile_multiuse, top.disabled_eg_tiles)

        top.eg_tile_window.grab_release()
        top.eg_tile_window.withdraw()

    def auto_draw_player(self, x, y, current_tile):
        try:
            self.canvas.delete("player")
        except:
            pass
        #  get current tile origin
        origin = self.tiles[current_tile]["origin"]
        x = ((x / 512) * self.tile_size) + origin[0] + 4
        y = ((y / 512) * self.tile_size) + origin[1] + 8
        cross_size = self.spotsize / 1.5
        # use create_line to draw an x
        self.canvas.create_line(
            x - cross_size,
            y - cross_size,
            x + cross_size,
            y + cross_size,
            width=self.linewidth,
            fill="red",
            tags=["player"],
        )
        self.canvas.create_line(
            x + cross_size,
            y - cross_size,
            x - cross_size,
            y + cross_size,
            width=self.linewidth,
            fill="red",
            tags=["player"],
        )

    self: DoorPage = typing.cast(DoorPage, ttk.Frame(parent))
    self.eg_selection_mode = eg_selection_mode
    self.eg_tile_window = None
    dungeon_name = [k for k, v in dungeon_worlds.items() if v == tab_world][0]

    self.dungeon = dungeon_name

    # self.cwidth = 1024
    # self.cheight = 512

    self.cwidth = cdims[0]
    self.cheight = cdims[1]
    self.aspect_ratio = aspect_ratio
    self.map_dims = aspect_ratio
    self.cwidth = int(cdims[1] * self.aspect_ratio[1] / self.aspect_ratio[0])
    self.show_all_doors = False

    self.spotsize = int((self.cheight // 50) / 2)
    self.linewidth = int(self.cheight // 200)
    self.select_state = SelectState.NoneSelected

    if vanilla_data:
        # Original vanilla data was stored at 2048x1024, so we need to scale it down to the current size
        self.tile_size = int(vanilla_data["tile_size"] / 2048 * self.cwidth)
        self.map_dims = vanilla_data["map_dims"]
        self.x_offset = vanilla_data["x_offset"]
        self.y_offset = vanilla_data["y_offset"]

    init_page(self)

    # self.load_yaml = reload_page
    self.return_connections = return_connections
    self.init_page = init_page
    self.deactivate_tiles = deactivate_tiles
    self.redraw_canvas = redraw_canvas
    self.auto_add_tile = auto_add_tile
    self.auto_draw_player = auto_draw_player
    self.auto_add_door_link = auto_add_door_link
    self.auto_add_lobby = auto_add_lobby
    self.auto_add_lamp_icon = auto_add_lamp_icon

    #  If we're in eg selection mode, we need to use the special function to only draw tiles and not connections
    if self.eg_selection_mode:
        draw_vanilla_eg_map(self, top)
    else:
        redraw_canvas(self)

    # TODO: Add a new button to store this info somwhere as JSON for the generation
    return self
