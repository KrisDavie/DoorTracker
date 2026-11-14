"""Joining rooms into blocks, the save file, removing supertiles, and layout."""

import copy

from data.doors_data import dark_tiles
from gui.Doors.rooms import DOORS, INTERIOR_DOORS, SPLIT, SUPERTILES, supertile
from support import grow, joined_doors, new_model, next_link, open_doors, positions


def stairs_pair(model):
    """An up stair and a down stair, in two lit, unsplit supertiles that are not on the map."""

    def stair(facing, avoid=None):
        return next(
            d
            for tile in sorted(SUPERTILES)
            if tile not in model.tiles and tile not in dark_tiles and tile != avoid and SPLIT.part_count(tile) == 1
            for d in supertile(tile).doors
            if DOORS[d].facing == facing and d not in INTERIOR_DOORS
        )

    up = stair("Up")
    return up, stair("Dn", avoid=DOORS[up].tile)


def test_rooms_linked_through_facing_doorways_are_joined():
    model = new_model()
    door, other = next_link(model)
    model.add_link(door, other)
    (link,) = model.door_links
    a, b = model.rooms.node(door), model.rooms.node(other)
    assert link in model.blocks.joined
    assert model.blocks.root[a] == model.blocks.root[b]
    # The two doorways meet, and are drawn as a seam instead of two dots
    ax, ay = model.port(door)
    bx, by = model.port(other)
    assert abs(ax - bx) + abs(ay - by) < 40
    assert door not in {dot.door for dot in model.door_dots(a)}


def test_stairs_link_rooms_without_joining_them():
    model = grow(new_model(), 4)
    up, down = stairs_pair(model)
    model.add_link(up, down)
    link = model.door_links[-1]
    assert link not in model.blocks.joined
    assert model.blocks.root[model.rooms.node(up)] != model.blocks.root[model.rooms.node(down)]
    assert "cannot be joined" in (model.toggle_join(link) or "")


def test_a_join_split_by_hand_stays_split():
    model = grow(new_model(), 3)
    link = model.door_links[0]
    assert link in model.blocks.joined
    assert model.toggle_join(link) is None
    model.add_link(*next_link(model))
    assert link not in model.blocks.joined

    again = new_model()
    again.load(model.save())
    assert (link.door, link.linked_door) not in joined_doors(again)
    assert joined_doors(again) == joined_doors(model)


def test_removing_a_link_leaves_the_other_joins_alone():
    model = grow(new_model(), 6)
    before = joined_doors(model)
    removed = model.door_links[0]
    model.remove_link(removed)
    assert joined_doors(model) == [pair for pair in before if pair != (removed.door, removed.linked_door)]


def contested_map():
    """A map where two links want the same spot, and the one that got it is not the one the default order picks."""
    base = grow(new_model(), 8)
    loser = next(x for x in base.door_links if base.join_offset(x.door, x.linked_door) is not None and x not in base.blocks.joined)
    saved = base.save()
    saved["joined_links"].insert(0, base.door_links.index(loser))
    model = new_model()
    model.load(saved)
    assert (loser.door, loser.linked_door) in joined_doors(model)
    assert joined_doors(model) != joined_doors(base)
    return model


def decorated_map():
    """A contested map with a bit of everything else a save has to carry."""
    model = contested_map()
    model.add_link(*stairs_pair(model))
    model.toggle_join(next(x for x in model.door_links if x in model.blocks.joined))
    model.set_pinned(model.rooms.node(model.door_links[3].door), True)
    spare = [d for tile in model.tiles for d in open_doors(model, tile)]
    model.annotate(spare[0], "Bow", [])
    model.auto_add_lobby(next(d for d in spare[1:] if DOORS[d].facing == "So"))

    # Still contested: the default order would join different links
    by_default = new_model()
    by_default.load({**model.save(), "joined_links": []})
    assert joined_doors(by_default) != joined_doors(model)
    return model


def contents(model):
    """Everything a save has to carry, read from the model."""
    return {
        "links": [(link.door, link.linked_door, link.join) for link in model.door_links],
        "joined": joined_doors(model),
        "lobbies": [(lobby.door, lobby.lobby) for lobby in model.lobby_doors],
        "icons": model.special_doors,
        "pinned": model.fixed,
        "lit": {tile: state.has_been_lit for tile, state in model.tiles.items()},
        "positions": {node: (round(x, 1), round(y, 1)) for node, (x, y) in model.pos.items()},
    }


def test_a_save_loads_back_to_the_same_map():
    model = decorated_map()
    saved = model.save()
    again = new_model()
    again.load(copy.deepcopy(saved))
    assert contents(again) == contents(model)
    assert again.save() == saved


def test_files_from_before_join_was_called_join_still_load():
    model = decorated_map()
    saved = model.save()
    older = copy.deepcopy(saved)
    older["stacked_links"] = older.pop("joined_links")
    for entry in older["door_links"]:
        if "join" in entry:
            entry["stack"] = entry.pop("join")
    again = new_model()
    again.load(older)
    assert contents(again) == contents(model)


def test_a_file_with_no_saved_joins_gets_them_from_its_positions():
    model = decorated_map()
    saved = model.save()
    del saved["joined_links"]
    again = new_model()
    again.load(saved)
    assert joined_doors(again) == joined_doors(model)


def test_a_file_naming_doors_this_version_does_not_know_still_loads():
    model = decorated_map()
    saved = model.save()
    saved["door_links"].append({"door": "No Such Door N", "linked_door": saved["door_links"][0]["door"]})
    saved["lobby_doors"].append({"door": "No Such Door S", "lobby": "Nowhere"})
    saved["special_doors"]["No Such Door E"] = "Bow"

    again = new_model()
    again.load(saved)
    again.relayout()
    assert joined_doors(again) == joined_doors(model)
    assert all("No Such Door" not in edge.a + edge.b for edge in again.edges())
    assert again.save()["door_links"] == saved["door_links"]


def test_removing_a_supertile_removes_everything_on_it():
    model = decorated_map()
    link = model.door_links[2]
    tile = DOORS[link.linked_door].tile
    node = model.rooms.node(link.linked_door)
    model.set_pinned(node, True)
    model.toggle_expanded(node)
    model.move_player(tile, 250, 250)
    model.move_player(tile, 250, 250)
    model.annotate(open_doors(model, tile)[0], "Bow", [])

    assert model.remove_tile(tile) is True
    doors = set(supertile(tile).doors)
    assert not [x for x in model.door_links if x.door in doors or x.linked_door in doors]
    assert not doors & set(model.special_doors)
    assert model.player is None
    for nodes in (model.pos, model.fixed, model.kept_expanded, model.visited, model.blocks.root, model.nodes()):
        assert not [n for n in nodes if n.tile == tile]
    # Still a working map
    model.relayout()
    model.save()

    start = next(iter(new_model().tiles))
    assert model.remove_tile(start) is False


def test_relayout_leaves_no_rooms_overlapping():
    model = grow(new_model(), 20)
    model.relayout()

    # Parts of one supertile may share picture area; any two supertiles may not, joined or not
    boxes = []
    for node, (x, y) in model.pos.items():
        for left, top, right, bottom in model.pieces(node):
            boxes.append((node.tile, x + left, y + top, x + right, y + bottom))
    for i, (tile, left, top, right, bottom) in enumerate(boxes):
        for other, l2, t2, r2, b2 in boxes[i + 1 :]:
            if other != tile:
                assert right <= l2 or r2 <= left or bottom <= t2 or b2 <= top, (tile, other)


def test_relayout_leaves_pinned_rooms_where_they_are():
    model = grow(new_model(), 20)
    pinned = model.rooms.node(model.door_links[4].linked_door)
    model.set_pinned(pinned, True)
    before = positions(model)
    held = model.blocks.of(pinned)
    model.relayout()

    def moved(node):
        (x, y), (was_x, was_y) = positions(model)[node], before[node]
        return abs(x - was_x) + abs(y - was_y) > 0.01

    assert not [node for node in held if moved(node)]
    assert [node for node in before if moved(node)]


def test_adding_a_room_does_not_move_the_rooms_already_there():
    model = grow(new_model(), 8)
    model.relayout()
    before = positions(model)

    # A room with no link yet, as the tracker adds it; then the link
    door, other = next_link(model)
    model.add_tile(DOORS[other].tile, has_been_lit=True)
    assert {node: positions(model)[node] for node in before} == before
    model.auto_add_door_link(door, other)
    moved = [node for node in before if positions(model)[node] != before[node]]
    assert moved == []
