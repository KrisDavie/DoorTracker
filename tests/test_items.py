"""The items panel, and the reading of small keys."""

from gui.Doors.logic import BIG_KEYS, ITEMS_AT, ITEMS_LENGTH, READABLE, small_keys
from gui.qt.items_panel import BIG_KEY_PICTURE, GRID, PICTURE_NAMES, PICTURES, SHORT_NAMES, picture

SLOTS = [slot for row in GRID for slot in row if slot is not None]


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
    assert panel.isHidden()  # nothing read yet

    held = frozenset({"Hammer", "Fighter Sword", "Master Sword", "Big Key (Desert Palace)"})
    page.set_items(held, {"Desert_Palace": 2})
    assert not panel.isHidden()
    # In the bottom right corner of the map
    assert panel.geometry().bottomRight() == page.view.rect().bottomRight()

    shown = {slot.items[0]: label for slot, label in panel.slots}
    assert shown["Fighter Sword"].toolTip() == "Master Sword"  # the better one
    assert shown["Hammer"].pixmap().toImage() == picture_in_cell("Hammer")
    assert shown["Hookshot"].pixmap().toImage() != picture_in_cell("Hookshot")  # greyed out
    assert panel.counts["Desert_Palace"].text() == "2" and panel.counts["Desert_Palace"].isEnabled()
    assert panel.counts["Eastern_Palace"].text() == "0" and not panel.counts["Eastern_Palace"].isEnabled()
    assert panel.big_keys["Desert_Palace"].pixmap().toImage() == panel.big_key.toImage()
    assert panel.big_keys["Eastern_Palace"].pixmap().toImage() == panel.no_big_key.toImage()

    page.set_items(None, {})
    assert panel.isHidden()


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
