"""Mouse handling in the map view, driven with real mouse events."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from gui.qt.graph_page import Hit
from support import grow, open_doors, positions


class At:
    """Stands in for a mouse event at a point of the viewport."""

    def __init__(self, point):
        self.point = point

    def position(self):
        return QPointF(self.point)


def page_with_map(window, app):
    window.select_dungeon("Turtle_Rock")
    page = window.pages["Turtle_Rock"]
    grow(page.model, 5)
    page.rebuild()
    page.fit_view()
    app.processEvents()
    return page


def on_screen(page, x, y):
    return page.view.mapFromScene(QPointF(x, y))


def point_on(page, wanted):
    """A viewport point where this Hit is what the mouse is over."""
    if wanted.edge is not None:
        path = next(item for item in page._links if item.edge is wanted.edge).path()
        candidates = [path.pointAtPercent(k / 10) for k in range(1, 10)]
    else:
        x, y = page.model.pos[wanted.node]
        left, top, right, bottom = page.model.box(wanted.node)
        candidates = [QPointF(x + left + (right - left) * i / 6, y + top + (bottom - top) * j / 6) for i in range(1, 6) for j in range(1, 6)]
    for candidate in candidates:
        point = on_screen(page, candidate.x(), candidate.y())
        if page.hit_at(At(point)) == wanted:
            return point
    raise AssertionError(f"nowhere to click on {wanted}")


def test_linking_two_doors_by_clicking_then_removing_the_link(window, app):
    page = page_with_map(window, app)
    model, viewport = page.model, page.view.viewport()
    first, second = [doors[0] for doors in (open_doors(model, tile) for tile in model.tiles) if doors][:2]
    links = len(model.door_links)

    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, on_screen(page, *model.port(first)))
    assert page.selected_door == first
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, on_screen(page, *model.port(second)))
    assert page.selected_door is None
    assert [(x.door, x.linked_door) for x in model.door_links[links:]] == [(first, second)]

    edge = next(item.edge for item in page._links if item.edge.link is model.door_links[-1])
    QTest.mouseClick(viewport, Qt.RightButton, Qt.NoModifier, point_on(page, Hit(edge=edge)))
    assert len(model.door_links) == links


def test_dragging_moves_the_whole_block_and_pins_nothing(window, app):
    page = page_with_map(window, app)
    model, viewport = page.model, page.view.viewport()
    node = next(n for n in model.nodes() if len(model.blocks.of(n)) > 1)
    block = set(model.blocks.of(node))
    before = positions(model)
    start = point_on(page, Hit(node=node))

    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    for step in range(1, 7):
        QTest.mouseMove(viewport, start + QPoint(10 * step, 4 * step))
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 24))

    moves = {n: (model.pos[n][0] - before[n][0], model.pos[n][1] - before[n][1]) for n in before}
    assert moves[node][0] > 20
    assert {moves[n] for n in block} == {moves[node]}
    assert {moves[n] for n in before if n not in block} <= {(0.0, 0.0)}
    assert not model.fixed and not model.held

    QTest.mouseClick(viewport, Qt.LeftButton, Qt.ControlModifier, start + QPoint(60, 24))
    assert model.fixed == block
