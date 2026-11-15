"""The static room data built in gui/Doors/rooms.py."""

import ast

import data.doors_data as doors_data
from gui.Doors.randomizer import literals, parse
from gui.Doors.rooms import DOORS, ROOM_LINKS, ROOM_PORTS, SPLIT, SUPERTILES, WHOLE
from gui.Doors.rules import called

# The randomizer's tables that data/doors_data.py holds a copy of
COPIED = (
    "logical_connections",
    "vanilla_logical_connections",
    "spiral_staircases",
    "straight_staircases",
    "open_edges",
    "falldown_pits",
    "dungeon_warps",
    "ladders",
    "interior_doors",
    "default_door_connections",
    "default_one_way_connections",
)


def test_the_copied_door_tables_are_the_randomizers():
    for name in COPIED:
        (theirs,) = literals("DoorShuffle.py", name)
        assert sorted(map(tuple, getattr(doors_data, name))) == sorted(map(tuple, theirs)), name


def test_the_regions_are_the_randomizers_but_for_what_the_tracker_adds():
    theirs = {}
    for node in ast.walk(parse("Regions.py")):
        if isinstance(node, ast.Call) and called(node) == "create_dungeon_region":
            theirs[ast.literal_eval(node.args[1])] = (ast.literal_eval(node.args[4]) or []) if len(node.args) > 4 else []
    assert set(doors_data.regions_to_doors) == set(theirs)

    def own(name):
        """A door the tracker puts where a drop lands."""
        return "Drop Entrance" in name or name == "Sewer Drop"

    for region, exits in theirs.items():
        # The tracker has a block pushed across the ice cross leave by the door it slides out of
        expected = {doors_data.door_fix_map.get(name, name) for name in exits if not own(name)}
        assert {name for name in doors_data.regions_to_doors[region] if not own(name)} == expected, region


def test_every_door_is_in_exactly_one_part_of_its_supertile():
    for tile, record in SUPERTILES.items():
        in_parts = [name for part in record.parts for name in part]
        assert sorted(in_parts) == sorted(record.doors), tile
        for index, part in enumerate(record.parts):
            for name in part:
                assert DOORS[name].tile == tile and DOORS[name].part == index, name


def test_warps_and_holes_run_between_two_supertiles():
    # A warp inside one supertile joins its parts instead of being drawn
    for link in ROOM_LINKS:
        start, end = ROOM_PORTS[link.a], ROOM_PORTS[link.b]
        assert start.tile != end.tile, link
        assert link.a not in DOORS and link.b not in DOORS, link
        for view in (SPLIT, WHOLE):
            assert view.node(link.a).tile == start.tile and view.node(link.b).tile == end.tile
