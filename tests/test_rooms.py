"""The static room data built in gui/Doors/rooms.py."""

import ast

from data.doors_data import door_coordinates
from gui.Doors.randomizer import parse
from gui.Doors.rooms import DOORS, ROOM_LINKS, ROOM_PORTS, SPLIT, SUPERTILES, WHOLE
from gui.Doors.rules import called

# The kinds of door in the randomizer's Doors.py that are walked through, which the tracker draws
WALKED = {"Nrml", "Intr", "Sprl", "StrS", "Lddr", "Open"}


def test_the_doors_placed_by_hand_are_the_randomizers():
    kinds = {}
    for node in ast.walk(parse("Doors.py")):
        if isinstance(node, ast.Call) and called(node) == "create_door" and len(node.args) == 3:
            kind = node.args[2]
            assert isinstance(kind, ast.Name)
            kinds[ast.literal_eval(node.args[1])] = kind.id
    placed = {entry["name"] for entries in door_coordinates.values() for entry in entries}
    # A door the randomizer renames or adds has no place until data/doors_data.py gives it one
    assert {name for name, kind in kinds.items() if kind in WALKED} <= placed
    # The places for doors the randomizer lacks are the tracker's own, where a drop lands
    assert all("Drop Entrance" in name or name == "Sewer Drop" for name in placed - set(kinds))


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
