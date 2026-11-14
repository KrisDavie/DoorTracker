"""The items panel, and the reading of small keys."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from gui.Doors.logic import BIG_KEYS, ITEMS_AT, ITEMS_LENGTH, READABLE, small_keys
from gui.qt.items_panel import BIG_KEY_PICTURE, PICTURE_NAMES, PICTURES, SHORT_NAMES, SLOTS, clicked, picture


def test_every_item_read_has_a_place_and_a_picture():
    placed = [item for slot in SLOTS for item in slot.items]
    assert sorted(placed) == sorted(READABLE - set(BIG_KEYS.values()))
    assert list(SHORT_NAMES) == list(BIG_KEYS)
    pictures = [PICTURE_NAMES.get(item, item) for item in placed] + [slot.start for slot in SLOTS if slot.start] + [BIG_KEY_PICTURE]
    for name in pictures:
        assert (PICTURES / f"{name}.gif").exists(), name


def test_small_keys_for_the_dungeon_the_player_is_in_are_counted_apart():
    save = bytearray(ITEMS_LENGTH)
    for address, value in {0x37C: 1, 0x37F: 2, 0x382: 5}.items():
        save[address - ITEMS_AT] = value

    save[0x36F - ITEMS_AT] = 0xFF  # outside
    keys = small_keys(bytes(save), 0xFF)
    assert (keys["Hyrule_Castle"], keys["Desert_Palace"], keys["Palace_of_Darkness"], keys["Ganons_Tower"]) == (1, 2, 5, 0)

    # In Palace of Darkness, dungeon 0x0C, with one of its keys used; then in the castle, which shares the sewers' keys
    save[0x36F - ITEMS_AT] = 4
    assert small_keys(bytes(save), 0x0C)["Palace_of_Darkness"] == 4
    assert small_keys(bytes(save), 0x0C)["Desert_Palace"] == 2
    assert small_keys(bytes(save), 0x02)["Hyrule_Castle"] == 4


def test_the_panel_lights_what_is_held(window):
    page = window.pages["Eastern_Palace"]
    panel = page.items_panel
    shown = {slot.items[0]: label for slot, label in panel.slots}
    # In the bottom right corner of the map, with nothing lit before anything is read
    assert not panel.isHidden()
    assert panel.geometry().bottomRight() == page.view.rect().bottomRight()
    assert shown["Hammer"].pixmap().toImage() != picture_in_cell("Hammer")

    held = frozenset({"Hammer", "Fighter Sword", "Master Sword", "Big Key (Desert Palace)"})
    page.set_items(held, {"Desert_Palace": 2})
    assert shown["Fighter Sword"].toolTip() == "Master Sword"  # the better one
    assert shown["Hammer"].pixmap().toImage() == picture_in_cell("Hammer")
    assert shown["Hookshot"].pixmap().toImage() != picture_in_cell("Hookshot")  # greyed out
    assert panel.counts["Desert_Palace"].text() == "2" and panel.counts["Eastern_Palace"].text() == "0"
    assert panel.big_keys["Desert_Palace"].pixmap().toImage() == panel.big_key.toImage()
    assert panel.big_keys["Eastern_Palace"].pixmap().toImage() == panel.no_big_key.toImage()


def test_clicks_go_through_what_a_slot_can_hold_and_right_clicks_go_back():
    sword = next(slot for slot in SLOTS if "Master Sword" in slot.items)
    boomerang = next(slot for slot in SLOTS if "Red Boomerang" in slot.items)
    held = frozenset({"Hammer"})
    held = clicked(sword, clicked(sword, held, 1), 1)
    assert held == {"Hammer", "Fighter Sword", "Master Sword"}
    assert clicked(sword, held, -1) == {"Hammer", "Fighter Sword"}
    assert clicked(sword, frozenset(), -1) == set(sword.items)  # back from none is the best
    # The two boomerangs: none, blue, red, both
    seen = [frozenset()]
    for _ in range(4):
        seen.append(clicked(boomerang, seen[-1], 1))
    assert seen == [set(), {"Blue Boomerang"}, {"Red Boomerang"}, {"Blue Boomerang", "Red Boomerang"}, set()]


def test_clicking_in_the_panel_sets_what_is_held_in_every_tab(window, app):
    page, other = window.pages["Eastern_Palace"], window.pages["Thieves_Town"]
    panel = page.items_panel
    shown = {slot.items[0]: label for slot, label in panel.slots}
    left, right = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton

    QTest.mouseClick(shown["Hammer"], left)
    QTest.mouseClick(panel.counts["Desert_Palace"], left)
    QTest.mouseClick(panel.counts["Desert_Palace"], left)
    QTest.mouseClick(panel.counts["Swamp_Palace"], right)  # not below none
    QTest.mouseClick(panel.big_keys["Thieves_Town"], left)
    assert other.model.items == {"Hammer", "Big Key (Thieves Town)"}
    assert other.items_panel.counts["Desert_Palace"].text() == "2"
    assert other.items_panel.counts["Swamp_Palace"].text() == "0"

    QTest.mouseClick(shown["Hammer"], right)
    assert other.model.items == {"Big Key (Thieves Town)"}


def picture_in_cell(name):
    """An item's picture as its slot shows it when held: centred in the cell."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPixmap

    from gui.qt.items_panel import CELL

    cell = QPixmap(CELL, CELL)
    cell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cell)
    whole = picture(name)
    painter.drawPixmap((CELL - whole.width()) // 2, 0, whole)
    painter.end()
    return cell.toImage()


def test_the_tab_closes_the_panel_in_every_tab_and_it_stays_in_its_corner(window):
    for page in window.pages.values():
        page.set_items(frozenset({"Hammer"}), {})
    page, other = window.pages["Eastern_Palace"], window.pages["Desert_Palace"]
    assert not page.items_panel.body.isHidden()

    page.items_panel.tab.click()
    assert page.items_panel.body.isHidden() and other.items_panel.body.isHidden()
    assert window.settings["show_items"] is False
    # Only the tab is left, still in the corner
    assert not page.items_panel.isHidden()
    assert page.items_panel.geometry().bottomRight() == page.view.rect().bottomRight()

    page.items_panel.tab.click()
    assert not page.items_panel.body.isHidden()
    assert page.items_panel.geometry().bottomRight() == page.view.rect().bottomRight()
