"""Qt view of a dungeon map. Scene coordinates are the model's world units; the view transform is the camera."""

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
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
    QCheckBox,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from data.doors_data import mandatory_tiles
from data.doors_sprite_data import ITEM_SHEET_PATH
from data.room_bounds import room_bounds
from gui.Doors.graph_model import THUMB, Edge, GraphModel
from gui.Doors.layout import LINK_GAP, convex_hull
from gui.Doors.rooms import (
    DIRECTIONS,
    DOORS,
    DUNGEON_BACKGROUNDS,
    INTERIOR_DOORS,
    WHOLE,
    EdgeKind,
    Node,
    door_direction,
    supertile,
)
from gui.qt.style import (
    BACKGROUND,
    DOOR_RADIUS,
    DOOR_SELECTED,
    DOOR_STYLES,
    DROP_COLOUR,
    DUNGEON_COLOURS,
    EDGE_FADED,
    PLAYER,
    UNKNOWN_DUNGEON_COLOUR,
    WARP_COLOUR,
    lighten,
    link_colours,
)

MIN_ZOOM, MAX_ZOOM = 0.1, 4.0
WORLD = 1_000_000  # scene half-extent


@dataclass(frozen=True)
class Hit:
    """What is under the mouse. One field is set, or none over the background."""

    node: Node = None  # a room card
    door: str = None  # a door dot
    icon: str = None  # an icon, by the door it is on
    edge: Edge = None  # a line between doors, or the seam of a joined link


@dataclass
class Press:
    """A left button press, until the button is released."""

    hit: Hit
    pos: QPointF  # last mouse position, in view pixels
    node: Node = None  # what dragging moves; None pans the view
    moved: bool = False


class Assets:
    """Pixmaps shared by all tabs: supertile pictures at several sizes, and the icon sheet."""

    def __init__(self, eg_img):
        self.eg_img = eg_img  # PIL image of the whole EG map
        self._tiles = {}
        self._sheet = None
        self._icons = {}

    def tile(self, tile, wanted_px, blank_dead=False):
        """Supertile pixmap at the smallest stored size >= wanted_px. blank_dead paints over dead rooms."""
        bounds = room_bounds.get(tile, {})
        blank_dead = blank_dead and bool(bounds.get("dead"))
        key = (tile, blank_dead)
        if key not in self._tiles:
            x, y = tile
            if self.eg_img is None:
                image = QImage(256, 256, QImage.Format_RGB888)
                image.fill(QColor("#444"))
            else:
                crop = self.eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).convert("RGB")
                if blank_dead:
                    from PIL import ImageDraw

                    draw = ImageDraw.Draw(crop)
                    for left, top, right, bottom in bounds["dead"]:
                        draw.rectangle((left - 2, top - 2, right + 1, bottom + 1), fill=tuple(bounds["background"]))
                image = QImage(crop.tobytes(), 512, 512, 512 * 3, QImage.Format_RGB888).copy()
            levels = {}
            for size in (512, 256, 128, 64):
                scaled = (
                    image
                    if image.width() == size
                    else image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                )
                levels[size] = QPixmap.fromImage(scaled)
            self._tiles[key] = levels
        levels = self._tiles[key]
        for size in (64, 128, 256, 512):
            if size >= wanted_px:
                return levels[size]
        return levels[512]

    def icon(self, name):
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

    def __init__(self, page, node):
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
        self.blank_dead = bool(model.experimental_flags.get("hide_dead_rooms"))
        self.colour = QColor(DUNGEON_COLOURS.get(supertile(node.tile).dungeon, UNKNOWN_DUNGEON_COLOUR))
        self.hidden = model.is_hidden_dark(node.tile)
        self.compact = node in model.compact
        self.title = "Dark room" if self.hidden else model.rooms.title(node)
        self.pinned = node in model.fixed
        self.keep_expanded = node in model.kept_expanded
        self.setZValue(1)

    @staticmethod
    def _around(pieces, grow):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
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
            painter.drawText(first, Qt.AlignCenter, "?")
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

        painter.setBrush(Qt.NoBrush)
        if self.keep_expanded:
            painter.setPen(QPen(QColor("#18c418"), 6))
            painter.drawPath(self.outline)
        painter.setPen(QPen(self.colour, 2))
        painter.drawPath(self.outline)

        if lod * 11 >= 5 and self.page.labels_box.isChecked():
            font = QFont()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            if self.compact:
                painter.setPen(QColor("#111"))
                text = metrics.elidedText(self.title, Qt.ElideRight, first.width() - 6)
                painter.drawText(first, Qt.AlignCenter, text)
            # Full-size rooms are labelled by LabelItem

        if self.pinned:
            self._paint_pin(painter, first)

        if self.page.model.player is not None and self.page.model.player.node == self.node:
            painter.setPen(QPen(QColor(PLAYER), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.player_outline)

    @staticmethod
    def _paint_pin(painter, rect):
        """A pushpin in the top right corner."""
        size = 20.0
        box = QRectF(rect.right() - size - 3, rect.top() + 3, size, size)
        painter.setPen(QPen(QColor("#222"), 1))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(box)
        painter.setPen(QPen(QColor("#222"), 1.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(
            QPointF(box.left() + size * 0.46, box.top() + size * 0.54),
            QPointF(box.left() + size * 0.2, box.top() + size * 0.8),
        )
        painter.setPen(QPen(QColor("#7a1512"), 1))
        painter.setBrush(QColor("#e53935"))
        painter.drawEllipse(QRectF(box.left() + size * 0.36, box.top() + size * 0.16, size * 0.48, size * 0.48))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff8a80"))
        painter.drawEllipse(QRectF(box.left() + size * 0.52, box.top() + size * 0.24, size * 0.14, size * 0.14))


class LabelItem(QGraphicsItem):
    """Room name at the top-left of its first piece, on a layer above all rooms so it is never clipped."""

    def __init__(self, room):
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
        self.setAcceptedMouseButtons(Qt.NoButton)

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
        painter.drawText(self.tag.adjusted(3, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text)


class ReachItem(QGraphicsItem):
    """Debug overlay of repulsion shapes. Dashed outline = shape grown by half the reach; overlap means repulsion."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.shapes = []
        self.bounds = QRectF()
        self.setZValue(0.5)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def refresh(self):
        self.prepareGeometryChange()
        self.shapes = self.page.model.repulsion_shapes()
        bounds = QRectF()
        for shape in self.shapes:
            for left, top, right, bottom in shape.boxes:
                bounds = bounds.united(QRectF(left, top, right - left, bottom - top))
            if shape.circle:
                x, y, radius = shape.circle
                bounds = bounds.united(QRectF(x - radius, y - radius, radius * 2, radius * 2))
        reach = max((shape.reach for shape in self.shapes), default=0.0)
        self.bounds = bounds.adjusted(-reach, -reach, reach, reach)
        self.update()

    def boundingRect(self):
        return self.bounds

    def shape(self):
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        solid = QPen(QColor(255, 255, 255, 200), 0)
        dashed = QPen(QColor(255, 255, 255, 200), 0, Qt.DashLine)
        fill = QColor(255, 255, 255, 28)
        for shape in self.shapes:
            reach, half = shape.reach, shape.reach / 2
            if shape.circle:
                x, y, radius = shape.circle
                painter.setBrush(fill)
                painter.setPen(dashed)
                painter.drawEllipse(QPointF(x, y), radius + half, radius + half)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(solid)
                painter.drawEllipse(QPointF(x, y), radius, radius)
            else:
                # Rooms grown by half the reach
                grown = QPainterPath()
                grown.setFillRule(Qt.WindingFill)
                for left, top, right, bottom in shape.boxes:
                    grown.addRoundedRect(QRectF(left - half, top - half, right - left + reach, bottom - top + reach), half, half)
                painter.setBrush(fill)
                painter.setPen(dashed)
                painter.drawPath(grown.simplified())


class DoorsItem(QGraphicsItem):
    """Door dots and player marker of one node, above the links."""

    def __init__(self, page, node):
        super().__init__()
        self.page = page
        self.node = node
        # Door positions are relative to the full supertile, not the drawn pieces
        self.w, self.h = (page.model.size(node) if node in page.model.compact else (THUMB, THUMB))
        self.dots = page.model.door_dots(node)
        self.setZValue(3)
        # Hit shape is the dots only
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        return QRectF(-self.w / 2 - 12, -self.h / 2 - 12, self.w + 24, self.h + 24)

    def shape(self):
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        page = self.page
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
            painter.setPen(QPen(QColor(PLAYER), 3, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(x - 7, y - 7), QPointF(x + 7, y + 7))
            painter.drawLine(QPointF(x + 7, y - 7), QPointF(x - 7, y + 7))


class SeamItem(QGraphicsRectItem):
    """Bar across the doorway of two joined rooms."""

    def __init__(self, parent, x, y, vertical, edge):
        long_side, short_side = 11.0, 5.0
        hw, hh = (long_side, short_side) if vertical else (short_side, long_side)
        super().__init__(QRectF(x - hw, y - hh, hw * 2, hh * 2), parent)
        self.hit = Hit(edge=edge)
        self.setPen(QPen(QColor("#111"), 2))
        self.setBrush(QColor("#fffbe0"))


class IconItem(QGraphicsItem):
    """Icon on a door: an annotation or a lobby entrance."""

    def __init__(self, parent, page, door, x, y, icon, lobby=None, direction=(0, 1)):
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
        if self.lobby:
            painter.setPen(QPen(QColor("#111"), 2.5, Qt.DashLine))
            painter.drawLine(self.origin, self.spot)
        box = QRectF(self.spot.x() - 9, self.spot.y() - 9, 18, 18)
        painter.setPen(QPen(QColor("#111") if self.lobby else QColor("white"), 2 if self.lobby else 1))
        painter.setBrush(QColor("white"))
        painter.drawRect(box.adjusted(-1, -1, 1, 1) if self.lobby else box)
        if self.icon is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            painter.drawPixmap(QRectF(self.spot.x() - 8, self.spot.y() - 8, 16, 16), self.icon, QRectF(0, 0, 16, 16))
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
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
                painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.lobby.replace("_", " "))


class LinkItem(QGraphicsPathItem):
    """A link, interior connection, drop or warp between two doors."""

    def __init__(self, page, edge, colour):
        super().__init__()
        self.page = page
        self.edge = edge
        self.hit = Hit(edge=edge)
        self.interior = edge.kind is EdgeKind.INTERIOR
        self.dashed = edge.kind is EdgeKind.WARP
        self.colour = QColor("#222") if self.interior else QColor(colour)
        self.arrow = None
        self.setZValue(2)
        self.set_state(faded=False, strong=False)
        self.update_path()

    def set_state(self, faded, strong):
        if self.interior:
            pen = QPen(self.colour, 1.5, Qt.DashLine)
        else:
            pen = QPen(
                QColor(EDGE_FADED) if faded else self.colour,
                4 if strong else 3,
                Qt.DashLine if self.dashed else Qt.SolidLine,
                Qt.RoundCap,
            )
        self.setPen(pen)
        if self.arrow is not None:
            self.arrow.setBrush(pen.color())
        self.setZValue(2.5 if strong else 2)

    def update_path(self):
        model = self.page.model
        edge = self.edge
        a, b = edge.a, edge.b
        ax, ay = model.port(a)
        bx, by = model.port(b)
        dist = math.hypot(bx - ax, by - ay)
        reach = min(60.0, dist / 2.2)
        node_a, node_b = model.rooms.node(a), model.rooms.node(b)
        if node_a == node_b:
            reach = max(reach, 30.0)
        da = DIRECTIONS.get(door_direction(a)) if not model.is_hidden_dark(node_a.tile) else None
        db = DIRECTIONS.get(door_direction(b)) if not model.is_hidden_dark(node_b.tile) else None
        path = QPainterPath(QPointF(ax, ay))
        c1 = QPointF(ax + da[0] * reach, ay + da[1] * reach) if da else None
        c2 = QPointF(bx + db[0] * reach, by + db[1] * reach) if db else None
        end = QPointF(bx, by)
        same_block = model.blocks.root.get(node_a) == model.blocks.root.get(node_b)
        if same_block and da and db and not self.interior and dist > 1:
            # Same block: the plain curve would be a straight line, so bow it sideways
            px, py = -(by - ay) / dist, (bx - ax) / dist
            if py < 0 or (py == 0 and px < 0):
                px, py = -px, -py
            bow = dist * 0.3
            path.cubicTo(c1 + QPointF(px * bow, py * bow), c2 + QPointF(px * bow, py * bow), end)
        elif c1 is not None and c2 is not None:
            path.cubicTo(c1, c2, end)
        elif c1 is not None or c2 is not None:
            path.quadTo(c1 if c1 is not None else c2, end)
        else:
            path.lineTo(end)
        self.setPath(path)

        if edge.kind in (EdgeKind.WARP, EdgeKind.HOLE, EdgeKind.DROP):
            one_way = not edge.both_ways
        else:
            one_way = not self.interior and (
                model.decoupled() or (door_direction(a) not in DIRECTIONS and "Stairs" not in a and "Ladder" not in a)
            )
        if one_way:
            # Tracked drops can be stored either way round; the arrow always points pit -> landing
            backwards = (
                not model.decoupled() and door_direction(a) == "Up" and door_direction(b) == "Dn"
            )
            tip_x, tip_y = (ax, ay) if backwards else (bx, by)
            tail = path.pointAtPercent(0.08 if backwards else 0.92) if dist > 1 else QPointF(bx, by)
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
                self.arrow.setPen(Qt.NoPen)
                self.arrow.setBrush(self.pen().color())
            self.arrow.setPolygon(head)

    def shape(self):
        # Wider hit area than the drawn line
        stroker = QPainterPathStroker()
        stroker.setWidth(9)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())


class GraphView(QGraphicsView):
    """Camera: pan and zoom by view transform only."""

    def __init__(self, page, use_gl=True):
        super().__init__(page.scene)
        self.page = page
        self.setSceneRect(-WORLD, -WORLD, WORLD * 2, WORLD * 2)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor(DUNGEON_BACKGROUNDS.get(page.dungeon_name, BACKGROUND)))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setDragMode(QGraphicsView.NoDrag)
        self.gl = False
        if use_gl:
            try:
                from PySide6.QtOpenGLWidgets import QOpenGLWidget

                viewport = QOpenGLWidget()
                fmt = QSurfaceFormat()
                fmt.setSamples(4)
                viewport.setFormat(fmt)
                self.setViewport(viewport)
                self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
                self.viewport().setMouseTracking(True)
                self.gl = True
            except Exception:
                self.gl = False
        if not self.gl:
            self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
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

    def zoom_at(self, view_pos, factor):
        """Zoom about a viewport point."""
        factor = max(MIN_ZOOM / self.zoom(), min(MAX_ZOOM / self.zoom(), factor))
        before = self.mapToScene(view_pos)
        self.scale(factor, factor)
        after = self.mapToScene(view_pos)
        self.translate(after.x() - before.x(), after.y() - before.y())

    def pan(self, dx, dy):
        self.translate(dx / self.zoom(), dy / self.zoom())

    def fit(self, bounds):
        x0, y0, x1, y1 = bounds
        pad = 70
        size = self.viewport().size()
        zoom = min(size.width() / (x1 - x0 + pad * 2), size.height() / (y1 - y0 + pad * 2))
        self.set_camera((x0 + x1) / 2, (y0 + y1) / 2, min(1.0, zoom))

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
        if event.key() == Qt.Key_Escape:
            self.page.cancel_selection()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):
        self.page.set_hover(Hit())
        super().leaveEvent(event)


class GraphPage(QWidget):
    """One dungeon tab: toolbar, view and input handling."""

    def __init__(self, top, tab_world, assets, use_gl=True):
        super().__init__()
        self.top = top
        self.tab_world = tab_world
        self.assets = assets
        self.model = GraphModel(tab_world, top.experimental_flags)
        self.dungeon_name = self.model.dungeon_name

        background = QColor(DUNGEON_BACKGROUNDS.get(self.dungeon_name, BACKGROUND))
        self.text_colour = QColor("#111") if background.lightness() > 150 else QColor("white")
        self.selected_door = None
        self.hot_door = None
        self._focus = None
        self._press = None
        self._rooms = {}
        self._doors = {}
        self._labels = {}
        self._links = []
        self._hulls = []
        self._reach = None
        self._rubber = None
        self._needs_fit = True
        self._settling_size = False

        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        self.view = GraphView(self, use_gl=use_gl)

        self._build_toolbar()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.view, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._tick)
        self.rebuild()

    # ------------------------------------------------------------------ toolbar

    def _build_toolbar(self):
        self.toolbar = QWidget()
        row = QHBoxLayout(self.toolbar)
        row.setContentsMargins(6, 3, 6, 3)
        fit = QPushButton("Fit")
        fit.clicked.connect(self.fit_view)
        relayout = QPushButton("Re-layout")
        relayout.clicked.connect(self.relayout)
        self.group_box = QCheckBox("Group by original dungeon")
        self.group_box.toggled.connect(self._on_group)
        self.join_box = QCheckBox("Join fitting rooms")
        self.join_box.setChecked(True)
        self.join_box.toggled.connect(self._on_join)
        self.spacing_slider = QSlider(Qt.Horizontal)
        self.spacing_slider.setRange(10, 200)
        self.spacing_slider.setValue(int(self.model.spacing))
        self.spacing_slider.setFixedWidth(120)
        self.spacing_slider.valueChanged.connect(self._on_spacing)
        self.pull_slider = QSlider(Qt.Horizontal)
        self.pull_slider.setRange(10, 40)
        self.pull_slider.setValue(int(self.model.leaf_pull * 10))
        self.pull_slider.setFixedWidth(80)
        self.pull_slider.valueChanged.connect(self._on_pull)
        self.simulate_box = QCheckBox("Simulate")
        self.simulate_box.toggled.connect(self._on_simulate)
        self.circle_box = QCheckBox("Circle repulsion")
        self.circle_box.setToolTip("Experiment: each block repels as one circle around all its rooms")
        self.circle_box.toggled.connect(self._on_circle)
        self.reach_box = QCheckBox("Show repulsion")
        self.reach_box.setToolTip("Draw what each block repels as. Blocks push each other when their dashed outlines overlap")
        self.reach_box.toggled.connect(self._on_reach)
        self.follow_box = QCheckBox("Follow player")
        self.labels_box = QCheckBox("Labels")
        self.labels_box.setChecked(True)
        self.labels_box.toggled.connect(self._on_labels)
        self.status = QLabel("")
        self.status.setMinimumWidth(50)
        for widget in (fit, relayout, self.group_box, self.join_box):
            row.addWidget(widget)
        row.addWidget(QLabel("Spacing"))
        row.addWidget(self.spacing_slider)
        row.addWidget(QLabel("Satellite pull"))
        row.addWidget(self.pull_slider)
        row.addWidget(self.circle_box)
        row.addWidget(self.reach_box)
        row.addWidget(self.simulate_box)
        row.addWidget(self.follow_box)
        row.addWidget(self.labels_box)
        row.addWidget(self.status, 1)

    def _on_labels(self, checked):
        for label in self._labels.values():
            label.setVisible(checked)
        self.scene.update()

    def _on_group(self, checked):
        self.model.group_by_dungeon = checked
        self.relayout()

    def _on_join(self, checked):
        self.model.auto_join = checked
        self.relayout()

    def _on_spacing(self, value):
        self.model.spacing = float(value)
        self._forces_changed()

    def _on_reach(self, checked):
        if self._reach is not None:
            self._reach.setVisible(checked)
            if checked:
                self._reach.refresh()

    def _on_circle(self, checked):
        self.model.circle_repulsion = checked
        self._forces_changed()

    def _on_pull(self, value):
        self.model.leaf_pull = value / 10
        self._forces_changed()

    def _forces_changed(self):
        """Settle now unless the simulation is running."""
        if not self.simulate_box.isChecked():
            self.model.settle(150)
            self.update_positions()

    def _on_simulate(self, checked):
        if checked:
            self.timer.start()
        else:
            self.timer.stop()

    def _tick(self):
        if not self.isVisible():
            return
        self.model.settle(3)
        self.update_positions()

    # -------------------------------------------------------------------- scene

    def rebuild(self):
        """Recreate all scene items from the model. For data changes, not per frame."""
        model = self.model
        self.scene.clear()
        self._reach = ReachItem(self)
        self._reach.setVisible(self.reach_box.isChecked())
        self.scene.addItem(self._reach)
        self._rooms, self._doors, self._links, self._hulls = {}, {}, [], []
        self._labels = {}
        self._rubber = None
        self._focus = None
        self.hot_door = None

        if model.group_by_dungeon:
            by_dungeon = {}
            for node in model.nodes():
                by_dungeon.setdefault(supertile(node.tile).dungeon, []).append(node)
            for dungeon, members in by_dungeon.items():
                colour = DUNGEON_COLOURS.get(dungeon, UNKNOWN_DUNGEON_COLOUR)
                hull = QGraphicsPolygonItem()
                hull.setPen(QPen(QColor(lighten(colour, 0.35)), 2))
                hull.setBrush(QColor(lighten(colour, 0.82)))
                hull.setZValue(0)
                hull.members = members
                self.scene.addItem(hull)
                self._hulls.append(hull)

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
                label.setVisible(self.labels_box.isChecked())
                self.scene.addItem(label)
                self._labels[node] = label

        for door, icon in model.special_doors.items():
            node = self.model.rooms.node(door)
            if node not in self._doors or door not in DOORS:
                continue
            x, y = model.port_offset(door)
            if door in lobbies:
                direction = DIRECTIONS.get(door_direction(door)) or (0, 1)
                if door in ("Sanctuary Mirror Route", "Sewer Drop") or "Drop" in door:
                    direction = (0, -1)
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
                vertical = DIRECTIONS[door_direction(edge.a)][0] == 0
                SeamItem(self._doors[node], (ax + bx) / 2 - cx, (ay + by) / 2 - cy, vertical, edge)
                continue
            if edge.kind is EdgeKind.WARP:
                colour = WARP_COLOUR
            elif edge.kind in (EdgeKind.DROP, EdgeKind.HOLE):
                colour = DROP_COLOUR
            else:
                colour = colours.get(edge.link, "#222")
            link = LinkItem(self, edge, colour)
            self.scene.addItem(link)
            self._links.append(link)

        self.update_positions(links=False)
        if self._needs_fit and model.pos and self.view.viewport().width() > 50 and self.isVisible():
            self.fit_view()

    def update_positions(self, links=True):
        """Move existing items to the model's positions. The per-frame path."""
        model = self.model
        for node, room in self._rooms.items():
            if node in model.pos:
                x, y = model.pos[node]
                room.setPos(x, y)
                self._doors[node].setPos(x, y)
                if node in self._labels:
                    self._labels[node].setPos(x, y)
        if links:
            for link in self._links:
                link.update_path()
        if self._reach is not None and self._reach.isVisible():
            self._reach.refresh()
        for hull in self._hulls:
            points = []
            for node in hull.members:
                x, y = model.pos[node]
                left, top, right, bottom = model.box(node)
                for px in (left - 16, right + 16):
                    for py in (top - 16, bottom + 16):
                        points.append((x + px, y + py))
            hull.setPolygon(QPolygonF([QPointF(px, py) for px, py in convex_hull(points)]))
        if self._rubber is not None and self.selected_door:
            line = self._rubber.line()
            start = model.port(self.selected_door)
            self._rubber.setLine(start[0], start[1], line.x2(), line.y2())

    def fit_view(self):
        self._needs_fit = False
        self.view.fit(self.model.bounds())

    def showEvent(self, event):
        super().showEvent(event)
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
        QApplication.setOverrideCursor(Qt.WaitCursor)
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

    def door_at(self, scene_pos):
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

    def node_at(self, scene_pos):
        for node, (x, y) in self.model.pos.items():
            if any(
                left <= scene_pos.x() - x <= right and top <= scene_pos.y() - y <= bottom
                for left, top, right, bottom in self.model.pieces(node)
            ):
                return node
        return None

    def hit_at(self, event):
        """What is under the mouse. A door dot wins over anything but an icon."""
        view_pos = event.position().toPoint()
        item = self.view.itemAt(view_pos)
        while item is not None and not hasattr(item, "hit"):
            item = item.parentItem()
        hit = item.hit if item is not None else Hit()
        if hit.icon is None:
            door = self.door_at(self.view.mapToScene(view_pos))
            if door is not None:
                return Hit(door=door)
        return hit

    # ------------------------------------------------------------------- mouse

    def on_press(self, event):
        self.view.setFocus()
        hit = self.hit_at(event)
        scene_pos = self.view.mapToScene(event.position().toPoint())
        if event.button() == Qt.RightButton:
            self._context(event, hit, scene_pos)
            return
        if event.button() == Qt.MiddleButton:
            self._middle(hit)
            return
        if event.button() != Qt.LeftButton:
            return
        node = self._node_of(hit, scene_pos)
        if event.modifiers() & Qt.ControlModifier:
            if node is not None:
                self.set_pinned(node, node not in self.model.fixed)
            return
        self._press = Press(hit, event.position(), node)

    def _node_of(self, hit, scene_pos):
        """The node a press on this would pin or drag; None for the background or a link in open space."""
        if hit.node is not None:
            return hit.node
        if hit.door is not None or hit.icon is not None:
            return self.model.rooms.node(hit.door or hit.icon)
        if hit.edge is not None:
            # A link over a room acts on that room
            return self.node_at(scene_pos) or (self.model.rooms.node(hit.edge.a) if self._within_block(hit.edge) else None)
        return None

    def _within_block(self, edge):
        """True for an edge that does not leave its block: a joined link, or both ends on one node."""
        return edge.link in self.model.blocks.joined or self.model.rooms.node(edge.a) == self.model.rooms.node(edge.b)

    def on_move(self, event):
        press = self._press
        if press is None or not (event.buttons() & Qt.LeftButton):
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

    def on_release(self, event):
        press, self._press = self._press, None
        self.model.drop()
        if press is None or event.button() != Qt.LeftButton or press.moved:
            return
        if press.hit.door is not None:
            self._door_clicked(press.hit.door)
        elif press.hit == Hit() and self.selected_door:
            self.cancel_selection()

    def on_double_click(self, event):
        if event.button() != Qt.LeftButton:
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
            direction = DIRECTIONS.get(door_direction(door)) or (1, 0)
            reach = THUMB / 2 + LINK_GAP
            self.add_tile_from_picker(x + direction[0] * reach, y + direction[1] * reach)
        elif hit == Hit():
            self.add_tile_from_picker(scene_pos.x(), scene_pos.y())

    def _door_clicked(self, door):
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

    def _draw_rubber(self, scene_pos):
        start = self.model.port(self.selected_door)
        if self._rubber is None:
            self._rubber = QGraphicsLineItem()
            self._rubber.setPen(QPen(QColor(DOOR_SELECTED), 2, Qt.DashLine))
            self._rubber.setZValue(4)
            self._rubber.setAcceptedMouseButtons(Qt.NoButton)
            self.scene.addItem(self._rubber)
        self._rubber.setLine(start[0], start[1], scene_pos.x(), scene_pos.y())

    def _repaint_doors(self):
        for item in self._doors.values():
            item.update()

    # ------------------------------------------------------------------- hover

    def set_hover(self, hit):
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
            if model.is_hidden_dark(node.tile):
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

    def _middle(self, hit):
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

    def _context(self, event, hit, scene_pos):
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

    def set_pinned(self, node, pinned):
        self.model.set_pinned(node, pinned)
        for member in self.model.blocks.of(node):
            if member in self._rooms:
                self._rooms[member].pinned = pinned
                self._rooms[member].update()

    def unpin_all(self):
        self.model.unpin_all()
        for room in self._rooms.values():
            room.pinned = False
            room.update()

    def remove_tile(self, tile):
        # Also removes its links, lobbies and icons: confirm first
        answer = QMessageBox.question(
            self,
            "Remove supertile",
            f"Remove {WHOLE.title(Node(*tile))} and every link, lobby and annotation on it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self.model.remove_tile(tile):
            if self.selected_door in DOORS and DOORS[self.selected_door].tile == tile:
                self.cancel_selection()
            self.rebuild()

    def add_tile_from_picker(self, x, y):
        tile = self.top.pick_eg_tile(self)
        if tile is None or tile in self.model.tiles:
            return
        # Added by hand: show it lit
        self.model.add_tile(tile, has_been_lit=True, at=(x, y))
        self.rebuild()

    # ------------------------------------------------- called by the tracker

    @property
    def tiles(self):
        return self.model.tiles

    @property
    def show_all_doors(self):
        return self.model.show_all_doors

    @show_all_doors.setter
    def show_all_doors(self, value):
        self.model.show_all_doors = value

    def init_page(self):
        self.model.reset()
        self.selected_door = None
        self._needs_fit = True
        self.rebuild()

    def load_yaml(self, data):
        had_positions = self.model.load(data)
        self.selected_door = None
        self.spacing_slider.blockSignals(True)
        self.pull_slider.blockSignals(True)
        self.spacing_slider.setValue(int(self.model.spacing))
        self.pull_slider.setValue(int(self.model.leaf_pull * 10))
        self.spacing_slider.blockSignals(False)
        self.pull_slider.blockSignals(False)
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

    def auto_add_tile(self, tile, was_lit=False, player=None):
        """Add a supertile the player entered. player=(x, y) within it."""
        if self.model.add_tile(tile, has_been_lit=was_lit, player=player):
            self.rebuild()

    def auto_add_door_link(self, door, linked_door):
        added = self.model.auto_add_door_link(door, linked_door)
        self._arrived(linked_door, added)

    def auto_add_lobby(self, door):
        added = self.model.auto_add_lobby(door)
        self._arrived(door, added)

    def _arrived(self, door, changed):
        """Tell the model which door the player entered by, then refresh."""
        if door is not None:
            self.model.arrive(door)
        if changed:
            self.rebuild()
        elif self.model.located is not None and self.model.located not in self._rooms:
            self.redraw_canvas()
        else:
            self.scene.update()

    def auto_light_tile(self, tile):
        """A dark supertile on the map has been seen lit."""
        if self.model.light(tile):
            self.rebuild()

    def auto_draw_player(self, x, y, tile):
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
        if previous != node and self.follow_box.isChecked() and node in model.pos:
            # Follow player: recentre when the room is not fully visible
            cx, cy, zoom = self.view.camera()
            size = self.view.viewport().size()
            px, py = model.pos[node]
            if (
                abs(px - cx) > size.width() / 2 / zoom - THUMB / 2 - 20
                or abs(py - cy) > size.height() / 2 / zoom - THUMB / 2 - 20
            ):
                self.view.set_camera(px, py, zoom)

    def clear_player(self):
        model = self.model
        if model.player is not None:
            node = model.player.node
            model.clear_player()
            if node in self._rooms:
                self._rooms[node].update()
                self._doors[node].update()
