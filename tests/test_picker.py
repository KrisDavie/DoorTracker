"""The Add supertile picker."""

import DoorsTracker
from gui.Doors.rooms import DOORLESS_ROOMS, SUPERTILES, Node


def test_every_known_supertile_can_be_picked_and_drawn(window, app):
    picker = DoorsTracker.EgPicker(window, window.assets, unavailable=set())
    assert set(picker.buttons) == set(SUPERTILES)
    assert all(button.isEnabled() for button in picker.buttons.values())

    # A room with no doors, which no vanilla layout includes
    fairy = DOORLESS_ROOMS["Ice Fairy"].tile
    picker.buttons[fairy].click()
    assert picker.choice == fairy

    page = window.pages["Ice_Palace"]
    window.pick_eg_tile = lambda page: fairy
    page.add_tile_from_picker(0.0, 0.0)
    app.processEvents()
    assert Node(*fairy) in page._rooms
    assert page._rooms[Node(*fairy)].title == "Ice Fairy"
