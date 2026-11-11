from pathlib import Path
from data.worlds_data import World

ITEM_SHEET_PATH = Path(__file__).parent / "Doors_Sheet.png"


item_table = {
    "Bomb Door": (0, 0),
    "Slash Door": (0, 1),
    "Dash Door": (0, 2),
    "Key Door": (0, 3),
    "Big Key Door": (0, 4),
    "Trap Door": (0, 5),
    "Master Sword": (0, 6),
    "Bow": (0, 7),
    "Fire Rod": (0, 8),
    "Boomerang": (1, 7),
    "Cape": (1, 8),
    "Quake": (2, 7),
    "Powder": (2, 8),
    "Somaria": (1, 0),
    "Lamp": (1, 1),
    "Hammer": (1, 2),
    "Flippers": (1, 3),
    "Hookshot": (1, 4),
    "Skull": (1, 5),
    "Checkmark": (2, 5),
    "Crossmark": (3, 5),
    "Blue Peg": (4, 5),
    "Orange Peg": (5, 5),
    "Peg Switch": (6, 5),
    "Sanctuary_Mirror": (8, 5),
    "Drop": (7, 5),
}

dungeon_lobbies = {
    World.HyruleCastle: {
        "Hyrule Castle East": (3, 0),
        "Hyrule Castle South": (3, 1),
        "Hyrule Castle West": (3, 2),
        "Sanctuary": (3, 3),
    },
    World.EasternPalace: {
        "Eastern": (3, 4),
    },
    World.DesertPalace: {
        "Desert Back": (4, 0),
        "Desert East": (4, 1),
        "Desert South": (4, 2),
        "Desert West": (4, 3),
    },
    World.TowerOfHera: {
        "Hera": (4, 4),
    },
    World.CastleTower: {
        "Agahnims Tower": (5, 0),
    },
    World.PalaceOfDarkness: {
        "Palace of Darkness": (5, 1),
    },
    World.SwampPalace: {
        "Swamp": (5, 2),
    },
    World.SkullWoods: {
        "Skull 3": (6, 0),
        "Skull 2 East": (6, 1),
        "Skull 1": (6, 2),
        "Skull 2 West": (6, 3),
    },
    World.ThievesTown: {
        "Thieves Town": (7, 0),
    },
    World.IcePalace: {
        "Ice": (7, 1),
    },
    World.MiseryMire: {
        "Mire": (7, 2),
    },
    World.TurtleRock: {
        "Turtle Rock Main": (8, 0),
        "Turtle Rock Chest": (8, 1),
        "Turtle Rock Eye Bridge": (8, 2),
        "Turtle Rock Lazy Eyes": (8, 3),
    },
    World.GanonsTower: {
        "Ganons Tower": (8, 4),
    },
}
# Flatten the dictionary
all_dungeon_lobbies = {k: v for d in dungeon_lobbies.values() for k, v in d.items()}
all_icons = {**item_table, **all_dungeon_lobbies}
