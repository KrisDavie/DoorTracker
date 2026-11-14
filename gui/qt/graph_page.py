"""Qt view of a dungeon map. Scene coordinates are the model's world units; the view transform is the camera."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QSurfaceFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.doors_data import mandatory_tiles
from data.doors_sprite_data import ITEM_SHEET_PATH
from data.room_bounds import room_bounds
from data.worlds_data import World
from gui.Doors.graph_model import THUMB, Edge, GraphModel, TileState
from gui.Doors.layout import LINK_GAP
from gui.Doors.rooms import (
    DOORS,
    DUNGEON_BACKGROUNDS,
    INTERIOR_DOORS,
    WHOLE,
    EdgeKind,
    Node,
    Tile,
    door_direction,
    door_vector,
    entrance_only,
    supertile,
)
from gui.qt.style import (
    BACKGROUND,
    DOOR_LINKED,
    DOOR_OPEN,
    DOOR_RADIUS,
    DOOR_SELECTED,
    DOOR_STYLES,
    DROP_COLOUR,
    EDGE_FADED,
    PLAYER,
    WARP_COLOUR,
    dungeon_colour,
    lighten,
    link_colours,
)

if TYPE_CHECKING:
    from DoorsTracker import MainWindow

MIN_ZOOM, MAX_ZOOM = 0.1, 4.0
# Settings that are attributes of the model: setting -> attribute
MODEL_OPTIONS = {
    "show_all_doors": "show_all_doors",
    "auto_join": "auto_join",
    "circle_repulsion": "circle_repulsion",
    "spacing": "spacing",
    "dead_end_pull": "leaf_pull",
}
WORLD = 1_000_000  # scene half-extent
CHECK_SIZE = 9.0  # side of a check's square, world units
# A room this close to where it is drawn is not redrawn: under half a pixel at full zoom. A settled map still
# shifts by less than this on every solver step, which would otherwise redraw everything
STILL = 0.1


@dataclass(frozen=True)
class Hit:
    """What is under the mouse. One of the first four is set, or none over the background."""

    node: Node | None = None  # a room card
    door: str | None = None  # a door dot
    icon: str | None = None  # an icon, by the door it is on
    edge: Edge | None = None  # a line between doors, or the seam of a joined link
    check: str | None = None  # a check's square, with the node it is on


@dataclass
class Press:
    """A left button press, until the button is released."""

    hit: Hit
    pos: QPointF  # last mouse position, in view pixels
    node: Node | None = None  # what dragging moves; None pans the view
    moved: bool = False


class Assets:
    """Pixmaps shared by all tabs: supertile pictures at several sizes, and the icon sheet."""

    def __init__(self, eg_img: Image.Image | None):
        self.eg_img = eg_img  # the whole EG map
        self._tiles: dict[tuple[Tile, bool], dict[int, QPixmap]] = {}
        self._thumbnails: dict[tuple[Tile, int], QPixmap] = {}
        self._sheet: QPixmap | None = None
        self._icons: dict[str, QPixmap] = {}

    def thumbnail(self, tile: Tile, size: int) -> QPixmap:
        """Supertile picture at an exact size, for the supertile picker."""
        key = (tile, size)
        if key not in self._thumbnails:
            x, y = tile
            if self.eg_img is None:
                image = QImage(size, size, QImage.Format.Format_RGB888)
                image.fill(QColor("#444"))
            else:
                crop = self.eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).convert("RGB")
                crop = crop.resize((size, size), Image.Resampling.BILINEAR, reducing_gap=2.0)
                image = QImage(crop.tobytes(), size, size, size * 3, QImage.Format.Format_RGB888).copy()
            self._thumbnails[key] = QPixmap.fromImage(image)
        return self._thumbnails[key]

    def tile(self, tile: Tile, wanted_px: float, blank_dead: bool = False) -> QPixmap:
        """Supertile pixmap at the smallest stored size >= wanted_px. blank_dead paints over dead rooms."""
        bounds = room_bounds.get(tile, {})
        blank_dead = blank_dead and bool(bounds.get("dead"))
        key = (tile, blank_dead)
        if key not in self._tiles:
            x, y = tile
            if self.eg_img is None:
                image = QImage(256, 256, QImage.Format.Format_RGB888)
                image.fill(QColor("#444"))
            else:
                crop = self.eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).convert("RGB")
                if blank_dead:
                    from PIL import ImageDraw

                    draw = ImageDraw.Draw(crop)
                    for left, top, right, bottom in bounds["dead"]:
                        draw.rectangle((left - 2, top - 2, right + 1, bottom + 1), fill=tuple(bounds["background"]))
                image = QImage(crop.tobytes(), 512, 512, 512 * 3, QImage.Format.Format_RGB888).copy()
            levels = {}
            for size in (512, 256, 128, 64):
                scaled = (
                    image
                    if image.width() == size
                    else image.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                levels[size] = QPixmap.fromImage(scaled)
            self._tiles[key] = levels
        levels = self._tiles[key]
        for size in (64, 128, 256, 512):
            if size >= wanted_px:
                return levels[size]
        return levels[512]

    def icon(self, name: str) -> QPixmap | None:
        import data.doors_sprite_data as sprites

        if name not in self._icons:
            if name not in sprites.all_icons:
                return None
            if self._sheet is None:
                self._sheet = QPixmap(str(ITEM_SHEET_PATH))
            row, column = sprites.all_icons[name]
            self._icons[name] = self._sheet.copy(column * 16, row * 16, 16, 16)
        return self._icons[name]


class RoomItem(QGraphicsItem):
    """One node: picture, border, pin. Doors are a separate item (DoorsItem) above the links."""

    def __init__(self, page: GraphPage, node: Node):
        super().__init__()
        self.page = page
        self.node = node
        self.hit = Hit(node=node)
        model = page.model
        self.box = model.box(node)
        # Sorted so pieces[0] is the top-left one
        self.pieces = [
            QRectF(left, top, right - left, bottom - top)
            for left, top, right, bottom in sorted(model.pieces(node), key=lambda p: (p[1], p[0]))
        ]
        # Border follows the union of the pieces
        self.outline = self._around(self.pieces, 0)
        self.player_outline = self._around(self.pieces, 3)
        self.w, self.h = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.blank_dead = bool(model.experimental_flags.get("trim_rooms"))
        self.colour = QColor(dungeon_colour(supertile(node.tile).dungeon))
        self.hidden = model.is_hidden_dark(node.tile)
        self.compact = node in model.compact
        self.title = "Dark room" if self.hidden else model.rooms.title(node)
        self.pinned = node in model.fixed
        self.keep_expanded = node in model.kept_expanded
        self.setZValue(1)

    @staticmethod
    def _around(pieces, grow):
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for rect in pieces:
            path.addRect(rect.adjusted(-grow, -grow, grow, grow))
        return path.simplified()

    def boundingRect(self):
        return QRectF(self.box[0] - 5, self.box[1] - 5, self.w + 10, self.h + 10)

    def shape(self):
        path = QPainterPath()
        for rect in self.pieces:
            path.addRect(rect)
        return path

    def paint(self, painter, option, widget=None):
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        first = self.pieces[0]
        if self.compact:
            painter.fillRect(first, QColor(lighten(self.colour.name(), 0.7)))
        elif self.hidden:
            painter.fillRect(first, QColor("#000"))
            font = QFont()
            font.setPixelSize(40)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#555"))
            painter.drawText(first, Qt.AlignmentFlag.AlignCenter, "?")
        else:
            pixmap = self.page.assets.tile(
                self.node.tile, THUMB * lod * painter.device().devicePixelRatioF(), blank_dead=self.blank_dead
            )
            per_unit = pixmap.width() / THUMB
            for rect in self.pieces:
                source = QRectF(
                    (rect.left() + THUMB / 2) * per_unit,
                    (rect.top() + THUMB / 2) * per_unit,
                    rect.width() * per_unit,
                    rect.height() * per_unit,
                )
                painter.drawPixmap(rect, pixmap, source)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.keep_expanded:
            painter.setPen(QPen(QColor("#18c418"), 6))
            painter.drawPath(self.outline)
        painter.setPen(QPen(self.colour, 2))
        painter.drawPath(self.outline)

        if lod * 11 >= 5 and self.page.top.settings["labels"]:
            font = QFont()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            if self.compact:
                painter.setPen(QColor("#111"))
                text = metrics.elidedText(self.title, Qt.TextElideMode.ElideRight, first.width() - 6)
                painter.drawText(first, Qt.AlignmentFlag.AlignCenter, text)
            # Full-size rooms are labelled by LabelItem

        if self.pinned:
            self._paint_pin(painter, first)

        if self.page.model.player is not None and self.page.model.player.node == self.node:
            painter.setPen(QPen(QColor(PLAYER), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self.player_outline)

    @staticmethod
    def _paint_pin(painter, rect):
        """A pushpin in the top right corner."""
        size = 20.0
        box = QRectF(rect.right() - size - 3, rect.top() + 3, size, size)
        painter.setPen(QPen(QColor("#222"), 1))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(box)
        painter.setPen(QPen(QColor("#222"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(
            QPointF(box.left() + size * 0.46, box.top() + size * 0.54),
            QPointF(box.left() + size * 0.2, box.top() + size * 0.8),
        )
        painter.setPen(QPen(QColor("#7a1512"), 1))
        painter.setBrush(QColor("#e53935"))
        painter.drawEllipse(QRectF(box.left() + size * 0.36, box.top() + size * 0.16, size * 0.48, size * 0.48))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ff8a80"))
        painter.drawEllipse(QRectF(box.left() + size * 0.52, box.top() + size * 0.24, size * 0.14, size * 0.14))


class LabelItem(QGraphicsItem):
    """Room name at the top-left of its first piece, on a layer above all rooms so it is never clipped."""

    def __init__(self, room: RoomItem):
        super().__init__()
        self.text = room.title
        self.colour = room.colour
        self.font = QFont()
        self.font.setPixelSize(11)
        self.font.setBold(True)
        metrics = QFontMetricsF(self.font)
        first = room.pieces[0]
        self.tag = QRectF(first.left(), first.top(), metrics.horizontalAdvance(self.text) + 7, metrics.height() + 2)
        self.setZValue(1.5)
        self.setOpacity(0.5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.tag

    def shape(self):
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        if option.levelOfDetailFromTransform(painter.worldTransform()) * 11 < 5:
            return
        painter.fillRect(self.tag, self.colour)
        painter.setFont(self.font)
        painter.setPen(QColor("white"))
        painter.drawText(self.tag.adjusted(3, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)


class ReachItem(QGraphicsItem):
    """Debug overlay of what pushes blocks apart.

    Each outline is a shape grown by half a reach, so two blocks push when the same kind of outline overlaps.
    Solid: the push between rooms. Dashed: the push between circles, when repelling by circle.
    Hatched: a pinned or held block, which pushes but is not moved.
    """

    def __init__(self, page: GraphPage):
        super().__init__()
        self.page = page
        self.shapes = []
        self.outlines: list[QPainterPath] = []  # of the push between rooms, one per shape
        self._merged: dict[tuple, QPainterPath] = {}  # see _outline
        self.bounds = QRectF()
        self.setZValue(0.5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def refresh(self):
        self.prepareGeometryChange()
        self.shapes = self.page.model.repulsion_shapes()
        self.outlines = [self._outline(shape) for shape in self.shapes]
        bounds = QRectF()
        for shape in self.shapes:
            for left, top, right, bottom in shape.boxes:
                bounds = bounds.united(QRectF(left, top, right - left, bottom - top))
            if shape.circle:
                x, y, radius = shape.circle
                bounds = bounds.united(QRectF(x - radius, y - radius, radius * 2, radius * 2))
        reach = max((max(shape.reach, shape.contact) for shape in self.shapes), default=0.0)
        self.bounds = bounds.adjusted(-reach, -reach, reach, reach)
        self.update()

    def boundingRect(self):
        return self.bounds

    def shape(self):
        return QPainterPath()

    def _outline(self, shape) -> QPainterPath:
        """A block's rooms grown by half the push's reach. Rounded, as the solver measures the gap between two rooms.

        Merging the rooms into one outline is slow, and a block keeps its shape as it moves: each shape is
        merged once and after that only moved.
        """
        x0, y0 = shape.boxes[0][:2]
        boxes = tuple((round(left - x0, 2), round(top - y0, 2), round(right - x0, 2), round(bottom - y0, 2)) for left, top, right, bottom in shape.boxes)
        merged = self._merged.get((shape.contact, boxes))
        if merged is None:
            reach, half = shape.contact, shape.contact / 2
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for left, top, right, bottom in boxes:
                path.addRoundedRect(QRectF(left - half, top - half, right - left + reach, bottom - top + reach), half, half)
            merged = self._merged[shape.contact, boxes] = path.simplified()
        return merged.translated(x0, y0)

    def paint(self, painter, option, widget=None):
        stiff = QPen(QColor(255, 200, 90, 230), 0)
        soft = QPen(QColor(255, 255, 255, 200), 0, Qt.PenStyle.DashLine)
        faint = QPen(QColor(255, 255, 255, 110), 0, Qt.PenStyle.DotLine)
        for shape, outline in zip(self.shapes, self.outlines):
            fill = QBrush(QColor(255, 255, 255, 110), Qt.BrushStyle.BDiagPattern) if shape.fixed else QBrush(QColor(255, 255, 255, 28))
            if shape.circle:
                x, y, radius = shape.circle
                painter.setBrush(fill)
                painter.setPen(soft)
                painter.drawEllipse(QPointF(x, y), radius + shape.reach / 2, radius + shape.reach / 2)
                # The circle itself
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(faint)
                painter.drawEllipse(QPointF(x, y), radius, radius)
            else:
                painter.setBrush(fill)
            painter.setPen(stiff)
            painter.drawPath(outline)


class DoorsItem(QGraphicsItem):
    """Door dots and player marker of one node, above the links."""

    def __init__(self, page: GraphPage, node: Node):
        super().__init__()
        self.page = page
        self.node = node
        # Door positions are relative to the full supertile, not the drawn pieces
        self.w, self.h = (page.model.size(node) if node in page.model.compact else (THUMB, THUMB))
        self.dots = page.model.door_dots(node)
        self.checks = page.model.check_spots(node) if page.top.settings["show_checks"] else []
        self.setZValue(3)
        # Hit shape is the dots only
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return QRectF(-self.w / 2 - 12, -self.h / 2 - 12, self.w + 24, self.h + 24)

    def shape(self):
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        page = self.page
        # Checks are squares, under the door dots, in the doors' colours: green to find, grey once collected
        half = CHECK_SIZE / 2
        painter.setPen(QPen(QColor("#111"), 1.5))
        for check in self.checks:
            painter.setBrush(QColor(DOOR_LINKED if check.name in page.top.collected else DOOR_OPEN))
            painter.drawRect(QRectF(check.x - half, check.y - half, CHECK_SIZE, CHECK_SIZE))
        for dot in self.dots:
            style = DOOR_STYLES[dot.state]
            fill, radius, outline = style.fill, DOOR_RADIUS * style.scale, style.outline
            if dot.door == page.selected_door:
                fill, radius, outline = DOOR_SELECTED, DOOR_RADIUS + 1, 2
            if dot.door == page.hot_door:
                fill, radius, outline = PLAYER, DOOR_RADIUS + 1, 2
            painter.setPen(QPen(QColor("#111"), outline))
            painter.setBrush(QColor(fill))
            painter.drawEllipse(QPointF(dot.x, dot.y), radius, radius)
        player = page.model.player
        if player is not None and player.node == self.node and self.node not in page.model.compact:
            x = (player.x / 512 - 0.5) * THUMB
            y = (player.y / 512 - 0.5) * THUMB
            painter.setPen(QPen(QColor(PLAYER), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x - 7, y - 7), QPointF(x + 7, y + 7))
            painter.drawLine(QPointF(x + 7, y - 7), QPointF(x - 7, y + 7))


class SeamItem(QGraphicsRectItem):
    """Bar across the doorway of two joined rooms."""

    def __init__(self, parent: QGraphicsItem, x: float, y: float, vertical: bool, edge: Edge):
        long_side, short_side = 11.0, 5.0
        hw, hh = (long_side, short_side) if vertical else (short_side, long_side)
        super().__init__(QRectF(x - hw, y - hh, hw * 2, hh * 2), parent)
        self.hit = Hit(edge=edge)
        self.setPen(QPen(QColor("#111"), 2))
        self.setBrush(QColor("#fffbe0"))


class IconItem(QGraphicsItem):
    """Icon on a door: an annotation or a lobby entrance."""

    def __init__(
        self,
        parent: QGraphicsItem,
        page: GraphPage,
        door: str,
        x: float,
        y: float,
        icon: str,
        lobby: str | None = None,
        direction: tuple[int, int] = (0, 1),
    ):
        super().__init__(parent)
        self.page = page
        self.hit = Hit(icon=door)
        self.icon = page.assets.icon(icon)
        self.lobby = lobby
        self.origin = QPointF(x, y)
        self.direction = direction
        self.spot = QPointF(x + direction[0] * 30, y + direction[1] * 30) if lobby else QPointF(x, y)

    def boundingRect(self):
        rect = QRectF(self.spot.x() - 60, self.spot.y() - 30, 120, 60)
        return rect.united(QRectF(self.origin.x() - 2, self.origin.y() - 2, 4, 4))

    def shape(self):
        path = QPainterPath()
        path.addRect(QRectF(self.spot.x() - 11, self.spot.y() - 11, 22, 22))
        return path

    def paint(self, painter, option, widget=None):
        if self.lobby and self.spot != self.origin:
            painter.setPen(QPen(QColor("#111"), 2.5, Qt.PenStyle.DashLine))
            painter.drawLine(self.origin, self.spot)
        box = QRectF(self.spot.x() - 9, self.spot.y() - 9, 18, 18)
        painter.setPen(QPen(QColor("#111") if self.lobby else QColor("white"), 2 if self.lobby else 1))
        painter.setBrush(QColor("white"))
        painter.drawRect(box.adjusted(-1, -1, 1, 1) if self.lobby else box)
        if self.icon is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(QRectF(self.spot.x() - 8, self.spot.y() - 8, 16, 16), self.icon, QRectF(0, 0, 16, 16))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self.lobby:
            lod = option.levelOfDetailFromTransform(painter.worldTransform())
            if lod * 10 >= 5:
                font = QFont()
                font.setPixelSize(10)
                font.setBold(True)
                painter.setFont(font)
                # Text colour chosen for contrast with the tab background
                painter.setPen(self.page.text_colour)
                below = self.direction[1] >= 0
                text_rect = QRectF(self.spot.x() - 60, self.spot.y() + (12 if below else -26), 120, 14)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.lobby.replace("_", " "))


class LinkItem(QGraphicsPathItem):
    """A link, interior connection, drop or warp between two doors."""

    def __init__(self, page: GraphPage, edge: Edge, colour: str):
        super().__init__()
        self.page = page
        self.edge = edge
        self.hit = Hit(edge=edge)
        self.interior = edge.kind is EdgeKind.INTERIOR
        self.dashed = edge.kind is EdgeKind.WARP
        self.colour = QColor("#222") if self.interior else QColor(colour)
        self.arrow = None
        # Worked out once: a link is made anew whenever the map's data changes, and its path is redrawn
        # every time either room moves
        model = page.model
        a, b = edge.a, edge.b
        self.node_a, self.node_b = model.rooms.node(a), model.rooms.node(b)
        self.offset_a, self.offset_b = model.port_offset(a), model.port_offset(b)
        self.facing_a = door_vector(a) if not model.is_hidden_dark(self.node_a.tile) else None
        self.facing_b = door_vector(b) if not model.is_hidden_dark(self.node_b.tile) else None
        self.same_block = model.blocks.root.get(self.node_a) == model.blocks.root.get(self.node_b)
        if edge.kind in (EdgeKind.WARP, EdgeKind.HOLE, EdgeKind.DROP):
            self.one_way = not edge.both_ways
        else:
            self.one_way = not self.interior and (
                model.decoupled() or (door_vector(a) is None and "Stairs" not in a and "Ladder" not in a)
            )
        # Tracked drops can be stored either way round; the arrow always points pit -> landing
        self.backwards = not model.decoupled() and door_direction(a) == "Up" and door_direction(b) == "Dn"
        self.setZValue(2)
        self.set_state(faded=False, strong=False)
        self.update_path()

    def set_state(self, faded, strong):
        if self.interior:
            pen = QPen(self.colour, 1.5, Qt.PenStyle.DashLine)
        else:
            pen = QPen(
                QColor(EDGE_FADED) if faded else self.colour,
                4 if strong else 3,
                Qt.PenStyle.DashLine if self.dashed else Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        self.setPen(pen)
        if self.arrow is not None:
            self.arrow.setBrush(pen.color())
        self.setZValue(2.5 if strong else 2)

    def update_path(self):
        pos = self.page.model.pos
        ax, ay = pos[self.node_a][0] + self.offset_a[0], pos[self.node_a][1] + self.offset_a[1]
        bx, by = pos[self.node_b][0] + self.offset_b[0], pos[self.node_b][1] + self.offset_b[1]
        dist = math.hypot(bx - ax, by - ay)
        reach = min(60.0, dist / 2.2)
        if self.node_a == self.node_b:
            reach = max(reach, 30.0)
        da, db = self.facing_a, self.facing_b
        path = QPainterPath(QPointF(ax, ay))
        # Control points out from each door that faces a direction
        c1 = QPointF(ax + da[0] * reach, ay + da[1] * reach) if da else None
        c2 = QPointF(bx + db[0] * reach, by + db[1] * reach) if db else None
        end = QPointF(bx, by)
        if c1 is not None and c2 is not None:
            if self.same_block and not self.interior and dist > 1:
                # Same block: the plain curve would be a straight line, so bow it sideways
                px, py = -(by - ay) / dist, (bx - ax) / dist
                if py < 0 or (py == 0 and px < 0):
                    px, py = -px, -py
                bow = dist * 0.3
                path.cubicTo(c1 + QPointF(px * bow, py * bow), c2 + QPointF(px * bow, py * bow), end)
            else:
                path.cubicTo(c1, c2, end)
        elif c1 is not None:
            path.quadTo(c1, end)
        elif c2 is not None:
            path.quadTo(c2, end)
        else:
            path.lineTo(end)
        self.setPath(path)

        if self.one_way:
            tip_x, tip_y = (ax, ay) if self.backwards else (bx, by)
            tail = path.pointAtPercent(0.08 if self.backwards else 0.92) if dist > 1 else QPointF(bx, by)
            angle = math.atan2(tip_y - tail.y(), tip_x - tail.x())
            head = QPolygonF(
                [
                    QPointF(tip_x, tip_y),
                    QPointF(tip_x - 16 * math.cos(angle - 0.4), tip_y - 16 * math.sin(angle - 0.4)),
                    QPointF(tip_x - 16 * math.cos(angle + 0.4), tip_y - 16 * math.sin(angle + 0.4)),
                ]
            )
            if self.arrow is None:
                self.arrow = QGraphicsPolygonItem(self)
                self.arrow.setPen(Qt.PenStyle.NoPen)
                self.arrow.setBrush(self.pen().color())
            self.arrow.setPolygon(head)

    def shape(self):
        # Wider hit area than the drawn line
        stroker = QPainterPathStroker()
        stroker.setWidth(9)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())


class GraphView(QGraphicsView):
    """Camera: pan and zoom by view transform only."""

    def __init__(self, page: GraphPage, use_gl: bool = True):
        super().__init__(page.scene)
        self.page = page
        self.setSceneRect(-WORLD, -WORLD, WORLD * 2, WORLD * 2)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(QColor(DUNGEON_BACKGROUNDS.get(page.dungeon_name, BACKGROUND)))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.gl = False
        if use_gl:
            try:
                from PySide6.QtOpenGLWidgets import QOpenGLWidget

                viewport = QOpenGLWidget()
                fmt = QSurfaceFormat()
                fmt.setSamples(4)
                viewport.setFormat(fmt)
                self.setViewport(viewport)
                self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
                self.viewport().setMouseTracking(True)
                self.gl = True
            except Exception:
                self.gl = False
        if not self.gl:
            self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        # Mouse tracking for hover, on both the view and its viewport
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    # ---- camera

    def zoom(self):
        return self.transform().m11()

    def camera(self):
        centre = self.mapToScene(self.viewport().rect().center())
        return centre.x(), centre.y(), self.zoom()

    def set_camera(self, x, y, zoom):
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.resetTransform()
        self.scale(zoom, zoom)
        self.centerOn(x, y)
        # centerOn rounds to whole pixels; correct the remainder
        centre = self.mapToScene(self.viewport().rect().center())
        self.translate(centre.x() - x, centre.y() - y)
        self.page.top.map_changed()

    def zoom_at(self, view_pos, factor):
        """Zoom about a viewport point."""
        factor = max(MIN_ZOOM / self.zoom(), min(MAX_ZOOM / self.zoom(), factor))
        before = self.mapToScene(view_pos)
        self.scale(factor, factor)
        after = self.mapToScene(view_pos)
        self.translate(after.x() - before.x(), after.y() - before.y())
        self.page.top.map_changed()

    def pan(self, dx, dy):
        self.translate(dx / self.zoom(), dy / self.zoom())
        self.page.top.map_changed()

    def fit(self, bounds):
        x0, y0, x1, y1 = bounds
        pad = 70
        size = self.viewport().size()
        zoom = min(size.width() / (x1 - x0 + pad * 2), size.height() / (y1 - y0 + pad * 2))
        self.set_camera((x0 + x1) / 2, (y0 + y1) / 2, min(1.0, zoom))

    # ---- timing, for Show FPS

    # The background is drawn first and the foreground last. Timing between them leaves out the wait for the
    # screen's refresh, which is spent before and after
    def drawBackground(self, painter, rect):
        self._draw_began = time.perf_counter()
        super().drawBackground(painter, rect)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        self.page.frame_drawn((time.perf_counter() - self._draw_began) * 1000)

    # ---- input, forwarded to the page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.page.view_resized()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.page._settling_size = False
        if delta:
            self.zoom_at(event.position().toPoint(), 1.0015**delta)
        event.accept()

    def mousePressEvent(self, event):
        self.page.on_press(event)

    def mouseMoveEvent(self, event):
        self.page.on_move(event)

    def mouseReleaseEvent(self, event):
        self.page.on_release(event)

    def mouseDoubleClickEvent(self, event):
        self.page.on_double_click(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.page.cancel_selection()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):
        self.page.set_hover(Hit())
        super().leaveEvent(event)


class GraphPage(QWidget):
    """One dungeon tab: view and input handling."""

    def __init__(self, top: MainWindow, tab_world: World, assets: Assets, use_gl: bool = True):
        super().__init__()
        self.top = top
        self.tab_world = tab_world
        self.assets = assets
        self.model = GraphModel(tab_world, top.settings)
        for name, attribute in MODEL_OPTIONS.items():
            setattr(self.model, attribute, top.settings[name])
        self.dungeon_name = self.model.dungeon_name

        background = QColor(DUNGEON_BACKGROUNDS.get(self.dungeon_name, BACKGROUND))
        self.text_colour = QColor("#111") if background.lightness() > 150 else QColor("white")
        self.selected_door: str | None = None  # first door of a link being made
        self.hot_door: str | None = None  # door under the mouse
        self._focus: Node | None = None  # hovered room; links not touching it are faded
        self._press: Press | None = None
        self._rooms: dict[Node, RoomItem] = {}
        self._doors: dict[Node, DoorsItem] = {}
        self._labels: dict[Node, LabelItem] = {}
        self._links: list[LinkItem] = []
        self._drawn_at: dict[Node, tuple[float, float]] = {}  # where each room's items were last put
        self._reach: ReachItem | None = None
        self._rubber: QGraphicsLineItem | None = None
        self._needs_fit = True
        self._settling_size = False
        self._forces_stale = False  # a force setting changed while this tab was hidden

        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.view = GraphView(self, use_gl=use_gl)

        self.status = top.status
        # These act on this tab only, so they are not on the window's toolbar: they float over a corner of the map
        panel = QWidget(self.view)
        panel.setAutoFillBackground(True)
        buttons = QHBoxLayout(panel)
        buttons.setContentsMargins(3, 3, 3, 3)
        buttons.setSpacing(3)
        fit = QPushButton("Fit")
        fit.clicked.connect(self.fit_view)
        relayout = QPushButton("Re-layout")
        relayout.clicked.connect(self.relayout)
        buttons.addWidget(fit)
        buttons.addWidget(relayout)
        panel.adjustSize()
        # View -> Show FPS. The readout is on the window's toolbar: a widget over the map makes the map
        # redraw whenever it changes, which would add to the count
        self._frames: deque[float] = deque()  # when each frame of the last second was drawn
        self._draw_ms = 0.0  # how long the last frame took to draw
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(250)
        self._fps_timer.timeout.connect(self._show_fps)
        if top.settings["show_fps"]:
            self._fps_timer.start()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._tick)
        if top.settings["simulate"]:
            self.timer.start()
        self.rebuild()

    # ---------------------------------------------------------------------- fps

    def frame_drawn(self, milliseconds: float) -> None:
        """The view has drawn the map once, in this long."""
        if self.top.settings["show_fps"]:
            self._frames.append(time.perf_counter())
            self._draw_ms = milliseconds

    def _show_fps(self) -> None:
        if not self.isVisible():
            return
        since = time.perf_counter() - 1
        while self._frames and self._frames[0] < since:
            self._frames.popleft()
        self.top.fps_label.setText(f"{len(self._frames)} fps  {self._draw_ms:.1f} ms")

    # ------------------------------------------------------------------ options

    def option_changed(self, name: str) -> None:
        """Act on a setting the window has just changed."""
        value = self.top.settings[name]
        if name in MODEL_OPTIONS:
            setattr(self.model, MODEL_OPTIONS[name], value)
        if name == "labels":
            for label in self._labels.values():
                label.setVisible(value)
            self.scene.update()
        elif name == "show_repulsion":
            if self._reach is not None:
                self._reach.setVisible(value)
                if value:
                    self._reach.refresh()
        elif name == "simulate":
            if value:
                self.timer.start()
            else:
                self.timer.stop()
        elif name in ("spacing", "dead_end_pull", "circle_repulsion"):
            if self.isVisible():
                self._forces_changed()
            else:
                # Settled when the tab is next shown, not on every step of a slider
                self._forces_stale = True
        elif name in ("auto_join", "trim_rooms", "split_rooms"):
            # These change which blocks there are, or their shapes
            self.relayout()
        elif name == "show_fps":
            if value:
                self._fps_timer.start()
            else:
                self._fps_timer.stop()
        elif name != "follow_player":
            self.redraw_canvas()

    def _forces_changed(self):
        """Settle now unless the simulation is running."""
        self._forces_stale = False
        if not self.top.settings["simulate"]:
            self.model.settle(150)
            self.update_positions()
        # The reach changed even if no room moved
        self._refresh_reach()
        self.top.map_changed()

    def _tick(self):
        if not self.isVisible():
            return
        self.model.settle(3)
        self.update_positions()

    # -------------------------------------------------------------------- scene

    def rebuild(self) -> None:
        """Recreate all scene items from the model. For data changes, not per frame."""
        model = self.model
        self.scene.clear()
        self._reach = ReachItem(self)
        self._reach.setVisible(self.top.settings["show_repulsion"])
        self.scene.addItem(self._reach)
        self._rooms, self._doors, self._links = {}, {}, []
        self._drawn_at = {}
        self._labels = {}
        self._rubber = None
        self._focus = None
        self.hot_door = None

        lobbies = {x.door: x.lobby for x in model.lobby_doors}
        for node in model.nodes():
            room = RoomItem(self, node)
            doors = DoorsItem(self, node)
            self.scene.addItem(room)
            self.scene.addItem(doors)
            self._rooms[node] = room
            self._doors[node] = doors
            if not room.compact:
                label = LabelItem(room)
                label.setVisible(self.top.settings["labels"])
                self.scene.addItem(label)
                self._labels[node] = label

        for door, icon in model.special_doors.items():
            if door not in DOORS:
                continue  # a file can name doors this version does not know
            node = self.model.rooms.node(door)
            if node not in self._doors:
                continue
            x, y = model.port_offset(door)
            if door in lobbies:
                direction = door_vector(door) or (0, 1)
                if "Drop" in door:
                    direction = (0, -1)
                if entrance_only(door):
                    # No dot to point at: the marker goes on the spot itself
                    direction = (0, 0)
                if model.is_hidden_dark(node.tile):
                    direction = (0, 1)
                lobby = lobbies[door]
                picture = "Drop" if "Drop" in lobby or "Drop" in door else lobby
                IconItem(self._doors[node], self, door, x, y, picture, lobby=lobby, direction=direction)
            else:
                IconItem(self._doors[node], self, door, x, y, icon)

        colours = dict(zip(model.door_links, link_colours(len(model.door_links))))
        for edge in model.edges():
            if edge.link in model.blocks.joined:
                # Joined: a seam across the doorway instead of a line
                node = self.model.rooms.node(edge.a)
                ax, ay = model.port(edge.a)
                bx, by = model.port(edge.b)
                cx, cy = model.pos[node]
                # Joined doorways face north/south or east/west
                vertical = door_vector(edge.a) in ((0, -1), (0, 1))
                SeamItem(self._doors[node], (ax + bx) / 2 - cx, (ay + by) / 2 - cy, vertical, edge)
                continue
            if edge.kind is EdgeKind.WARP:
                colour = WARP_COLOUR
            elif edge.kind in (EdgeKind.DROP, EdgeKind.HOLE):
                colour = DROP_COLOUR
            elif edge.link is not None:
                colour = colours[edge.link]
            else:
                colour = "#222"
            link = LinkItem(self, edge, colour)
            self.scene.addItem(link)
            self._links.append(link)

        self.update_positions(links=False)
        if self._needs_fit and model.pos and self.view.viewport().width() > 50 and self.isVisible():
            self.fit_view()
        self.top.map_changed()

    def update_positions(self, links: bool = True) -> None:
        """Move existing items to the model's positions. The per-frame path: only what moved is touched."""
        model = self.model
        moved = set()
        for node, room in self._rooms.items():
            if node in model.pos:
                x, y = model.pos[node]
                drawn = self._drawn_at.get(node)
                if drawn is not None and abs(drawn[0] - x) < STILL and abs(drawn[1] - y) < STILL:
                    continue
                self._drawn_at[node] = (x, y)
                moved.add(node)
                room.setPos(x, y)
                self._doors[node].setPos(x, y)
                if node in self._labels:
                    self._labels[node].setPos(x, y)
        if links:
            for link in self._links:
                if link.node_a in moved or link.node_b in moved:
                    link.update_path()
        if moved:
            self._refresh_reach()
        if self._rubber is not None and self.selected_door:
            line = self._rubber.line()
            start = model.port(self.selected_door)
            self._rubber.setLine(start[0], start[1], line.x2(), line.y2())

    def fit_view(self):
        self._needs_fit = False
        self.view.fit(self.model.bounds())

    def showEvent(self, event):
        super().showEvent(event)
        if self._forces_stale:
            self._forces_changed()
        if self._needs_fit and self.model.pos:
            # A tab not yet shown has no real size: refit on resize until the user moves the camera
            self._settling_size = True
            self.fit_view()
            QTimer.singleShot(400, self._stop_settling)

    def _stop_settling(self):
        self._settling_size = False

    def view_resized(self):
        if self._settling_size and self.model.pos:
            self.fit_view()

    def relayout(self):
        # Can take a few seconds on a big map
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            no_map_before = self.model.relayout()
        finally:
            QApplication.restoreOverrideCursor()
        self.rebuild()
        if no_map_before:
            self.fit_view()

    def redraw_canvas(self):
        self.model.update()
        self.rebuild()

    # ------------------------------------------------------------- hit testing

    def door_at(self, scene_pos: QPointF) -> str | None:
        """Door under the mouse, found by geometry (dots are not separate items)."""
        model = self.model
        reach = max(1.0, 6 / self.view.zoom())
        nearest, found = math.inf, None
        for node, doors in self._doors.items():
            if node not in model.pos:
                continue
            x, y = model.pos[node]
            if abs(scene_pos.x() - x) > doors.w / 2 + 10 or abs(scene_pos.y() - y) > doors.h / 2 + 10:
                continue
            for dot in doors.dots:
                distance = math.hypot(scene_pos.x() - x - dot.x, scene_pos.y() - y - dot.y)
                if distance <= max(DOOR_RADIUS * DOOR_STYLES[dot.state].scale, reach) + 1 and distance < nearest:
                    nearest, found = distance, dot.door
        return found

    def node_at(self, scene_pos: QPointF) -> Node | None:
        for node, (x, y) in self.model.pos.items():
            if any(
                left <= scene_pos.x() - x <= right and top <= scene_pos.y() - y <= bottom
                for left, top, right, bottom in self.model.pieces(node)
            ):
                return node
        return None

    def hit_at(self, event) -> Hit:
        """What is under the mouse. A door dot wins over anything but an icon."""
        view_pos = event.position().toPoint()
        # The item under the mouse, or the nearest parent of it, that says what it is
        item = self.view.itemAt(view_pos)
        found: Hit | None = None
        while item is not None and found is None:
            found = getattr(item, "hit", None)
            item = item.parentItem()
        hit = found if found is not None else Hit()
        scene_pos = self.view.mapToScene(view_pos)
        if hit.icon is None:
            door = self.door_at(scene_pos)
            if door is not None:
                return Hit(door=door)
        if hit.node is not None and hit.node in self._doors:
            # Check squares are not separate items either
            x, y = self.model.pos[hit.node]
            reach = max(CHECK_SIZE / 2, 5 / self.view.zoom())
            for check in self._doors[hit.node].checks:
                if abs(scene_pos.x() - x - check.x) <= reach and abs(scene_pos.y() - y - check.y) <= reach:
                    return Hit(node=hit.node, check=check.name)
        return hit

    # ------------------------------------------------------------------- mouse

    def on_press(self, event):
        self.view.setFocus()
        hit = self.hit_at(event)
        scene_pos = self.view.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.RightButton:
            self._context(event, hit, scene_pos)
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle(hit)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        node = self._node_of(hit, scene_pos)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if node is not None:
                self.set_pinned(node, node not in self.model.fixed)
            return
        self._press = Press(hit, event.position(), node)

    def _node_of(self, hit: Hit, scene_pos: QPointF) -> Node | None:
        """The node a press on this would pin or drag; None for the background or a link in open space."""
        if hit.node is not None:
            return hit.node
        door = hit.door or hit.icon
        if door is not None:
            return self.model.rooms.node(door)
        if hit.edge is not None:
            # A link over a room acts on that room
            return self.node_at(scene_pos) or (self.model.rooms.node(hit.edge.a) if self._within_block(hit.edge) else None)
        return None

    def _within_block(self, edge: Edge) -> bool:
        """True for an edge that does not leave its block: a joined link, or both ends on one node."""
        return edge.link in self.model.blocks.joined or self.model.rooms.node(edge.a) == self.model.rooms.node(edge.b)

    def on_move(self, event):
        press = self._press
        if press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            self.set_hover(self.hit_at(event))
            if self.selected_door:
                self._draw_rubber(self.view.mapToScene(event.position().toPoint()))
            return
        delta = event.position() - press.pos
        if not press.moved and abs(delta.x()) + abs(delta.y()) < 4:
            return
        press.moved = True
        press.pos = event.position()
        if press.node is None or press.node not in self.model.pos:
            self._settling_size = False
            self.view.pan(delta.x(), delta.y())
            return
        zoom = self.view.zoom()
        self.model.drag(press.node, delta.x() / zoom, delta.y() / zoom)
        self.update_positions()
        self.top.map_changed()

    def on_release(self, event):
        press, self._press = self._press, None
        self.model.drop()
        if press is not None and press.moved:
            # The dropped block is no longer held
            self._refresh_reach()
        if press is None or event.button() != Qt.MouseButton.LeftButton or press.moved:
            return
        if press.hit.door is not None:
            self._door_clicked(press.hit.door)
        elif press.hit == Hit() and self.selected_door:
            self.cancel_selection()

    def on_double_click(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press = None
        hit = self.hit_at(event)
        scene_pos = self.view.mapToScene(event.position().toPoint())
        if hit.door is not None:
            door = hit.door
            if self.model.has_target(door) or door in INTERIOR_DOORS:
                return
            self.cancel_selection()
            x, y = self.model.port(door)
            direction = door_vector(door) or (1, 0)
            reach = THUMB / 2 + LINK_GAP
            self.add_tile_from_picker(x + direction[0] * reach, y + direction[1] * reach)
        elif hit == Hit():
            self.add_tile_from_picker(scene_pos.x(), scene_pos.y())

    def _door_clicked(self, door: str) -> None:
        model = self.model
        if door in INTERIOR_DOORS or door in model.lobby_door_names():
            return
        if self.selected_door is None:
            if model.has_target(door):
                return
            self.selected_door = door
            self._repaint_doors()
            return
        if door == self.selected_door:
            self.cancel_selection()
            return
        if model.has_target(door) and not model.decoupled():
            return
        source, self.selected_door = self.selected_door, None
        model.add_link(source, door)
        self.rebuild()

    def cancel_selection(self):
        self.selected_door = None
        if self._rubber is not None:
            self.scene.removeItem(self._rubber)
            self._rubber = None
        self._repaint_doors()

    def _draw_rubber(self, scene_pos: QPointF) -> None:
        """Draw the line from the door being linked to the mouse."""
        if self.selected_door is None:
            return
        start = self.model.port(self.selected_door)
        if self._rubber is None:
            self._rubber = QGraphicsLineItem()
            self._rubber.setPen(QPen(QColor(DOOR_SELECTED), 2, Qt.PenStyle.DashLine))
            self._rubber.setZValue(4)
            self._rubber.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.scene.addItem(self._rubber)
        self._rubber.setLine(start[0], start[1], scene_pos.x(), scene_pos.y())

    def _repaint_doors(self):
        for item in self._doors.values():
            item.update()

    # ------------------------------------------------------------------- hover

    def set_hover(self, hit: Hit) -> None:
        """Show what the mouse is over in the status line, and highlight it."""
        model = self.model
        if hit.door != self.hot_door:
            self.hot_door = hit.door
            self._repaint_doors()
        if hit.door is not None:
            door = hit.door
            target = model.link_map().get(door)
            text = door + (f"  →  {target}" if target else "")
            if door in model.special_doors:
                text += f"   [{model.special_doors[door]}]"
            focus = model.rooms.node(door)
        elif hit.edge is not None:
            edge = hit.edge
            text = f"{edge.a}  ↔  {edge.b}"
            if edge.link in model.blocks.joined:
                text += "   (joined — middle click to split)"
            elif edge.link is not None and model.join_offset(edge.a, edge.b) is not None:
                text += "   (middle click to join)"
            elif edge.link is None and model.rooms.node(edge.a) != model.rooms.node(edge.b):
                if edge.kind in (EdgeKind.WARP, EdgeKind.HOLE):
                    # The far end is a port, not a door: name the room it lands in
                    text = f"{edge.a}  →  {model.rooms.title(model.rooms.node(edge.b))}"
                text += "   (warp)" if edge.kind is EdgeKind.WARP else "   (vanilla drop, assumed)"
            focus = self._focus
        elif hit.node is not None:
            node = hit.node
            if hit.check is not None:
                text = hit.check + ("   (collected)" if hit.check in self.top.collected else "")
            elif model.is_hidden_dark(node.tile):
                text = "Dark room"
            else:
                text = f"{', '.join(model.rooms.regions(node)[:4]) or model.rooms.title(node)}   (EG {node.x},{node.y})"
            focus = node
        elif hit.icon is not None:
            text = f"{hit.icon}: {model.special_doors.get(hit.icon, '')}"
            focus = model.rooms.node(hit.icon)
        else:
            text, focus = "", None
        if self.selected_door:
            text = f"Linking {self.selected_door} — click another door (Esc to cancel)   {text}"
        if text != self.status.text():
            self.status.setText(text)
        if self._press is None and focus != self._focus:
            self._focus = focus
            # Fade links not touching the hovered room
            for link in self._links:
                if link.interior:
                    continue
                touches = focus is None or focus in (model.rooms.node(link.edge.a), model.rooms.node(link.edge.b))
                link.set_state(faded=not touches, strong=touches and focus is not None)

    # ------------------------------------------------------------ other buttons

    def _middle(self, hit: Hit) -> None:
        model = self.model
        if hit.edge is not None:
            if hit.edge.link is None:
                return
            message = model.toggle_join(hit.edge.link)
            if message:
                self.status.setText(message)
            else:
                self.rebuild()
        elif hit.node is not None:
            model.toggle_expanded(hit.node)
            self.rebuild()

    def _context(self, event, hit: Hit, scene_pos: QPointF) -> None:
        model = self.model
        if hit.door is not None:
            icon = self.top.pick_icon(self.tab_world)
            if icon:
                import data.doors_sprite_data as sprites

                model.annotate(hit.door, icon, sprites.all_dungeon_lobbies)
                self.rebuild()
        elif hit.edge is not None:
            if hit.edge.link is not None:
                model.remove_link(hit.edge.link)
                self.rebuild()
        elif hit.icon is not None:
            model.remove_annotation(hit.icon)
            self.rebuild()
        elif hit.node is not None:
            node = hit.node
            menu = QMenu(self)
            if node in model.fixed:
                menu.addAction("Unpin", lambda: self.set_pinned(node, False))
            else:
                menu.addAction("Pin in place", lambda: self.set_pinned(node, True))
            if node.tile not in mandatory_tiles[self.tab_world]:
                menu.addSeparator()
                menu.addAction("Remove supertile…", lambda: self.remove_tile(node.tile))
            menu.exec(event.globalPosition().toPoint())
        else:
            menu = QMenu(self)
            menu.addAction("Fit to window", self.fit_view)
            menu.addAction("Re-layout", self.relayout)
            menu.addAction("Unpin all", self.unpin_all)
            menu.addAction("Add supertile here…", lambda: self.add_tile_from_picker(scene_pos.x(), scene_pos.y()))
            menu.exec(event.globalPosition().toPoint())

    def set_pinned(self, node: Node, pinned: bool) -> None:
        self.model.set_pinned(node, pinned)
        for member in self.model.blocks.of(node):
            if member in self._rooms:
                self._rooms[member].pinned = pinned
                self._rooms[member].update()
        self._refresh_reach()
        self.top.map_changed()

    def unpin_all(self):
        self.model.unpin_all()
        for room in self._rooms.values():
            room.pinned = False
            room.update()
        self._refresh_reach()
        self.top.map_changed()

    def _refresh_reach(self):
        if self._reach is not None and self._reach.isVisible():
            self._reach.refresh()

    def remove_tile(self, tile: Tile) -> None:
        # Also removes its links, lobbies and icons: confirm first
        answer = QMessageBox.question(
            self,
            "Remove supertile",
            f"Remove {WHOLE.title(Node(*tile))} and every link, lobby and annotation on it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes and self.model.remove_tile(tile):
            selected = DOORS.get(self.selected_door) if self.selected_door else None
            if selected is not None and selected.tile == tile:
                self.cancel_selection()
            self.rebuild()

    def add_tile_from_picker(self, x: float, y: float) -> None:
        tile = self.top.pick_eg_tile(self)
        if tile is None or tile in self.model.tiles:
            return
        # Added by hand: show it lit
        self.model.add_tile(tile, has_been_lit=True, at=(x, y))
        self.rebuild()

    # ------------------------------------------------- called by the tracker

    @property
    def tiles(self) -> dict[Tile, TileState]:
        return self.model.tiles

    def init_page(self):
        self.model.reset()
        self.selected_door = None
        self._needs_fit = True
        self.rebuild()

    def load_yaml(self, data):
        had_positions = self.model.load(data)
        self.selected_door = None
        camera = data.get("camera")
        self._needs_fit = not (camera and had_positions)
        self.rebuild()
        if camera and had_positions:
            # Restore the saved camera
            self.view.set_camera(float(camera[0]), float(camera[1]), float(camera[2]))

    def return_connections(self):
        data = self.model.save()
        x, y, zoom = self.view.camera()
        data["camera"] = [round(x, 1), round(y, 1), round(zoom, 4)]
        return data

    def auto_add_tile(self, tile: Tile, was_lit: bool = False, player: tuple[float, float] | None = None) -> None:
        """Add a supertile the player entered. player=(x, y) within it."""
        if self.model.add_tile(tile, has_been_lit=was_lit, player=player):
            self.rebuild()

    def auto_add_door_link(self, door: str | None, linked_door: str | None) -> None:
        added = self.model.auto_add_door_link(door, linked_door)
        self._arrived(linked_door, added)

    def auto_add_lobby(self, door: str | None) -> None:
        added = self.model.auto_add_lobby(door)
        self._arrived(door, added)

    def _arrived(self, door: str | None, changed: bool) -> None:
        """Tell the model which door the player entered by, then refresh."""
        if door is not None:
            self.model.arrive(door)
        if changed:
            self.rebuild()
        elif self.model.located is not None and self.model.located not in self._rooms:
            self.redraw_canvas()
        else:
            self.scene.update()

    def auto_light_tile(self, tile: Tile) -> None:
        """A dark supertile on the map has been seen lit."""
        if self.model.light(tile):
            self.rebuild()

    def auto_draw_player(self, x: float, y: float, tile: Tile) -> None:
        model = self.model
        if tile not in model.tiles:
            return
        previous = model.player.node if model.player else None
        node = model.move_player(tile, x, y)
        if node is None:
            return  # part not known yet; see GraphModel.locate
        if node not in self._rooms:
            self.redraw_canvas()  # newly shown part
        for changed in {previous, node}:
            if changed in self._rooms:
                self._rooms[changed].update()
                self._doors[changed].update()
        if previous != node and self.top.settings["follow_player"] and node in model.pos:
            # Follow player: recentre when the room is not fully visible
            cx, cy, zoom = self.view.camera()
            size = self.view.viewport().size()
            px, py = model.pos[node]
            if (
                abs(px - cx) > size.width() / 2 / zoom - THUMB / 2 - 20
                or abs(py - cy) > size.height() / 2 / zoom - THUMB / 2 - 20
            ):
                self.view.set_camera(px, py, zoom)

    def clear_player(self) -> None:
        model = self.model
        if model.player is not None:
            node = model.player.node
            model.clear_player()
            if node in self._rooms:
                self._rooms[node].update()
                self._doors[node].update()
