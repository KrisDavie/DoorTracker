"""Colours and sizes used to draw the map."""

from dataclasses import dataclass

from PIL import ImageColor

DOOR_RADIUS = 5.5  # an unexplored door; linked and interior doors are drawn smaller

DUNGEON_COLOURS = {
    "Hyrule_Castle": "#566573",
    "Eastern_Palace": "#2e8b57",
    "Desert_Palace": "#b9892b",
    "Tower_of_Hera": "#b4532a",
    "Castle_Tower": "#8e5bb5",
    "Palace_of_Darkness": "#5b3f96",
    "Swamp_Palace": "#2878b5",
    "Skull_Woods": "#6b8e23",
    "Thieves_Town": "#8b5a2b",
    "Ice_Palace": "#3aa6c9",
    "Misery_Mire": "#8f8f2a",
    "Turtle_Rock": "#c0392b",
    "Ganons_Tower": "#2c2c34",
}
UNKNOWN_DUNGEON_COLOUR = "#666666"

BACKGROUND = "#eef0f3"
DOOR_OPEN = "#1fd655"
DOOR_LINKED = "#9aa0a6"
DOOR_INTERIOR = "#1b2a8a"
DOOR_SELECTED = "#ff9800"
PLAYER = "#e60000"
EDGE_FADED = "#c9cdd4"
WARP_COLOUR = "#7b4fc4"
DROP_COLOUR = "#4a4f57"


@dataclass(frozen=True)
class DoorStyle:
    fill: str
    scale: float  # of DOOR_RADIUS
    outline: float  # width


# How a door dot is drawn, by its state
DOOR_STYLES = {
    "open": DoorStyle(DOOR_OPEN, 1.0, 1.5),
    "linked": DoorStyle(DOOR_LINKED, 0.7, 1),
    "interior": DoorStyle(DOOR_INTERIOR, 0.7, 1),
}


def lighten(colour, amount):
    r, g, b = ImageColor.getrgb(colour)
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def link_colours(n):
    """n distinct hues, dark enough to read on the light background."""
    colours = []
    for i in range(n):
        # Golden angle hue steps
        hue = (i * 137.508) % 360
        r, g, b = ImageColor.getrgb(f"hsl({hue:.0f}, 78%, {38 + (i % 3) * 6}%)")
        colours.append(f"#{r:02x}{g:02x}{b:02x}")
    return colours


