"""Helpers for building maps in tests. Maps are built from the door tables, not from tracker files."""

from data.doors_data import dark_tiles
from data.worlds_data import dungeon_worlds
from gui.Doors.graph_model import GraphModel
from gui.Doors.rooms import DOORS, INTERIOR_DOORS, SPLIT, SUPERTILES, supertile

OPPOSITE = {"No": "So", "So": "No", "Ea": "We", "We": "Ea"}


def new_model(tab="Turtle_Rock", **flags):
    settings = {
        "hide_single_route_tiles": False,
        "prefer_fill_map": False,
        "decoupled_doors": False,
        "vanilla_drops": True,
        "hide_dead_rooms": True,
        "split_rooms": True,
    }
    settings.update(flags)
    return GraphModel(dungeon_worlds[tab], settings)


def parts_shown(model, tile):
    return sorted(node.part for node in model.nodes() if node.tile == tile)


def point_in(model, tile, part):
    """A player position, 0..512, that the model places in this part of a split supertile."""
    for left, top, right, bottom in supertile(tile).areas[part]:
        x, y = (left + right) / 2, (top + bottom) / 2
        if model.player_node(tile, x, y).part == part:
            return x, y
    raise AssertionError(f"no point found in part {part} of {tile}")


def open_doors(model, tile):
    """Doors of a supertile that can take a link: not interior, not linked, not an entrance."""
    return [
        name
        for name in supertile(tile).doors
        if name not in INTERIOR_DOORS and not model.has_target(name) and name not in model.lobby_door_names()
    ]


def next_link(model):
    """(door on the map, facing door of a supertile not on the map).

    The new supertile is lit and unsplit, and the one with the most doorways, so the map can keep growing.
    """

    def doorways(tile):
        return [d for d in open_doors(model, tile) if DOORS[d].facing in OPPOSITE]

    best = None
    for tile in list(model.tiles):
        for door in doorways(tile):
            for other in sorted(SUPERTILES):
                if other in model.tiles or other in dark_tiles or SPLIT.part_count(other) > 1:
                    continue
                for candidate in doorways(other):
                    if DOORS[candidate].facing == OPPOSITE[DOORS[door].facing]:
                        if best is None or len(doorways(other)) > best[0]:
                            best = (len(doorways(other)), door, candidate)
                        break
    return best[1:]


def grow(model, rooms):
    """Link new supertiles onto the map through facing doorways until it has this many more."""
    for _ in range(rooms):
        model.add_link(*next_link(model))
    return model


def positions(model):
    return {node: tuple(xy) for node, xy in model.pos.items()}


def joined_doors(model):
    return sorted((link.door, link.linked_door) for link in model.blocks.joined)
