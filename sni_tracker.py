"""Auto-tracking: polls game memory through SNI and reports rooms, links and lobbies to the UI."""

import argparse
import asyncio
import math

import grpc.aio

import sni.sni_pb2 as sni_pb2
import sni.sni_pb2_grpc as sni
from data.doors_data import dark_tiles, door_coordinates, doors_data

dungeon_ids = {
    "00": "Hyrule_Castle",
    "02": "Hyrule_Castle",
    "04": "Eastern_Palace",
    "06": "Desert_Palace",
    "14": "Tower_of_Hera",
    "08": "Castle_Tower",
    "0c": "Palace_of_Darkness",
    "0a": "Swamp_Palace",
    "10": "Skull_Woods",
    "16": "Thieves_Town",
    "12": "Ice_Palace",
    "0e": "Misery_Mire",
    "18": "Turtle_Rock",
    "1a": "Ganons_Tower",
}

mem_addresses = {
    "race": (0x180213, 0x1),
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


def build_multi_request(add_space, mem_mapping):
    requests = {}
    for name, (address, size) in mem_addresses.items():
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
    # door_coordinates is a defaultdict; [] would insert the key
    everything = door_coordinates.get(tile)
    if not everything:
        return None
    try:
        # Filter by layer
        doors = [door for door in everything if doors_data[door["name"]][2] == layer]  # type: ignore
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


async def sni_probe(ui, args: argparse.Namespace, forced_autotrack: bool = False, device: str = None):
    """Run tracking, reconnecting on SNI/device errors.

    `ui` needs set_title, set_devices, race_rom_warning, highlight_dungeon, select_dungeon and
    `pages` (dungeon name -> page).
    """
    last_error = None
    resumed = False
    while True:
        channel = grpc.aio.insecure_channel(f"localhost:{args.port}")
        try:
            await _sni_session(ui, args, channel, forced_autotrack, device or getattr(ui, "device", None), resumed)
            return  # race rom
        except (grpc.aio.AioRpcError, OSError) as error:
            details = error.details() if isinstance(error, grpc.aio.AioRpcError) else str(error)
            if details != last_error:
                print(f"Auto-tracking lost its connection: {details}")
                last_error = details
            ui.set_title(f"Jank Door Tracker - Reconnecting... ({details.split(chr(59))[0][:70]})")
        finally:
            await channel.close()
        resumed = True
        await asyncio.sleep(RETRY_SECONDS)


async def _sni_session(ui, args, channel, forced_autotrack, device, resumed=False):
    """Track over one connection. Returns to stop tracking; raises AioRpcError if the connection drops."""
    debug = args.debug
    stub = sni.DevicesStub(channel)
    while True:
        response = await stub.ListDevices(sni_pb2.DevicesRequest(kinds=""))
        if len(response.devices) > 0:
            break
        else:
            ui.set_title(f"Jank Door Tracker - Waiting for devices...")
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

    if not forced_autotrack:
        ui.set_title(f"Jank Door Tracker - Auto-tracking Enabled (Connected to {dev_uri})")
    else:
        ui.set_title(
            f"Jank Door Tracker - Auto-tracking Forced (!! Race Rom Detected !!) (Connected to {dev_uri})"
        )

    current_tile = None
    previous_tile = None
    current_x = None
    current_y = None
    previous_x = None
    previous_y = None
    previous_layer = None
    was_transitioning = False
    was_falling = False
    # After a reconnect, don't treat the first room as a dungeon entry (same skip as after a death)
    was_dead = resumed
    cycle_skipped = False
    was_mirroring = False
    previous_dungeon = False
    tab_changed = False
    is_dark = False
    boss_just_killed = False
    old_data = {k: None for k in mem_request_names}
    eg_tile = (0, 0)

    # Main loop for data collection
    while True:
        try:
            mem_req = sni_pb2.MultiReadMemoryRequest(uri=dev_uri, requests=list(mem_request.values()))
            mem_data = await mem_stub.MultiRead(mem_req)
            data = des_data(mem_request_names, mem_data)
            data_diff = {k: v for k, v in data.items() if v != old_data[k]}
            old_data = data
            if len(data_diff) != 0 and args.debug:
                print(data_diff)

            if boss_just_killed:
                if data["gamemode"] != "09":
                    await asyncio.sleep(0.1)
                    continue

            # Are we even in game?
            if int(data["gamemode"], 16) <= 0x5 or int(data["gamemode"], 16) >= 0x0B:
                if data["gamemode"] == "16":
                    boss_just_killed = True
                    await asyncio.sleep(0.1)
                    continue
                if data["mirror"] == "f7":
                    was_mirroring = True

                await asyncio.sleep(0.1)
                continue

            if data["race"] == "01" and not forced_autotrack:
                ui.race_rom_warning()
                ui.set_title(f"Jank Door Tracker - Auto-tracking Disabled")
                break

            # if args.darkpos:
            #     is_dark = False
            # else:
            is_dark = data["lampcone"] == "00" and data["torches"] == "00"

            if data["dungeon"] not in dungeon_ids.keys() or data["indoors"] != "01":
                if (
                    previous_dungeon in dungeon_ids.keys()
                    and data["indoors"] == "00"
                    and data["mirror"] != "0f"
                    and not boss_just_killed
                ):
                    ui.highlight_dungeon(None)
                    # Just left a dungeon, add the last door as a lobby
                    new_door = find_closest_door(current_x, current_y, eg_tile, previous_layer)
                    dp_content.auto_add_lobby(new_door)  # type: ignore
                current_tile = None
                previous_tile = None
                current_x = None
                current_y = None
                previous_x = None
                previous_y = None
                previous_layer = None
                cycle_skipped = False
                was_mirroring = False
                previous_dungeon = False
                tab_changed = False
                is_dark = False
                boss_just_killed = False
                await asyncio.sleep(0.1)
                continue

            previous_dungeon = data["dungeon"]
            ui.highlight_dungeon(dungeon_ids[data["dungeon"]])

            if not tab_changed:
                tab_changed = True
                ui.select_dungeon(dungeon_ids[data["dungeon"]])

            if data["transitioning"] != "00":
                was_transitioning = True
                await asyncio.sleep(0.1)
                continue

            # Both dying and falling can change supertile with no real doors
            if data["dead"] == "01":
                previous_tile = current_tile = None
                was_dead = True
                continue

            if data["falling"] != "00" and data["falling"] != "01":
                previous_tile = current_tile = None
                was_falling = True
                continue

            if not cycle_skipped and (was_transitioning or was_falling or was_dead):
                cycle_skipped = True
                continue

            cycle_skipped = False

            # TODO: Check doors to see if they're entrances and add lobbies?

            eg_tile = (
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
            current_x = (current_x_subtile * 255) + int(data["link_x"][:2], 16)
            current_y = (current_y_subtile * 255) + int(data["link_y"][:2], 16)

            if eg_tile not in dp_content.tiles:
                dp_content.auto_add_tile(eg_tile, was_lit=not is_dark, player=(current_x, current_y))
            else:
                if not dp_content.tiles[eg_tile]["has_been_lit"] and not is_dark:
                    dp_content.tiles[eg_tile]["has_been_lit"] = True
                    dp_content.redraw_canvas()

            if eg_tile not in dark_tiles or not is_dark:
                dp_content.auto_draw_player(current_x, current_y, eg_tile)
            else:
                dp_content.clear_player()

            if (previous_tile != eg_tile and previous_tile == None) or (was_mirroring and data["mirror"] != "0f"):
                previous_tile = eg_tile
                current_tile = eg_tile
                if was_falling or was_dead:
                    was_falling = False
                    was_dead = False
                    continue
                # We just entered a new dungeon, add an entrance
                if eg_tile == (2, 1):
                    continue
                new_door = find_closest_door(
                    current_x,
                    current_y,
                    eg_tile,
                    data["layer"],
                    closest_distance=32 if was_mirroring else 128,
                )
                dp_content.auto_add_lobby(new_door)
                was_mirroring = False

            elif (previous_tile != eg_tile and previous_tile != None) or was_transitioning:
                was_transitioning = False
                previous_tile = current_tile
                current_tile = eg_tile

                new_door = find_closest_door(current_x, current_y, eg_tile, data["layer"])
                try:
                    old_door = find_closest_door(previous_x, previous_y, previous_tile, previous_layer)
                except TypeError:
                    # We likely fell in a hole to a dungeon, so we don't have a previous door
                    continue
                if old_door == new_door:
                    continue
                dp_content.auto_add_door_link(old_door, new_door)

            previous_x = current_x
            previous_y = current_y
            previous_layer = data["layer"]

            await asyncio.sleep(0.1)
        except grpc.aio.AioRpcError:
            raise  # sni_probe reconnects
        # except Exception as e:
        #     print(e)
        #     await asyncio.sleep(1)
