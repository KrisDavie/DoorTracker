"""Jank Door Tracker: auto-tracks ALttP door randomizer dungeon layouts through SNI. Qt entry point."""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

import yaml
from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import data.doors_sprite_data as sprites
from data.doors_data import eg_tile_multiuse
from data.vanilla_data import vanilla_layout_optimized
from data.worlds_data import dungeon_worlds
from gui.Doors import rooms
from gui.qt.graph_page import Assets, GraphPage

WINDOW_SIZES = {"small": (1064, 632), "medium": (1588, 888), "large": (2088, 1144)}
TITLE = "Jank Door Tracker"


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
            button.setIcon(QIcon(assets.icon(name).scaled(32, 32, Qt.KeepAspectRatio, Qt.FastTransformation)))
            button.setIconSize(QSize(32, 32))
            button.setToolTip(name.replace("_", " "))
            usable = (name in sprites.item_table or name in sprites.dungeon_lobbies[world]) and name != "Sanctuary_Mirror"
            button.setEnabled(usable)
            button.clicked.connect(lambda checked=False, name=name: self._pick(name))
            grid.addWidget(button, row, column)

    def _pick(self, name):
        self.choice = name
        self.accept()


class EgPicker(QDialog):
    """Pick a supertile to add, from each dungeon's vanilla layout."""

    def __init__(self, parent, assets, unavailable):
        super().__init__(parent)
        self.setWindowTitle("Add supertile")
        self.choice = None
        tabs = QTabWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        for name, layout_data in vanilla_layout_optimized.items():
            tiles = layout_data["tiles"]
            if not tiles:
                continue
            page = QWidget()
            grid = QGridLayout(page)
            grid.setSpacing(3)
            min_x = min(t["map_tile"][0] for t in tiles.values())
            min_y = min(t["map_tile"][1] for t in tiles.values())
            for tile, placement in tiles.items():
                button = QToolButton()
                button.setIcon(QIcon(assets.thumbnail(tile, 96)))
                button.setIconSize(QSize(96, 96))
                button.setToolTip(rooms.WHOLE.title(rooms.Node(*tile)))
                # Disabled if already on the map or used up
                button.setEnabled(tile not in unavailable)
                button.clicked.connect(lambda checked=False, tile=tile: self._pick(tile))
                grid.addWidget(button, placement["map_tile"][1] - min_y, placement["map_tile"][0] - min_x)
            tabs.addTab(page, "Other Lobby Tiles" if name == "Lobbyable_Tiles" else name.replace("_", " "))
            if name == parent.current_dungeon():
                tabs.setCurrentWidget(page)

    def _pick(self, tile):
        self.choice = tile
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.setWindowTitle(TITLE)
        self.resize(*WINDOW_SIZES[args.size])
        self.experimental_flags = {
            "hide_single_route_tiles": False,
            "prefer_fill_map": False,
            "decoupled_doors": False,
            "vanilla_drops": True,
            "hide_dead_rooms": True,
            "split_rooms": True,
        }
        self.device = None
        self.sni_task = None
        self.loop = None

        eg_map = Path(__file__).parent / "data" / "maps" / "egmap.png"
        self.assets = Assets(Image.open(eg_map))
        _add_thumbnails(self.assets)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.pages = {}
        for dungeon, world in dungeon_worlds.items():
            if dungeon in ("Overworld", "Underworld"):
                continue
            page = GraphPage(self, world, self.assets, use_gl=not args.no_gl)
            self.pages[dungeon] = page
            self.tabs.addTab(page, dungeon.replace("_", " "))
        self._build_menus()

    # -------------------------------------------------------------------- menus

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addAction("Load Tracker Data", lambda: self.load_file())
        file_menu.addAction("Save Tracker Data", self.save_file)
        file_menu.addSeparator()
        file_menu.addAction("Stop Auto-tracking", self.stop_tracking)
        file_menu.addAction("Reconnect to SNI", lambda: self.start_tracking())
        self.devices_menu = file_menu.addMenu("Devices")
        self.set_devices([])
        file_menu.addSeparator()
        file_menu.addAction("Reset Tracker", self.reset_tracker)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        view_menu = bar.addMenu("View")
        view_menu.addAction("Fit to window", lambda: self.tabs.currentWidget().fit_view())
        view_menu.addAction("Re-layout", lambda: self.tabs.currentWidget().relayout())
        show_all = QAction("Show All Doors", self, checkable=True)
        show_all.toggled.connect(self._show_all_doors)
        view_menu.addAction(show_all)

        experimental = bar.addMenu("Experimental")
        for label, flag in (
            ("Hide Single Route Tiles", "hide_single_route_tiles"),
            ("Enable Decoupled Support", "decoupled_doors"),
            ("Drops Are Not Shuffled", "vanilla_drops"),
            ("Hide Dead Rooms", "hide_dead_rooms"),
            ("Split Partitioned Rooms", "split_rooms"),
        ):
            action = QAction(label, self, checkable=True)
            action.setChecked(self.experimental_flags[flag])
            action.toggled.connect(lambda checked, flag=flag: self._set_flag(flag, checked))
            experimental.addAction(action)

    def _show_all_doors(self, checked):
        for page in self.pages.values():
            page.show_all_doors = checked
            page.redraw_canvas()

    def _set_flag(self, flag, checked):
        self.experimental_flags[flag] = checked
        for page in self.pages.values():
            if flag in ("hide_dead_rooms", "split_rooms"):
                # These change block shapes or count
                page.relayout()
            else:
                page.redraw_canvas()

    def current_dungeon(self):
        return self.tabs.currentWidget().dungeon_name

    # -------------------------------------------------------------------- files

    def load_file(self, file=None):
        if file is None:
            file, _ = QFileDialog.getOpenFileName(self, "Load Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        with open(file, mode="r") as fh:
            try:
                data = yaml.safe_load(fh)
            except Exception:
                from SpoilerToYaml import parse_dr_spoiler

                data = parse_dr_spoiler(fh)
        if "Agahnims_Tower" in data:
            data["Castle_Tower"] = data.pop("Agahnims_Tower")
        for dungeon, dungeon_data in data.items():
            if dungeon in self.pages:
                self.pages[dungeon].load_yaml(dungeon_data)

    def save_file(self):
        file, _ = QFileDialog.getSaveFileName(self, "Save Tracker Data", ".", "Yaml Files (*.yaml *.yml);;All Files (*)")
        if not file:
            return
        if not file.endswith((".yaml", ".yml")):
            file += ".yaml"
        with open(file, mode="w") as fh:
            yaml.dump({dungeon: page.return_connections() for dungeon, page in self.pages.items()}, fh)

    def reset_tracker(self):
        answer = QMessageBox.question(
            self,
            "Reset?",
            "This will reset your tracker, losing all connections etc.\nAre you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            for page in self.pages.values():
                page.init_page()

    # ------------------------------------------------------------------ pickers

    def pick_icon(self, world):
        dialog = IconPicker(self, self.assets, world)
        return dialog.choice if dialog.exec() else None

    def pick_eg_tile(self, page):
        used = {}
        for other in self.pages.values():
            for tile in other.model.tiles:
                used[tile] = used.get(tile, 0) + 1
        unavailable = {tile for tile, count in used.items() if count >= eg_tile_multiuse.get(tile, 1)}
        unavailable |= set(page.model.tiles)
        dialog = EgPicker(self, self.assets, unavailable)
        return dialog.choice if dialog.exec() else None

    # ------------------------------------------------------- called by the tracker

    def set_title(self, text):
        self.setWindowTitle(text)

    def set_devices(self, uris):
        self.devices_menu.clear()
        if not uris:
            self.devices_menu.addAction("No Devices...").setEnabled(False)
        for uri in uris:
            self.devices_menu.addAction(uri, lambda uri=uri: self.start_tracking(device=uri))

    def race_rom_warning(self):
        box = QMessageBox(self)
        box.setWindowTitle("Warning - Race Rom Detected")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            "A Race Rom has been detected, auto-tracking has been automatically disabled.\n\n"
            "When auto-tracking is enabled, this tracker does not abide by the current auto-tracking rules set by "
            "the racing council.\nYou can continue to use this tracker, but you will need to manually track layouts.\n\n"
            "If you would like to continue using auto-tracking, you can force it to be enabled by clicking the "
            "button below."
        )
        box.addButton("OK", QMessageBox.AcceptRole)
        force = box.addButton("Force Auto-Tracking", QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is force:
            # Deferred: this runs inside the task being restarted
            QTimer.singleShot(0, lambda: self.start_tracking(forced=True, device=self.device))

    def highlight_dungeon(self, name):
        for dungeon, page in self.pages.items():
            label = dungeon.replace("_", " ")
            self.tabs.setTabText(self.tabs.indexOf(page), f"▶ {label}" if dungeon == name else label)

    def select_dungeon(self, name):
        self.tabs.setCurrentWidget(self.pages[name])

    # ---------------------------------------------------------------------- SNI

    def start_tracking(self, forced=False, device=None):
        from sni_tracker import sni_probe

        self.stop_tracking()
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            self._pump = QTimer(self)
            self._pump.setInterval(10)
            self._pump.timeout.connect(self._pump_asyncio)
            self._pump.start()
        self.sni_task = self.loop.create_task(sni_probe(self, self.args, forced_autotrack=forced, device=device))

    def stop_tracking(self):
        if self.sni_task is not None:
            self.sni_task.cancel()
            self.sni_task = None
            self.setWindowTitle(f"{TITLE} - Auto-tracking disabled")

    def _pump_asyncio(self):
        """Run pending asyncio callbacks once, from the Qt timer."""
        self.loop.call_soon(self.loop.stop)
        self.loop.run_forever()
        if self.sni_task is not None and self.sni_task.done() and not self.sni_task.cancelled():
            error = self.sni_task.exception()
            self.sni_task = None
            if error is not None:
                print(f"Auto-tracking stopped: {error!r}")
                self.setWindowTitle(f"{TITLE} - Auto-tracking stopped (is SNI running?)")

    def closeEvent(self, event):
        if self.sni_task is not None:
            self.sni_task.cancel()
        super().closeEvent(event)


def _add_thumbnails(assets):
    """Add a cached thumbnail() to assets, for the supertile picker."""
    cache = {}

    def thumbnail(tile, size):
        key = (tile, size)
        if key not in cache:
            x, y = tile
            crop = assets.eg_img.crop((x * 512, y * 512, (x + 1) * 512, (y + 1) * 512)).convert("RGB")
            crop = crop.resize((size, size), Image.BILINEAR, reducing_gap=2.0)
            cache[key] = QPixmap.fromImage(QImage(crop.tobytes(), size, size, size * 3, QImage.Format_RGB888).copy())
        return cache[key]

    assets.thumbnail = thumbnail


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
    parser.add_argument("--size", choices=list(WINDOW_SIZES), default="medium", help="Set the window size")
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
    window = MainWindow(args)
    window.show()
    install_interrupt_handler(app, window)
    if args.tracker_file:
        window.load_file(args.tracker_file)
    if not args.no_autotrack:
        window.start_tracking()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
