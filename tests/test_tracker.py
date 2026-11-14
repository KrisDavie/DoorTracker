"""The tracking loop in sni_tracker.py, run against a fake SNI that plays back memory readings."""

import argparse
import asyncio

import grpc

import DoorsTracker
import sni_tracker
from data.doors_data import dark_tiles, door_coordinates, doors_data
from gui.Doors.logic import ITEMS_AT
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


def reading(tile, x, y, lamp=True, transitioning=False, indoors=True, seed="0102030405", falling=False, dungeon=DUNGEON):
    """What the tracker reads from memory with the player at pixel (x, y) of a supertile."""

    def coordinate(supertile, pixel):
        half = 1 if pixel > 255 else 0
        return f"{pixel - half * 255:02x}{supertile * 2 + half:02x}"

    return {
        "race": "00",
        "seed_hash": seed,
        "gamemode": "07",
        "indoors": "01" if indoors else "00",
        "link_y": coordinate(tile[1], y),
        "link_x": coordinate(tile[0], x),
        "falling": "02" if falling else "00",
        "mirror": "00",
        "transitioning": "01" if transitioning else "00",
        "layer": "00",
        "dead": "00",
        "dungeon": dungeon,
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


def play(window, app, monkeypatch, steps, collected=(), equipment=None):
    """Feed the readings to the real loop. Returns the map's state as it was before each labelled reading, and at the end.

    collected: (table, room, mask) flags the game has set, for the tracker's reads of what has been collected.
    equipment: {address in save data: byte} for the items held.
    """
    model = window.pages[TAB].model
    seen = {}
    tables = {name: bytearray(size) for name, (_, size) in sni_tracker.check_addresses.items()}
    for table, room, mask in collected:
        word = int.from_bytes(tables[table][room * 2 : room * 2 + 2], "little") | mask
        tables[table][room * 2 : room * 2 + 2] = word.to_bytes(2, "little")
    for address, value in (equipment or {}).items():
        tables["items"][address - ITEMS_AT] = value

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
            if request.requests[0].requestAddress == sni_tracker.check_addresses["room"][0]:
                return Reply(responses=[Reply(data=bytes(tables[name])) for name in sni_tracker.check_addresses])
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


def test_the_tracker_stops_when_the_window_says_to_disconnect(window, app, monkeypatch):
    monkeypatch.setattr(window, "seed_seen", lambda seed_hash: False)
    tile, door = door_facing("No")
    seen = play(window, app, monkeypatch, [(f"reading {k}", reading(tile, door["x"], door["y"])) for k in range(3)])

    # It stopped at the first reading, before putting the player on the map
    assert list(seen) == ["reading 0"]
    assert window.pages[TAB].model.player is None
    assert "disconnected" in window.windowTitle()


def test_checks_the_game_has_flagged_are_collected(window, app, monkeypatch):
    tile, door = door_facing("No")
    in_game = reading(tile, door["x"], door["y"])
    flagged = {
        "Eastern Palace - Compass Chest": ("room", 0xA8, 0x10),
        "Eastern Palace - Boss": ("room", 0xC8, 0x800),
        "Eastern Palace - Prize": ("prize", 0, 0x2000),
        # A key under a pot and one dropped by an enemy are flagged in the randomizer's own tables
        "Eastern Palace - Dark Square Pot Key": ("pot", 0xBA, 0x8000 >> 4),
        "Eastern Palace - Dark Eyegore Key Drop": ("enemy", 0x99, 0x8000 >> 3),
        # or, as a fallback, by the room's "key taken" bit
        "Hyrule Castle - Key Rat Key Drop": ("room", 0x21, 0x400),
    }
    # Flags that belong to no check, and a chest's neighbour bit, mark nothing
    noise = [("room", 0xA8, 0x8000), ("pot", 0xBA, 0x8000 >> 5), ("enemy", 0x99, 0x8000 >> 2)]

    play(window, app, monkeypatch, [("one", in_game), ("two", in_game)], collected=list(flagged.values()) + noise)
    assert window.collected == set(flagged)


def test_the_items_the_game_holds_reach_every_tab(window, app, monkeypatch):
    tile, door = door_facing("No")
    in_game = reading(tile, door["x"], door["y"])
    assert window.pages[TAB].model.items is None

    # The hammer, and the mitts, which also lift what the glove lifts
    play(window, app, monkeypatch, [("one", in_game), ("two", in_game)], equipment={0x34B: 1, 0x354: 2})
    for page in window.pages.values():
        assert page.model.items == {"Hammer", "Power Glove", "Titans Mitts"}


def test_falling_into_a_dungeon_by_a_drop_makes_the_drop_a_way_in(window, app, monkeypatch):
    castle = window.pages["Hyrule_Castle"].model
    assert castle.assumed("Sewer Drop")
    # The sewer drop's supertile, in the castle's dungeon, at about where the drop lands
    landing = dict(tile=(1, 1), x=400, y=290, dungeon="00")
    steps = [("falling", reading(**landing, falling=True))] + [(f"landed {k}", reading(**landing)) for k in range(3)]

    play(window, app, monkeypatch, steps)
    assert not castle.assumed("Sewer Drop")


def test_leaving_a_dungeon_before_a_position_is_read_adds_no_entrance(window, app, monkeypatch):
    tile, doors = supertile_with_doors_facing("So")
    at_door = (tile, doors["So"]["x"], doors["So"]["y"])
    inside, outside = reading(*at_door), reading(*at_door, indoors=False)
    # Back in, and out again while still in the doorway: no position is read on this visit
    in_the_doorway = reading(*at_door, transitioning=True)

    seen = play(
        window,
        app,
        monkeypatch,
        [("in", inside), ("in still", inside), ("out", outside), ("back in", in_the_doorway), ("out again", outside), ("outside", outside)],
    )
    assert seen["end"]["entrances"] == seen["back in"]["entrances"] == [doors["So"]["name"]]


def test_loading_another_seed_mid_dungeon_adds_nothing_from_the_old_game(window, app, monkeypatch):
    # The connection survives a change of ROM, so the tracker still remembers the old game's room
    monkeypatch.setattr(window, "_ask", lambda *args: DoorsTracker.NEW_MAP)
    first, north_door = door_facing("No")
    second, south_door = door_facing("So", avoid=first)
    old_game = reading(first, north_door["x"], north_door["y"], seed="aaaaaaaaaa")
    new_game = reading(second, south_door["x"], south_door["y"], seed="bbbbbbbbbb")

    seen = play(window, app, monkeypatch, [(f"old {k}", old_game) for k in range(3)] + [(f"new {k}", new_game) for k in range(3)])
    assert window.seed_hash == "bbbbbbbbbb"
    assert (seen["end"]["links"], seen["end"]["entrances"]) == ([], [])


def supertile_with_doors_facing(*facings):
    """(supertile, door table entry by facing) of a lit Palace of Darkness supertile with a door facing each way."""
    for tile, entries in sorted(door_coordinates.items()):
        doors = {}
        for entry in entries:
            name = entry["name"]
            if name.startswith("PoD") and name not in INTERIOR_DOORS and doors_data[name][2] == "00":
                doors.setdefault(doors_data[name][1], entry)
        if tile not in dark_tiles and all(facing in doors for facing in facings):
            return tile, doors
    raise AssertionError(f"no supertile with doors facing {facings}")


def test_leaving_a_dungeon_makes_the_door_left_by_an_entrance(window, app, monkeypatch):
    # Come in by a north door, which is not an entrance, and leave by a south door
    tile, doors = supertile_with_doors_facing("No", "So")
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
