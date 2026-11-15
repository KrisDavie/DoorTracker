"""Checks drawn on the cards."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from data.doors_data import regions_to_doors
from gui.Doors.checks import checks
from gui.Doors.graph_model import CHECKS_BY_TILE, CheckState
from gui.Doors.logic import ITEMS_AT, ITEMS_LENGTH, items_held
from gui.Doors.rooms import DOORS, SPLIT, Node
from gui.Doors.rules import check_regions
from support import new_model


class At:
    """Stands in for a mouse event at a point of the viewport."""

    def __init__(self, point):
        self.point = point

    def position(self):
        return QPointF(self.point)


def model_leading_to(name, tab):
    """A map of the check's supertile, with an entrance on a door of the region the check is in."""
    model = new_model(tab)
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door(next(door for door in regions_to_doors[check_regions[name]] if door in DOORS), tab)
    model.update()
    return model


def test_every_check_is_drawn_on_exactly_one_part_of_its_supertile():
    model = new_model()
    for tile, names in CHECKS_BY_TILE.items():
        drawn = [spot.name for part in range(SPLIT.part_count(tile)) for spot in model.check_spots(Node(*tile, part))]
        assert sorted(drawn) == sorted(names), tile


def test_a_check_is_drawn_on_the_part_its_region_is_in():
    model = new_model()
    for name, check in checks.items():
        doors = [door for door in regions_to_doors.get(check_regions[name], ()) if door in DOORS and DOORS[door].tile == check["tile"]]
        if doors:
            assert name in [spot.name for spot in model.check_spots(SPLIT.node(doors[0]))], name


def test_a_passage_that_takes_a_lever_opens_once_the_lever_can_be_reached():
    # The chests are down a ladder that is under water until the swamp is drained
    name = "Swamp Palace - Flooded Room - Left"
    model = new_model("Swamp_Palace")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door("Swamp Flooded Room Up Stairs", "Swamp_Palace")
    model.update()
    model.set_items(frozenset({"Flippers", "Hookshot", "Hammer"}))
    assert model.check_state(name) is CheckState.BLOCKED
    # A way to the part of the room with the lever
    model.add_lobby_door("Swamp Drain Right Up Stairs", "Swamp_Palace")
    model.update()
    assert model.check_state(name) is CheckState.OPEN


def test_items_are_read_from_the_save_data():
    save = bytearray(ITEMS_LENGTH)
    # Hammer, mitts, a swordless seed's sword byte, the red shield, red boomerang, something in the second bottle,
    # bombs, and the big keys of Thieves' Town and Turtle Rock
    equipment = {0x34B: 1, 0x354: 2, 0x359: 0xFF, 0x35A: 2, 0x38C: 0x40, 0x35D: 3, 0x370: 10, 0x366: 0x18}
    for address, value in equipment.items():
        save[address - ITEMS_AT] = value
    held = {"Hammer", "Power Glove", "Titans Mitts", "Blue Shield", "Red Shield", "Red Boomerang", "Bottle", "Bombs"}
    assert items_held(bytes(save)) == held | {"Big Key (Thieves Town)", "Big Key (Turtle Rock)"}


def test_a_check_is_blocked_until_the_item_its_rule_names_is_held():
    name = "Thieves' Town - Big Chest"
    model = model_leading_to(name, "Thieves_Town")
    assert model.check_state(name) is CheckState.OPEN  # no game read yet: nothing is known to be missing
    model.set_items(frozenset({"Big Key (Thieves Town)"}))
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(frozenset({"Big Key (Thieves Town)", "Hammer"}))
    assert model.check_state(name) is CheckState.OPEN


def test_a_big_chest_takes_the_big_key_of_the_tab_it_is_on():
    name = "Eastern Palace - Big Chest"
    for tab, key in (("Eastern_Palace", "Big Key (Eastern Palace)"), ("Hyrule_Castle", "Big Key (Escape)")):
        model = model_leading_to(name, tab)
        model.set_items(frozenset({"Big Key (Desert Palace)"}))
        assert model.check_state(name) is CheckState.BLOCKED, tab
        model.set_items(frozenset({key}))
        assert model.check_state(name) is CheckState.OPEN, tab


def test_a_check_past_a_passage_is_blocked_until_the_item_for_the_passage_is_held():
    # The chest is across the moat from the lobby
    name = "Swamp Palace - Entrance"
    model = new_model("Swamp_Palace")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.add_lobby_door("Swamp Lobby S", "Swamp_Palace")
    model.update()
    model.set_items(frozenset())
    assert model.check_state(name) is CheckState.BLOCKED
    model.set_items(frozenset({"Flippers"}))
    assert model.check_state(name) is CheckState.OPEN


def test_a_check_the_map_does_not_lead_to_is_unrouted():
    name = "Ganons Tower - Validation Chest"
    model = new_model("Ganons_Tower")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.update()
    # A room being on the map is no way to it
    assert model.check_state(name) is CheckState.UNROUTED
    # Nor is this door, the way out of the chest's room: the chest is only reached across the gap from Moldorm
    model.add_lobby_door("GT Validation WS", "Ganons_Tower")
    model.update()
    assert model.check_state(name) is CheckState.UNROUTED


def test_a_check_the_map_does_not_lead_to_that_takes_an_item_not_held_is_both():
    name = "Thieves' Town - Big Chest"
    model = new_model("Thieves_Town")
    model.add_tile(checks[name]["tile"], has_been_lit=True)
    model.update()
    model.set_items(frozenset())
    assert model.check_state(name) is CheckState.UNROUTED_BLOCKED


def test_a_drop_is_no_way_in_until_the_player_has_used_it_or_says_so():
    # The secret room's chests, in the room the sewer drop lands in, with no other way to it on the map
    name = "Sewers - Secret Room - Left"
    model = new_model("Hyrule_Castle")
    assert model.assumed("Sewer Drop")
    assert model.check_state(name) is CheckState.UNROUTED

    model.set_entrance_used("Sewer Drop", True)
    assert model.check_state(name) is CheckState.OPEN
    model.set_entrance_used("Sewer Drop", False)
    assert model.check_state(name) is CheckState.UNROUTED

    # Being seen in the drop's supertile is not using the drop, nor is coming in by the stairs at its top, behind
    # blocks that only push the other way
    tile = checks[name]["tile"]
    model.move_player(tile, 400, 290)
    model.arrive("Sewers Secret Room Up Stairs")
    assert model.assumed("Sewer Drop")
    # Falling into the dungeon there is
    model.dropped_in(tile, 400, 290)
    assert not model.assumed("Sewer Drop")
    assert model.check_state(name) is CheckState.OPEN
    # and that is kept with the map
    reloaded = new_model("Hyrule_Castle")
    reloaded.load(model.save())
    assert reloaded.check_state(name) is CheckState.OPEN


def test_clicking_a_drops_marker_says_the_player_can_use_it(window, app):
    window.select_dungeon("Hyrule_Castle")
    page = window.pages["Hyrule_Castle"]
    page.fit_view()
    app.processEvents()
    model = page.model
    x, y = model.port("Sewer Drop")
    marker = page.view.mapFromScene(QPointF(x, y))
    assert page.hit_at(At(marker)).icon == "Sewer Drop"

    # A click says it can be used, a right click takes that back; a second click changes nothing
    viewport = page.view.viewport()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=marker)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=marker)
    assert not model.assumed("Sewer Drop")
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=marker)
    assert model.assumed("Sewer Drop")


def test_a_check_is_named_on_hover_and_collected_by_clicking(window, app):
    name = "Eastern Palace - Compass Chest"
    tile = checks[name]["tile"]
    window.select_dungeon("Eastern_Palace")
    page = window.pages["Eastern_Palace"]
    page.model.add_tile(tile, has_been_lit=True)
    page.rebuild()
    page.fit_view()
    app.processEvents()
    node = next(n for n in page.model.nodes() if any(spot.name == name for spot in page.model.check_spots(n)))
    spot = next(spot for spot in page.model.check_spots(node) if spot.name == name)
    x, y = page.model.pos[node]
    on_it = page.view.mapFromScene(QPointF(x + spot.x, y + spot.y))
    viewport = page.view.viewport()

    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == name
    # A click collects it, a right click takes that back; a second click changes nothing
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=on_it)
    assert window.collected == {name}
    page.set_hover(page.hit_at(At(on_it)))
    assert page.status.text() == f"{name}   (collected)"
    QTest.mouseClick(viewport, Qt.MouseButton.RightButton, pos=on_it)
    assert window.collected == set()
