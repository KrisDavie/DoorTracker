"""The tracking loop in sni_tracker.py, run against a fake SNI that plays back memory readings."""

import argparse
import asyncio

import grpc

import sni_tracker
from data.doors_data import dark_tiles, door_coordinates, doors_data
from gui.Doors.rooms import INTERIOR_DOORS

DUNGEON, TAB = "0c", "Palace_of_Darkness"
DARK_ROOM = (10, 11)


def door_facing(facing, avoid=None):
    """(supertile, door table entry) of a lit Palace of Darkness door facing this way, on layer 00."""
    for tile, entries in sorted(door_coordinates.items()):
        if tile in dark_tiles or tile == avoid:
            continue
        for entry in entries:
            name = entry["name"]
            if name.startswith("PoD") and name not in INTERIOR_DOORS and doors_data[name][1:3] == (facing, "00"):
                return tile, entry
    raise AssertionError(f"no {facing} door")


def reading(tile, x, y, lamp=True, transitioning=False, indoors=True):
    """What the tracker reads from memory with the player at pixel (x, y) of a supertile."""

    def coordinate(supertile, pixel):
        half = 1 if pixel > 255 else 0
        return f"{pixel - half * 255:02x}{supertile * 2 + half:02x}"

    return {
        "race": "00",
        "gamemode": "07",
        "indoors": "01" if indoors else "00",
        "link_y": coordinate(tile[1], y),
        "link_x": coordinate(tile[0], x),
        "falling": "00",
        "mirror": "00",
        "transitioning": "01" if transitioning else "00",
        "layer": "00",
        "dead": "00",
        "dungeon": DUNGEON,
        "lampcone": "01" if lamp else "00",
        "torches": "00",
        "dungeon_room": f"{tile[1] * 16 + tile[0]:02x}",
    }


class Reply:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class PlaybackOver(grpc.aio.AioRpcError):
    def __init__(self):
        pass


def play(window, app, monkeypatch, steps):
    """Feed the readings to the real loop. Returns the map's state as it was before each labelled reading, and at the end."""
    model = window.pages[TAB].model
    seen = {}

    def state():
        return {
            "player": model.player and model.player.node.tile,
            "links": [(link.door, link.linked_door) for link in model.door_links],
            "entrances": [lobby.door for lobby in model.lobby_doors],
            "dark room lit": DARK_ROOM in model.tiles and model.tiles[DARK_ROOM].has_been_lit,
            "dark room hidden": model.is_hidden_dark(DARK_ROOM),
        }

    class Devices:
        def __init__(self, channel):
            pass

        async def ListDevices(self, request):
            return Reply(devices=[Reply(uri="fake://snes")])

    class Memory:
        def __init__(self, channel):
            self.served = 0

        async def MappingDetect(self, request):
            return Reply(memoryMapping=0)

        async def MultiRead(self, request):
            app.processEvents()
            if self.served == len(steps):
                seen["end"] = state()
                raise PlaybackOver()
            label, values = steps[self.served]
            seen[label] = state()
            self.served += 1
            return Reply(responses=[Reply(data=bytes.fromhex(values[name])) for name in sni_tracker.mem_addresses])

    monkeypatch.setattr(sni_tracker.sni, "DevicesStub", Devices)
    monkeypatch.setattr(sni_tracker.sni, "DeviceMemoryStub", Memory)

    async def session():
        try:
            await sni_tracker._sni_session(window, argparse.Namespace(debug=False), None, False, None, {"in_dungeon": False})
        except PlaybackOver:
            pass

    asyncio.run(asyncio.wait_for(session(), 30))
    return seen


def test_walking_through_a_door_and_into_a_dark_room(window, app, monkeypatch):
    first, north_door = door_facing("No")
    second, south_door = door_facing("So", avoid=first)
    at_first = (first, north_door["x"], north_door["y"])
    at_second = (second, south_door["x"], south_door["y"])
    in_dark = (DARK_ROOM, 250, 250)

    seen = play(
        window,
        app,
        monkeypatch,
        [
            ("start", reading(*at_first)),
            ("in the first room", reading(*at_first)),
            ("through the door", reading(*at_first, transitioning=True)),
            ("arriving", reading(*at_second)),
            ("arrived", reading(*at_second)),
            ("standing there", reading(*at_second)),
            ("leaving", reading(*at_second, transitioning=True)),
            ("entering the dark", reading(*in_dark, lamp=False)),
            ("in the dark", reading(*in_dark, lamp=False)),
            ("still in the dark", reading(*in_dark, lamp=False)),
            ("lamp lit", reading(*in_dark)),
            ("looking around", reading(*in_dark)),
        ],
    )

    link = (north_door["name"], south_door["name"])
    assert seen["through the door"]["player"] == first
    assert link not in seen["through the door"]["links"]
    assert seen["leaving"]["player"] == second
    assert link in seen["leaving"]["links"]
    # Dark with no lamp: on the map but hidden, and the player is not drawn
    assert seen["lamp lit"] == {**seen["lamp lit"], "player": None, "dark room lit": False, "dark room hidden": True}
    assert seen["end"] == {**seen["end"], "player": DARK_ROOM, "dark room lit": True, "dark room hidden": False}


def test_leaving_a_dungeon_makes_the_door_left_by_an_entrance(window, app, monkeypatch):
    # A lit supertile with a north door to come in by (not an entrance) and a south door to leave by
    for tile, entries in sorted(door_coordinates.items()):
        doors = {}
        for entry in entries:
            name = entry["name"]
            if name.startswith("PoD") and name not in INTERIOR_DOORS and doors_data[name][2] == "00":
                doors.setdefault(doors_data[name][1], entry)
        if tile not in dark_tiles and "No" in doors and "So" in doors:
            break
    at_north = (tile, doors["No"]["x"], doors["No"]["y"])
    at_south = (tile, doors["So"]["x"], doors["So"]["y"])

    seen = play(
        window,
        app,
        monkeypatch,
        [
            ("came in", reading(*at_north)),
            ("walked across", reading(*at_south)),
            ("at the south door", reading(*at_south)),
            ("outside", reading(*at_south, indoors=False)),
            ("still outside", reading(*at_south, indoors=False)),
        ],
    )

    assert doors["So"]["name"] not in seen["outside"]["entrances"]
    assert doors["So"]["name"] in seen["end"]["entrances"]
