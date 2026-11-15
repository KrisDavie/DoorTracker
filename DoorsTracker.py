"""Janker Door Tracker: auto-tracks ALttP door randomizer dungeon layouts through SNI. Qt entry point."""

import argparse
import asyncio
import math
import signal
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from PySide6.QtCore import QByteArray, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import data.doors_sprite_data as sprites
from data.doors_data import dungeon_lobbies, eg_tile_multiuse
from data.vanilla_data import vanilla_layout_optimized
from data.worlds_data import World, dungeon_worlds
from gui import files
from gui.Doors import rooms
from gui.Doors.checks import checks
from gui.Doors.layout import REPEL_RANGE
from gui.Doors.logic import items_held, small_keys
from gui.qt.graph_page import Assets, GraphPage

WINDOW_SIZES = {"small": (1064, 632), "medium": (1588, 888), "large": (2088, 1144)}
TITLE = "Janker Door Tracker"
# The map is autosaved this long after its last change, in ms
SAVE_DELAY = 1000
# and once more this long after that if Simulate is on, as the cards keep moving
DRIFT_SAVE_DELAY = 10_000
# Holds the name of the autosave written last
LATEST = "latest.txt"
# Answers to the questions asked about a map
NEW_MAP, KEEP_MAP, USE_SAVED, DISCONNECT, CANCEL = "Start a new map", "Keep this map", "Use the saved map", "Disconnect", "Cancel"
# What is kept between launches, and its value on a first launch. A saved setting not listed here is ignored
DEFAULT_SETTINGS: dict[str, Any] = {
    "autosave": True,
    "tab": None,  # dungeon of the selected tab
    "window": None,  # QWidget.saveGeometry(), as hex
    # View and Experimental menus
    "show_all_doors": False,
    "show_checks": True,
    "show_fps": False,
    "show_items": True,  # the items panel is open; its tab changes this
    "hide_single_route_tiles": False,
    "decoupled_doors": False,
    "vanilla_drops": True,
    "trim_rooms": True,
    "split_rooms": True,
    # Toolbar
    "auto_join": True,
    "spacing": float(REPEL_RANGE),
    "dead_end_pull": 2.5,
    "circle_repulsion": False,
    "show_repulsion": False,
    "simulate": False,
    "follow_player": False,
    "labels": True,
}


def read_settings(file: Path) -> dict[str, Any]:
    """The settings a file holds. Raises if it cannot be read as settings, or a value is of the wrong kind."""
    saved = yaml.safe_load(file.read_text())
    if not isinstance(saved, dict):
        raise ValueError("not a list of settings")
    settings = {}
    for name, value in saved.items():
        if name not in DEFAULT_SETTINGS:
            continue
        default = DEFAULT_SETTINGS[name]
        if isinstance(default, bool):
            right_kind = isinstance(value, bool)
        elif isinstance(default, float):
            # yaml also reads .nan and .inf as numbers
            right_kind = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else:
            # A setting with no default is text, once it has a value
            right_kind = value is None or isinstance(value, str)
        if not right_kind:
            raise ValueError(f"{name}: {value!r}")
        settings[name] = value
    return settings


def read_autosave(file: Path) -> dict[str, Any]:
    """The map an autosave holds. Raises if the file is not a whole autosave."""
    text = file.read_text()
    if not text.endswith("...\n"):
        raise ValueError("the file is cut short")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("not a tracker file")
    return data


def autosave_name(seed_hash: str | None) -> str:
    """Each seed's map has its own file. A map not yet seen in a game has no seed."""
    return f"autosave-{seed_hash}.yaml" if seed_hash else "autosave.yaml"


class IconPicker(QDialog):
    """The annotation and lobby icons, laid out as they are on the icon sheet."""

    def __init__(self, parent, assets, world):
        super().__init__(parent)
        self.setWindowTitle("Annotate door")
        self.choice = None
        grid = QGridLayout(self)
        grid.setSpacing(2)
        for name, (row, column) in sprites.all_icons.items():
            button = QToolButton()
            button.setIcon(QIcon(assets.icon(name).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)))
            button.setIconSize(QSize(32, 32))
            button.setToolTip(name.replace("_", " "))
            usable = (name in sprites.item_table or name in sprites.dungeon_lobbies[world]) and name != "Sanctuary_Mirror"
            button.setEnabled(usable)
            # Signals go to methods, never lambdas: Qt keeps a lambda that holds a widget alive, and the widget with it
            button.setObjectName(name)
            button.clicked.connect(self._pick)
            grid.addWidget(button, row, column)

    def _pick(self):
        self.choice = self.sender().objectName()
        self.accept()


class EgPicker(QDialog):
    """Pick a supertile to add. Each dungeon's tab is its vanilla layout, with its other supertiles underneath."""

    def __init__(self, parent, assets, unavailable):
        super().__init__(parent)
        self.setWindowTitle("Add supertile")
        self.choice = None
        self.buttons = {}  # by supertile
        tabs = QTabWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        # Supertiles the vanilla layouts leave out, by dungeon
        laid_out = {tile for layout_data in vanilla_layout_optimized.values() for tile in layout_data["tiles"]}
        left_out = {}
        for tile in sorted(rooms.SUPERTILES):
            if tile not in laid_out:
                left_out.setdefault(rooms.SUPERTILES[tile].dungeon, []).append(tile)

        for name, layout_data in vanilla_layout_optimized.items():
            tiles = layout_data["tiles"]
            if not tiles:
                continue
            page = QWidget()
            grid = QGridLayout(page)
            grid.setSpacing(3)
            columns = [t["map_tile"][0] for t in tiles.values()]
            rows = [t["map_tile"][1] for t in tiles.values()]
            for tile, placement in tiles.items():
                button = self._button(tile, assets, unavailable)
                grid.addWidget(button, placement["map_tile"][1] - min(rows), placement["map_tile"][0] - min(columns))
            # A gap, then the rest in rows as wide as the layout
            width = max(columns) - min(columns) + 1
            below = max(rows) - min(rows) + 1
            grid.setRowMinimumHeight(below, 12)
            for index, tile in enumerate(left_out.get(name, [])):
                grid.addWidget(self._button(tile, assets, unavailable), below + 1 + index // width, index % width)

            tabs.addTab(page, "Other Lobby Tiles" if name == "Lobbyable_Tiles" else name.replace("_", " "))
            if name == parent.current_dungeon():
                tabs.setCurrentWidget(page)

    def _button(self, tile, assets, unavailable):
        button = QToolButton()
        button.setIcon(QIcon(assets.thumbnail(tile, 96)))
        button.setIconSize(QSize(96, 96))
        button.setToolTip(rooms.WHOLE.title(rooms.Node(*tile)))
        # Disabled if already on the map or used up
        button.setEnabled(tile not in unavailable)
        button.clicked.connect(self._pick)
        self.buttons[tile] = button
        return button

    def _pick(self):
        self.choice = next(tile for tile, button in self.buttons.items() if button is self.sender())
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, args: argparse.Namespace, settings_file: Path | None = None):
        """settings_file: where the options are kept between launches. None to not keep them."""
        super().__init__()
        self.args = args
        self.settings_file = settings_file
        # Shared with every page's model
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        if settings_file is not None and settings_file.exists():
            try:
                self.settings.update(read_settings(settings_file))
            except Exception as error:
                traceback.print_exc()
                QMessageBox.warning(
                    self,
                    "Settings not loaded",
                    f"{settings_file}\n\n{error!r}\n\nThe default settings are used. The file is replaced the next "
                    "time a setting changes, or when the tracker closes.",
                )
        self.autosave: Path | None = None  # folder; see start_autosave
        self._latest: str | None = None  # autosave file the next launch loads, as LATEST says
        self.autosave_on: bool = self.settings["autosave"]  # File -> Autosave, for this run
        self.seed_hash: str | None = None  # of the game the map was made on, once known; kept in the tracker file
        self.collected: set[str] = set()  # checks collected, by name in gui/Doors/checks.py; kept in the tracker file
        self._held: tuple[frozenset[str], dict[str, int]] | None = None  # the items and small keys last read or clicked
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_after_change)
        self._drift_timer = QTimer(self)
        self._drift_timer.setSingleShot(True)
        self._drift_timer.timeout.connect(self._write_autosave)
        self.setWindowTitle(TITLE)
        geometry = None if args.size else self.settings["window"]
        # restoreGeometry returns False for bytes that are not a geometry
        if not (geometry and self.restoreGeometry(QByteArray.fromHex(geometry.encode()))):
            self.resize(*WINDOW_SIZES[args.size or "medium"])
        self.device: str | None = None
        self.connected = False  # the auto-tracker is reading from a device
        self._adopt_seed = False  # see new_map
        self.sni_task: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

        eg_map = Path(__file__).parent / "data" / "maps" / "egmap.png"
        self.assets = Assets(Image.open(eg_map))

        self.tabs = QTabWidget()
        # The toolbar is above the tabs: what it sets is the same in every tab
        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_toolbar())
        column.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.pages: dict[str, GraphPage] = {}  # by dungeon, in tab order
        for dungeon, world in dungeon_worlds.items():
            if dungeon in ("Overworld", "Underworld"):
                continue
            page = GraphPage(self, world, self.assets, use_gl=not args.no_gl)
            self.pages[dungeon] = page
            self.tabs.addTab(page, dungeon.replace("_", " "))
        if self.settings["tab"] in self.pages:
            self.select_dungeon(self.settings["tab"])
        self.tabs.currentChanged.connect(self._tab_changed)
        self._build_menus()

    # -------------------------------------------------------------------- menus

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addAction("New", self.new_map).setShortcut(QKeySequence.StandardKey.New)
        file_menu.addAction("Open Tracker Data", self._open).setShortcut(QKeySequence.StandardKey.Open)
        file_menu.addAction("Save Tracker Data", self.save_file).setShortcut(QKeySequence.StandardKey.Save)
        self.autosave_action = QAction("Autosave", self, checkable=True)
        self.autosave_action.setChecked(self.autosave_on)
        self.autosave_action.toggled.connect(self._set_autosave)
        file_menu.addAction(self.autosave_action)
        file_menu.addSeparator()
        file_menu.addAction("Stop Auto-tracking", self.stop_tracking)
        file_menu.addAction("Reconnect to SNI", self._reconnect)
        self.devices_menu = file_menu.addMenu("Devices")
        self.set_devices([])
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        view_menu = bar.addMenu("View")
        view_menu.addAction("Fit to window", self._fit)
        view_menu.addAction("Re-layout", self._relayout)
        experimental = bar.addMenu("Experimental")
        for menu, label, name in (
            (view_menu, "Show All Doors", "show_all_doors"),
            (view_menu, "Show Checks", "show_checks"),
            (view_menu, "Show FPS", "show_fps"),
            (experimental, "Hide Single Route Tiles", "hide_single_route_tiles"),
            (experimental, "Enable Decoupled Support", "decoupled_doors"),
            (experimental, "Drops Are Not Shuffled", "vanilla_drops"),
            (experimental, "Trim Rooms", "trim_rooms"),
            (experimental, "Split Partitioned Rooms", "split_rooms"),
        ):
            action = QAction(label, self, checkable=True)
            action.setChecked(self.settings[name])
            action.setObjectName(name)
            action.toggled.connect(self._option_toggled)
            menu.addAction(action)

    # What the menus and the toolbar call. Signals go to methods, never lambdas: Qt keeps a lambda that holds the
    # window alive, and the window with it after it has closed

    def _tab_changed(self) -> None:
        self.set_setting("tab", self.current_dungeon())

    def _open(self) -> None:
        self.load_file()

    def _reconnect(self) -> None:
        self.start_tracking()

    def _fit(self) -> None:
        self.current_page().fit_view()

    def _relayout(self) -> None:
        self.current_page().relayout()

    def _option_toggled(self, checked: bool) -> None:
        """A menu option or a toolbar box, named after its setting, was toggled."""
        self.set_option(self.sender().objectName(), checked)

    def _slider_moved(self, value: int) -> None:
        name = self.sender().objectName()
        self.set_option(name, value / self._slider_steps[name])

    def _device_picked(self) -> None:
        self.start_tracking(device=self.sender().objectName())

    def _force_tracking(self) -> None:
        self.start_tracking(forced=True, device=self.device)

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(6, 3, 6, 3)

        self.boxes: dict[str, QCheckBox] = {}  # by setting

        def add_box(name: str, label: str, tip: str = "") -> None:
            box = QCheckBox(label)
            box.setToolTip(tip)
            box.setChecked(self.settings[name])
            box.setObjectName(name)
            box.toggled.connect(self._option_toggled)
            row.addWidget(box)
            self.boxes[name] = box

        self.sliders: dict[str, QSlider] = {}  # by setting
        self._slider_steps: dict[str, int] = {}  # slider steps per unit of its setting

        def add_slider(name: str, label: str, low: int, high: int, width: int, steps_per_unit: int) -> None:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(low, high)
            # A saved value outside the range is brought into it
            slider.setValue(round(min(max(self.settings[name] * steps_per_unit, low), high)))
            self.settings[name] = slider.value() / steps_per_unit
            slider.setFixedWidth(width)
            slider.setObjectName(name)
            self._slider_steps[name] = steps_per_unit
            slider.valueChanged.connect(self._slider_moved)
            row.addWidget(QLabel(label))
            row.addWidget(slider)
            self.sliders[name] = slider

        add_box("auto_join", "Join fitting rooms")
        add_slider("spacing", "Spacing", 10, 200, 120, 1)
        add_slider("dead_end_pull", "Dead-end pull", 10, 40, 80, 10)
        add_box("circle_repulsion", "Circle repulsion", "Experiment: each block repels as one circle around all its rooms")
        add_box(
            "show_repulsion",
            "Show repulsion",
            "Draw what pushes blocks apart. Two blocks push when the same kind of outline overlaps.\n"
            "Solid: the push between rooms, which reaches as far as the Spacing slider says.\n"
            "With Circle repulsion the dashed circles carry the slider's reach, and the rooms only push at close range.\n"
            "Hatched: a pinned block, which pushes but is not moved.",
        )
        add_box("simulate", "Simulate")
        add_box("follow_player", "Follow player")
        add_box("labels", "Labels")
        self.status = QLabel("")  # what the mouse is over
        self.status.setMinimumWidth(50)
        row.addWidget(self.status, 1)
        # View -> Show FPS: frames the tab in view drew in the last second, and how long the last one took
        self.fps_label = QLabel("")
        self.fps_label.setMinimumWidth(self.fps_label.fontMetrics().horizontalAdvance("000 fps  00.0 ms") + 8)
        self.fps_label.setVisible(self.settings["show_fps"])
        row.addWidget(self.fps_label)
        return toolbar

    def set_setting(self, name: str, value: Any) -> None:
        """Change a setting and keep it for the next launch."""
        self.settings[name] = value
        if self.settings_file is not None:
            try:
                files.write_text(self.settings_file, yaml.dump(self.settings))
            except OSError as error:
                traceback.print_exc()
                # Said once: no more writes are tried this run
                file, self.settings_file = self.settings_file, None
                QMessageBox.warning(
                    self, "Settings not saved", f"{file}\n\n{error!r}\n\nSettings changed from now on are not kept."
                )

    def set_option(self, name: str, value: bool | float) -> None:
        """Change a setting the pages act on, in every tab."""
        self.set_setting(name, value)
        if name == "show_fps":
            self.fps_label.setVisible(bool(value))
        for page in self.pages.values():
            page.option_changed(name)

    def current_page(self) -> GraphPage:
        return list(self.pages.values())[self.tabs.currentIndex()]

    def current_dungeon(self) -> str:
        return self.current_page().dungeon_name

    # -------------------------------------------------------------------- files

    def load_file(self, file: str | None = None) -> None:
        if file is None:
            file, _ = QFileDialog.getOpenFileName(self, "Open Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        with open(file, mode="r") as fh:
            try:
                data: dict[str, Any] = yaml.safe_load(fh)
            except Exception:
                from SpoilerToYaml import parse_dr_spoiler

                data = parse_dr_spoiler(fh)
        if self._save_timer.isActive():
            # The map on screen is about to be replaced: its last changes go to its autosave first
            self._write_autosave()
        self.load_data(data)

    def load_data(self, data: dict[str, Any]) -> None:
        """Show the map a tracker file holds."""
        if "Agahnims_Tower" in data:
            data["Castle_Tower"] = data.pop("Agahnims_Tower")
        self.seed_hash = data.pop("seed_hash", None)
        self.collected = set(data.pop("collected", None) or [])
        self._adopt_seed = False
        # A spoiler lists lobbies apart from the dungeons: file each under the dungeon that owns it
        for lobby, door in (data.pop("lobbies", None) or {}).items():
            if not isinstance(door, str):
                continue  # the parser's entry also has its empty default fields
            if door not in rooms.DOORS:
                door = door.rsplit(" (", 1)[0]
            dungeon = next((d for d, world in dungeon_worlds.items() if lobby in dungeon_lobbies.get(world, ())), None)
            if dungeon is None or door not in rooms.DOORS:
                print(f"Spoiler lobby not recognised: {lobby}: {door}")
                continue
            data[dungeon].setdefault("lobby_doors", []).append({"door": door, "lobby": lobby})
            data[dungeon].setdefault("special_doors", {})[door] = lobby
        for dungeon, dungeon_data in data.items():
            if dungeon in self.pages:
                self.pages[dungeon].load_yaml(dungeon_data)

    def save_file(self) -> None:
        file, _ = QFileDialog.getSaveFileName(self, "Save Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        if not file.endswith((".yaml", ".yml")):
            file += ".yaml"
        try:
            files.write_text(Path(file), yaml.dump(self.tracker_data()))
        except OSError as error:
            traceback.print_exc()
            QMessageBox.warning(self, "Tracker data not saved", f"{file}\n\n{error!r}")

    def tracker_data(self) -> dict[str, Any]:
        """Everything a tracker file holds."""
        data: dict[str, Any] = {dungeon: page.return_connections() for dungeon, page in self.pages.items()}
        if self.seed_hash is not None:
            data["seed_hash"] = self.seed_hash
        data["collected"] = sorted(self.collected)
        return data

    # ----------------------------------------------------------------- autosave

    def start_autosave(self, folder: Path, restore: bool) -> None:
        """Keep the map in this folder from here on. restore: first load the map the last run left there.

        Nothing is saved before this is called, so a new window cannot save its empty map over a file.
        """
        latest = folder / LATEST
        if restore and self.autosave_on and latest.exists():
            try:
                self._latest = latest.read_text().strip()
            except (OSError, ValueError) as error:  # not readable, or not text
                self._stop_autosave(
                    "Autosave not loaded",
                    f"{latest}\n\n{error!r}\n\nThe saved maps have been left as they are, and File -> Autosave has "
                    "been turned off.",
                )
            else:
                self._load_autosave(folder / self._latest)
        self.autosave = folder
        if not restore:
            self.map_changed()

    def _load_autosave(self, file: Path) -> bool:
        """Show the map an autosave holds. False if it could not be read: the file is then left alone."""
        try:
            self.load_data(read_autosave(file))
        except Exception as error:
            # Saving now would overwrite the file that failed to load
            self._stop_autosave(
                "Autosave not loaded",
                f"{file}\n\n{error!r}\n\nThe file has been left as it is, and File -> Autosave has been turned off. "
                "Turning it on again will save over the file.",
            )
            return False
        return True

    def _stop_autosave(self, title: str, text: str) -> None:
        """Turn autosave off after a failure, and say why. For this run only: the setting is kept."""
        traceback.print_exc()
        self.autosave_on = False
        self._save_timer.stop()
        self._drift_timer.stop()
        self.autosave_action.blockSignals(True)
        self.autosave_action.setChecked(False)
        self.autosave_action.blockSignals(False)
        QMessageBox.warning(self, title, text)

    def _set_autosave(self, checked: bool) -> None:
        self.autosave_on = checked
        self.set_setting("autosave", checked)
        if checked:
            self.map_changed()
        else:
            self._save_timer.stop()
            self._drift_timer.stop()

    def map_changed(self) -> None:
        """A page's saved state changed. The map is saved once the changes stop."""
        if self.autosave is not None and self.autosave_on:
            self._save_timer.start(SAVE_DELAY)

    def _save_after_change(self) -> None:
        self._write_autosave()
        if self.settings["simulate"]:
            self._drift_timer.start(DRIFT_SAVE_DELAY)

    def _write_autosave(self) -> bool:
        """Save the map to its seed's file. False if it was not saved: autosave is off, or the write failed."""
        if self.autosave is None or not self.autosave_on:
            return False
        name = autosave_name(self.seed_hash)
        try:
            # The end marker shows the file is whole when it is read back
            files.write_text(self.autosave / name, yaml.dump(self.tracker_data(), explicit_end=True))
            if name != self._latest:
                files.write_text(self.autosave / LATEST, name)
                self._latest = name
        except OSError as error:
            self._stop_autosave(
                "Autosave failed",
                f"{self.autosave / name}\n\n{error!r}\n\nFile -> Autosave has been turned off. Turn it on again to retry.",
            )
            return False
        return True

    def seed_seen(self, seed_hash: str) -> bool:
        """The auto-tracker is in a game with this hash. Each seed has its own autosave: a new seed swaps maps.

        Returns False if the user chose to disconnect and leave the map as it is: tracking must stop.

        The map on screen is only given another seed's hash once it has been swapped for that seed's map, or
        the user has said what to do with it. Otherwise one seed's map could be saved over another's.
        """
        if seed_hash == self.seed_hash:
            return True
        saved = self.autosave / autosave_name(seed_hash) if self.autosave is not None and self.autosave_on else None
        if self.seed_hash is None:
            adopt, self._adopt_seed = self._adopt_seed, False
            # The map on screen has not been seen in a game. It is this seed's, unless this seed has a map already
            if saved is not None and saved.exists() and not adopt:
                answer = self._ask(
                    "Saved map found",
                    "This seed already has a saved map.\n\nKeeping the map on screen will save it over that one.\n"
                    "Disconnecting leaves both maps as they are.",
                    USE_SAVED,
                    KEEP_MAP,
                    DISCONNECT,
                )
                if answer == DISCONNECT:
                    return False
                if answer == USE_SAVED:
                    self._swap_to(saved)
        elif not self._swap_to(saved):
            answer = self._ask(
                "Different seed",
                "The game is a different seed from this map, and the map could not be put away in its autosave.\n\n"
                "Keeping it will add the new seed's rooms to it.\nDisconnecting leaves it as it is.",
                NEW_MAP,
                KEEP_MAP,
                DISCONNECT,
            )
            if answer == DISCONNECT:
                return False
            if answer == NEW_MAP:
                self._clear_map()
        self.seed_hash = seed_hash
        self.map_changed()
        return True

    def _swap_to(self, saved: Path | None) -> bool:
        """Put the map on screen away in its autosave and show the saved one, or an empty map if there is none.

        saved: the autosave to show, or None if autosave is off. False if the map on screen could not be put
        away: it is then left on screen.
        """
        if saved is None or not self._write_autosave():
            return False
        if not (saved.exists() and self._load_autosave(saved)):
            self._clear_map()
        return True

    def _ask(self, title: str, text: str, *answers: str, warning: bool = False) -> str:
        """Ask a question with named answers; returns the one picked. Closing the dialog picks the last.

        warning: the text is html, and the last answer is the default.
        """
        box = QMessageBox(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Question, title, text, parent=self)
        buttons = {box.addButton(answer, QMessageBox.ButtonRole.ActionRole): answer for answer in answers}
        last = list(buttons)[-1]
        box.setEscapeButton(last)
        if warning:
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setDefaultButton(last)
        box.exec()
        return buttons.get(box.clickedButton(), answers[-1])

    def _clear_map(self) -> None:
        self.collected = set()
        for page in self.pages.values():
            page.init_page()

    def checks_read(self, memory: Mapping[str, bytes]) -> None:
        """The game's tables of what has been collected and the items held, as the auto-tracker just read them."""

        def word(table: str, room: int) -> int:
            return int.from_bytes(memory[table][room * 2 : room * 2 + 2], "little")

        collected = {name for name, check in checks.items() if any(word(table, room) & mask for table, room, mask in check["flags"])}
        if collected != self.collected:
            # This also puts back any check clicked on the map that the game does not agree with
            self._set_collected(collected)
        held = items_held(memory["items"]), small_keys(memory["items"], memory["dungeon"][0])
        if held != self._held:
            # This also puts back anything clicked in the items panel that the game does not agree with
            self.set_held(*held)

    def set_collected(self, check: str, collected: bool) -> None:
        """A check was clicked on the map to collect it, or right clicked to take that back."""
        if (check in self.collected) != collected:
            self._set_collected(self.collected ^ {check})

    def _set_collected(self, collected: set[str]) -> None:
        self.collected = collected
        for page in self.pages.values():
            page.scene.update()
        self.map_changed()

    def set_held(self, items: frozenset[str], small_keys: dict[str, int]) -> None:
        """What the player holds: as read from the game, or as clicked in the items panel."""
        self._held = items, small_keys
        for page in self.pages.values():
            page.set_items(items, small_keys)

    def new_map(self) -> None:
        """File -> New: an empty map that belongs to no seed."""
        if self.connected:
            answer = self._ask(
                "Connected to a game",
                "<h1>YOU ARE CONNECTED TO A GAME</h1>"
                "<p style='font-size: 13pt'>The new map will be attached to that game's seed as soon as the tracker "
                "next reads it, and will <b>REPLACE THE MAP SAVED FOR THAT SEED</b>.</p>"
                "<p style='font-size: 13pt'>That map cannot be brought back.</p>",
                NEW_MAP,
                CANCEL,
                warning=True,
            )
            if answer != NEW_MAP:
                return
            # Chosen knowing that: the new map takes the game's seed without a second question
            self._adopt_seed = True
        elif not all(page.model.untouched() for page in self.pages.values()):
            # Not connected. A map with a seed stays in that seed's autosave; any other has nowhere to go
            kept = self.seed_hash is not None and self.autosave is not None and self.autosave_on
            if not kept:
                answer = self._ask(
                    "Start a new map?",
                    "<p>The map on screen will be discarded.</p><p>"
                    + (
                        "It belongs to no seed, so the new map takes its place in the autosave."
                        if self.seed_hash is None
                        else "Autosave is off, so it is not saved anywhere."
                    )
                    + "</p>",
                    NEW_MAP,
                    CANCEL,
                    warning=True,
                )
                if answer != NEW_MAP:
                    return
        if self._save_timer.isActive():
            # The map on screen goes to its own autosave first
            self._write_autosave()
        self._clear_map()
        self.seed_hash = None
        self.map_changed()

    # ------------------------------------------------------------------ pickers

    def pick_icon(self, world: World) -> str | None:
        dialog = IconPicker(self, self.assets, world)
        return dialog.choice if dialog.exec() else None

    def pick_eg_tile(self, page: GraphPage) -> rooms.Tile | None:
        used: dict[rooms.Tile, int] = {}
        for other in self.pages.values():
            for tile in other.model.tiles:
                used[tile] = used.get(tile, 0) + 1
        unavailable = {tile for tile, count in used.items() if count >= eg_tile_multiuse.get(tile, 1)}
        unavailable |= set(page.model.tiles)
        dialog = EgPicker(self, self.assets, unavailable)
        return dialog.choice if dialog.exec() else None

    # ------------------------------------------------------- called by the tracker

    def set_title(self, text: str) -> None:
        self.setWindowTitle(text)

    def set_devices(self, uris: list[str]) -> None:
        self.devices_menu.clear()
        if not uris:
            self.devices_menu.addAction("No Devices...").setEnabled(False)
        for uri in uris:
            action = self.devices_menu.addAction(uri)
            action.setObjectName(uri)
            action.triggered.connect(self._device_picked)

    def race_rom_warning(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Warning - Race Rom Detected")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "A Race Rom has been detected, auto-tracking has been automatically disabled.\n\n"
            "When auto-tracking is enabled, this tracker does not abide by the current auto-tracking rules set by "
            "the racing council.\nYou can continue to use this tracker, but you will need to manually track layouts.\n\n"
            "If you would like to continue using auto-tracking, you can force it to be enabled by clicking the "
            "button below."
        )
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        force = box.addButton("Force Auto-Tracking", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is force:
            # Deferred: this runs inside the task being restarted
            QTimer.singleShot(0, self._force_tracking)

    def highlight_dungeon(self, name: str | None) -> None:
        for dungeon, page in self.pages.items():
            label = dungeon.replace("_", " ")
            self.tabs.setTabText(self.tabs.indexOf(page), f"▶ {label}" if dungeon == name else label)

    def select_dungeon(self, name: str) -> None:
        self.tabs.setCurrentWidget(self.pages[name])

    # ---------------------------------------------------------------------- SNI

    def start_tracking(self, forced: bool = False, device: str | None = None) -> None:
        from sni_tracker import sni_probe

        self.stop_tracking()
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            self._pump = QTimer(self)
            self._pump.setInterval(10)
            self._pump.timeout.connect(self._pump_asyncio)
            self._pump.start()
        self.sni_task = self.loop.create_task(sni_probe(self, self.args, forced_autotrack=forced, device=device))

    def stop_tracking(self) -> None:
        if self.sni_task is not None:
            self.sni_task.cancel()
            self.sni_task = None
            self.connected = False
            self.setWindowTitle(f"{TITLE} - Auto-tracking disabled")

    def _pump_asyncio(self):
        """Run pending asyncio callbacks once, from the Qt timer."""
        loop = self.loop
        # Already running while a dialog opened from the tracker is up: the dialog's event loop fires this timer too
        if loop is None or loop.is_running():
            return
        loop.call_soon(loop.stop)
        loop.run_forever()
        if self.sni_task is not None and self.sni_task.done() and not self.sni_task.cancelled():
            error = self.sni_task.exception()
            self.sni_task = None
            if error is not None:
                print(f"Auto-tracking stopped: {error!r}")
                self.setWindowTitle(f"{TITLE} - Auto-tracking stopped (is SNI running?)")

    def closeEvent(self, event):
        if self.sni_task is not None:
            self.sni_task.cancel()
        self._save_timer.stop()
        self._drift_timer.stop()
        self._write_autosave()
        self.set_setting("window", bytes(self.saveGeometry().toHex().data()).decode())
        super().closeEvent(event)


def install_interrupt_handler(app, window):
    """Close the window on Ctrl+C.

    Python signal handlers only run when the interpreter does, so a no-op timer wakes it while Qt's
    event loop is running.
    """
    signal.signal(signal.SIGINT, lambda signum, frame: window.close())
    wake = QTimer(app)
    wake.timeout.connect(lambda: None)
    wake.start(150)
    app._interrupt_wake = wake


def main():
    parser = argparse.ArgumentParser(description="Auto-tracker for dungeon layouts in the ALttP door randomizer")
    parser.add_argument("tracker_file", nargs="?", default=None, help="Tracker data (yaml) or spoiler to load on startup")
    parser.add_argument("--size", choices=list(WINDOW_SIZES), default=None, help="Set the window size, instead of the size it last had")
    parser.add_argument("--port", type=int, default=8191, help="SNI connection port")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug logging")
    parser.add_argument(
        "--no-autotrack",
        action="store_true",
        default=False,
        help="Don't automatically track doors (No SNI connection - Race Legal)",
    )
    parser.add_argument("--no-gl", action="store_true", default=False, help="Draw without OpenGL")
    args, qt_args = parser.parse_known_args()

    app = QApplication([sys.argv[0]] + qt_args)
    # Names the per-user folder
    app.setApplicationName("JankerDoorTracker")
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    folder.mkdir(parents=True, exist_ok=True)
    window = MainWindow(args, settings_file=folder / "settings.yaml")
    window.show()
    install_interrupt_handler(app, window)
    if args.tracker_file:
        window.load_file(args.tracker_file)
    window.start_autosave(folder, restore=not args.tracker_file)
    if not args.no_autotrack:
        window.start_tracking()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
