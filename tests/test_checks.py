"""Checks drawn on the cards."""

from PySide6.QtCore import QPointF

from data.checks import checks
from gui.Doors.graph_model import CHECKS_BY_TILE
from gui.Doors.rooms import SPLIT, Node
from support import new_model


class At:
    """Stands in for a mouse event at a point of the viewport."""

    def __init__(self, point):
        self.point = point

    def position(self):
        return QPointF(self.point)


def test_every_check_is_drawn_on_exactly_one_part_of_its_supertile():
    model = new_model()
    for tile, names in CHECKS_BY_TILE.items():
        drawn = [spot.name for part in range(SPLIT.part_count(tile)) for spot in model.check_spots(Node(*tile, part))]
        assert sorted(drawn) == sorted(names), tile


def test_hovering_a_check_names_it_and_says_when_it_is_collected(window, app):
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
    over_it = At(page.view.mapFromScene(QPointF(x + spot.x, y + spot.y)))

    page.set_hover(page.hit_at(over_it))
    assert page.status.text() == name
    window.collected = {name}
    page.set_hover(page.hit_at(over_it))
    assert page.status.text() == f"{name}   (collected)"
