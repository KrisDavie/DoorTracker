"""Qt view of a dungeon map.

The scene is the world: rooms sit at the positions the model gives them, in world units. The view
is a camera onto it: panning and zooming only change the view's transform, so nothing is redrawn
or rescaled by hand and the graphics card does the work.
"""

import math

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

from data.doors_data import door_coordinates_key, mandatory_tiles
from data.room_bounds import room_bounds
from gui.Doors.graph_model import (
    BACKGROUND,
    COMPACT_H,
    COMPACT_W,
    DIRECTIONS,
    DOOR_RADIUS,
    DROP_COLOUR,
    DOOR_SELECTED,
    DUNGEON_BACKGROUNDS,
    DUNGEON_COLOURS,
    EDGE_FADED,
    INTERIOR_DOORS,
    ITEM_SHEET_PATH,
    LINK_GAP,
    PLAYER,
    THUMB,
    UNKNOWN_DUNGEON_COLOUR,
    WARP_COLOUR,
    GraphModel,
    convex_hull,
    door_direction,
    door_tile,
    lighten,
    link_colours,
    tile_dungeon,
    tile_regions,
    tile_title,
)

MIN_ZOOM, MAX_ZOOM = 0.1, 4.0
WORLD = 1_000_000  # the scene is effectively endless


class Assets:
    """Pictures shared by every tab: supertile thumbnails at a few sizes, and the icon sheet."""

    def __init__(self, eg_img):
        self.eg_img = eg_img  # PIL image of the whole EG map
        self._tiles = {}
        self._sheet = None
        self._icons = {}

    def tile(self, tile, wanted_px, blank_dead=False):
        """The supertile picture, at the smallest stored size that is at least wanted_px wide.

        With blank_dead, rooms that have no door are painted over with the picture's background.
        """
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
    """One supertile: picture, border, name and pin. Doors are drawn by DoorsItem, above the links."""

    def __init__(self, page, tile):
        super().__init__()
        self.page = page
        self.tile = tile
        self.kind = "card"
        self.payload = tile
        model = page.model
        self.box = model._box(tile)
        # One rectangle per real room, top-left one first
        self.pieces = [
            QRectF(left, top, right - left, bottom - top)
            for left, top, right, bottom in sorted(model._pieces(tile), key=lambda p: (p[1], p[0]))
        ]
        # Pieces may touch or overlap; the border goes round them all together, never through the picture
        self.outline = self._around(self.pieces, 0)
        self.player_outline = self._around(self.pieces, 3)
        self.w, self.h = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.blank_dead = bool(model.experimental_flags.get("hide_dead_rooms"))
        self.colour = QColor(DUNGEON_COLOURS.get(tile_dungeon(tile), UNKNOWN_DUNGEON_COLOUR))
        self.hidden = model._is_hidden_dark(tile)
        self.compact = tile in model.compact
        self.title = "Dark room" if self.hidden else tile_title(tile)
        self.pinned = tile in model.fixed
        self.keep_expanded = tile in model.pinned_eg_tiles
        # The name goes inside the room when another room is stacked on top of it
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
                self.tile[:2], THUMB * lod * painter.device().devicePixelRatioF(), blank_dead=self.blank_dead
            )
            # Each piece shows the part of the picture that falls inside it
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
            # Full-size rooms get their name from a LabelItem, which is never cut to the room's width

        if self.pinned:
            self._paint_pin(painter, first)

        if self.page.model.player is not None and self.page.model.player[0] == self.tile:
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
    """A room's name, written out in full at the top-left corner of its first piece.

    It sits on a layer above every room, so a name that is wider than its room runs over whatever is
    next to it and is never cut short or hidden behind a neighbour.
    """

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
    """What each block repels as, drawn under the rooms.

    The solid outline is the shape; the dashed one is half the reach further out, so two blocks are
    pushing each other exactly when their dashed outlines overlap.
    """

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
        for circle, boxes, reach in self.shapes:
            for left, top, right, bottom in boxes:
                bounds = bounds.united(QRectF(left, top, right - left, bottom - top))
            if circle:
                bounds = bounds.united(QRectF(circle[0] - circle[2], circle[1] - circle[2], circle[2] * 2, circle[2] * 2))
        reach = max((shape[2] for shape in self.shapes), default=0.0)
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
        for circle, boxes, reach in self.shapes:
            half = reach / 2
            if circle:
                x, y, radius = circle
                painter.setBrush(fill)
                painter.setPen(dashed)
                painter.drawEllipse(QPointF(x, y), radius + half, radius + half)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(solid)
                painter.drawEllipse(QPointF(x, y), radius, radius)
            else:
                # Wall to wall from every room: the rooms grown by half the reach, corners rounded
                grown = QPainterPath()
                grown.setFillRule(Qt.WindingFill)
                for left, top, right, bottom in boxes:
                    grown.addRoundedRect(QRectF(left - half, top - half, right - left + reach, bottom - top + reach), half, half)
                painter.setBrush(fill)
                painter.setPen(dashed)
                painter.drawPath(grown.simplified())


class DoorsItem(QGraphicsItem):
    """The doors of one room, and the player marker. Sits above the links so a door is never hidden."""

    def __init__(self, page, tile):
        super().__init__()
        self.page = page
        self.tile = tile
        self.kind = "card"
        self.payload = tile
        # Doors keep their place on the full supertile, whatever part of the room is drawn
        self.w, self.h = (page.model._size(tile) if tile in page.model.compact else (THUMB, THUMB))
        self.dots = page.model._door_dots(tile)
        self.setZValue(3)
        # Only the dots count as this item; clicks elsewhere fall through to the link or the room below
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        return QRectF(-self.w / 2 - 12, -self.h / 2 - 12, self.w + 24, self.h + 24)

    def shape(self):
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        page = self.page
        for door, ox, oy, radius, fill, outline in self.dots:
            if door == page.selected_door:
                fill, radius, outline = DOOR_SELECTED, DOOR_RADIUS + 1, 2
            if door == page.hot_door:
                fill, radius, outline = PLAYER, DOOR_RADIUS + 1, 2
            painter.setPen(QPen(QColor("#111"), outline))
            painter.setBrush(QColor(fill))
            painter.drawEllipse(QPointF(ox, oy), radius, radius)
        player = page.model.player
        if player is not None and player[0] == self.tile and self.tile not in page.model.compact:
            x = (player[1] / 512 - 0.5) * THUMB
            y = (player[2] / 512 - 0.5) * THUMB
            painter.setPen(QPen(QColor(PLAYER), 3, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(x - 7, y - 7), QPointF(x + 7, y + 7))
            painter.drawLine(QPointF(x + 7, y - 7), QPointF(x - 7, y + 7))


class SeamItem(QGraphicsRectItem):
    """A doorway shared by two stacked rooms: an opening across the wall instead of two dots and a line."""

    def __init__(self, parent, x, y, vertical, payload):
        long_side, short_side = 11.0, 5.0
        hw, hh = (long_side, short_side) if vertical else (short_side, long_side)
        super().__init__(QRectF(x - hw, y - hh, hw * 2, hh * 2), parent)
        self.kind = "edge"
        self.payload = payload
        self.setPen(QPen(QColor("#111"), 2))
        self.setBrush(QColor("#fffbe0"))


class IconItem(QGraphicsItem):
    """An annotation on a door, or a lobby drawn as an entrance hanging off its door."""

    def __init__(self, parent, page, door, x, y, icon, lobby=None, direction=(0, 1)):
        super().__init__(parent)
        self.page = page
        self.kind = "icon"
        self.payload = door
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
                # Written straight on the map, so it has to stand out against that dungeon's background
                painter.setPen(self.page.text_colour)
                below = self.direction[1] >= 0
                text_rect = QRectF(self.spot.x() - 60, self.spot.y() + (12 if below else -26), 120, 14)
                painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.lobby.replace("_", " "))


class LinkItem(QGraphicsPathItem):
    """A link between two doors in different blocks (or an interior connection inside one room)."""

    def __init__(self, page, a, b, n, kind, colour):
        super().__init__()
        self.page = page
        self.kind = "edge"
        self.payload = (a, b, n)
        self.interior = kind == "interior"
        self.link_kind = kind
        self.dashed = kind.startswith("warp")
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
        a, b, n = self.payload
        ax, ay = model._port(a)
        bx, by = model._port(b)
        dist = math.hypot(bx - ax, by - ay)
        reach = min(60.0, dist / 2.2)
        if door_tile(a) == door_tile(b):
            reach = max(reach, 30.0)
        da = DIRECTIONS.get(door_direction(a)) if not model._is_hidden_dark(door_tile(a)) else None
        db = DIRECTIONS.get(door_direction(b)) if not model._is_hidden_dark(door_tile(b)) else None
        path = QPainterPath(QPointF(ax, ay))
        c1 = QPointF(ax + da[0] * reach, ay + da[1] * reach) if da else None
        c2 = QPointF(bx + db[0] * reach, by + db[1] * reach) if db else None
        end = QPointF(bx, by)
        if c1 is not None and c2 is not None:
            path.cubicTo(c1, c2, end)
        elif c1 is not None or c2 is not None:
            path.quadTo(c1 if c1 is not None else c2, end)
        else:
            path.lineTo(end)
        self.setPath(path)

        if self.link_kind in ("warp", "hole", "drop"):
            one_way = True
        elif self.link_kind.endswith("_both"):
            one_way = False
        else:
            one_way = not self.interior and (
                model._decoupled() or (door_direction(a) not in DIRECTIONS and "Stairs" not in a and "Ladder" not in a)
            )
        if one_way:
            # A tracked drop can be stored either way round. You fall from the pit (facing down) to the
            # drop entrance (facing up), so that is the way the arrow points whichever came first.
            backwards = (
                not model._decoupled() and door_direction(a) == "Up" and door_direction(b) == "Dn"
            )
            tip_x, tip_y = (ax, ay) if backwards else (bx, by)
            # Arrow head at the landing end, pointing along the last bit of the curve
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
                self.arrow.kind = "edge"
                self.arrow.payload = self.payload
            self.arrow.setPolygon(head)

    def shape(self):
        # Easier to hit than a three unit wide line
        stroker = QPainterPathStroker()
        stroker.setWidth(9)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())


class GraphView(QGraphicsView):
    """The camera. Everything it does is a change of transform; the scene underneath never moves for it."""

    def __init__(self, page, use_gl=True):
        super().__init__(page.scene)
        self.page = page
        self.setSceneRect(-WORLD, -WORLD, WORLD * 2, WORLD * 2)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        # Each dungeon's map sits on that dungeon's own background, the colour between the rooms in its pictures
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
        # Hovering needs mouse moves without a button held, on the view and on whichever viewport it ended up with
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
        # centerOn lands on a whole pixel; take up the remainder so the camera is exactly where asked
        centre = self.mapToScene(self.viewport().rect().center())
        self.translate(centre.x() - x, centre.y() - y)

    def zoom_at(self, view_pos, factor):
        """Zoom keeping the world point under the mouse where it is on screen."""
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

    # ---- input goes to the page, which knows what the map means

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
        self.page.set_hover(None, None)
        super().leaveEvent(event)


class GraphPage(QWidget):
    """One dungeon tab: toolbar, camera view, and the glue between mouse and model."""

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
        self.stack_box = QCheckBox("Stack fitting rooms")
        self.stack_box.setChecked(True)
        self.stack_box.toggled.connect(self._on_stack)
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
        for widget in (fit, relayout, self.group_box, self.stack_box):
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

    def _on_stack(self, checked):
        self.model.auto_stack = checked
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
        """With Simulate on the running simulation picks it up; otherwise move to the new resting place at once."""
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
        """Throw the drawn map away and draw it again from the model. Done when the data changes, not per frame."""
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
            for tile in model.nodes():
                by_dungeon.setdefault(tile_dungeon(tile), []).append(tile)
            for dungeon, members in by_dungeon.items():
                colour = DUNGEON_COLOURS.get(dungeon, UNKNOWN_DUNGEON_COLOUR)
                hull = QGraphicsPolygonItem()
                hull.setPen(QPen(QColor(lighten(colour, 0.35)), 2))
                hull.setBrush(QColor(lighten(colour, 0.82)))
                hull.setZValue(0)
                hull.members = members
                self.scene.addItem(hull)
                self._hulls.append(hull)

        lobbies = {x["door"]: x["lobby"] for x in model.lobby_doors}
        for tile in model.nodes():
            room = RoomItem(self, tile)
            doors = DoorsItem(self, tile)
            self.scene.addItem(room)
            self.scene.addItem(doors)
            self._rooms[tile] = room
            self._doors[tile] = doors
            if not room.compact:
                label = LabelItem(room)
                label.setVisible(self.labels_box.isChecked())
                self.scene.addItem(label)
                self._labels[tile] = label

        for door, icon in model.special_doors.items():
            tile = door_tile(door)
            if tile not in self._doors or door not in door_coordinates_key:
                continue
            x, y = model._port_offset(door)
            if door in lobbies:
                direction = DIRECTIONS.get(door_direction(door)) or (0, 1)
                if door in ("Sanctuary Mirror Route", "Sewer Drop") or "Drop" in door:
                    direction = (0, -1)
                if model._is_hidden_dark(tile):
                    direction = (0, 1)
                lobby = lobbies[door]
                picture = "Drop" if "Drop" in lobby or "Drop" in door else lobby
                IconItem(self._doors[tile], self, door, x, y, picture, lobby=lobby, direction=direction)
            else:
                IconItem(self._doors[tile], self, door, x, y, icon)

        for n in sorted(model.joined):
            a, b = model.door_links[n]["door"], model.door_links[n]["linked_door"]
            tile = door_tile(a)
            ax, ay = model._port(a)
            bx, by = model._port(b)
            cx, cy = model.pos[tile]
            vertical = DIRECTIONS[door_direction(a)][0] == 0
            SeamItem(self._doors[tile], (ax + bx) / 2 - cx, (ay + by) / 2 - cy, vertical, (a, b, n))

        colours = link_colours(len(model.door_links))
        for a, b, kind, n in model._edges():
            if n in model.joined:
                continue
            if kind.startswith("warp"):
                colour = WARP_COLOUR
            elif kind in ("drop", "hole", "hole_both"):
                colour = DROP_COLOUR
            else:
                colour = colours[n] if n is not None else "#222"
            link = LinkItem(self, a, b, n, kind, colour)
            self.scene.addItem(link)
            self._links.append(link)

        self.update_positions(links=False)
        if self._needs_fit and model.pos and self.view.viewport().width() > 50 and self.isVisible():
            self.fit_view()

    def update_positions(self, links=True):
        """Move what is drawn to where the model now has it. This is all a simulation frame or a drag costs."""
        model = self.model
        for tile, room in self._rooms.items():
            if tile in model.pos:
                x, y = model.pos[tile]
                room.setPos(x, y)
                self._doors[tile].setPos(x, y)
                if tile in self._labels:
                    self._labels[tile].setPos(x, y)
        if links:
            for link in self._links:
                link.update_path()
        if self._reach is not None and self._reach.isVisible():
            self._reach.refresh()
        for hull in self._hulls:
            points = []
            for tile in hull.members:
                x, y = model.pos[tile]
                left, top, right, bottom = model._box(tile)
                for px in (left - 16, right + 16):
                    for py in (top - 16, bottom + 16):
                        points.append((x + px, y + py))
            hull.setPolygon(QPolygonF([QPointF(px, py) for px, py in convex_hull(points)]))
        if self._rubber is not None and self.selected_door:
            line = self._rubber.line()
            start = model._port(self.selected_door)
            self._rubber.setLine(start[0], start[1], line.x2(), line.y2())

    def fit_view(self):
        self._needs_fit = False
        self.view.fit(self.model._bounds())

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_fit and self.model.pos:
            # A tab that has never been shown does not have its real size yet. Fit now, and again as the
            # size arrives, until the user takes over the camera.
            self._settling_size = True
            self.fit_view()
            QTimer.singleShot(400, self._stop_settling)

    def _stop_settling(self):
        self._settling_size = False

    def view_resized(self):
        if self._settling_size and self.model.pos:
            self.fit_view()

    def relayout(self):
        # Searching for an arrangement takes a second or two on a big map
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
        """The door dot under the mouse, by geometry: doors are painted by their room, not items of their own."""
        model = self.model
        reach = max(1.0, 6 / self.view.zoom())
        best = None
        for tile, doors in self._doors.items():
            if tile not in model.pos:
                continue
            x, y = model.pos[tile]
            if abs(scene_pos.x() - x) > doors.w / 2 + 10 or abs(scene_pos.y() - y) > doors.h / 2 + 10:
                continue
            for door, ox, oy, radius, fill, outline in doors.dots:
                distance = math.hypot(scene_pos.x() - x - ox, scene_pos.y() - y - oy)
                if distance <= max(radius, reach) + 1 and (best is None or distance < best[0]):
                    best = (distance, door)
        return best[1] if best else None

    def room_at(self, scene_pos):
        for tile, (x, y) in self.model.pos.items():
            if any(
                left <= scene_pos.x() - x <= right and top <= scene_pos.y() - y <= bottom
                for left, top, right, bottom in self.model._pieces(tile)
            ):
                return tile
        return None

    def hit(self, event):
        """What is under the mouse, as (kind, payload). Doors win over whatever is drawn across them."""
        view_pos = event.position().toPoint()
        scene_pos = self.view.mapToScene(view_pos)
        item = self.view.itemAt(view_pos)
        while item is not None and not hasattr(item, "kind"):
            item = item.parentItem()
        kind, payload = (item.kind, item.payload) if item is not None else (None, None)
        if kind != "icon":
            door = self.door_at(scene_pos)
            if door is not None:
                return "door", door
        return kind, payload

    # ------------------------------------------------------------------- mouse

    def on_press(self, event):
        self.view.setFocus()
        kind, payload = self.hit(event)
        scene_pos = self.view.mapToScene(event.position().toPoint())
        if event.button() == Qt.RightButton:
            self._context(event, kind, payload, scene_pos)
            return
        if event.button() == Qt.MiddleButton:
            self._middle(kind, payload)
            return
        if event.button() != Qt.LeftButton:
            return
        if event.modifiers() & Qt.ControlModifier:
            tile = self._room_of(kind, payload, scene_pos)
            if tile is not None:
                self.set_pinned(tile, tile not in self.model.fixed)
            return

        press = {"kind": kind, "payload": payload, "pos": event.position(), "moved": False, "tile": None}
        inside = kind == "edge" and (
            payload[2] in self.model.joined or door_tile(payload[0]) == door_tile(payload[1])
        )
        if kind in ("card", "icon", "door") or inside:
            press["tile"] = self._room_of(kind, payload, scene_pos)
        elif kind == "edge" and self.room_at(scene_pos) is not None:
            # A link passing over a room does not get in the way of dragging that room
            press["tile"] = self.room_at(scene_pos)
        self._press = press

    def _room_of(self, kind, payload, scene_pos):
        if kind == "card":
            return payload
        if kind in ("door", "icon"):
            return door_tile(payload)
        if kind == "edge":
            return self.room_at(scene_pos) or (
                door_tile(payload[0])
                if door_tile(payload[0]) == door_tile(payload[1]) or payload[2] in self.model.joined
                else None
            )
        return None

    def on_move(self, event):
        press = self._press
        if press is None or not (event.buttons() & Qt.LeftButton):
            kind, payload = self.hit(event)
            self.set_hover(kind, payload)
            if self.selected_door:
                self._draw_rubber(self.view.mapToScene(event.position().toPoint()))
            return
        delta = event.position() - press["pos"]
        if not press["moved"] and abs(delta.x()) + abs(delta.y()) < 4:
            return
        press["moved"] = True
        press["pos"] = event.position()
        if press["tile"] is None or press["tile"] not in self.model.pos:
            self._settling_size = False
            self.view.pan(delta.x(), delta.y())
            return
        # A stack moves as one piece; with Simulate on everything else reacts while it is held
        zoom = self.view.zoom()
        self.model._held = set(self.model._stack_of(press["tile"]))
        self.model.move_stack(press["tile"], delta.x() / zoom, delta.y() / zoom)
        self.update_positions()

    def on_release(self, event):
        press, self._press = self._press, None
        self.model._held = set()
        if press is None or event.button() != Qt.LeftButton:
            return
        if press["moved"]:
            # A dropped block stays exactly where it was put. It is not pinned.
            if press["tile"] is not None:
                self.model.unsettled.difference_update(self.model._stack_of(press["tile"]))
            return
        if press["kind"] == "door":
            self._door_clicked(press["payload"])
        elif press["kind"] is None and self.selected_door:
            self.cancel_selection()

    def on_double_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._press = None
        kind, payload = self.hit(event)
        scene_pos = self.view.mapToScene(event.position().toPoint())
        if kind == "door":
            if self.model.has_target(payload) or payload in INTERIOR_DOORS:
                return
            self.cancel_selection()
            x, y = self.model._port(payload)
            direction = DIRECTIONS.get(door_direction(payload)) or (1, 0)
            reach = THUMB / 2 + LINK_GAP
            self.add_tile_from_picker(x + direction[0] * reach, y + direction[1] * reach)
        elif kind is None:
            self.add_tile_from_picker(scene_pos.x(), scene_pos.y())

    def _door_clicked(self, door):
        model = self.model
        if door in INTERIOR_DOORS or door in model._lobby_door_names():
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
        if model.has_target(door) and not model._decoupled():
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
        start = self.model._port(self.selected_door)
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

    def set_hover(self, kind, payload):
        model = self.model
        hot = payload if kind == "door" else None
        if hot != self.hot_door:
            self.hot_door = hot
            self._repaint_doors()
        if kind == "door":
            target = model._link_map().get(payload)
            text = payload + (f"  →  {target}" if target else "")
            if payload in model.special_doors:
                text += f"   [{model.special_doors[payload]}]"
            focus = door_tile(payload)
        elif kind == "edge":
            text = f"{payload[0]}  ↔  {payload[1]}"
            if payload[2] in model.joined:
                text += "   (stacked — middle click to split)"
            elif payload[2] is not None and model._join_offset(payload[0], payload[1]) is not None:
                text += "   (middle click to stack)"
            elif payload[2] is None and door_tile(payload[0]) != door_tile(payload[1]):
                if payload[1].endswith(" landing"):
                    text = f"{payload[0]}  →  {tile_title(door_tile(payload[1]))}"
                text += "   (warp)" if "Warp" in payload[0] else "   (vanilla drop, assumed)"
            focus = self._focus
        elif kind == "card":
            text = f"{', '.join(tile_regions(payload)[:4]) or tile_title(payload)}   (EG {payload[0]},{payload[1]})"
            focus = payload
        elif kind == "icon":
            text = f"{payload}: {model.special_doors.get(payload, '')}"
            focus = door_tile(payload)
        else:
            text, focus = "", None
        if self.selected_door:
            text = f"Linking {self.selected_door} — click another door (Esc to cancel)   {text}"
        if text != self.status.text():
            self.status.setText(text)
        if self._press is None and focus != self._focus:
            self._focus = focus
            # Fade every link that does not touch the room under the mouse
            for link in self._links:
                if link.interior:
                    continue
                a, b, n = link.payload
                touches = focus is None or door_tile(a) == focus or door_tile(b) == focus
                link.set_state(faded=not touches, strong=touches and focus is not None)

    # ------------------------------------------------------------ other buttons

    def _middle(self, kind, payload):
        model = self.model
        if kind == "edge":
            a, b, n = payload
            if n is None:
                return
            message = model.toggle_stack(a, b, n)
            if message:
                self.status.setText(message)
            else:
                self.rebuild()
        elif kind == "card":
            if payload in model.pinned_eg_tiles:
                model.pinned_eg_tiles.discard(payload)
            else:
                model.pinned_eg_tiles.add(payload)
            self.redraw_canvas()

    def _context(self, event, kind, payload, scene_pos):
        model = self.model
        if kind == "door":
            icon = self.top.pick_icon(self.tab_world)
            if icon:
                import data.doors_sprite_data as sprites

                model.annotate(payload, icon, sprites.all_dungeon_lobbies)
                self.rebuild()
        elif kind == "edge":
            if payload[2] is not None:
                model.remove_link(payload[2])
                self.rebuild()
        elif kind == "icon":
            model.remove_annotation(payload)
            self.rebuild()
        elif kind == "card":
            tile = payload
            menu = QMenu(self)
            if tile in model.fixed:
                menu.addAction("Unpin", lambda: self.set_pinned(tile, False))
            else:
                menu.addAction("Pin in place", lambda: self.set_pinned(tile, True))
            if tile[:2] not in mandatory_tiles[self.tab_world]:
                menu.addSeparator()
                menu.addAction("Remove supertile…", lambda: self.remove_tile(tile))
            menu.exec(event.globalPosition().toPoint())
        else:
            menu = QMenu(self)
            menu.addAction("Fit to window", self.fit_view)
            menu.addAction("Re-layout", self.relayout)
            menu.addAction("Unpin all", self.unpin_all)
            menu.addAction("Add supertile here…", lambda: self.add_tile_from_picker(scene_pos.x(), scene_pos.y()))
            menu.exec(event.globalPosition().toPoint())

    def set_pinned(self, tile, pinned):
        self.model.set_pinned(tile, pinned)
        for member in self.model._stack_of(tile):
            if member in self._rooms:
                self._rooms[member].pinned = pinned
                self._rooms[member].update()

    def unpin_all(self):
        self.model.fixed.clear()
        for room in self._rooms.values():
            room.pinned = False
            room.update()

    def remove_tile(self, tile):
        # Takes the room's links, lobbies and annotations with it, so never without asking
        answer = QMessageBox.question(
            self,
            "Remove supertile",
            f"Remove {tile_title(tile[:2])} and every link, lobby and annotation on it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self.model.remove_tile(tile):
            self.rebuild()

    def add_tile_from_picker(self, x, y):
        tile = self.top.pick_eg_tile(self)
        if tile is None or tile in self.model.tiles:
            return
        # Picked by hand, so the player knows what it is: never obscure it
        self.model.add_tile(tile, has_been_lit=True, at=(x, y))
        self.rebuild()

    # ------------------------------------------------- what the tracker calls

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
            # Come back to the same view the map was saved with
            self.view.set_camera(float(camera[0]), float(camera[1]), float(camera[2]))

    def return_connections(self):
        data = self.model.save()
        x, y, zoom = self.view.camera()
        data["camera"] = [round(x, 1), round(y, 1), round(zoom, 4)]
        return data

    def auto_add_tile(self, tile, was_lit=False):
        if self.model.add_tile(tile, has_been_lit=was_lit):
            self.rebuild()

    def auto_add_door_link(self, door, linked_door):
        added = self.model.auto_add_door_link(door, linked_door)
        self._arrived(linked_door, added)

    def auto_add_lobby(self, door):
        added = self.model.auto_add_lobby(door)
        self._arrived(door, added)

    def _arrived(self, door, changed):
        """The player came in by this door: that, not where they stand, says which block they are in."""
        if door is not None:
            self.model.arrive(door)
        if changed:
            self.rebuild()
        elif self.model.located is not None and self.model.located not in self._rooms:
            self.redraw_canvas()
        else:
            self.scene.update()

    def auto_draw_player(self, x, y, current_tile):
        model = self.model
        if current_tile not in model.tiles:
            return
        previous = model.player[0] if model.player else None
        # A partitioned supertile is several blocks: the marker goes on the one the player is in
        current_tile = model.locate(current_tile, x, y)
        if current_tile is None:
            return  # just walked in: the door that says which part comes next
        model.player = (current_tile, x, y)
        if current_tile not in self._rooms:
            self.redraw_canvas()  # a part of the supertile that was not on the map until now
        for tile in {previous, current_tile}:
            if tile in self._rooms:
                self._rooms[tile].update()
                self._doors[tile].update()
        if previous != current_tile and self.follow_box.isChecked() and current_tile in model.pos:
            # Centre the camera on the player's room when it is not fully on screen
            cx, cy, zoom = self.view.camera()
            size = self.view.viewport().size()
            px, py = model.pos[current_tile]
            if (
                abs(px - cx) > size.width() / 2 / zoom - THUMB / 2 - 20
                or abs(py - cy) > size.height() / 2 / zoom - THUMB / 2 - 20
            ):
                self.view.set_camera(px, py, zoom)

    def clear_player(self):
        model = self.model
        if model.player is not None:
            tile = model.player[0]
            model.player = None
            if tile in self._rooms:
                self._rooms[tile].update()
                self._doors[tile].update()
