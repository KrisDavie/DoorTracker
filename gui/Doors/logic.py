"""What the player holds, and whether that meets one of the randomizer's rules (gui/Doors/rules.py)."""

# An item's name, ("all", rule, ...), ("any", rule, ...), or a bool
Rule = bool | str | tuple

# The part of the game's save data that holds the equipment
ITEMS_AT = 0x340
ITEMS_LENGTH = 0x4F

# item -> (address in save data, least value that means it is held). From the randomizer's InitialSram.py
AT_LEAST = {
    "Bow": (0x340, 1),
    "Hookshot": (0x342, 1),
    "Fire Rod": (0x345, 1),
    "Ice Rod": (0x346, 1),
    "Bombos": (0x347, 1),
    "Ether": (0x348, 1),
    "Quake": (0x349, 1),
    "Lamp": (0x34A, 1),
    "Hammer": (0x34B, 1),
    "Bug Catching Net": (0x34D, 1),
    "Book of Mudora": (0x34E, 1),
    "Cane of Somaria": (0x350, 1),
    "Cane of Byrna": (0x351, 1),
    "Cape": (0x352, 1),
    "Magic Mirror": (0x353, 2),  # 1 is the scroll that only works in dungeons
    "Power Glove": (0x354, 1),
    "Titans Mitts": (0x354, 2),
    "Pegasus Boots": (0x355, 1),
    "Flippers": (0x356, 1),
    "Moon Pearl": (0x357, 1),
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
    "Big Key (Escape)": (0x367, 0xC0),
    "Big Key (Eastern Palace)": (0x367, 0x20),
    "Big Key (Desert Palace)": (0x367, 0x10),
    "Big Key (Tower of Hera)": (0x366, 0x20),
    "Big Key (Agahnims Tower)": (0x367, 0x08),
    "Big Key (Palace of Darkness)": (0x367, 0x02),
    "Big Key (Swamp Palace)": (0x367, 0x04),
    "Big Key (Skull Woods)": (0x366, 0x80),
    "Big Key (Thieves Town)": (0x366, 0x10),
    "Big Key (Ice Palace)": (0x366, 0x40),
    "Big Key (Misery Mire)": (0x367, 0x01),
    "Big Key (Turtle Rock)": (0x366, 0x08),
    "Big Key (Ganons Tower)": (0x366, 0x04),
}
# The tracker's name for a dungeon -> its big key
BIG_KEYS = {
    "Hyrule_Castle": "Big Key (Escape)",
    "Eastern_Palace": "Big Key (Eastern Palace)",
    "Desert_Palace": "Big Key (Desert Palace)",
    "Tower_of_Hera": "Big Key (Tower of Hera)",
    "Castle_Tower": "Big Key (Agahnims Tower)",
    "Palace_of_Darkness": "Big Key (Palace of Darkness)",
    "Swamp_Palace": "Big Key (Swamp Palace)",
    "Skull_Woods": "Big Key (Skull Woods)",
    "Thieves_Town": "Big Key (Thieves Town)",
    "Ice_Palace": "Big Key (Ice Palace)",
    "Misery_Mire": "Big Key (Misery Mire)",
    "Turtle_Rock": "Big Key (Turtle Rock)",
    "Ganons_Tower": "Big Key (Ganons Tower)",
}
# The tracker's name for a dungeon -> where its small keys are counted. The game numbers the dungeons in twos, in
# this order from 0, with the sewers and the castle sharing the first count
SMALL_KEYS_AT = {
    "Hyrule_Castle": 0x37C,
    "Eastern_Palace": 0x37E,
    "Desert_Palace": 0x37F,
    "Castle_Tower": 0x380,
    "Swamp_Palace": 0x381,
    "Palace_of_Darkness": 0x382,
    "Misery_Mire": 0x383,
    "Skull_Woods": 0x384,
    "Ice_Palace": 0x385,
    "Tower_of_Hera": 0x386,
    "Thieves_Town": 0x387,
    "Turtle_Rock": 0x388,
    "Ganons_Tower": 0x389,
}
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
    if here != 0xFF:
        counted_at = 0x37C if dungeon <= 2 else 0x37C + dungeon // 2
        for name, address in SMALL_KEYS_AT.items():
            if address == counted_at:
                keys[name] = here
    return keys


def holds(rule: Rule, items: frozenset[str]) -> bool:
    """Whether the items meet a rule."""
    if isinstance(rule, bool):
        return rule
    if isinstance(rule, str):
        return rule in items
    kind, *parts = rule
    return (all if kind == "all" else any)(holds(part, items) for part in parts)
