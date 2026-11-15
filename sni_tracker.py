"""Auto-tracking: polls game memory through SNI and reports rooms, links and lobbies to the UI."""

import argparse
import asyncio
import math
from collections.abc import Container, Mapping
from dataclasses import dataclass
from typing import Protocol

import grpc.aio

import sni.sni_pb2 as sni_pb2
import sni.sni_pb2_grpc as sni
from data.doors_data import dark_tiles, door_coordinates, doors_data
from gui.Doors.logic import DUNGEON_NUMBERS, ITEMS_AT, ITEMS_LENGTH
from gui.Doors.randomizer import numbers

# The "dungeon" byte, as it is read, -> the tracker's name for the dungeon
dungeon_ids = {f"{number:02x}": tab for number, tab in DUNGEON_NUMBERS.items()}

mem_addresses = {
    "race": (0x180213, 0x1),
    "seed_hash": (0x180215, 0x5),  # the code shown on the file select screen; differs per seed
    "gamemode": (0xF50010, 0x1),
    "indoors": (0xF5001B, 0x1),
    "link_y": (0xF50020, 0x2),
    "link_x": (0xF50022, 0x2),
    "falling": (0xF5005B, 0x1),
    "mirror": (0xF50095, 0x1),
    "transitioning": (0xF500B0, 0x1),
    "layer": (0xF500EE, 0x1),
    "dead": (0xF5010A, 0x1),
    "dungeon": (0xF5040C, 0x1),
    "lampcone": (0xF50458, 0x1),
    "torches": (0xF5045A, 0x1),
    "dungeon_room": (0xF5048E, 0x1),
}


# Read less often than the rest, as it is 1.9 KB together: the flags that mark checks as collected (two bytes
# per room in each table, and one word for the dungeon prizes) and the player's items
CLIENT = numbers("MultiClient.py")  # the addresses the randomizer's client names
SAVE_DATA = CLIENT["SAVEDATA_START"]
check_addresses = {
    "room": (SAVE_DATA, 0x250),
    "pot": (CLIENT["POT_ITEMS_SRAM_START"], CLIENT["ITEM_SRAM_SIZE"]),  # the randomizer's table of pots emptied
    "enemy": (CLIENT["SPRITE_ITEMS_SRAM_START"], CLIENT["ITEM_SRAM_SIZE"]),  # and of enemy drops taken
    "prize": (SAVE_DATA + 0x472, 0x2),
    "items": (SAVE_DATA + ITEMS_AT, ITEMS_LENGTH),
    "dungeon": mem_addresses["dungeon"],  # which dungeon's keys the game is counting apart
}
READINGS_PER_CHECK_READ = 10


def build_multi_request(add_space, mem_mapping, addresses=mem_addresses):
    requests = {}
    for name, (address, size) in addresses.items():
        request = sni_pb2.ReadMemoryRequest()
        request.requestAddressSpace = add_space
        request.requestMemoryMapping = mem_mapping
        request.requestAddress = address
        request.size = size
        requests[name] = request
    return requests


def des_data(mem_request_names, mem_data):
    data = {mem_request_names[n]: x.data.hex() for n, x in enumerate(mem_data.responses)}
    return data


def find_closest_door(x, y, tile, layer, closest_distance=128):
    #  X and Y are none when dropping in a hole
    everything = door_coordinates.get(tile)
    if not everything:
        return None
    try:
        # Filter by layer
        doors = [door for door in everything if doors_data[door["name"]][2] == layer]
        if len(doors) == 0:
            print(f"No doors found for {tile} layer {layer}")
            doors = everything
    except KeyError:
        return None
    closest_door = None
    for door in doors:
        distance = math.sqrt((x - door["x"]) ** 2 + (y - door["y"]) ** 2)
        if distance < closest_distance:
            closest_distance = distance
            closest_door = door["name"]
    return closest_door


RETRY_SECONDS = 2


class TrackerPage(Protocol):
    """What the tracker needs from a dungeon's page."""

    @property
    def tiles(self) -> Container[tuple[int, int]]: ...

    def auto_add_tile(self, tile: tuple[int, int], was_lit: bool = False, player: tuple[float, float] | None = None) -> None: ...

    def auto_light_tile(self, tile: tuple[int, int]) -> None: ...

    def auto_draw_player(self, x: float, y: float, tile: tuple[int, int]) -> None: ...

    def clear_player(self) -> None: ...

    def auto_add_lobby(self, door: str | None) -> None: ...

    def auto_dropped_in(self, tile: tuple[int, int], x: float, y: float) -> None: ...

    def auto_add_door_link(self, door: str | None, linked_door: str | None) -> None: ...


class TrackerUI(Protocol):
    """What the tracker needs from the window."""

    device: str | None
    connected: bool  # reading from a device through SNI

    @property
    def pages(self) -> Mapping[str, TrackerPage]: ...  # by dungeon name

    def set_title(self, text: str) -> None: ...

    def set_devices(self, uris: list[str]) -> None: ...

    def race_rom_warning(self) -> None: ...

    def seed_seen(self, seed_hash: str) -> bool: ...  # False to stop tracking

    def checks_read(self, memory: Mapping[str, bytes]) -> None: ...  # by name in check_addresses

    def highlight_dungeon(self, name: str | None) -> None: ...

    def select_dungeon(self, name: str) -> None: ...


@dataclass
class Stay:
    """What the tracker remembers about the dungeon the player is in. Forgotten on leaving it."""

    eg_tile: tuple[int, int] | None = None  # supertile of the last reading; None until one is read
    current_tile: tuple[int, int] | None = None
    previous_tile: tuple[int, int] | None = None
    current_x: int | None = None  # position in the supertile
    current_y: int | None = None
    previous_x: int | None = None
    previous_y: int | None = None
    previous_layer: str | None = None
    previous_dungeon: str | None = None  # the dungeon this is, once read
    tab_changed: bool = False  # its tab has been brought to the front
    cycle_skipped: bool = False
    was_mirroring: bool = False
    boss_just_killed: bool = False
    resumed: bool = False  # the player did not walk in: the tracker reconnected, or another game was loaded
    fell_in: bool = False  # the player came into the dungeon falling, down a drop


@dataclass
class Game:
    """What the tracker remembers about the game being read. Forgotten when another seed is loaded."""

    stay: Stay
    seed_hash: str | None = None  # None until the game is first read
    # These outlast leaving a dungeon
    was_transitioning: bool = False
    was_falling: bool = False
    was_dead: bool = False


async def sni_probe(ui: TrackerUI, args: argparse.Namespace, forced_autotrack: bool = False, device: str | None = None) -> None:
    """Run tracking, reconnecting on SNI/device errors."""
    last_error = None
    seen = {"in_dungeon": False}  # kept across reconnects
    while True:
        channel = grpc.aio.insecure_channel(f"localhost:{args.port}")
        try:
            await _sni_session(ui, args, channel, forced_autotrack, device or ui.device, seen)
            return  # race rom
        except (grpc.aio.AioRpcError, OSError) as error:
            details = (error.details() if isinstance(error, grpc.aio.AioRpcError) else None) or str(error)
            if details != last_error:
                print(f"Auto-tracking lost its connection: {details}")
                last_error = details
            ui.set_title(f"Janker Door Tracker -Reconnecting... ({details.split(chr(59))[0][:70]})")
        finally:
            ui.connected = False
            await channel.close()
        await asyncio.sleep(RETRY_SECONDS)


async def _sni_session(
    ui: TrackerUI, args: argparse.Namespace, channel, forced_autotrack: bool, device: str | None, seen: dict[str, bool]
) -> None:
    """Track over one connection. Returns to stop tracking; raises AioRpcError if the connection drops.

    seen["in_dungeon"] is updated on every reading, for the next session to pick up.
    """
    debug = args.debug
    stub = sni.DevicesStub(channel)
    while True:
        response = await stub.ListDevices(sni_pb2.DevicesRequest(kinds=""))
        if len(response.devices) > 0:
            break
        else:
            ui.set_title("Janker Door Tracker -Waiting for devices...")
            await asyncio.sleep(1)
    ui.set_devices([_device.uri for _device in response.devices])

    if device and device in [x.uri for x in response.devices]:
        dev_uri = device
    else:
        dev_uri = response.devices[0].uri
    ui.device = dev_uri
    if debug:
        print("Found device: " + response.devices[0].uri)
    dev_addrspace = 0
    mem_stub = sni.DeviceMemoryStub(channel)
    mem_mapping = await mem_stub.MappingDetect(sni_pb2.DetectMemoryMappingRequest(uri=dev_uri))
    mem_mapping = mem_mapping.memoryMapping
    mem_request = build_multi_request(dev_addrspace, mem_mapping)
    mem_request_names = list(mem_request.keys())
    check_request = build_multi_request(dev_addrspace, mem_mapping, check_addresses)
    readings_to_check_read = 0
    ui.connected = True

    if not forced_autotrack:
        ui.set_title(f"Janker Door Tracker -Auto-tracking Enabled (Connected to {dev_uri})")
    else:
        ui.set_title(
            f"Janker Door Tracker -Auto-tracking Forced (!! Race Rom Detected !!) (Connected to {dev_uri})"
        )

    # Reconnected mid-dungeon: the first room seen is not a dungeon entry
    game = Game(Stay(resumed=seen["in_dungeon"]))
    old_data = {k: None for k in mem_request_names}

    # Main loop for data collection
    while True:
        try:
            stay = game.stay
            mem_req = sni_pb2.MultiReadMemoryRequest(uri=dev_uri, requests=list(mem_request.values()))
            mem_data = await mem_stub.MultiRead(mem_req)
            data = des_data(mem_request_names, mem_data)
            data_diff = {k: v for k, v in data.items() if v != old_data[k]}
            old_data = data
            if len(data_diff) != 0 and args.debug:
                print(data_diff)

            if stay.boss_just_killed:
                if data["gamemode"] != "09":
                    await asyncio.sleep(0.1)
                    continue

            # Are we even in game?
            if int(data["gamemode"], 16) <= 0x5 or int(data["gamemode"], 16) >= 0x0B:
                if data["gamemode"] == "16":
                    stay.boss_just_killed = True
                    await asyncio.sleep(0.1)
                    continue
                if data["mirror"] == "f7":
                    stay.was_mirroring = True

                await asyncio.sleep(0.1)
                continue

            # Only in game: with no game running the bytes read are not a seed's.
            if data["seed_hash"] != game.seed_hash:
                if game.seed_hash is not None:
                    # Another game was loaded and the connection stayed up. What is remembered is the old game's:
                    # acting on it would link its last door to this game's first room
                    game = Game(Stay(resumed=True))
                    stay = game.stay
                game.seed_hash = data["seed_hash"]
            # Before the race check, so a race seed gets its own map even though it is not tracked
            if not ui.seed_seen(data["seed_hash"]):
                ui.set_title("Janker Door Tracker -Auto-tracking stopped: disconnected to leave the map as it is")
                break

            if data["race"] == "01" and not forced_autotrack:
                ui.race_rom_warning()
                ui.set_title("Janker Door Tracker -Auto-tracking Disabled")
                break

            if readings_to_check_read == 0:
                readings_to_check_read = READINGS_PER_CHECK_READ
                reply = await mem_stub.MultiRead(sni_pb2.MultiReadMemoryRequest(uri=dev_uri, requests=list(check_request.values())))
                ui.checks_read({name: bytes(response.data) for name, response in zip(check_request, reply.responses)})
            readings_to_check_read -= 1

            # if args.darkpos:
            #     is_dark = False
            # else:
            is_dark = data["lampcone"] == "00" and data["torches"] == "00"

            if data["dungeon"] not in dungeon_ids.keys() or data["indoors"] != "01":
                if (
                    stay.previous_dungeon in dungeon_ids
                    and data["indoors"] == "00"
                    and data["mirror"] != "0f"
                    and not stay.boss_just_killed
                ):
                    ui.highlight_dungeon(None)
                    # Just left a dungeon, add the last door as a lobby. Not if the player left before a
                    # position was read, as in a doorway: there is then no door to find
                    if stay.eg_tile is not None and stay.current_x is not None:
                        new_door = find_closest_door(stay.current_x, stay.current_y, stay.eg_tile, stay.previous_layer)
                        ui.pages[dungeon_ids[stay.previous_dungeon]].auto_add_lobby(new_door)
                game.stay = Stay()
                seen["in_dungeon"] = False
                await asyncio.sleep(0.1)
                continue

            seen["in_dungeon"] = True
            stay.previous_dungeon = data["dungeon"]
            ui.highlight_dungeon(dungeon_ids[data["dungeon"]])

            if not stay.tab_changed:
                stay.tab_changed = True
                ui.select_dungeon(dungeon_ids[data["dungeon"]])

            if data["transitioning"] != "00":
                game.was_transitioning = True
                await asyncio.sleep(0.1)
                continue

            # Both dying and falling can change supertile with no real doors
            if data["dead"] == "01":
                stay.previous_tile = stay.current_tile = None
                game.was_dead = True
                continue

            if data["falling"] != "00" and data["falling"] != "01":
                if stay.eg_tile is None and not stay.resumed:
                    # Falling before any room of this dungeon was read: from outside, not down a pit inside it.
                    # A stay the tracker joined part way through says nothing either way
                    stay.fell_in = True
                stay.previous_tile = stay.current_tile = None
                game.was_falling = True
                continue

            if not stay.cycle_skipped and (game.was_transitioning or game.was_falling or game.was_dead):
                stay.cycle_skipped = True
                continue

            stay.cycle_skipped = False

            # TODO: Check doors to see if they're entrances and add lobbies?

            eg_tile = stay.eg_tile = (
                int(data["dungeon_room"], 16) % 16,
                int(data["dungeon_room"], 16) // 16,
            )
            current_x_supertile = int(data["link_x"][2:], 16) // 2
            current_y_supertile = int(data["link_y"][2:], 16) // 2

            if eg_tile != (current_x_supertile, current_y_supertile):
                print(f"Supertile mismatch: {eg_tile} != {current_x_supertile}, {current_y_supertile}")
                continue

            dp_content = ui.pages[dungeon_ids[data["dungeon"]]]

            current_x_subtile = int(data["link_x"][2:], 16) % 2
            current_y_subtile = int(data["link_y"][2:], 16) % 2
            current_x = stay.current_x = (current_x_subtile * 255) + int(data["link_x"][:2], 16)
            current_y = stay.current_y = (current_y_subtile * 255) + int(data["link_y"][:2], 16)

            if eg_tile not in dp_content.tiles:
                dp_content.auto_add_tile(eg_tile, was_lit=not is_dark, player=(current_x, current_y))
            elif not is_dark:
                dp_content.auto_light_tile(eg_tile)

            if eg_tile not in dark_tiles or not is_dark:
                dp_content.auto_draw_player(current_x, current_y, eg_tile)
            else:
                dp_content.clear_player()

            if (stay.previous_tile != eg_tile and stay.previous_tile == None) or (
                stay.was_mirroring and data["mirror"] != "0f"
            ):
                stay.previous_tile = eg_tile
                stay.current_tile = eg_tile
                if stay.fell_in:
                    stay.fell_in = False
                    dp_content.auto_dropped_in(eg_tile, current_x, current_y)
                if game.was_falling or game.was_dead or stay.resumed:
                    game.was_falling = False
                    game.was_dead = False
                    stay.resumed = False
                    continue
                # We just entered a new dungeon, add an entrance
                if eg_tile == (2, 1):
                    continue
                new_door = find_closest_door(
                    current_x,
                    current_y,
                    eg_tile,
                    data["layer"],
                    closest_distance=32 if stay.was_mirroring else 128,
                )
                dp_content.auto_add_lobby(new_door)
                stay.was_mirroring = False

            elif (stay.previous_tile != eg_tile and stay.previous_tile != None) or game.was_transitioning:
                game.was_transitioning = False
                stay.previous_tile = stay.current_tile
                stay.current_tile = eg_tile

                new_door = find_closest_door(current_x, current_y, eg_tile, data["layer"])
                try:
                    old_door = find_closest_door(stay.previous_x, stay.previous_y, stay.previous_tile, stay.previous_layer)
                except TypeError:
                    # We likely fell in a hole to a dungeon, so we don't have a previous door
                    continue
                if old_door == new_door:
                    continue
                dp_content.auto_add_door_link(old_door, new_door)

            stay.previous_x = current_x
            stay.previous_y = current_y
            stay.previous_layer = data["layer"]

            await asyncio.sleep(0.1)
        except grpc.aio.AioRpcError:
            raise  # sni_probe reconnects
        # except Exception as e:
        #     print(e)
        #     await asyncio.sleep(1)
