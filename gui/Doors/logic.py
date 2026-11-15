"""What the player holds, and whether that meets one of the randomizer's rules (gui/Doors/rules.py)."""

from data.worlds_data import dungeon_worlds
from gui.Doors.randomizer import dungeon_name, literals

# After gui.Doors.randomizer, which makes the randomizer importable. The randomizer's name for a dungeon -> a
# tuple that ends in the game's number for the dungeon, -> its big key, and -> its small key
from ALttPDoorRandomizer.DoorShuffle import compass_data  # noqa: E402
from ALttPDoorRandomizer.Dungeons import dungeon_bigs, dungeon_keys  # noqa: E402

# An item's name, ("all", rule, ...), ("any", rule, ...), or a bool
Rule = bool | str | tuple

# The part of the game's save data that holds the equipment
ITEMS_AT = 0x340
ITEMS_LENGTH = 0x4F

# What the randomizer's InitialSram.py gives a starting item by: item -> (address in save data, value) for an item
# with a slot of its own, item -> (address, bit) for the big keys among others, and small key -> the addresses
# its count is kept at
_SLOTS, _FLAGS, _COUNTS = literals("InitialSram.py", "set_table", "or_table", "keys")
# The tracker's names for the dungeons
DUNGEONS = [tab for tab in dungeon_worlds if dungeon_name(tab) in dungeon_bigs]

# item -> (address, least value that means it is held). The ones listed here InitialSram.py sets by other means
AT_LEAST = {
    **_SLOTS,
    "Bow": (0x340, 1),
    "Power Glove": (0x354, 1),
    "Titans Mitts": (0x354, 2),
    "Pegasus Boots": (0x355, 1),
    "Flippers": (0x356, 1),
    "Fighter Sword": (0x359, 1),
    "Master Sword": (0x359, 2),
    "Tempered Sword": (0x359, 3),
    "Golden Sword": (0x359, 4),
    "Blue Shield": (0x35A, 1),
    "Red Shield": (0x35A, 2),
    "Mirror Shield": (0x35A, 3),
    "Blue Mail": (0x35B, 1),
    "Red Mail": (0x35B, 2),
    # Not an item: room for bombs. It is none until the bomb bag is found, in seeds that have one
    "Bombs": (0x370, 1),
}
# item -> (address, bit). 0x38C is the randomizer's own record of the items that share a slot in the menu, where
# the slot itself only holds the one last picked up
BITS = {
    "Blue Boomerang": (0x38C, 0x80),
    "Red Boomerang": (0x38C, 0x40),
    "Mushroom": (0x38C, 0x20),
    "Magic Powder": (0x38C, 0x10),
    "Shovel": (0x38C, 0x04),
    "Ocarina": (0x38C, 0x03),  # working or not
    **{key: _FLAGS[key] for key in dungeon_bigs.values()},
}
# The tracker's name for a dungeon -> its big key, and -> where its small keys are counted
BIG_KEYS = {tab: dungeon_bigs[dungeon_name(tab)] for tab in DUNGEONS}
SMALL_KEYS_AT = {tab: _COUNTS[dungeon_keys[dungeon_name(tab)]][0] for tab in DUNGEONS}
# The game's number for a dungeon -> the tracker's name for it. The sewers have a number of their own
DUNGEON_NUMBERS = {0x00: "Hyrule_Castle"} | {compass_data[dungeon_name(tab)][4]: tab for tab in DUNGEONS}
KEYS_HERE_AT = 0x36F  # the small keys for the dungeon the player is in; 0xFF outside
BOTTLES_AT = range(0x35C, 0x360)  # what is in each of the four bottles; 0 for no bottle
BOTTLE = "Bottle"
READABLE = frozenset(AT_LEAST) | frozenset(BITS) | {BOTTLE}
SWORD = 0x359
NO_SWORDS = 0xFF  # what a swordless seed puts in the sword's byte


def items_held(save: bytes) -> frozenset[str]:
    """The items held, from the ITEMS_LENGTH bytes of save data at ITEMS_AT."""

    def at(address: int) -> int:
        value = save[address - ITEMS_AT]
        return 0 if address == SWORD and value == NO_SWORDS else value

    held = {item for item, (address, least) in AT_LEAST.items() if at(address) >= least}
    held |= {item for item, (address, bit) in BITS.items() if at(address) & bit}
    if any(at(address) for address in BOTTLES_AT):
        held.add(BOTTLE)
    return frozenset(held)


def small_keys(save: bytes, dungeon: int) -> dict[str, int]:
    """Small keys held for each dungeon, by the tracker's name for it.

    dungeon: the game's number for the dungeon the player is in. While they are in it the game counts its keys
    at KEYS_HERE_AT, and only writes the dungeon's own count when they leave.
    """
    keys = {name: save[address - ITEMS_AT] for name, address in SMALL_KEYS_AT.items()}
    here = save[KEYS_HERE_AT - ITEMS_AT]
    if here != 0xFF and dungeon in DUNGEON_NUMBERS:
        keys[DUNGEON_NUMBERS[dungeon]] = here
    return keys


def holds(rule: Rule, items: frozenset[str]) -> bool:
    """Whether the items meet a rule."""
    if isinstance(rule, bool):
        return rule
    if isinstance(rule, str):
        return rule in items
    kind, *parts = rule
    return (all if kind == "all" else any)(holds(part, items) for part in parts)
