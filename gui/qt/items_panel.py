"""The items panel: the game's item menu with what the player holds lit, and each dungeon's keys. It floats over a
corner of the map, and its tab hides it."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLayout, QToolButton, QVBoxLayout, QWidget

from gui.Doors.logic import BIG_KEYS, BOTTLE
from gui.Doors.randomizer import FOLDER

PICTURES = FOLDER / "data" / "itemgfx"  # the randomizer's own, 32 pixels high
CELL = 32
KEY_CELL = 18  # width of a dungeon's column of keys
# item -> its picture's name, where that is not the item's
PICTURE_NAMES = {
    "Blue Boomerang": "Boomerang",
    "Bombs": "Bomb",
    "Bug Catching Net": "Bug Net",
    "Cane of Somaria": "Somaria",
    "Cane of Byrna": "Byrna",
    "Cape": "Magic Cape",
    "Titans Mitts": "Titans Mitt",
    "Red Shield": "Fire Shield",
}
BIG_KEY_PICTURE = "Big Key"


@dataclass(frozen=True)
class Slot:
    """One place in the grid, and the items that can be in it."""

    items: tuple[str, ...]
    together: bool = False  # the items share it; otherwise each takes the place of the one before
    start: str | None = None  # picture of what the player has in it from the start


def one(item: str) -> Slot:
    return Slot((item,))


# The grid of items in the game's menu, and what the menu shows apart from it: abilities and equipment
MENU = [
    [one("Bow"), Slot(("Blue Boomerang", "Red Boomerang"), together=True), one("Hookshot"), one("Bombs"), Slot(("Mushroom", "Magic Powder"), together=True)],
    [one("Fire Rod"), one("Ice Rod"), one("Bombos"), one("Ether"), one("Quake")],
    [one("Lamp"), one("Hammer"), Slot(("Shovel", "Ocarina"), together=True), one("Bug Catching Net"), one("Book of Mudora")],
    [one(BOTTLE), one("Cane of Somaria"), one("Cane of Byrna"), one("Cape"), one("Magic Mirror")],
]
ABILITIES = [one("Pegasus Boots"), Slot(("Power Glove", "Titans Mitts")), one("Flippers"), one("Moon Pearl")]
EQUIPMENT = [
    Slot(("Fighter Sword", "Master Sword", "Tempered Sword", "Golden Sword")),
    Slot(("Blue Shield", "Red Shield", "Mirror Shield")),
    Slot(("Blue Mail", "Red Mail"), start="Green Mail"),
]
SLOTS = [slot for row in (*MENU, ABILITIES, EQUIPMENT) for slot in row]
# The tracker's name for a dungeon -> what the keys strip calls it, in the order of the tabs
SHORT_NAMES = {
    "Hyrule_Castle": "HC",
    "Eastern_Palace": "EP",
    "Desert_Palace": "DP",
    "Tower_of_Hera": "TH",
    "Castle_Tower": "AT",
    "Palace_of_Darkness": "PD",
    "Swamp_Palace": "SP",
    "Skull_Woods": "SW",
    "Thieves_Town": "TT",
    "Ice_Palace": "IP",
    "Misery_Mire": "MM",
    "Turtle_Rock": "TR",
    "Ganons_Tower": "GT",
}


def picture(name: str) -> QPixmap:
    return QPixmap(str(PICTURES / f"{name}.gif"))


def greyed(lit: QPixmap) -> QPixmap:
    """A picture as a placeholder: grey and faint."""
    faint = QPixmap(lit.size())
    faint.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faint)
    painter.setOpacity(0.4)
    painter.drawImage(0, 0, lit.toImage().convertToFormat(QImage.Format.Format_Grayscale8))
    # The grey copy has lost what was see-through: cut it back to the picture's shape
    painter.setOpacity(1.0)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawPixmap(0, 0, lit)
    painter.end()
    return faint


def slot_picture(slot: Slot, held: frozenset[str]) -> QPixmap:
    """What a slot shows: greyed out, its first item, when none of its items is held and it starts empty."""
    mine = [item for item in slot.items if item in held]
    cell = QPixmap(CELL, CELL)
    cell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cell)
    if slot.together and len(mine) == 2:
        # Both: each at half size, which is the size the game draws them, in opposite corners
        for item, corner in zip(mine, (0, CELL // 2)):
            whole = picture(PICTURE_NAMES.get(item, item))
            half = whole.scaled(whole.width() // 2, whole.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            painter.drawPixmap(corner + (CELL // 2 - half.width()) // 2, corner, half)
    else:
        item = mine[-1] if mine else slot.items[0]
        shown = picture(slot.start if slot.start and not mine else PICTURE_NAMES.get(item, item))
        painter.drawPixmap((CELL - shown.width()) // 2, 0, shown)
    painter.end()
    return cell if mine or slot.start else greyed(cell)


def states(slot: Slot) -> list[frozenset[str]]:
    """What can be held of a slot's items, in the order that clicking goes through."""
    if slot.together:
        first, second = slot.items
        return [frozenset(), frozenset({first}), frozenset({second}), frozenset({first, second})]
    # A better sword is held along with the lesser ones, as the game's own count has it
    return [frozenset(slot.items[:count]) for count in range(len(slot.items) + 1)]


def clicked(slot: Slot, held: frozenset[str], step: int) -> frozenset[str]:
    """What is held after a click on a slot (step 1) or a right click (step -1)."""
    choices = states(slot)
    mine = held & frozenset(slot.items)
    now = choices.index(mine) if mine in choices else 0
    return (held - mine) | choices[(now + step) % len(choices)]


class Cell(QLabel):
    """A picture or a number that a click or a right click adjusts."""

    def __init__(self, pressed: Callable[[object, int], None], what: object):
        """pressed(what, step): this was clicked (step 1) or right clicked (step -1)."""
        super().__init__()
        self.pressed = pressed
        self.what = what

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed(self.what, 1)
        elif event.button() == Qt.MouseButton.RightButton:
            self.pressed(self.what, -1)


def spread(columns: Sequence[QLayout]) -> QHBoxLayout:
    """A row with the columns spread evenly over its width."""
    row = QHBoxLayout()
    row.setSpacing(0)
    for place, column in enumerate(columns):
        if place:
            row.addStretch()
        row.addLayout(column)
    return row


class ItemsPanel(QWidget):
    def __init__(self, parent: QWidget, toggled: Callable[[bool], None], changed: Callable[[frozenset[str], dict[str, int]], None]):
        """toggled(open): the tab was clicked, to open the panel or to close it.
        changed(items, small keys): a click in the panel changed what is held to this.
        """
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.toggled = toggled
        self.changed = changed
        self.items: frozenset[str] = frozenset()  # as last shown
        self.small_keys: dict[str, int] = {}
        self.tab = QToolButton()
        self.tab.setFixedSize(36, 16)
        # A method, not a lambda: Qt would keep a lambda that holds this panel alive, and with it the window
        self.tab.clicked.connect(self._tab_clicked)
        column.addWidget(self.tab, alignment=Qt.AlignmentFlag.AlignRight)

        self.body = QWidget()
        # The pictures are drawn for the game's black menu
        palette = self.body.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#16161a"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
        self.body.setPalette(palette)
        self.faint = QPalette(palette)  # for a count of no keys
        self.faint.setColor(QPalette.ColorRole.WindowText, QColor("#6a6a72"))
        self.bright = palette
        # Without this it takes the map view's role, which is not Window
        self.body.setBackgroundRole(QPalette.ColorRole.Window)
        self.body.setAutoFillBackground(True)
        column.addWidget(self.body)
        inside = QVBoxLayout(self.body)
        inside.setContentsMargins(4, 4, 4, 4)
        inside.setSpacing(4)

        self.slots: list[tuple[Slot, QLabel]] = []

        def cell(slot: Slot) -> QLabel:
            label = Cell(self._pressed, slot)
            label.setFixedSize(CELL, CELL)
            self.slots.append((slot, label))
            return label

        grid = QGridLayout()
        grid.setSpacing(2)
        inside.addLayout(grid)
        for row, slots in enumerate(MENU):
            for place, slot in enumerate(slots):
                grid.addWidget(cell(slot), row, place)
        # To the right of the menu's grid, after a gap: a column of abilities and a column of equipment
        width = len(MENU[0])
        grid.setColumnMinimumWidth(width, 6)
        for place, slots in enumerate((ABILITIES, EQUIPMENT)):
            for row, slot in enumerate(slots):
                grid.addWidget(cell(slot), row, width + 1 + place)

        small = QFont(self.font())
        small.setPixelSize(10)
        self.counts: dict[str, QLabel] = {}  # small keys, by dungeon
        self.big_keys: dict[str, QLabel] = {}
        self.big_key = picture(BIG_KEY_PICTURE).scaled(CELL // 2, CELL // 2, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        self.no_big_key = greyed(self.big_key)
        columns = []
        for dungeon, short in SHORT_NAMES.items():
            name, count, key = QLabel(short), Cell(self._pressed, ("small keys", dungeon)), Cell(self._pressed, ("big key", dungeon))
            name.setFont(small)
            column = QVBoxLayout()
            column.setSpacing(0)
            for label in (name, count, key):
                label.setFixedWidth(KEY_CELL)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setToolTip(dungeon.replace("_", " "))
                column.addWidget(label)
            columns.append(column)
            self.counts[dungeon], self.big_keys[dungeon] = count, key
        inside.addLayout(spread(columns))
        self.show_held(None, {})

    def _tab_clicked(self) -> None:
        self.toggled(self.body.isHidden())

    def _pressed(self, what: object, step: int) -> None:
        """A slot, a dungeon's small keys or its big key was clicked (step 1) or right clicked (step -1)."""
        items, small_keys = self.items, dict(self.small_keys)
        if isinstance(what, Slot):
            items = clicked(what, items, step)
        elif isinstance(what, tuple):
            kind, dungeon = what
            if kind == "big key":
                items = items ^ {BIG_KEYS[dungeon]}
            else:
                small_keys[dungeon] = max(0, small_keys.get(dungeon, 0) + step)
        self.changed(items, small_keys)

    def mousePressEvent(self, event):
        # A click between the pictures is not a click on the map under the panel
        event.accept()

    mouseReleaseEvent = mouseDoubleClickEvent = mousePressEvent

    def set_open(self, is_open: bool) -> None:
        """Show everything, or only the tab."""
        self.body.setVisible(is_open)
        self.tab.setArrowType(Qt.ArrowType.DownArrow if is_open else Qt.ArrowType.UpArrow)
        self.adjustSize()

    def show_held(self, items: frozenset[str] | None, small_keys: Mapping[str, int]) -> None:
        """Light what is held. items is None when none have been read or clicked: nothing is lit."""
        self.items, self.small_keys = items or frozenset(), dict(small_keys)
        for slot, label in self.slots:
            mine = [item for item in slot.items if item in self.items]
            label.setPixmap(slot_picture(slot, self.items))
            label.setToolTip(", ".join(mine if slot.together else mine[-1:]) or slot.start or slot.items[0])
        for dungeon, count in self.counts.items():
            held = self.small_keys.get(dungeon, 0)
            count.setText(str(held))
            count.setPalette(self.bright if held else self.faint)
            self.big_keys[dungeon].setPixmap(self.big_key if BIG_KEYS[dungeon] in self.items else self.no_big_key)
