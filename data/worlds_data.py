from enum import Enum
from pathlib import Path

import gui.new_location_data as location_data


class World(Enum):
    LightWorld = 0
    DarkWorld = 1
    UnderWorld = 2
    HyruleCastle = 3
    EasternPalace = 4
    DesertPalace = 5
    TowerOfHera = 6
    CastleTower = 7
    PalaceOfDarkness = 8
    SwampPalace = 9
    SkullWoods = 10
    ThievesTown = 11
    IcePalace = 12
    MiseryMire = 13
    TurtleRock = 14
    GanonsTower = 15
    OverWorld = 16


dungeon_worlds = {
    "Overworld": World.OverWorld,
    "Underworld": World.UnderWorld,
    "Hyrule_Castle": World.HyruleCastle,
    "Eastern_Palace": World.EasternPalace,
    "Desert_Palace": World.DesertPalace,
    "Tower_of_Hera": World.TowerOfHera,
    "Castle_Tower": World.CastleTower,
    "Palace_of_Darkness": World.PalaceOfDarkness,
    "Swamp_Palace": World.SwampPalace,
    "Skull_Woods": World.SkullWoods,
    "Thieves_Town": World.ThievesTown,
    "Ice_Palace": World.IcePalace,
    "Misery_Mire": World.MiseryMire,
    "Turtle_Rock": World.TurtleRock,
    "Ganons_Tower": World.GanonsTower,
}

MAPS_DIR = Path("data") / "maps"


worlds_data = {
    World.LightWorld: {
        "entrances": location_data.lightworld_coordinates,
        "locations": location_data.lightworld_items,
        "map_file": MAPS_DIR / "lightworld512.png",
        "map_image": None,
        "canvas_image": None,
    },
    World.DarkWorld: {
        "entrances": location_data.darkworld_coordinates,
        "locations": location_data.darkworld_items,
        "map_file": MAPS_DIR / "darkworld512.png",
        "map_image": None,
        "canvas_image": None,
    },
    World.OverWorld: {
        "entrances": {**location_data.lightworld_coordinates, **location_data.darkworld_coordinates},
        "locations": {
            **{
                k: {"x": v["x"] / 2, "y": v["y"] / 2, "loc_type": v["loc_type"]}
                for k, v in location_data.lightworld_items.items()
            },
            **{
                k: {"x": (v["x"] / 2) + 256, "y": v["y"] / 2, "loc_type": v["loc_type"]}
                for k, v in location_data.darkworld_items.items()
            },
        },
        "map_file": MAPS_DIR / "overworld.png",
    },
    World.UnderWorld: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Underworld_Items_Trimmed_512.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Underworld" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.HyruleCastle: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Hyrule_Castle.png",
        "map_file": None,
        "supertile_locs": [
            k for k, v in location_data.underworld_categories.items() if "Escape" in v or "Hyrule Castle" in v
        ],
        "map_image": None,
        "canvas_image": None,
    },
    World.EasternPalace: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Eastern_Palace.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Eastern Palace" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.DesertPalace: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Desert_Palace.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Desert Palace" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.TowerOfHera: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Tower_of_Hera.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Tower of Hera" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.CastleTower: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Castle_Tower.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Castle Tower" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.PalaceOfDarkness: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Palace_of_Darkness.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Palace of Darkness" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.SwampPalace: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Swamp_Palace.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Swamp Palace" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.SkullWoods: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Skull_Woods.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Skull Woods" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.ThievesTown: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Thieves_Town.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Thieves' Town" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.IcePalace: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Ice_Palace.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Ice Palace" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.MiseryMire: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Misery_Mire.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Misery Mire" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.TurtleRock: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Turtle_Rock.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Turtle Rock" in v],
        "map_image": None,
        "canvas_image": None,
    },
    World.GanonsTower: {
        "locations": location_data.underworld_items,
        "locations_bak": location_data.underworld_items,
        # "map_file": MAPS_DIR / "Dungeons" / "Ganons_Tower.png",
        "map_file": None,
        "supertile_locs": [k for k, v in location_data.underworld_categories.items() if "Ganons Tower" in v],
        "map_image": None,
        "canvas_image": None,
    },
}
