"""The static room data built in gui/Doors/rooms.py."""

from gui.Doors.rooms import DOORS, ROOM_LINKS, ROOM_PORTS, SPLIT, SUPERTILES, WHOLE


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
