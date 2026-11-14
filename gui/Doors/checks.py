"""The dungeon checks the tracker shows: where each is drawn, and the memory flag it sets when collected.

Built when the tracker starts. The flags come from the door randomizer's own tables (gui/Doors/randomizer.py);
where each check is drawn comes from data/new_location_data.py.

flags: (table, room, mask). The check is collected when any of them is set. Tables:
  "room"   the room's word of save data
  "pot"    the room's word of the randomizer's pot table
  "enemy"  the room's word of the randomizer's enemy drop table
  "prize"  the dungeon prizes word; room is unused

Chests, bosses and prizes set a bit in the room's save data. A key in a pot or dropped by an enemy sets a bit in
the randomizer's own pot or enemy table, numbered by the pot's or enemy's place in the room; the room's "key taken"
bit is listed for those as well, in case a version of the rom sets that instead.
"""

import ast
from typing import TypedDict

from data.new_location_data import underworld_items
from gui.Doors.randomizer import parse
from gui.Doors.rooms import SUPERTILES

# After gui.Doors.randomizer, which makes these importable
from ALttPDoorRandomizer import PotShuffle  # noqa: E402
from ALttPDoorRandomizer.BaseClasses import PotItem  # noqa: E402
from ALttPDoorRandomizer.source.rom.DataTables import get_uw_enemy_table  # noqa: E402

KINDS = ("chest", "key_pot", "drop", "prize")


class Check(TypedDict):
    tile: tuple[int, int]  # supertile
    x: int  # position in the supertile, 0..512
    y: int
    flags: list[tuple[str, int, int]]


def client_tables(*names: str) -> list[dict]:
    """Tables of the randomizer's client, MultiClient.py. It is read as text, as the client needs packages the
    tracker does not have."""
    found = {}
    for node in parse("MultiClient.py").body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return [found[name] for name in names]


def key_drop_bits() -> dict[str, tuple[str, tuple[str, int, int]]]:
    """Name the key drop is drawn under -> (its name as a check, (table, room, mask)).

    The bits are worked out as the randomizer's client does. The position data lists a key in a pot under the
    pot's own name, "<room> Pot #<n>", which is also how the randomizer names its pots.
    """
    enemies = get_uw_enemy_table().room_map
    bits = {}
    for name, data in PotShuffle.key_drop_data.items():
        where = data[1]
        if isinstance(where, int):
            # A pot: its room
            room = where
            (index,) = [k for k, pot in enumerate(PotShuffle.vanilla_pots[room]) if pot.item == PotItem.Key]
            bits[f"{PotShuffle.vanilla_pots[room][index].room} Pot #{index + 1}"] = (name, ("pot", room, 0x8000 >> index))
        elif isinstance(where, tuple):
            # An enemy: (address, room, its place in the room's list)
            _, room, index = where
            # Overlords are in the enemy list but have no bit
            index -= sum(1 for sprite in enemies[room][:index] if sprite.sub_type == 0x07)
            bits[name] = (name, ("enemy", room, 0x8000 >> index))
    return bits


def read() -> dict[str, Check]:
    # Check -> (room, mask in the room's save data), and dungeon prize -> mask in the prizes word
    in_rooms, prizes = client_tables("location_table_uw", "location_table_boss")
    drops = key_drop_bits()
    found: dict[str, Check] = {}
    for tile, spots in sorted(underworld_items.items()):
        if tile not in SUPERTILES:
            continue
        room = tile[1] * 16 + tile[0]
        for name, spot in spots.items():
            if spot["loc_type"] not in KINDS:
                continue
            flags: list[tuple[str, int, int]] = []
            if name in drops:
                name, flag = drops[name]
                flags.append(flag)
            if name in in_rooms:
                assert in_rooms[name][0] == room, f"{name}: drawn in room {room:#x}, flagged in {in_rooms[name][0]:#x}"
                flags.append(("room", room, in_rooms[name][1]))
            if name in prizes:
                flags.append(("prize", 0, prizes[name]))
            if flags:
                found[name] = {"tile": tile, "x": int(spot["x"]), "y": int(spot["y"]), "flags": flags}
    return found


checks = read()
