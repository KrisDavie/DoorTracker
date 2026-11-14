"""The items panel: the game's item menu with what the player holds lit, and each dungeon's keys. It floats over a
corner of the map, and its tab hides it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QToolButton, QVBoxLayout, QWidget

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


# Two columns of equipment, then the game's menu
GRID: list[list[Slot | None]] = [
    [
        Slot(("Fighter Sword", "Master Sword", "Tempered Sword", "Golden Sword")),
        Slot(("Blue Shield", "Red Shield", "Mirror Shield")),
        one("Bow"),
        Slot(("Blue Boomerang", "Red Boomerang"), together=True),
        one("Hookshot"),
        one("Bombs"),
        Slot(("Mushroom", "Magic Powder"), together=True),
    ],
    [
        Slot(("Blue Mail", "Red Mail"), start="Green Mail"),
        None,
        one("Fire Rod"),
        one("Ice Rod"),
        one("Bombos"),
        one("Ether"),
        one("Quake"),
    ],
    [
        Slot(("Power Glove", "Titans Mitts")),
        one("Pegasus Boots"),
        one("Lamp"),
        one("Hammer"),
        Slot(("Shovel", "Ocarina"), together=True),
        one("Bug Catching Net"),
        one("Book of Mudora"),
    ],
    [
        one("Flippers"),
        one("Moon Pearl"),
        one(BOTTLE),
        one("Cane of Somaria"),
        one("Cane of Byrna"),
        one("Cape"),
        one("Magic Mirror"),
    ],
]
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


class ItemsPanel(QWidget):
    def __init__(self, parent: QWidget, toggled: Callable[[bool], None]):
        """toggled(open): the tab was clicked, to open the panel or to close it."""
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.toggled = toggled
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
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6a6a72"))
        self.body.setPalette(palette)
        # Without this it takes the map view's role, which is not Window
        self.body.setBackgroundRole(QPalette.ColorRole.Window)
        self.body.setAutoFillBackground(True)
        column.addWidget(self.body)
        inside = QVBoxLayout(self.body)
        inside.setContentsMargins(4, 4, 4, 4)
        inside.setSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(2)
        inside.addLayout(grid)
        self.slots: list[tuple[Slot, QLabel]] = []
        for row, slots in enumerate(GRID):
            for place, slot in enumerate(slots):
                if slot is not None:
                    label = QLabel()
                    label.setFixedSize(CELL, CELL)
                    grid.addWidget(label, row, place)
                    self.slots.append((slot, label))

        strip = QGridLayout()
        strip.setSpacing(0)
        inside.addLayout(strip)
        small = QFont(self.font())
        small.setPixelSize(10)
        self.counts: dict[str, QLabel] = {}  # small keys, by dungeon
        self.big_keys: dict[str, QLabel] = {}
        self.big_key = picture(BIG_KEY_PICTURE).scaled(CELL // 2, CELL // 2, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        self.no_big_key = greyed(self.big_key)
        for place, (dungeon, short) in enumerate(SHORT_NAMES.items()):
            name, count, key = QLabel(short), QLabel("0"), QLabel()
            name.setFont(small)
            for row, label in enumerate((name, count, key)):
                label.setFixedWidth(KEY_CELL)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setToolTip(dungeon.replace("_", " "))
                strip.addWidget(label, row, place)
            self.counts[dungeon], self.big_keys[dungeon] = count, key
        self.hide()

    def _tab_clicked(self) -> None:
        self.toggled(self.body.isHidden())

    def set_open(self, is_open: bool) -> None:
        """Show everything, or only the tab."""
        self.body.setVisible(is_open)
        self.tab.setArrowType(Qt.ArrowType.DownArrow if is_open else Qt.ArrowType.UpArrow)
        self.adjustSize()

    def show_held(self, items: frozenset[str] | None, small_keys: Mapping[str, int]) -> None:
        """Light what is held. With no items read, from no game, there is no panel."""
        if items is None:
            self.hide()
            return
        for slot, label in self.slots:
            mine = [item for item in slot.items if item in items]
            label.setPixmap(slot_picture(slot, items))
            label.setToolTip(", ".join(mine if slot.together else mine[-1:]) or slot.start or slot.items[0])
        for dungeon, count in self.counts.items():
            count.setText(str(small_keys.get(dungeon, 0)))
            # Not enabled: drawn in the grey set for that in the palette
            count.setEnabled(small_keys.get(dungeon, 0) > 0)
            self.big_keys[dungeon].setPixmap(self.big_key if BIG_KEYS[dungeon] in items else self.no_big_key)
        self.show()
