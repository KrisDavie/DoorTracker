"""Which parts of a split supertile are on the map.

Supertiles used:
(13, 9)  GT: part 0 Crystal Conveyor and Compass Room, part 1 Invisible Bridges
(11, 13) Thieves: part 0 the lobby, part 1 the big chest nook, whose picture area lies inside the lobby's
(11, 7)  GT: three parts; a warp runs from its part 1 to part 1 of (13, 9)
(9, 10)  Eastern: part 1 is the courtyard, where the warp from the fairy room (9, 8) lands
"""

from data.doors_data import dark_tiles
from gui.Doors.rooms import SPLIT, Node, supertile
from support import new_model, parts_shown, point_in


def test_a_supertile_entered_without_a_door_shows_only_the_part_stood_in():
    model = new_model()
    model.add_tile((13, 9), has_been_lit=True, player=point_in(model, (13, 9), 1))
    assert parts_shown(model, (13, 9)) == [1]


def test_the_door_entered_by_overrides_the_guess_from_position():
    model = new_model()
    nook = point_in(model, (11, 13), 1)
    model.add_tile((11, 13), has_been_lit=True, player=nook)
    assert parts_shown(model, (11, 13)) == [1]
    # The tracker reports the position first, then the door
    assert model.locate((11, 13), *nook) is None
    model.arrive("Thieves Lobby S")
    model.update()
    assert parts_shown(model, (11, 13)) == [0]
    assert model.move_player((11, 13), *nook).part == 0


def test_a_supertile_added_by_hand_shows_every_part_as_one_block():
    model = new_model()
    model.add_tile((13, 9), has_been_lit=True)
    assert parts_shown(model, (13, 9)) == [0, 1]
    assert len({model.blocks.root[node] for node in model.nodes() if node.tile == (13, 9)}) == 1


def test_a_link_shows_the_part_its_door_is_in():
    model = new_model()
    model.add_tile((13, 9), has_been_lit=True, player=point_in(model, (13, 9), 0))
    model.add_tile((11, 13), has_been_lit=True, player=point_in(model, (11, 13), 0))
    assert parts_shown(model, (13, 9)) == [0]
    model.add_link("Thieves Lobby E", "GT Invisible Bridges WS")
    assert parts_shown(model, (13, 9)) == [0, 1]


def test_a_warp_shows_the_part_it_lands_in_but_not_the_part_it_leaves():
    model = new_model("Eastern_Palace")
    model.add_tile((9, 10), has_been_lit=True, player=point_in(model, (9, 10), 0))
    assert parts_shown(model, (9, 10)) == [0]
    model.add_tile((9, 8), has_been_lit=True)
    assert parts_shown(model, (9, 10)) == [0, 1]

    # Standing where the warp from (11, 7) part 1 lands does not show that part
    model = new_model("Ganons_Tower")
    model.add_tile((13, 9), has_been_lit=True, player=point_in(model, (13, 9), 1))
    model.add_tile((11, 7), has_been_lit=True)
    model.arrive("GT DMs Room SW")
    model.update()
    assert parts_shown(model, (11, 7)) == [2]


def test_a_warp_brings_in_the_supertile_it_leads_to_but_not_the_one_it_comes_from():
    # From part 0 of (13, 9) a warp leads to part 0 of (11, 7)
    model = new_model("Ganons_Tower")
    model.add_tile((13, 9), has_been_lit=True, player=point_in(model, (13, 9), 0))
    assert parts_shown(model, (11, 7)) == [0]

    # Part 1 of (13, 9) is only where a warp from (11, 7) lands
    model = new_model("Ganons_Tower")
    model.add_tile((13, 9), has_been_lit=True, player=point_in(model, (13, 9), 1))
    assert (11, 7) not in model.tiles


def test_an_unlit_dark_supertile_is_one_card_whatever_is_known_of_its_parts():
    # (10, 6): part 0 PoD Dark Basement, part 1 PoD Dark Alley, where the warp from (11, 0) lands
    model = new_model("Palace_of_Darkness")
    model.add_tile((10, 6), has_been_lit=False, player=point_in(model, (10, 6), 0))
    model.add_tile((11, 0), has_been_lit=True)
    assert parts_shown(model, (10, 6)) == [0]
    card = Node(10, 6)
    assert sorted(model.rooms.doors(card)) == sorted(supertile((10, 6)).doors)
    assert {model.rooms.node(door) for door in supertile((10, 6)).doors} == {card}
    x, y = model.pos[card]

    # Lit: the parts that are known, about where the card was
    model.light((10, 6))
    assert parts_shown(model, (10, 6)) == [0, 1]
    for part in (0, 1):
        px, py = model.pos[Node(10, 6, part)]
        assert abs(px - x) + abs(py - y) < 128


def test_what_is_learnt_in_the_dark_is_kept_for_when_the_room_is_lit():
    model = new_model("Palace_of_Darkness")
    model.add_tile((10, 6), has_been_lit=False, player=point_in(model, (10, 6), 1))
    assert parts_shown(model, (10, 6)) == [0]
    again = new_model("Palace_of_Darkness")
    again.load(model.save())
    again.light((10, 6))
    assert parts_shown(again, (10, 6)) == [1]


def test_parts_reached_without_a_link_survive_a_save():
    model = new_model()
    model.add_tile((13, 9), has_been_lit=True, player=point_in(model, (13, 9), 1))
    model.add_tile((11, 7), has_been_lit=True)
    saved = model.save()

    again = new_model()
    again.load(saved)
    assert parts_shown(again, (13, 9)) == [1]
    assert parts_shown(again, (11, 7)) == [0, 1, 2]

    # A file from before reached parts were saved
    del saved["reached_parts"]
    older = new_model()
    older.load(saved)
    assert parts_shown(older, (13, 9)) == [0, 1]


def test_an_unlit_dark_room_hides_its_shape_and_where_its_doors_are():
    tile = next(t for t in sorted(dark_tiles) if SPLIT.part_count(t) == 1 and len(supertile(t).doors) > 1)
    node = Node(*tile)
    model = new_model()
    model.add_tile(tile, has_been_lit=False, player=(250, 250))
    assert {(dot.x, dot.y) for dot in model.door_dots(node)} == {(0.0, 0.0)}
    assert model.pieces(node) == [(-64.0, -64.0, 64.0, 64.0)]

    assert model.light(tile) is True
    assert model.light(tile) is False
    assert len({(dot.x, dot.y) for dot in model.door_dots(node)}) > 1
